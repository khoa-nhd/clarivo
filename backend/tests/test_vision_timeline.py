"""The contract between vision inference and vision scoring.

``analyze_video`` used to decode a file, run four models over it and score the
result in one 700-line function. The models are about 970 MB of wheels - torch
alone is 543 MB - against a 500 MB serverless limit, and a camera recording
cannot reach a serverless function at all through a 4.5 MB request body cap. So
the deployed backend could never score video, no matter how it was configured.

``score_timeline`` is the scoring half on its own: pure NumPy, importable with
no OpenCV, OpenVINO, Ultralytics or torch present, and fed a timeline of what
some model saw rather than pixels. That lets the browser run the models and the
backend keep the scoring - the part that is tested, benchmarked and carries
every decision.

The numbers below were captured from the single-function version before the
split, with the inference layer scripted so the result depends only on the
scoring half. They are here to catch a change in scoring dressed up as a
refactor.
"""

import math
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from local_scoring.config import VisionConfig
from local_scoring.vision_analyzer import COCO, score_timeline

SAMPLES = 80


def _pose(i: int):
    if 30 <= i < 40:
        return None
    jitter = 0.4 * math.sin(i / 5.0)
    xy = [[0.0, 0.0] for _ in range(13)]
    conf = [0.0] * 13
    layout = {
        "nose": (64, 28), "left_eye": (58, 25), "right_eye": (70, 25),
        "left_ear": (52, 28), "right_ear": (76, 28),
        "left_shoulder": (46, 52), "right_shoulder": (82, 52 + jitter),
        "left_elbow": (40, 78), "right_elbow": (88, 78),
        "left_wrist": (38, 100), "right_wrist": (90, 100),
        "left_hip": (50, 104), "right_hip": (78, 104),
    }
    for name, (x, y) in layout.items():
        idx = COCO[name]
        xy[idx] = [float(x), float(y)]
        conf[idx] = 0.35 if (i >= 60 and "wrist" in name) else 0.9
    return {"xy": xy, "conf": conf}


def _frame(i: int):
    """One sampled frame: centred, then out of frame, then a sustained turn."""
    record = {"face_count": 0, "head_pose": None, "gaze": None,
              "pose": _pose(i), "pose_attempted": True}
    if 30 <= i < 40:
        return record
    if 40 <= i < 60:
        record["face_count"] = 1
        record["head_pose"] = (38.0 + 0.5 * (i - 40), 4.0, 2.0)
        return record
    yaw = 2.0 * math.sin(i / 6.0)
    pitch = 1.5 * math.cos(i / 7.0)
    record["face_count"] = 1
    record["head_pose"] = (yaw, pitch, 1.0 * math.sin(i / 11.0))
    record["gaze"] = (yaw * 0.8, pitch * 0.9, 0.7)
    return record


def _timeline():
    return [_frame(i) for i in range(SAMPLES)]


@pytest.fixture(scope="module")
def result():
    return score_timeline(
        _timeline(),
        duration_seconds=8.0,
        duration_source="container_frame_count",
        cfg=VisionConfig(sample_fps=10.0, pose_every_n_samples=1),
        source_fps=10.0,
        advanced_frames=SAMPLES,
    )


def test_the_scorer_runs_without_the_computer_vision_stack():
    """Guards the whole reason for the split.

    Run in a fresh interpreter with the heavy modules poisoned, because by the
    time the rest of this suite has run they are long since imported and an
    in-process check would pass for the wrong reason.
    """
    script = textwrap.dedent("""
        import sys
        for name in ("openvino", "cv2", "ultralytics", "torch"):
            sys.modules[name] = None          # any import of these now raises
        from local_scoring.vision_analyzer import score_timeline
        out = score_timeline(
            [{"face_count": 1, "head_pose": (0.0, 0.0, 0.0),
              "gaze": None, "pose": None, "pose_attempted": False}] * 20,
            duration_seconds=2.0, duration_source="container_frame_count",
        )
        assert out["vision_score"] is not None
        print("OK")
    """)
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).resolve().parent.parent),
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr[-1500:]
    assert "OK" in proc.stdout


@pytest.mark.parametrize(("name", "expected"), [
    ("overall", 88.8),
    ("camera_attention", 85.0),
    ("engagement", 82.8),
    ("presence", 95.0),
    ("head_stability", 93.4),
    ("posture", 95.1),
    ("score_confidence", 67.2),
])
def test_scores_match_the_pre_split_implementation(result, name, expected):
    assert result["scores"][name] == pytest.approx(expected, abs=0.05)


def test_vision_score_matches_the_pre_split_implementation(result):
    assert result["vision_score"] == pytest.approx(88.8, abs=0.05)


@pytest.mark.parametrize(("name", "expected"), [
    ("sampled_frames", 80),
    ("forward_frames", 51),
    ("slight_off_frames", 4),
    ("looking_away_frames", 15),
    ("away_frames", 0),
    ("sample_fps_effective", 10.0),
    ("duration_seconds", 8.0),
    ("posture_good_percent", 100.0),
    ("posture_bad_percent", 0.0),
    ("head_motion_median_deg", 0.324),
])
def test_metrics_match_the_pre_split_implementation(result, name, expected):
    assert result["metrics"][name] == pytest.approx(expected, abs=0.05)


def test_the_sustained_turn_is_still_detected(result):
    """Frames 40-59 are a single 2 s turn; it must not vanish in the split."""
    assert result["metrics"]["looking_away_frames"] == 15


def test_a_face_box_without_a_head_pose_counts_as_no_orientation():
    """A detector that finds a face but yields no angles gives no evidence.

    The browser path can produce this - a face is detected at the edge of the
    frame but the transformation matrix is degenerate - and inventing an angle
    for it would quietly bias the calibration.
    """
    frames = [dict(_frame(i), head_pose=None, gaze=None) for i in range(SAMPLES)]
    out = score_timeline(
        frames, duration_seconds=8.0, duration_source="container_frame_count",
        cfg=VisionConfig(sample_fps=10.0, pose_every_n_samples=1),
    )
    assert out["metrics"]["forward_frames"] == 0


def test_a_malformed_angle_triple_is_rejected_rather_than_scored():
    """NaN must not reach the calibrator, where it would poison every later frame."""
    frames = [dict(_frame(i), head_pose=(float("nan"), 0.0, 0.0)) for i in range(SAMPLES)]
    out = score_timeline(
        frames, duration_seconds=8.0, duration_source="container_frame_count",
        cfg=VisionConfig(sample_fps=10.0, pose_every_n_samples=1),
    )
    assert out["metrics"]["forward_frames"] == 0
    assert math.isfinite(float(out["vision_score"]))


def test_an_empty_timeline_is_an_error_not_a_zero_score():
    """Scoring nothing as 0 would be indistinguishable from a terrible talk."""
    with pytest.raises(RuntimeError):
        score_timeline([], duration_seconds=8.0, duration_source="x")
