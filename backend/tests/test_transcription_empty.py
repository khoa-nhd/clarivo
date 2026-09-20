"""Regression tests for how an empty transcript is handled.

Whisper legitimately returns an empty transcript: a screen recording made
without a microphone, a video whose audio track is silent, someone who has not
started speaking. That is a *result*, not a failure.

The extractor used to raise on it, and `/api/transcribe` turned the raise into
a 502 "Clarivo could not transcribe this recording", which blocked the whole
upload - including the visual analysis, which needs no transcript at all, and
the transcript box the user could simply have typed into. The error also
pointed at Whisper when Whisper had in fact answered 200.
"""

import sys
import types

_ov = types.ModuleType("openvino")
_ov.Core = object
sys.modules.setdefault("openvino", _ov)

import pytest

from app.cloudflare_transcription import CloudflareTranscriptionError, _extract_text


def test_empty_transcript_is_returned_not_raised():
    assert _extract_text({"result": {"text": ""}}) == ""


def test_whitespace_only_transcript_becomes_empty():
    assert _extract_text({"result": {"text": "   \n  "}}) == ""


def test_normal_transcript_still_works():
    assert _extract_text({"result": {"text": "  Merge sort splits the list.  "}}) == (
        "Merge sort splits the list."
    )


@pytest.mark.parametrize("key", ["text", "transcription", "response"])
def test_every_accepted_field_name_is_read(key):
    assert _extract_text({"result": {key: "hello"}}) == "hello"


def test_bare_string_result_is_accepted():
    assert _extract_text({"result": "hello there"}) == "hello there"


def test_empty_bare_string_is_not_an_error():
    assert _extract_text({"result": ""}) == ""


def test_response_with_no_transcript_field_is_still_an_error():
    """A reply this code does not understand is a genuine failure."""
    with pytest.raises(CloudflareTranscriptionError):
        _extract_text({"result": {"unexpected": 1}})


def test_a_present_but_null_field_is_an_error_not_an_empty_transcript():
    """null is not the same as "", and should not be silently read as silence."""
    with pytest.raises(CloudflareTranscriptionError):
        _extract_text({"result": {"text": None}})


def test_no_stray_print_statements_in_the_request_handlers():
    """A print() in a handler can take the whole request down.

    A debug `print` containing an emoji once sat at the top of the transcribe
    handler. A Windows console runs cp1252, which cannot encode it, so the
    print raised UnicodeEncodeError on every transcription request and the
    generic handler answered 502. Logging never has this failure mode.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parent.parent / "main.py").read_text(encoding="utf-8")
    offenders = [
        line.strip()
        for line in source.splitlines()
        if line.lstrip().startswith("print(")
    ]
    assert offenders == [], f"use logger instead of print in request handlers: {offenders}"
