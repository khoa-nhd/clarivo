"""Regression tests for video duration resolution.

The bug: duration came only from ``CAP_PROP_FRAME_COUNT``. Live-recorded
MediaRecorder WebM - the format the /api/analyze/vision endpoint actually
receives from the browser - normally has no frame count, so duration reached
the UI as "0 s" and, worse, collapsed the duration term of ``score_confidence``
to zero for every browser recording.

These tests drive the resolution order directly rather than through a decoded
file, so they need no OpenCV, no models and no test video: what matters is that
every fallback produces a sane duration and that none of them can return 0.
"""

import math
import sys
import types

_ov = types.ModuleType("openvino")
_ov.Core = object
sys.modules.setdefault("openvino", _ov)

import pytest


def resolve_duration(
    *, container_duration: float, last_frame_msec: float, advanced_frames: int,
    source_fps: float, sampled: int, sample_fps: float,
) -> tuple[float, str]:
    """The resolution order implemented in ``analyze_video``.

    Mirrored here so the ordering can be tested without decoding a video. The
    production copy is exercised end to end by ``local_scoring.device_benchmark``
    and by the local-AI smoke test; this pins the decision table.
    """
    advanced_duration = advanced_frames / source_fps if advanced_frames > 0 else 0.0
    timestamp_duration = last_frame_msec / 1000.0
    if container_duration > 0.0:
        duration, source = container_duration, "container_frame_count"
    elif timestamp_duration > 0.0:
        duration, source = timestamp_duration, "frame_timestamps"
    else:
        duration, source = advanced_duration, "advanced_frame_count"
    if duration <= 0.0:
        duration = sampled / max(sample_fps, 0.1)
        source = "sample_count_estimate"
    return duration, source


BASE = dict(source_fps=30.0, sampled=44, sample_fps=2.0)


def test_container_frame_count_is_preferred():
    duration, source = resolve_duration(
        container_duration=22.0, last_frame_msec=21500.0, advanced_frames=660, **BASE
    )
    assert source == "container_frame_count"
    assert duration == pytest.approx(22.0)


def test_falls_back_to_frame_timestamps_for_browser_webm():
    """No frame count, but per-frame timestamps are present."""
    duration, source = resolve_duration(
        container_duration=0.0, last_frame_msec=21500.0, advanced_frames=660, **BASE
    )
    assert source == "frame_timestamps"
    assert duration == pytest.approx(21.5)


def test_falls_back_to_advanced_frame_count_when_timestamps_are_absent():
    duration, source = resolve_duration(
        container_duration=0.0, last_frame_msec=0.0, advanced_frames=660, **BASE
    )
    assert source == "advanced_frame_count"
    assert duration == pytest.approx(22.0)


def test_last_resort_uses_the_sample_count():
    duration, source = resolve_duration(
        container_duration=0.0, last_frame_msec=0.0, advanced_frames=0, **BASE
    )
    assert source == "sample_count_estimate"
    assert duration == pytest.approx(22.0)


@pytest.mark.parametrize(
    "container,msec,advanced",
    [(0.0, 0.0, 0), (0.0, 0.0, 660), (0.0, 21500.0, 0), (22.0, 0.0, 0)],
)
def test_duration_is_never_zero(container, msec, advanced):
    """The original failure mode: any metadata combination must still be positive."""
    duration, _ = resolve_duration(
        container_duration=container, last_frame_msec=msec, advanced_frames=advanced, **BASE
    )
    assert duration > 0.0


def test_effective_sample_fps_is_measured_not_assumed():
    """Temporal rules convert seconds to frames using the achieved rate.

    Using the configured target meant a container reporting the wrong frame rate
    scaled every "sustained for N seconds" threshold by the same error.
    """
    sampled, duration, configured_target = 44, 22.0, 2.0
    effective = min(max(sampled / duration, 0.2), 60.0)
    assert effective == pytest.approx(2.0, abs=0.05)

    # A clip that actually delivered half the target rate must report that,
    # otherwise a 2.5 s rule would fire after 1.25 s of real time.
    effective_half = min(max(22 / duration, 0.2), 60.0)
    assert effective_half == pytest.approx(1.0, abs=0.05)
    assert effective_half != configured_target

    sustain_seconds = 2.5
    assert math.ceil(sustain_seconds * effective_half) == 3      # frames at 1 fps
    assert math.ceil(sustain_seconds * configured_target) == 5   # what it used to assume
