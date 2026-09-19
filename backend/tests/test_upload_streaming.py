"""Regression tests for how uploads reach disk.

The endpoints used to do `await file.read(max_bytes + 1)`, which holds the
entire recording in memory before writing it out. That was survivable at the
old 80 MB ceiling and is not at the sizes a five-minute capture reaches - a
high-bitrate phone recording is around 160 MB per minute, so five minutes is
most of a gigabyte held in RAM per concurrent request, twice over once the
bytes are copied to a temp file.

Uploads now stream to disk a chunk at a time, and the size cap is enforced
while the bytes arrive rather than after all of them have been buffered.
"""

import sys
import types

_ov = types.ModuleType("openvino")
_ov.Core = object
sys.modules.setdefault("openvino", _ov)

import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException

import main
from app.local_delivery import upload_limits


class FakeUpload:
    """Minimal UploadFile stand-in that records how much was ever handed out."""

    def __init__(self, total_bytes: int, chunk_limit: int | None = None):
        self.remaining = total_bytes
        self.total_bytes = total_bytes
        self.bytes_served = 0
        self.largest_single_read = 0
        self.chunk_limit = chunk_limit

    async def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        take = self.remaining if size is None or size < 0 else min(size, self.remaining)
        if self.chunk_limit is not None:
            take = min(take, self.chunk_limit)
        self.remaining -= take
        self.bytes_served += take
        self.largest_single_read = max(self.largest_single_read, take)
        return b"\0" * take


def _run(coro):
    return asyncio.run(coro)


def test_upload_is_written_in_chunks_not_read_whole(tmp_path):
    """A 40 MB upload must never be requested in one read."""
    upload = FakeUpload(40 * 1024 * 1024)
    destination = tmp_path / "video.mp4"

    written = _run(main._stream_upload(upload, destination, 100 * 1024 * 1024, "The camera recording"))

    assert written == upload.total_bytes
    assert destination.stat().st_size == upload.total_bytes
    assert upload.largest_single_read <= main.UPLOAD_CHUNK_BYTES, (
        f"read {upload.largest_single_read} bytes at once; the whole body must never be buffered"
    )


def test_oversized_upload_is_rejected_before_the_whole_body_is_consumed(tmp_path):
    """The cap is checked as bytes arrive, so a huge file is cut off early."""
    limit = 8 * 1024 * 1024
    upload = FakeUpload(200 * 1024 * 1024)
    destination = tmp_path / "video.mp4"

    with pytest.raises(HTTPException) as excinfo:
        _run(main._stream_upload(upload, destination, limit, "The camera recording"))

    assert excinfo.value.status_code == 413
    assert "MB limit" in excinfo.value.detail
    # Only just past the limit should have been consumed, not the 200 MB body.
    assert upload.bytes_served <= limit + main.UPLOAD_CHUNK_BYTES
    assert upload.bytes_served < upload.total_bytes / 2


def test_empty_upload_is_a_400_not_a_crash(tmp_path):
    upload = FakeUpload(0)
    with pytest.raises(HTTPException) as excinfo:
        _run(main._stream_upload(upload, tmp_path / "x.wav", 1024, "The audio recording"))
    assert excinfo.value.status_code == 400


def test_upload_exactly_at_the_limit_is_accepted(tmp_path):
    limit = 4 * 1024 * 1024
    upload = FakeUpload(limit)
    written = _run(main._stream_upload(upload, tmp_path / "v.mp4", limit, "The camera recording"))
    assert written == limit


def test_limits_are_published_for_the_browser(monkeypatch):
    """The browser enforces the server's numbers rather than its own copy.

    The upload panel used to hard-code 80 MB while the server read
    LOCAL_MAX_VIDEO_BYTES; the two had already drifted apart.
    """
    monkeypatch.setenv("LOCAL_MAX_VIDEO_BYTES", "1024000000")
    monkeypatch.setenv("LOCAL_MAX_AUDIO_WAV_BYTES", "64000000")
    monkeypatch.setenv("MAX_RECORDING_SECONDS", "300")

    limits = upload_limits()
    assert limits["max_video_bytes"] == 1_024_000_000
    assert limits["max_audio_wav_bytes"] == 64_000_000
    assert limits["max_recording_seconds"] == 300

    # A five-minute capture at a high phone-recording bitrate must fit.
    five_minutes_at_160mb_per_minute = 5 * 160 * 1024 * 1024
    assert limits["max_video_bytes"] > five_minutes_at_160mb_per_minute


def test_default_video_ceiling_covers_five_minutes():
    from app.local_delivery import DEFAULT_MAX_VIDEO_BYTES

    assert DEFAULT_MAX_VIDEO_BYTES >= 5 * 160 * 1024 * 1024
