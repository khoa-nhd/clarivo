"""The endpoint that scores visual delivery without the models being here.

/api/analyze/vision runs OpenVINO over an uploaded video and therefore only
exists on a machine carrying ~970 MB of wheels and 58 MB of weights. On the
deployed backend neither the wheels nor the video can arrive - the stack is
twice the 500 MB function limit, and a recording is many times the 4.5 MB
request body cap.

/api/analyze/vision-timeline takes what the browser's own models saw instead.
These tests pin that it works with none of the heavy stack importable, and that
a malformed timeline is a 422 rather than a 500.
"""

import math
import sys
import types

_ov = types.ModuleType("openvino")
_ov.Core = object
sys.modules.setdefault("openvino", _ov)

import pytest
from starlette.testclient import TestClient

import main
from local_scoring.vision_analyzer import COCO

LAYOUT = {
    "nose": (64, 28), "left_eye": (58, 25), "right_eye": (70, 25),
    "left_ear": (52, 28), "right_ear": (76, 28),
    "left_shoulder": (46, 52), "right_shoulder": (82, 52),
    "left_elbow": (40, 78), "right_elbow": (88, 78),
    "left_wrist": (38, 100), "right_wrist": (90, 100),
    "left_hip": (50, 104), "right_hip": (78, 104),
}


def _pose():
    xy = [[0.0, 0.0] for _ in range(13)]
    conf = [0.0] * 13
    for name, (x, y) in LAYOUT.items():
        xy[COCO[name]] = [float(x), float(y)]
        conf[COCO[name]] = 0.9
    return {"xy": xy, "conf": conf}


def _timeline(count=120):
    frames = []
    for i in range(count):
        yaw = 40.0 if 60 <= i < 90 else 2.0 * math.sin(i / 6.0)
        frames.append({
            "face_count": 1,
            "head_pose": [yaw, 1.0, 0.5],
            "gaze": [yaw * 0.8, 0.9, 0.7],
            "pose": _pose(),
            "pose_attempted": True,
        })
    return frames


@pytest.fixture(scope="module")
def client():
    with TestClient(main.app) as c:
        yield c


def test_a_browser_timeline_is_scored(client):
    response = client.post("/api/analyze/vision-timeline", json={
        "frames": _timeline(), "duration_seconds": 60.0, "sample_fps": 2.0,
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["visual_score"] is not None
    assert body["visual"]["attention_score"] is not None
    assert body["visual"]["posture_score"] is not None


def test_health_advertises_the_browser_path(client):
    delivery = client.get("/api/health").json()["delivery_analysis"]
    # True wherever NumPy is installed, which is every deployment of this app.
    assert delivery["vision_timeline_ready"] is True


def test_a_sustained_turn_lowers_attention_against_a_centred_talk(client):
    """The scoring must still respond to the signal, not just return a number."""
    centred = [dict(f, head_pose=[0.0, 1.0, 0.5], gaze=[0.0, 0.9, 0.7]) for f in _timeline()]
    body = {"duration_seconds": 60.0, "sample_fps": 2.0}
    good = client.post("/api/analyze/vision-timeline", json={**body, "frames": centred}).json()
    turned = client.post("/api/analyze/vision-timeline", json={**body, "frames": _timeline()}).json()
    assert turned["visual"]["attention_score"] < good["visual"]["attention_score"]


def test_an_empty_timeline_is_a_422(client):
    response = client.post("/api/analyze/vision-timeline", json={
        "frames": [], "duration_seconds": 10.0, "sample_fps": 2.0,
    })
    assert response.status_code == 422


def test_an_oversized_timeline_is_refused(client):
    """One request must not be able to ask for unbounded work."""
    response = client.post("/api/analyze/vision-timeline", json={
        "frames": _timeline(1) * 5001, "duration_seconds": 60.0, "sample_fps": 2.0,
    })
    assert response.status_code == 422


def test_a_missing_duration_falls_back_to_the_sample_rate(client):
    """Without this every "sustained for N seconds" rule is scaled by guesswork."""
    response = client.post("/api/analyze/vision-timeline", json={
        "frames": _timeline(), "duration_seconds": 0.0, "sample_fps": 2.0,
    })
    assert response.status_code == 200
    # 120 frames at 2 fps is a minute.
    assert response.json()["visual"]["duration_seconds"] == pytest.approx(60.0, abs=0.5)


def test_a_wrongly_shaped_head_pose_is_rejected_by_validation(client):
    response = client.post("/api/analyze/vision-timeline", json={
        "frames": [{"face_count": 1, "head_pose": [1.0, 2.0], "pose_attempted": False}],
        "duration_seconds": 10.0, "sample_fps": 2.0,
    })
    assert response.status_code == 422


def test_frames_with_no_face_are_scored_as_absence_not_rejected(client):
    """A presenter who steps out of shot is a result, not a bad request."""
    frames = [{"face_count": 0, "head_pose": None, "gaze": None,
               "pose": None, "pose_attempted": True} for _ in range(60)]
    response = client.post("/api/analyze/vision-timeline", json={
        "frames": frames, "duration_seconds": 30.0, "sample_fps": 2.0,
    })
    assert response.status_code == 200
    assert response.json()["visual"]["presence_score"] is not None
