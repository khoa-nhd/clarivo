"""Regression tests for the camera-attention decision layer.

Two bugs are guarded here:

1. Camera-bias calibration only searched the opening ~20 seconds of a session.
   A presenter who began by facing a slide had that turn absorbed into the
   baseline, after which the look-away was normalised to "centred" and never
   reported.
2. The engaged / slight-off / off-axis banding had no hysteresis, so a
   presenter sitting near a threshold flickered between bands and one
   continuous look-away was reported as a string of short ones - which could
   trip the "repeated short glances" rule from a single sustained glance.
"""

import sys
import types

_ov = types.ModuleType("openvino")
_ov.Core = object
sys.modules.setdefault("openvino", _ov)

import pytest

from local_scoring.cv_temporal_benchmark import evaluate_sequence, run
from local_scoring.config import VisionConfig
from local_scoring.synthetic_vision import attention_suite, build_sequence

PRE_FIX = VisionConfig(gaze_calibration_use_full_session=False, orientation_hysteresis_points=0.0)


def _by_name(name):
    return next(s for s in attention_suite() if s.name == name)


def test_calibration_survives_an_off_axis_opening():
    sequence = _by_name("early_look_away_then_centred")
    result = evaluate_sequence(sequence, VisionConfig())
    assert result["fn"] == 0, "sustained look-away at the start of the session was missed"
    assert result["camera_bias_yaw_error_deg"] <= 3.0

    regressed = evaluate_sequence(sequence, PRE_FIX)
    assert regressed["fn"] == 1, "this sequence should still expose the old behaviour"


def test_hysteresis_keeps_one_look_away_as_one_event():
    """A single continuous look-away near a band boundary must not fragment."""
    sequence = build_sequence(
        "boundary_hover",
        duration_seconds=60.0,
        look_away_episodes=((20.0, 32.0, 43.0),),
        jitter_deg=3.0,
        seed=77,
    )
    cfg = VisionConfig()
    result = evaluate_sequence(sequence, cfg)
    assert result["predicted_events"] == 1, (
        f"one 12 s look-away reported as {result['predicted_events']} separate events"
    )
    assert result["fp"] == 0 and result["fn"] == 0


def test_brief_isolated_glance_is_tolerated():
    result = evaluate_sequence(_by_name("single_glance_1s"), VisionConfig())
    assert result["predicted_events"] == 0
    assert result["tolerated_glances"] == 1


def test_clustered_short_glances_are_reported():
    result = evaluate_sequence(_by_name("repeated_short_glances"), VisionConfig())
    assert result["tp"] == result["true_events"] > 0
    assert result["fp"] == 0


@pytest.mark.parametrize("name", ["clean_engaged", "high_jitter_engaged", "detector_dropouts"])
def test_engaged_sequences_produce_no_events(name):
    result = evaluate_sequence(_by_name(name), VisionConfig())
    assert result["predicted_events"] == 0


def test_suite_level_event_detection_is_exact():
    _, summary = run()
    event = summary["event_level"]
    assert event["precision"] == 1.0
    assert event["recall"] == 1.0
    assert summary["false_alarms_on_clean_sequences"] == 0
    # The sustain window is a deliberate delay; it must stay close to it and not
    # grow into feedback that no longer matches what the presenter did.
    assert summary["max_detection_latency_seconds"] <= VisionConfig().gaze_sustain_seconds
