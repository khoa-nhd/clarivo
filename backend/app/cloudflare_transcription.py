from __future__ import annotations

import base64
import os
from typing import Any

import requests


class CloudflareTranscriptionError(RuntimeError):
    pass


def _get_credentials() -> tuple[str, str, str]:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    auth_token = os.getenv("CLOUDFLARE_AUTH_TOKEN", "").strip()
    model = os.getenv(
        "CLOUDFLARE_TRANSCRIPTION_MODEL",
        "@cf/openai/whisper-large-v3-turbo",
    ).strip()

    if not account_id:
        raise CloudflareTranscriptionError(
            "CLOUDFLARE_ACCOUNT_ID is missing. Add your Cloudflare Account ID to backend/.env."
        )
    if not auth_token:
        raise CloudflareTranscriptionError(
            "CLOUDFLARE_AUTH_TOKEN is missing. Add your Workers AI API token to backend/.env."
        )
    if not model:
        raise CloudflareTranscriptionError("Cloudflare transcription model is not configured.")

    return account_id, auth_token, model


def _extract_text(payload: dict[str, Any]) -> str:
    result: Any = payload.get("result", payload)

    if isinstance(result, dict):
        for key in ("text", "transcription", "response"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    if isinstance(result, str) and result.strip():
        return result.strip()

    raise CloudflareTranscriptionError(
        "Whisper returned a response but no transcript text was found."
    )


def transcribe_audio(
    audio_bytes: bytes,
    *,
    topic: str = "",
    timeout: float | None = None,
) -> dict[str, Any]:
    """Transcribe one English presentation recording with Workers AI Whisper.

    The browser sends the original compressed MediaRecorder blob (normally
    WebM/Opus). We Base64-encode the bytes only inside the backend so the
    Cloudflare token never reaches the browser.
    """
    account_id, auth_token, model = _get_credentials()
    timeout = timeout or float(os.getenv("TRANSCRIPTION_TIMEOUT_SECONDS", "120"))

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    encoded_audio = base64.b64encode(audio_bytes).decode("ascii")

    initial_prompt = (
        "This is an English student presentation. Preserve technical terms, "
        "mathematical vocabulary, acronyms, and proper nouns accurately."
    )
    if topic.strip():
        initial_prompt += f" The presentation topic is: {topic.strip()}."

    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json",
            },
            json={
                "audio": encoded_audio,
                "task": "transcribe",
                "language": "en",
                "vad_filter": True,
                "condition_on_previous_text": True,
                "initial_prompt": initial_prompt,
            },
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise CloudflareTranscriptionError(
            "Audio transcription timed out. Retry transcription without recording again."
        ) from exc
    except requests.RequestException as exc:
        raise CloudflareTranscriptionError(
            f"Could not reach Cloudflare transcription: {exc}"
        ) from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise CloudflareTranscriptionError(
            f"Cloudflare transcription returned a non-JSON response ({response.status_code})."
        ) from exc

    if not response.ok or payload.get("success") is False:
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            messages = [
                item.get("message", str(item)) if isinstance(item, dict) else str(item)
                for item in errors
            ]
            detail = "; ".join(messages)
        else:
            detail = payload.get("message") or f"HTTP {response.status_code}"
        raise CloudflareTranscriptionError(f"Cloudflare transcription failed: {detail}")

    text = _extract_text(payload)
    return {
        "text": text,
        "word_count": len(text.split()),
        "model": model,
    }
