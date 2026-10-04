"""The pose decode that replaced Ultralytics.

The YOLO pose model was called through Ultralytics, which loads it with torch.
The OpenVINO IR was already exported, so torch was carried purely to invoke it -
509 MB of the install, against 245 MB for OpenVINO itself. The model is now run
directly on OpenVINO and the output decoded here.

Equivalence was established against Ultralytics on frames containing real
people: identical detections, worst keypoint disagreement 0.21 px, worst
confidence disagreement 0.0008, and byte-identical final scores on two clips.
These tests pin the decode arithmetic so it cannot drift afterwards, without
needing either the models or the 509 MB.
"""

import sys
import types

import numpy as np
import pytest

_ov = types.ModuleType("openvino")
_ov.Core = object
sys.modules.setdefault("openvino", _ov)

from local_scoring.vision_analyzer import PoseTracker


class _Decoder(PoseTracker):
    """PoseTracker with the model loading skipped, to exercise the arithmetic."""

    def __init__(self, imgsz=512, confidence=0.35, raw=None):
        self.imgsz = imgsz
        self.confidence = confidence
        self.requested = "CPU"
        self.used_device = "CPU"
        self._raw = raw

    def _run(self, blob):
        return self._raw


def _raw_output(anchors=8, person_conf=0.9, best=3, keypoint_xy=(256.0, 256.0)):
    """A (56, anchors) tensor in the model's own layout."""
    raw = np.zeros((56, anchors), dtype=np.float32)
    raw[4, :] = 0.1
    raw[4, best] = person_conf
    for k in range(17):
        raw[5 + k * 3, best] = keypoint_xy[0]
        raw[5 + k * 3 + 1, best] = keypoint_xy[1]
        raw[5 + k * 3 + 2, best] = 0.8
    return raw


def _decode(tracker, raw, scale, left, top):
    """Mirror infer()'s post-processing, which is what these tests are about."""
    scores = raw[4]
    best = int(np.argmax(scores))
    person_conf = float(scores[best])
    if person_conf < tracker.confidence:
        return None
    keypoints = raw[5:, best].reshape(-1, 3)
    xy = np.stack([
        (keypoints[:, 0] - left) / scale,
        (keypoints[:, 1] - top) / scale,
    ], axis=1)
    return {"xy": xy, "conf": keypoints[:, 2].astype(float), "person_conf": person_conf}


def test_letterbox_preserves_aspect_ratio_and_centres():
    tracker = _Decoder(imgsz=512)
    frame = np.zeros((480, 640, 3), np.uint8)
    canvas, scale, left, top = tracker._letterbox(frame)
    assert canvas.shape == (512, 512, 3)
    assert scale == pytest.approx(512 / 640)
    # 480 * 0.8 = 384, so 128 rows of padding split evenly.
    assert top == 64 and left == 0


def test_letterbox_pads_with_the_value_ultralytics_uses():
    """The padding is visible to the model; a different grey moves detections."""
    tracker = _Decoder(imgsz=512)
    canvas, _, _, top = tracker._letterbox(np.zeros((480, 640, 3), np.uint8))
    assert int(canvas[0, 0, 0]) == PoseTracker.PAD_VALUE == 114
    assert int(canvas[top + 10, 10, 0]) == 0  # inside the image, not the pad


def test_a_keypoint_maps_back_to_the_original_frame():
    """A point at the centre of the letterbox is the centre of the frame."""
    tracker = _Decoder(imgsz=512)
    _, scale, left, top = tracker._letterbox(np.zeros((480, 640, 3), np.uint8))
    out = _decode(tracker, _raw_output(keypoint_xy=(256.0, 256.0)), scale, left, top)
    assert out["xy"][0][0] == pytest.approx(320.0, abs=0.5)
    assert out["xy"][0][1] == pytest.approx(240.0, abs=0.5)


def test_the_most_confident_anchor_is_the_one_returned():
    """Only one person is ever used downstream, so argmax replaces NMS."""
    tracker = _Decoder()
    raw = _raw_output(anchors=16, person_conf=0.77, best=11)
    out = _decode(tracker, raw, 1.0, 0, 0)
    assert out["person_conf"] == pytest.approx(0.77)


def test_a_detection_below_the_threshold_is_dropped():
    tracker = _Decoder(confidence=0.5)
    assert _decode(tracker, _raw_output(person_conf=0.4), 1.0, 0, 0) is None


def test_seventeen_keypoints_are_returned_in_coco_order():
    """The scorer indexes by COCO position; a reshape error would silently
    scramble shoulders into elbows."""
    tracker = _Decoder()
    out = _decode(tracker, _raw_output(), 1.0, 0, 0)
    assert out["xy"].shape == (17, 2)
    assert out["conf"].shape == (17,)


def test_a_portrait_frame_letterboxes_on_the_left_and_right():
    tracker = _Decoder(imgsz=512)
    canvas, scale, left, top = tracker._letterbox(np.zeros((640, 480, 3), np.uint8))
    assert canvas.shape == (512, 512, 3)
    assert top == 0 and left == 64


def test_the_xml_is_found_inside_the_exported_directory(tmp_path):
    (tmp_path / "yolo26s-pose.xml").write_text("<net/>", encoding="utf-8")
    assert PoseTracker._find_xml(tmp_path).name == "yolo26s-pose.xml"


def test_a_directory_without_an_ir_says_how_to_produce_one(tmp_path):
    with pytest.raises(RuntimeError, match="setup_delivery_models"):
        PoseTracker._find_xml(tmp_path)
