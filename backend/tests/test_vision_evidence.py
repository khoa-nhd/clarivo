"""What the visual score is allowed to say, given what was actually observed.

Three questions were being collapsed into one:

    was the presenter in shot?        - the body model answers this
    where were they looking?          - only the face model answers this
    could we tell where they looked?  - nobody was asking

A frame with no face became "away". So a presenter the body model saw at full
confidence in every single frame, standing with good posture, was scored
presence 0 and away 100% - while the report's own
`pose_backed_presence_percent` said 100. The system knew they were there and
said they were not.

Separately, components with no observations behind them were still scored: a
recording of an empty room was given 94 for head stability, because with no
head ever detected the motion list is empty, the median is zero, and the curve
reads that as perfect stillness.
"""

import sys
import types

_ov = types.ModuleType("openvino")
_ov.Core = object
sys.modules.setdefault("openvino", _ov)

import pytest

from local_scoring.config import VisionConfig
from local_scoring.vision_analyzer import COCO, score_timeline

CFG = VisionConfig(sample_fps=2.0)
FRAMES = 24
DURATION = 12.0

LAYOUT = {
    "nose": (320, 200), "left_eye": (340, 185), "right_eye": (300, 185),
    "left_ear": (360, 195), "right_ear": (280, 195),
    "left_shoulder": (390, 300), "right_shoulder": (250, 300),
    "left_elbow": (410, 380), "right_elbow": (230, 380),
    "left_wrist": (420, 450), "right_wrist": (220, 450),
    "left_hip": (380, 470), "right_hip": (260, 470),
}


def _pose():
    xy = [[0.0, 0.0] for _ in range(13)]
    conf = [0.0] * 13
    for name, (x, y) in LAYOUT.items():
        xy[COCO[name]] = [float(x), float(y)]
        conf[COCO[name]] = 1.0
    return {"xy": xy, "conf": conf}


def _frame(*, face, yaw=0.5, body=True):
    return {
        "face_count": 1 if face else 0,
        "head_pose": [yaw, 1.0, 0.3] if face else None,
        "gaze": [yaw * 0.8, 0.9, 0.7] if face else None,
        "pose": _pose() if body else None,
        "pose_attempted": True,
    }


def _score(frames):
    return score_timeline(frames, duration_seconds=DURATION,
                          duration_source="browser_recording_duration", cfg=CFG)


@pytest.fixture(scope="module")
def facing():
    return _score([_frame(face=True) for _ in range(FRAMES)])


@pytest.fixture(scope="module")
def body_only():
    """Visible to the body model throughout; the face model never finds a face."""
    return _score([_frame(face=False) for _ in range(FRAMES)])


@pytest.fixture(scope="module")
def empty_room():
    return _score([_frame(face=False, body=False) for _ in range(FRAMES)])


@pytest.fixture(scope="module")
def turned_away():
    """Facing the camera, then turned 45 degrees away for half the session."""
    return _score([_frame(face=True, yaw=45.0 if 8 <= i < 20 else 1.0) for i in range(FRAMES)])


# ------------------------------------------------- presence is not attention

def test_a_presenter_the_body_model_sees_is_present(body_only):
    assert body_only["scores"]["presence"] > 80


def test_a_presenter_the_body_model_sees_is_not_counted_as_away(body_only):
    assert body_only["metrics"]["away_percent"] == 0.0


def test_those_frames_are_reported_as_unmeasurable_rather_than_hidden(body_only):
    assert body_only["metrics"]["orientation_unknown_percent"] == 100.0


def test_an_empty_room_is_still_absence(empty_room):
    assert empty_room["scores"]["presence"] == 0.0
    assert empty_room["metrics"]["away_percent"] == 100.0


# --------------------------------------------- nothing scored without evidence

def test_attention_is_withheld_when_orientation_was_never_measured(body_only):
    assert body_only["scores"]["camera_attention"] is None


def test_attention_is_given_when_orientation_was_measured(facing):
    assert facing["scores"]["camera_attention"] is not None
    assert facing["scores"]["camera_attention"] > 80


def test_head_stability_is_withheld_without_head_observations(empty_room):
    """It used to be 94 - absence of evidence scored as evidence of excellence."""
    assert empty_room["scores"]["head_stability"] is None


def test_an_empty_room_gets_no_grade_at_all(empty_room):
    assert empty_room["vision_score"] is None
    assert empty_room["visual_state"] == "NO_PRESENTER_DETECTED"


def test_a_real_recording_does_get_a_grade(facing):
    assert facing["vision_score"] is not None
    assert facing["visual_state"] == "PRESENTER_DETECTED"


# ------------------------------------------------- it responds to the behaviour

def test_turning_away_scores_lower_than_facing_the_camera(facing, turned_away):
    """The whole point. Without this the score is not measuring anything."""
    assert turned_away["vision_score"] < facing["vision_score"] - 5


def test_turning_away_lowers_attention_specifically(facing, turned_away):
    assert turned_away["scores"]["camera_attention"] < facing["scores"]["camera_attention"] - 10


def test_unmeasured_attention_lowers_confidence_rather_than_the_grade(facing, body_only):
    assert body_only["scores"]["score_confidence"] < facing["scores"]["score_confidence"]


# ------------------------------------------------------------------- feedback

def test_no_advice_is_given_about_a_direction_that_was_never_measured(body_only):
    joined = " ".join(body_only["feedback"]).lower()
    assert "off the camera/audience axis" not in joined
    assert "head orientation was mixed" not in joined


def test_the_reason_eye_contact_is_missing_is_stated(body_only):
    assert any("could not be assessed" in line for line in body_only["feedback"])


def test_a_measured_session_still_gets_orientation_advice(turned_away):
    joined = " ".join(turned_away["feedback"]).lower()
    assert "could not be assessed" not in joined
