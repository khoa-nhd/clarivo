from __future__ import annotations

import os
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def local_scoring_enabled() -> bool:
    return _env_bool("LOCAL_SCORING_ENABLED", False)


def _env_path(name: str, default: Path) -> Path:
    """Resolve a directory from the environment, treating blank as unset.

    ``os.getenv(name, default)`` returns the default only when the variable is
    absent, not when it is present but empty. ``.env.example`` ships
    ``LOCAL_CACHE_DIR=`` with no value, so the documented default was never
    reached: the value became ``""``, and ``Path("").resolve()`` is the process
    working directory. The OpenVINO compiled-model cache therefore landed
    wherever the server happened to be started from - scattering ~23 MB of blobs
    into the repository, and silently losing the cache altogether when that
    directory was not writable (``create_core`` swallows the failure), which
    costs a full model recompile on every single request.
    """
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default.resolve()
    return Path(raw.strip()).expanduser().resolve()


def _cache_dir() -> Path:
    """Where OpenVINO may cache compiled models.

    A serverless function's code directory is read-only, so creating this there
    raised ``OSError: [Errno 30] Read-only file system`` and took voice analysis
    down with it - for a cache that path never uses. The transcript comes from
    Cloudflare Whisper on the web, so no local model is ever compiled and
    nothing is ever written here. Falling back to the system temp directory
    keeps the local behaviour (a persistent cache that makes the second run
    faster) without letting an unused directory fail the request.
    """
    cache_dir = _env_path(
        "LOCAL_CACHE_DIR",
        Path(__file__).resolve().parent.parent / "local_scoring" / "cache",
    )
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir
    except OSError:
        fallback = Path(tempfile.gettempdir()) / "clarivo-openvino-cache"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def models_dir() -> Path:
    return _env_path(
        "LOCAL_MODELS_DIR",
        Path(__file__).resolve().parent.parent / "local_scoring" / "models",
    )


def _model_paths(base: Path) -> dict[str, Path]:
    return {
        "face": base / "face" / "face-detection-retail-0004.xml",
        "head": base / "head_pose" / "head-pose-estimation-adas-0001.xml",
        "landmarks": base / "landmarks" / "facial-landmarks-35-adas-0002.xml",
        "gaze": base / "gaze" / "gaze-estimation-adas-0002.xml",
        "pose": base / "yolo26s-pose_openvino_model",
    }


def models_ready() -> bool:
    paths = _model_paths(models_dir())
    return all(path.exists() for path in paths.values())


#: Import names each local capability needs, checked without importing them.
_AUDIO_REQUIREMENTS = ("numpy", "librosa", "soundfile")
# Ultralytics is no longer among these: the pose model runs through its
# exported OpenVINO IR, so ultralytics (and the 543 MB of torch behind it)
# is a setup-time dependency, not a runtime one.
_VISION_REQUIREMENTS = ("numpy", "cv2", "openvino")


@lru_cache(maxsize=1)
def _missing_modules() -> dict[str, tuple[str, ...]]:
    """Which local-analysis dependencies are absent from this interpreter.

    ``find_spec`` resolves the module without executing it, so this is cheap and
    safe to call on a serverless cold start.

    This exists because ``LOCAL_SCORING_ENABLED=true`` on a deployment built
    from the light ``requirements.txt`` - the public Vercel backend - used to be
    advertised as a working capability. ``/api/health`` reported
    ``enabled: true``, the frontend switched on the voice and visual panels, and
    every resulting request failed with a 500 carrying an internal
    ``ModuleNotFoundError`` message. Checking what is actually installed turns
    that misconfiguration into the clean 503 the frontend already handles.
    """
    from importlib.util import find_spec

    def absent(names: tuple[str, ...]) -> tuple[str, ...]:
        missing = []
        for name in names:
            try:
                if find_spec(name) is None:
                    missing.append(name)
            except (ImportError, ValueError):
                missing.append(name)
        return tuple(missing)

    return {
        "audio": absent(_AUDIO_REQUIREMENTS),
        "vision": absent(_VISION_REQUIREMENTS),
        # Scoring a timeline the browser produced needs the decision layer only,
        # which is pure NumPy. No OpenVINO, no OpenCV, no model weights - that is
        # the whole point of the split, and it is what makes visual analysis
        # possible on a serverless deployment.
        "vision_timeline": absent(("numpy",)),
    }


def capability_payload() -> dict[str, Any]:
    enabled_by_config = local_scoring_enabled()
    missing = _missing_modules()

    audio_ready = enabled_by_config and not missing["audio"]
    vision_ready = enabled_by_config and not missing["vision"] and models_ready()
    # Browser-side inference does not depend on LOCAL_SCORING_ENABLED: that flag
    # means "this machine may run the OpenVINO stack", and here the models run on
    # the viewer's device. The backend only scores the timeline they produce.
    vision_timeline_ready = not missing["vision_timeline"]
    enabled = audio_ready or vision_ready or vision_timeline_ready

    if vision_ready or audio_ready:
        mode = "local_openvino"
    elif vision_timeline_ready and not enabled_by_config:
        # Nothing local runs here, but visual analysis still works because the
        # models run in the browser and only the scoring happens server side.
        mode = "browser_inference"
    elif not enabled_by_config:
        mode = "disabled"
    else:
        # Configured on, but this deployment cannot actually run it.
        mode = "unavailable"

    payload: dict[str, Any] = {
        "enabled": enabled,
        "audio_ready": audio_ready,
        "vision_ready": vision_ready,
        "models_ready": vision_ready,  # backward compatibility with the previous UI
        # Visual analysis with the models running in the viewer's browser. True
        # on the serverless deployment, where vision_ready is necessarily false.
        "vision_timeline_ready": vision_timeline_ready,
        "mode": mode,
        # Published so the browser enforces the same ceilings the server does.
        # They were duplicated as constants in the upload panel and had already
        # drifted, so a file the server would have accepted was refused - and a
        # file it would refuse was uploaded in full before failing.
        "limits": upload_limits(),
    }
    if enabled_by_config and not (audio_ready and vision_ready):
        # Surface the reason per capability, so a deployment where one half
        # works and the other does not - voice-only is a legitimate serverless
        # shape - reports the real cause instead of blaming the models for a
        # missing package.
        payload["missing_dependencies"] = {
            "audio": list(missing["audio"]),
            "vision": list(missing["vision"]),
        }
        if not missing["vision"] and not models_ready():
            payload["missing_models"] = True
    if enabled_by_config and not enabled:
        payload["configured_but_unavailable"] = True
    return payload


#: Five minutes of phone or screen capture can easily reach several hundred MB,
#: so the ceiling is generous. Uploads stream to disk, so a large file costs
#: temporary disk space rather than server memory.
DEFAULT_MAX_VIDEO_BYTES = 1_024_000_000
DEFAULT_MAX_AUDIO_WAV_BYTES = 64_000_000


def upload_limits() -> dict[str, Any]:
    return {
        "max_video_bytes": int(os.getenv("LOCAL_MAX_VIDEO_BYTES", str(DEFAULT_MAX_VIDEO_BYTES))),
        "max_audio_wav_bytes": int(
            os.getenv("LOCAL_MAX_AUDIO_WAV_BYTES", str(DEFAULT_MAX_AUDIO_WAV_BYTES))
        ),
        "max_recording_seconds": int(os.getenv("MAX_RECORDING_SECONDS", "300")),
    }


def _device_choice(requested: str, kind: str) -> str:
    requested = (requested or "RECOMMENDED").strip().upper()
    if requested != "RECOMMENDED":
        return requested
    from local_scoring.device_utils import recommended_devices

    recommended = recommended_devices()
    return recommended[kind]


def _metric_score(scores: dict[str, Any], key: str) -> float | None:
    value = scores.get(key)
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _audio_priorities(audio: dict[str, Any]) -> list[str]:
    scores = audio.get("scores", {})
    candidates: list[tuple[float, str]] = []
    for key, text in [
        ("audibility", "Make your voice easier to hear over background noise."),
        ("pause_control", "Use pauses intentionally and avoid long silent gaps."),
    ]:
        score = _metric_score(scores, key)
        if score is not None:
            candidates.append((score, text))

    pace = _metric_score(scores, "pace")
    if pace is not None and float(scores.get("text_metric_reliability") or 0) >= 55:
        candidates.append((pace, "Keep your speaking pace in a comfortable presentation range."))
    filler = _metric_score(scores, "filler")
    if filler is not None and float(scores.get("filler_metric_reliability") or 0) >= 70:
        candidates.append((filler, "Reduce repeated filler sounds and prolonged hesitation vowels."))
    return [text for _, text in sorted(candidates, key=lambda item: item[0])[:2]]


def _vision_priorities(vision: dict[str, Any]) -> list[str]:
    scores = vision.get("scores", {})
    candidates: list[tuple[float, str]] = []
    for key, text in [
        ("camera_attention", "Reconnect with the camera/audience around key points."),
        ("head_stability", "Keep large or prolonged head turns more controlled."),
        ("posture", "Keep your head, shoulders, and torso more consistently aligned."),
    ]:
        score = _metric_score(scores, key)
        if score is not None:
            candidates.append((score, text))
    return [text for _, text in sorted(candidates, key=lambda item: item[0])[:2]]

def _compact_audio(audio: dict[str, Any], elapsed: float) -> dict[str, Any]:
    scores = audio.get("scores", {})
    metrics = audio.get("metrics", {})
    return {
        "schema_version": "clarivo-web-audio-phase20",
        "voice_score": audio.get("audio_score"),
        "voice": {
            # Clarivo keeps the Cloudflare Whisper + user-edited transcript as source of truth.
            "transcript_source": metrics.get("text_metric_source", "external_transcript"),
            "speech_state": metrics.get("speech_state"),
            "audio_status": metrics.get("audio_status"),
            # How the speech/silence threshold was chosen. "unimodal_no_background"
            # means the recording had no separable background lobe, which is the
            # case where an N/A verdict needs explaining rather than just showing.
            "vad_mode": metrics.get("vad_mode"),
            "vad_speech_background_separation_db": metrics.get("vad_otsu_separation_db"),
            "speech_threshold_dbfs": metrics.get("speech_threshold_dbfs"),
            "no_speech_detected": metrics.get("no_speech_detected"),
            "wpm": metrics.get("wpm"),
            "articulation_wpm": metrics.get("articulation_wpm"),
            "word_count": metrics.get("word_count"),
            "duration_seconds": metrics.get("duration_seconds"),
            "speaking_time_seconds": metrics.get("speaking_time_seconds"),
            "speaking_ratio": metrics.get("speaking_ratio"),
            "active_speaking_ratio": metrics.get("active_speaking_ratio"),
            "voice_activity_ratio": metrics.get("voice_activity_ratio"),
            "abnormal_dead_silence": metrics.get("abnormal_dead_silence"),
            "pace_score": scores.get("pace"),
            "pace_stability_score": scores.get("pace_stability"),
            "pause_score": scores.get("pause_control"),
            "audibility_score": scores.get("audibility"),
            "volume_stability_score": scores.get("volume_stability"),
            "fluency_score": scores.get("fluency"),
            "filler_score": scores.get("filler"),
            # Phase 20 filler: edited transcript fillers + acoustic prolonged-vowel hesitations.
            "filler_count": metrics.get("filler_count"),
            "filler_count_transcript": metrics.get("filler_count_transcript"),
            "implicit_filler_count": metrics.get("implicit_filler_count"),
            "implicit_filler_durations_seconds": metrics.get("implicit_filler_durations_seconds"),
            "implicit_filler_source": metrics.get("implicit_filler_source"),
            "fillers_per_minute": metrics.get("fillers_per_minute"),
            "fillers_per_100_words": metrics.get("fillers_per_100_words"),
            "filler_words": metrics.get("filler_words"),
            "filler_reliability": scores.get("filler_metric_reliability"),
            "filler_guard_triggered": metrics.get("filler_guard_triggered"),
            "fillers_used_in_overall": scores.get("fillers_used_in_overall"),
            "pace_used_in_overall": scores.get("pace_used_in_overall"),
            "cross_metric_pace_cap_triggered": metrics.get("cross_metric_pace_cap_triggered"),
            "cross_metric_min_wpm_triggered": metrics.get("cross_metric_min_wpm_triggered"),
            "normal_pause_count": metrics.get("normal_pause_count"),
            "long_pause_count": metrics.get("long_pause_count"),
            "very_long_pause_count": metrics.get("very_long_pause_count"),
            "average_pause_seconds": metrics.get("average_pause_seconds"),
            "longest_pause_seconds": metrics.get("longest_pause_seconds"),
            "pause_time_seconds": metrics.get("pause_time_seconds"),
            "speech_snr_db": metrics.get("speech_snr_db"),
            "noise_floor_dbfs": metrics.get("noise_floor_dbfs"),
            "audio_dynamic_range_db": metrics.get("audio_dynamic_range_db"),
            "discourse_marker_count": metrics.get("discourse_marker_count"),
            "discourse_markers": metrics.get("discourse_markers"),
            "text_reliability": scores.get("text_metric_reliability"),
            "feedback": list(audio.get("feedback", []))[:6],
        },
        "top_priorities": _audio_priorities(audio),
        "meta": {
            "engine": "Clarivo Audio Phase 20 · OpenVINO local",
            "analysis_seconds": round(elapsed, 2),
            "audio_confidence": scores.get("score_confidence"),
            "version": "phase20_cross_metric_hardened",
        },
    }


def _compact_vision(vision: dict[str, Any], elapsed: float) -> dict[str, Any]:
    scores = vision.get("scores", {})
    metrics = vision.get("metrics", {})
    return {
        "schema_version": "clarivo-web-vision-phase20",
        "visual_score": vision.get("vision_score"),
        # Distinguishes a poor delivery from a recording nobody appears in.
        "visual_state": vision.get("visual_state", "PRESENTER_DETECTED"),
        "visual": {
            "attention_score": scores.get("camera_attention"),
            "presence_score": scores.get("presence"),
            "engagement_score": scores.get("engagement"),
            "head_stability_score": scores.get("head_stability"),
            "posture_score": scores.get("posture"),
            # Phase 20 treats gesture as descriptive, not a universal numeric grade.
            "gesture_score": scores.get("gesture"),
            "duration_seconds": metrics.get("duration_seconds"),
            # Browser WebM often carries no duration header; this says which
            # evidence the reported duration came from.
            "duration_source": metrics.get("duration_source"),
            "sample_fps_effective": metrics.get("sample_fps_effective"),
            "forward_percent": metrics.get("forward_percent"),
            "visible_forward_percent": metrics.get("visible_forward_percent"),
            "direct_forward_percent": metrics.get("direct_forward_percent"),
            "looking_away_percent": metrics.get("looking_away_percent"),
            "slight_off_percent": metrics.get("slight_off_percent"),
            "away_percent": metrics.get("away_percent"),
            "held_orientation_percent": metrics.get("held_orientation_percent"),
            "looking_away_episode_count": metrics.get("looking_away_episode_count"),
            "sustained_looking_away_seconds": metrics.get("sustained_looking_away_seconds"),
            "sustained_away_seconds": metrics.get("sustained_away_seconds"),
            "pose_backed_presence_percent": metrics.get("pose_backed_presence_percent"),
            "gaze_estimation_used_percent": metrics.get("gaze_estimation_used_percent"),
            "average_abs_yaw_deg": metrics.get("average_abs_yaw_deg"),
            "average_abs_pitch_deg": metrics.get("average_abs_pitch_deg"),
            "head_motion_p75_deg": metrics.get("head_motion_p75_deg"),
            # New temporal anti-exploit signals.
            "gaze_repeat_triggered": metrics.get("gaze_repeat_triggered"),
            "gaze_repeat_episode_count": metrics.get("gaze_repeat_episode_count"),
            "gaze_accumulated_violation_percent": metrics.get("gaze_accumulated_violation_percent"),
            "head_turn_repeat_triggered": metrics.get("head_turn_repeat_triggered"),
            "head_turn_accumulated_violation_percent": metrics.get("head_turn_accumulated_violation_percent"),
            "posture_good_percent": metrics.get("posture_good_percent"),
            "posture_bad_percent": metrics.get("posture_bad_percent"),
            "posture_repeat_triggered": metrics.get("posture_repeat_triggered"),
            "posture_accumulated_violation_percent": metrics.get("posture_accumulated_violation_percent"),
            "posture_components": metrics.get("posture_components"),
            "posture_mode_distribution": metrics.get("posture_mode_distribution"),
            "gesture_level": metrics.get("gesture_level"),
            "gesture_activity_percent": metrics.get("gesture_activity_percent"),
            "gesture_event_count": metrics.get("gesture_event_count"),
            "arm_keypoint_visible_percent": metrics.get("arm_keypoint_visible_percent"),
            "gesture_reliable": metrics.get("gesture_reliable"),
            "feedback": list(vision.get("feedback", []))[:6],
        },
        "top_priorities": _vision_priorities(vision),
        "meta": {
            "engine": "Clarivo Vision Phase 20 · OpenVINO local",
            "analysis_seconds": round(elapsed, 2),
            "vision_confidence": scores.get("score_confidence"),
            "version": "phase20_temporal_hardened",
        },
    }

def analyze_audio_path(*, audio_path: Path, transcript: str) -> dict[str, Any]:
    """Analyse a WAV already on disk.

    Path-based so the HTTP layer can stream a large upload straight to a temp
    file rather than holding the whole recording in memory.
    """
    if not local_scoring_enabled():
        raise RuntimeError("Local audio analysis is disabled. Set LOCAL_SCORING_ENABLED=true on the local backend.")

    # Audio v11 does not need the vision models when the web transcript is supplied.
    from local_scoring.audio_analyzer import analyze_audio
    from local_scoring.config import AudioConfig

    model_base = models_dir()
    cache_dir = _cache_dir()

    started = time.perf_counter()
    audio = analyze_audio(
        audio_path,
        whisper_model_dir=model_base / "unused-web-transcript",
        device="CPU",
        language="en",
        cache_dir=cache_dir,
        transcript=transcript,
        cfg=AudioConfig(),
    )
    return _compact_audio(audio, time.perf_counter() - started)


def analyze_audio_file(*, audio_wav_bytes: bytes, transcript: str) -> dict[str, Any]:
    """In-memory variant, kept for callers that already hold the bytes."""
    with tempfile.TemporaryDirectory(prefix="clarivo_audio_") as tmp:
        audio_path = Path(tmp) / "audio.wav"
        audio_path.write_bytes(audio_wav_bytes)
        return analyze_audio_path(audio_path=audio_path, transcript=transcript)


def analyze_vision_path(*, video_path: Path) -> dict[str, Any]:
    """Analyse a video already on disk.

    Path-based so a multi-hundred-megabyte upload can be streamed to a temp
    file instead of being buffered whole in memory. The analyzer only ever
    decodes the sampled frames, so file size costs disk, not RAM.
    """
    if not local_scoring_enabled():
        raise RuntimeError("Local vision analysis is disabled. Set LOCAL_SCORING_ENABLED=true on the local backend.")
    if not models_ready():
        raise RuntimeError("OpenVINO vision models are missing. Run: python -m local_scoring.setup_delivery_models")

    from local_scoring.config import VisionConfig
    from local_scoring.vision_analyzer import analyze_video

    paths = _model_paths(models_dir())
    vision_device = _device_choice(os.getenv("LOCAL_VISION_DEVICE", "RECOMMENDED"), "vision")
    pose_device = _device_choice(os.getenv("LOCAL_POSE_DEVICE", "RECOMMENDED"), "pose")
    cache_dir = _cache_dir()

    started = time.perf_counter()
    vision = analyze_video(
        video_path,
        face_model=paths["face"],
        head_pose_model=paths["head"],
        landmarks_model=paths["landmarks"],
        gaze_model=paths["gaze"],
        pose_model_dir=paths["pose"],
        device=vision_device,
        pose_device=pose_device,
        cache_dir=cache_dir,
        cfg=VisionConfig(sample_fps=float(os.getenv("LOCAL_SAMPLE_FPS", "2.0"))),
    )
    return _compact_vision(vision, time.perf_counter() - started)


#: A five-minute talk sampled at 2 fps is 600 frames. The ceiling is generous
#: against that and still bounds how much work one request can ask for.
MAX_TIMELINE_FRAMES = 5_000


def analyze_vision_timeline(
    *,
    frames: list[dict[str, Any]],
    duration_seconds: float,
    sample_fps: float = 0.0,
) -> dict[str, Any]:
    """Score a timeline the browser produced by running models on the viewer's device.

    This is the path that makes visual analysis work on a deployment that cannot
    carry the models. The browser sends what it saw per frame - face count, head
    pose, gaze, pose keypoints - which is a few hundred kilobytes of JSON rather
    than a video that could not fit through the request limit anyway.

    The scoring is the same code the local OpenVINO path uses. Only the source
    of the angles differs, so the decision layer, its thresholds and its tests
    are shared rather than reimplemented.
    """
    from local_scoring.config import VisionConfig
    from local_scoring.vision_analyzer import score_timeline

    if not isinstance(frames, list) or not frames:
        raise ValueError("The vision timeline was empty.")
    if len(frames) > MAX_TIMELINE_FRAMES:
        raise ValueError(
            f"The vision timeline has {len(frames)} frames, over the "
            f"{MAX_TIMELINE_FRAMES} this backend accepts."
        )

    duration = float(duration_seconds or 0.0)
    if duration <= 0.0:
        # Without a duration every "sustained for N seconds" rule would be
        # scaled by an unknown factor. Fall back to the sampling rate the
        # browser reports, and say which evidence was used.
        duration = len(frames) / max(float(sample_fps or 2.0), 0.1)
        duration_source = "sample_count_estimate"
    else:
        duration_source = "browser_recording_duration"

    started = time.perf_counter()
    vision = score_timeline(
        frames,
        duration_seconds=duration,
        duration_source=duration_source,
        cfg=VisionConfig(sample_fps=float(sample_fps or 2.0)),
        source_fps=float(sample_fps or 0.0),
        advanced_frames=len(frames),
        benchmark={"inference_location": "browser", "scored_frames": len(frames)},
    )
    return _compact_vision(vision, time.perf_counter() - started)


def analyze_vision_file(*, video_bytes: bytes, video_suffix: str) -> dict[str, Any]:
    """In-memory variant, kept for callers that already hold the bytes."""
    with tempfile.TemporaryDirectory(prefix="clarivo_vision_") as tmp:
        suffix = video_suffix if video_suffix.startswith(".") else f".{video_suffix}"
        video_path = Path(tmp) / f"video{suffix or '.webm'}"
        video_path.write_bytes(video_bytes)
        return analyze_vision_path(video_path=video_path)


def analyze_delivery_files(
    *,
    audio_wav_bytes: bytes,
    video_bytes: bytes,
    video_suffix: str,
    transcript: str,
) -> dict[str, Any]:
    """Backward-compatible combined analysis endpoint used by older frontends."""
    audio = analyze_audio_file(audio_wav_bytes=audio_wav_bytes, transcript=transcript)
    vision = analyze_vision_file(video_bytes=video_bytes, video_suffix=video_suffix)
    priorities = []
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
