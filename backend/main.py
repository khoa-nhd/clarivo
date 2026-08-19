"""Clarivo FastAPI application used locally and by Vercel."""

import os

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

from app.cloudflare_transcription import transcribe_audio
from app.evaluator import evaluate_explanation
from app.schemas import AnalysisRequest, AnalysisResult, TranscriptionResult

app = FastAPI(title="Clarivo API", version="1.2.0")


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
