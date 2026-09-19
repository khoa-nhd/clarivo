"""Clarivo FastAPI application used locally and by Vercel."""

import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.cloudflare_transcription import transcribe_audio
from app.evaluator import evaluate_explanation
from app.drill_engine import DrillAIError, evaluate_qa_round, finalize_drill, generate_initial_drills, refresh_topics
from app.schemas import (
    AnalysisRequest,
    AnalysisResult,
    DrillGenerateRequest,
    DrillGenerateResult,
    FinalizeDrillRequest,
    FinalizeDrillResult,
    QAEvaluateRequest,
    QAEvaluateResult,
    TopicRefreshRequest,
    TopicRefreshResult,
    TranscriptionResult,
)
from app.local_delivery import (
    analyze_audio_path,
    analyze_delivery_files,
    analyze_vision_path,
    capability_payload,
    upload_limits,
)

app = FastAPI(title="Clarivo API", version="1.4.0")


def _allowed_origins() -> list[str]:
    defaults = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    raw = os.getenv("ALLOWED_ORIGINS", "")
    configured = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    return list(dict.fromkeys(defaults + configured))


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


#: Uploads are copied to disk a megabyte at a time. Reading the whole body with
#: `await file.read()` held an entire recording in memory - fine for the old
#: 80 MB ceiling, ruinous at the sizes a five-minute capture actually reaches.
UPLOAD_CHUNK_BYTES = 1024 * 1024


async def _stream_upload(upload: UploadFile, destination: Path, max_bytes: int, label: str) -> int:
    """Copy an upload to disk, enforcing the size cap as the bytes arrive.

    Checking during the copy means an oversized file is rejected part way
    through instead of after the server has already buffered all of it.
    """
    total = 0
    with destination.open("wb") as handle:
        while True:
            chunk = await upload.read(UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"{label} is larger than the {max_bytes // (1024 * 1024)} MB limit "
                        "this backend accepts. Raise LOCAL_MAX_VIDEO_BYTES, or record a shorter clip."
                    ),
                )
            handle.write(chunk)
    if total == 0:
        raise HTTPException(status_code=400, detail=f"{label} is empty.")
    return total



def _combine_delivery(audio: dict, vision: dict) -> dict:
    """Merge the two compact payloads the way the legacy combined route did."""
    priorities: list[str] = []
    for item in [*(audio.get("top_priorities") or []), *(vision.get("top_priorities") or [])]:
        if item not in priorities:
            priorities.append(item)
    return {
        "schema_version": "clarivo-web-delivery-v11",
        "voice_score": audio.get("voice_score"),
        "visual_score": vision.get("visual_score"),
        "voice": audio.get("voice"),
        "visual": vision.get("visual"),
        "top_priorities": priorities[:3],
        "meta": {
            "engine": "Clarivo Phase 20 local scoring",
            "analysis_seconds": round(
                float(audio.get("meta", {}).get("analysis_seconds") or 0)
                + float(vision.get("meta", {}).get("analysis_seconds") or 0),
                2,
            ),
            "audio_confidence": audio.get("meta", {}).get("audio_confidence"),
            "vision_confidence": vision.get("meta", {}).get("vision_confidence"),
        },
    }


def _local_unavailable_detail(capability: dict, kind: str) -> str:
    """Explain *why* local analysis is unavailable, without leaking internals.

    Three different situations used to produce the same opaque message, or - when
    the feature was switched on for a deployment that cannot run it - a 500
    carrying a raw ModuleNotFoundError.
    """
    if capability.get("mode") == "disabled":
        return (
            f"Local {kind} analysis is not enabled on this backend. "
            "It runs only on a local Intel machine with LOCAL_SCORING_ENABLED=true."
        )
    missing_map = capability.get("missing_dependencies")
    if missing_map is not None:
        missing = missing_map.get(kind) or []
        if missing:
            return (
                f"Local {kind} analysis is switched on but this deployment does not "
                f"include the required packages ({', '.join(missing)}). "
                "Install backend/requirements-local.txt, or set LOCAL_SCORING_ENABLED=false."
            )
        if capability.get("missing_models"):
            return (
                "Local OpenVINO models are not downloaded. Run: "
                "python -m local_scoring.setup_delivery_models"
            )
    if kind == "vision":
        return (
            "Local OpenVINO vision models are not ready. Run the delivery model setup command first."
        )
    return f"Local {kind} analysis is not available on this backend."


@app.get("/")
def root():
    return {
        "name": "Clarivo API",
        "ok": True,
        "health": "/api/health",
    }


@app.get("/api/health")
def health():
    provider = os.getenv("AI_PROVIDER", "mock").strip().lower()
    model = (
        os.getenv("CLOUDFLARE_MODEL", "@cf/qwen/qwen3-30b-a3b-fp8")
        if provider == "cloudflare"
        else "mock-evaluator"
    )
    transcription_provider = os.getenv("TRANSCRIPTION_PROVIDER", provider).strip().lower()
    transcription_model = (
        os.getenv(
            "CLOUDFLARE_TRANSCRIPTION_MODEL",
            "@cf/openai/whisper-large-v3-turbo",
        )
        if transcription_provider == "cloudflare"
        else "mock-transcriber"
    )
    return {
        "ok": True,
        "provider": provider,
        "model": model,
        "transcription_provider": transcription_provider,
        "transcription_model": transcription_model,
        "delivery_analysis": capability_payload(),
        "learning_loop": {
            "enabled": True,
            "qa_scoring_mode": "isolated_current_q_and_a",
            "same_type_followups": True,
            "topic_refresh": True,
            "max_rounds": int(os.getenv("DRILL_MAX_ROUNDS", "3")),
            "qa_criteria": ["accuracy", "directness", "consistency", "relevance", "audience_fit"],
        },
    }


@app.post("/api/transcribe", response_model=TranscriptionResult)
async def transcribe(
    audio: UploadFile = File(...),
    duration_seconds: float = Form(default=0),
    topic: str = Form(default=""),
):
    provider = os.getenv(
        "TRANSCRIPTION_PROVIDER",
        os.getenv("AI_PROVIDER", "mock"),
    ).strip().lower()

    print("🔥 TRANSCRIPTION PROVIDER:", repr(provider))

    max_recording_seconds = int(os.getenv("MAX_RECORDING_SECONDS", "300"))
    if duration_seconds > max_recording_seconds + 5:
        raise HTTPException(
            status_code=413,
            detail="Recording is longer than the 5-minute public demo limit.",
        )

    max_audio_bytes = int(os.getenv("MAX_AUDIO_BYTES", "3500000"))
    data = await audio.read(max_audio_bytes + 1)

    if not data:
        raise HTTPException(status_code=400, detail="The recorded audio file is empty.")
    if len(data) > max_audio_bytes:
        raise HTTPException(
            status_code=413,
            detail=(
                "Recording is too large for the free public backend. "
                "Keep recordings under 5 minutes and retry."
            ),
        )

    mime_type = (audio.content_type or "audio/webm").split(";")[0].strip().lower()

    if provider == "mock":
        return TranscriptionResult(
            text=(
                "Mock transcription: microphone audio was uploaded successfully. "
                "Set TRANSCRIPTION_PROVIDER=cloudflare to use real English Whisper transcription."
            ),
            word_count=16,
            duration_seconds=max(0, duration_seconds),
            mime_type=mime_type,
            size_bytes=len(data),
            model="mock-transcriber",
        )

    if provider != "cloudflare":
        raise HTTPException(
            status_code=500,
            detail=f"Unsupported transcription provider: {provider}",
        )

    try:
        result = transcribe_audio(data, topic=topic)
        return TranscriptionResult(
            text=result["text"],
            word_count=result["word_count"],
            duration_seconds=max(0, duration_seconds),
            mime_type=mime_type,
            size_bytes=len(data),
            model=result["model"],
        )
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if "rate limit" in lowered or "too many requests" in lowered or "http 429" in lowered:
            raise HTTPException(
                status_code=429,
                detail="The free transcription service is busy right now. Please wait a moment and retry.",
            ) from exc
        if "quota" in lowered or "neurons" in lowered or "daily" in lowered:
            raise HTTPException(
                status_code=429,
                detail="Clarivo has reached today's free AI allowance. You can keep the recording and retry later.",
            ) from exc
        if "account_id" in lowered or "auth_token" in lowered or "token" in lowered:
            raise HTTPException(
                status_code=503,
                detail="The transcription service is not configured correctly on the server.",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="Clarivo could not transcribe this recording. Keep the recording and retry transcription.",
        ) from exc


@app.post("/api/analyze", response_model=AnalysisResult, response_model_exclude_none=True)
def analyze(request: AnalysisRequest):
    max_transcript_chars = int(os.getenv("MAX_TRANSCRIPT_CHARS", "20000"))
    max_reference_chars = int(os.getenv("MAX_REFERENCE_CHARS", "20000"))

    if len(request.transcript) > max_transcript_chars:
        raise HTTPException(
            status_code=413,
            detail="Transcript is too long for the public demo. Keep it under 20,000 characters.",
        )
    if request.reference_content and len(request.reference_content) > max_reference_chars:
        raise HTTPException(
            status_code=413,
            detail="Reference content is too long for the public demo.",
        )

    try:
        return evaluate_explanation(request)
    except Exception as exc:
        message = str(exc)
        lowered = message.lower()
        if "rate limit" in lowered or "too many requests" in lowered or "http 429" in lowered:
            raise HTTPException(
                status_code=429,
                detail="The free AI service is busy right now. Please wait a moment and retry.",
            ) from exc
        if "quota" in lowered or "neurons" in lowered or "daily" in lowered:
            raise HTTPException(
                status_code=429,
                detail="Clarivo has reached today's free AI allowance. Please try again after the daily reset.",
            ) from exc
        # Do not expose credentials or stack traces to public users.
        if "account_id" in lowered or "auth_token" in lowered or "token" in lowered:
            raise HTTPException(
                status_code=503,
                detail="The AI service is not configured correctly on the server.",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="Clarivo could not finish this analysis. Please retry the session.",
        ) from exc




def _drill_http_error(exc: Exception) -> HTTPException:
    message = str(exc)
    lowered = message.lower()
    if "rate limit" in lowered or "too many requests" in lowered or "http 429" in lowered:
        return HTTPException(status_code=429, detail="The free AI service is busy right now. Please wait a moment and retry.")
    if "quota" in lowered or "neurons" in lowered or "daily" in lowered:
        return HTTPException(status_code=429, detail="Clarivo has reached today's free AI allowance. Please try again after the daily reset.")
    if "credential" in lowered or "account_id" in lowered or "auth_token" in lowered or "token" in lowered:
        return HTTPException(status_code=503, detail="The AI service is not configured correctly on the server.")
    return HTTPException(status_code=502, detail="Clarivo could not finish this learning drill. Please retry.")




@app.post("/api/topics/refresh", response_model=TopicRefreshResult)
def refresh_topic_library(request: TopicRefreshRequest):
    try:
        return refresh_topics(request)
    except Exception as exc:
        raise _drill_http_error(exc) from exc


@app.post("/api/drills/generate", response_model=DrillGenerateResult)
def generate_drills(request: DrillGenerateRequest):
    try:
        return generate_initial_drills(request)
    except Exception as exc:
        raise _drill_http_error(exc) from exc


@app.post("/api/drills/evaluate", response_model=QAEvaluateResult, response_model_exclude_none=True)
def evaluate_drill_answer(request: QAEvaluateRequest):
    try:
        return evaluate_qa_round(request)
    except Exception as exc:
        raise _drill_http_error(exc) from exc


@app.post("/api/drills/finalize", response_model=FinalizeDrillResult)
def finalize_drill_session(request: FinalizeDrillRequest):
    try:
        return finalize_drill(request)
    except Exception as exc:
        raise _drill_http_error(exc) from exc

@app.post("/api/analyze/audio")
async def analyze_audio_delivery(
    audio_wav: UploadFile = File(...),
    transcript: str = Form(...),
    duration_seconds: float = Form(default=0),
):
    capability = capability_payload()
    if not capability["audio_ready"]:
        raise HTTPException(
            status_code=503,
            detail=_local_unavailable_detail(capability, "audio"),
        )

    max_seconds = int(os.getenv("MAX_RECORDING_SECONDS", "300"))
    if duration_seconds > max_seconds + 5:
        raise HTTPException(status_code=413, detail="Recording is longer than the local analysis limit.")
    if len(transcript.strip()) < 10:
        raise HTTPException(status_code=400, detail="A transcript is required for audio analysis.")

    max_audio = upload_limits()["max_audio_wav_bytes"]
    with tempfile.TemporaryDirectory(prefix="clarivo_audio_") as tmp:
        audio_path = Path(tmp) / "audio.wav"
        await _stream_upload(audio_wav, audio_path, max_audio, "The audio recording")
        try:
            return await run_in_threadpool(
                analyze_audio_path,
                audio_path=audio_path,
                transcript=transcript,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Local audio analysis failed: {type(exc).__name__}: {exc}",
            ) from exc


@app.post("/api/analyze/vision")
async def analyze_visual_delivery(
    video: UploadFile = File(...),
    duration_seconds: float = Form(default=0),
):
    capability = capability_payload()
    if not capability["vision_ready"]:
        raise HTTPException(
            status_code=503,
            detail=_local_unavailable_detail(capability, "vision"),
        )

    max_seconds = int(os.getenv("MAX_RECORDING_SECONDS", "300"))
    if duration_seconds > max_seconds + 5:
        raise HTTPException(status_code=413, detail="Recording is longer than the local analysis limit.")

    max_video = upload_limits()["max_video_bytes"]
    filename = video.filename or "camera.webm"
    suffix = Path(filename).suffix or ".webm"
    with tempfile.TemporaryDirectory(prefix="clarivo_vision_") as tmp:
        video_path = Path(tmp) / f"video{suffix}"
        await _stream_upload(video, video_path, max_video, "The camera recording")
        try:
            return await run_in_threadpool(analyze_vision_path, video_path=video_path)
        except HTTPException:
            raise
        except Exception as exc:
            message = str(exc)
            lowered = message.lower()
            if "models are missing" in lowered or "models are not ready" in lowered:
                raise HTTPException(status_code=503, detail=message) from exc
            if "could not open video" in lowered or ("video" in lowered and "open" in lowered):
                raise HTTPException(
                    status_code=422,
                    detail="Clarivo could not decode this camera recording. Try Chrome/Edge and record again.",
                ) from exc
            raise HTTPException(
                status_code=500,
                detail=f"Local visual analysis failed: {type(exc).__name__}: {message}",
            ) from exc


@app.post("/api/analyze/delivery")
async def analyze_delivery(
    audio_wav: UploadFile = File(...),
    video: UploadFile = File(...),
    transcript: str = Form(...),
    duration_seconds: float = Form(default=0),
):
    capability = capability_payload()
    if not capability["audio_ready"]:
        raise HTTPException(status_code=503, detail=_local_unavailable_detail(capability, "audio"))
    if not capability["vision_ready"]:
        raise HTTPException(status_code=503, detail=_local_unavailable_detail(capability, "vision"))

    max_seconds = int(os.getenv("MAX_RECORDING_SECONDS", "300"))
    if duration_seconds > max_seconds + 5:
        raise HTTPException(status_code=413, detail="Recording is longer than the local analysis limit.")
    if len(transcript.strip()) < 10:
        raise HTTPException(status_code=400, detail="A transcript is required for delivery analysis.")

    limits = upload_limits()
    filename = video.filename or "camera.webm"
    suffix = Path(filename).suffix or ".webm"
    with tempfile.TemporaryDirectory(prefix="clarivo_delivery_") as tmp:
        audio_path = Path(tmp) / "audio.wav"
        video_path = Path(tmp) / f"video{suffix}"
        await _stream_upload(audio_wav, audio_path, limits["max_audio_wav_bytes"], "The audio recording")
        await _stream_upload(video, video_path, limits["max_video_bytes"], "The camera recording")
        try:
            audio_result = await run_in_threadpool(
                analyze_audio_path, audio_path=audio_path, transcript=transcript
            )
            vision_result = await run_in_threadpool(analyze_vision_path, video_path=video_path)
            return _combine_delivery(audio_result, vision_result)
        except HTTPException:
            raise
        except Exception as exc:
            message = str(exc)
            lowered = message.lower()
            if "models are missing" in lowered or "models are not ready" in lowered:
                raise HTTPException(status_code=503, detail=message) from exc
            if "could not open video" in lowered or ("video" in lowered and "open" in lowered):
                raise HTTPException(
                    status_code=422,
                    detail="Clarivo could not decode this camera recording. Try Chrome/Edge and record again.",
                ) from exc
            raise HTTPException(
                status_code=500,
                detail=f"Local delivery analysis failed: {type(exc).__name__}: {message}",
            ) from exc
