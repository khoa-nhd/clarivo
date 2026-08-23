from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import openvino as ov
from ultralytics import YOLO

from .config import VisionConfig
from .device_utils import create_core, fallback_chain
from .utils import clamp, piecewise_linear, safe_mean, safe_std

COCO = {
    "nose":0, "left_eye":1, "right_eye":2, "left_ear":3, "right_ear":4,
    "left_shoulder":5, "right_shoulder":6, "left_elbow":7, "right_elbow":8,
    "left_wrist":9, "right_wrist":10, "left_hip":11, "right_hip":12,
}

def _safe_float(val, default: float = 0.0) -> float:
    """Safely parse a finite float and reject NaN/Inf."""
    if val is None:
        return float(default)
    try:
        value = float(val)
    except (ValueError, TypeError):
        return float(default)
    return value if math.isfinite(value) else float(default)


def _ultra_device(d: str) -> str:
    d = d.lower()
    if d.startswith("intel:"):
        return d
    if d in {"cpu", "gpu", "npu"}:
        return f"intel:{d}"
    return "intel:cpu"


class OpenVINOHeadTracker:
    def __init__(self, face_xml: Path, head_xml: Path, device: str, cache_dir: Path,
                 landmarks_xml: Path | None = None, gaze_xml: Path | None = None):
        self.core = create_core(cache_dir / "runtime")
        self.face, self.face_device = self._compile(face_xml, device)
        self.head, self.head_device = self._compile(head_xml, device)
        self.landmarks = self.gaze = None
        self.landmarks_device = self.gaze_device = "DISABLED"
        if landmarks_xml is not None and Path(landmarks_xml).exists():
            try:
                self.landmarks, self.landmarks_device = self._compile(Path(landmarks_xml), device)
            except Exception as exc:
                print(f"      Facial landmarks unavailable: {type(exc).__name__}")
        if gaze_xml is not None and Path(gaze_xml).exists():
            try:
                self.gaze, self.gaze_device = self._compile(Path(gaze_xml), device)
            except Exception as exc:
                print(f"      Gaze model unavailable: {type(exc).__name__}")

    def _compile(self, xml: Path, requested: str):
        model = self.core.read_model(str(xml))
        last = None
        for d in fallback_chain(requested, include_auto=True):
            try:
                try:
                    compiled = self.core.compile_model(model, d, {"PERFORMANCE_HINT": "LATENCY"})
                except Exception:
                    compiled = self.core.compile_model(model, d)
                if d != requested.upper():
                    print(f"      Vision fallback: {requested.upper()} -> {d}")
                return compiled, d
            except Exception as exc:
                last = exc
        raise RuntimeError(f"Could not compile {xml.name}: {last}") from last

    @staticmethod
    def _image_blob(frame: np.ndarray, h: int, w: int) -> np.ndarray:
        resized = cv2.resize(frame, (int(w), int(h)), interpolation=cv2.INTER_LINEAR)
        return resized.transpose(2,0,1)[None].astype(np.float32)

    @classmethod
    def _blob(cls, frame: np.ndarray, compiled) -> np.ndarray:
        _, _, h, w = list(compiled.input(0).shape)
        return cls._image_blob(frame, int(h), int(w))

    def detect_faces(self, frame: np.ndarray, threshold: float):
        h,w = frame.shape[:2]
        result = self.face([self._blob(frame, self.face)])
        out = np.asarray(result[self.face.output(0)]).reshape(-1,7)
        faces=[]
        for det in out:
            conf=float(det[2])
            if conf < threshold:
                continue
            x1=int(np.clip(det[3]*w,0,w-1)); y1=int(np.clip(det[4]*h,0,h-1))
            x2=int(np.clip(det[5]*w,0,w-1)); y2=int(np.clip(det[6]*h,0,h-1))
            if x2>x1 and y2>y1:
                faces.append((x1,y1,x2,y2,conf))
        return faces

    def _face_crop(self, frame: np.ndarray, face, pad: float = 0.0):
        x1,y1,x2,y2,_=face
        fw,fh=x2-x1,y2-y1
        px,py=int(fw*pad),int(fh*pad)
        h,w=frame.shape[:2]
        ax=max(0,x1-px); ay=max(0,y1-py); bx=min(w,x2+px); by=min(h,y2+py)
        crop=frame[ay:by,ax:bx]
        return crop,(ax,ay,bx,by)

    def head_pose(self, frame: np.ndarray, face) -> tuple[float,float,float]:
        crop,_=self._face_crop(frame,face,pad=.08)
        if crop.size == 0:
            return 0.0,0.0,0.0
        result=self.head([self._blob(crop,self.head)])
        vals={}
        for out in self.head.outputs:
            try: name=out.get_any_name().lower()
            except Exception: name=str(out).lower()
            vals[name]=float(np.asarray(result[out]).reshape(-1)[0])
        def pick(token): return next((v for n,v in vals.items() if token in n),0.0)
        return pick("angle_y"), pick("angle_p"), pick("angle_r")

    def _landmark_points(self, frame: np.ndarray, face) -> tuple[list[np.ndarray], tuple[int,int,int,int]] | None:
        if self.landmarks is None:
            return None
        crop,box=self._face_crop(frame,face,pad=0.0)
        if crop.size == 0:
            return None
        result=self.landmarks([self._blob(crop,self.landmarks)])
        vals=np.asarray(result[self.landmarks.output(0)]).reshape(-1)
        if vals.size < 8:
            return None
        x1,y1,x2,y2=box; fw=max(1,x2-x1); fh=max(1,y2-y1)
        pts=[]
        for i in range(0,vals.size-1,2):
            pts.append(np.array([x1+float(vals[i])*fw, y1+float(vals[i+1])*fh],dtype=float))
        return pts,box

    @staticmethod
    def _crop_eye(frame: np.ndarray, p1: np.ndarray, p2: np.ndarray) -> tuple[np.ndarray | None,float]:
        center=(p1+p2)/2.0
        eye_w=float(np.linalg.norm(p2-p1))
        if eye_w < 5.0:
            return None, eye_w
        half=max(7.0,0.90*eye_w)
        h,w=frame.shape[:2]
        x1=max(0,int(round(center[0]-half))); x2=min(w,int(round(center[0]+half)))
        y1=max(0,int(round(center[1]-half))); y2=min(h,int(round(center[1]+half)))
        crop=frame[y1:y2,x1:x2]
        if crop.size == 0 or crop.shape[0] < 8 or crop.shape[1] < 8:
            return None, eye_w
        return crop,eye_w

    def gaze_angles(self, frame: np.ndarray, face, head_angles: tuple[float,float,float], disagreement_limit_deg: float = 35.0) -> tuple[float,float,float] | None:
        """Return gaze yaw, pitch and a geometry reliability in [0,1].

        Uses OpenVINO facial-landmarks-35 + gaze-estimation-adas when available.
        Falls back to caller's head pose when eye crops are too small/unreliable.
        """
        if self.landmarks is None or self.gaze is None:
            return None
        lm=self._landmark_points(frame,face)
        if lm is None:
            return None
        pts,box=lm
        if len(pts) < 4:
            return None
        # Model documentation: p0,p1 left eye corners; p2,p3 right eye corners.
        left,lw=self._crop_eye(frame,pts[0],pts[1])
        right,rw=self._crop_eye(frame,pts[2],pts[3])
        if left is None or right is None:
            return None
        x1,y1,x2,y2=box; face_w=max(1.0,float(x2-x1))
        eye_ratio=min(lw,rw)/face_w
        if eye_ratio < 0.07:
            return None

        yaw,pitch,roll=head_angles
        inputs={}
        for inp in self.gaze.inputs:
            try: name=inp.get_any_name()
            except Exception: name=str(inp)
            lname=name.lower(); shape=list(inp.shape)
            if "left_eye" in lname:
                inputs[name]=self._image_blob(left,int(shape[-2]),int(shape[-1]))
            elif "right_eye" in lname:
                inputs[name]=self._image_blob(right,int(shape[-2]),int(shape[-1]))
            elif "head_pose" in lname:
                inputs[name]=np.asarray([[yaw,pitch,roll]],dtype=np.float32)
        if len(inputs) < 3:
            return None
        result=self.gaze(inputs)
        vec=np.asarray(result[self.gaze.output(0)]).reshape(-1)[:3].astype(float)
        norm=float(np.linalg.norm(vec))
        if norm < 1e-6:
            return None
        x,y,z=(vec/norm).tolist()
        # Camera-facing gaze is approximately +Z according to the OMZ definition.
        gyaw=math.degrees(math.atan2(x,max(1e-6,z)))
        gpitch=math.degrees(math.atan2(-y,max(1e-6,math.hypot(x,z))))
        reliability=float(np.clip((eye_ratio-0.07)/0.08,0.0,1.0))
        head_yaw, head_pitch, _ = head_angles
        disagreement = math.hypot(float(gyaw) - float(head_yaw), float(gpitch) - float(head_pitch))
        # Eye gaze can legitimately differ from head pose, but an extreme
        # disagreement is a strong signal that the eye ROI/model output is not
        # trustworthy for this frame. Fall back to head pose instead of creating
        # a false "looking away" state.
        if disagreement > float(disagreement_limit_deg):
            return None
        if abs(gyaw) > 85.0 or abs(gpitch) > 75.0:
            return None
        return float(gyaw),float(gpitch),reliability


class PoseTracker:
    def __init__(self, model_dir: Path, requested: str, confidence: float, imgsz: int = 512):
        self.model = YOLO(str(model_dir), task="pose")
        self.requested = requested.upper()
        self.confidence = confidence
        self.imgsz = int(imgsz)
        self.used_device = None
        self.candidates = fallback_chain(requested)

    def infer(self, frame: np.ndarray) -> dict[str,Any] | None:
        last = None
        for d in self.candidates:
            try:
                results = self.model.predict(
                    source=frame,
                    imgsz=self.imgsz,
                    conf=self.confidence,
                    verbose=False,
                    device=_ultra_device(d),
                )
                self.used_device = d
                if not results:
                    return None
                r=results[0]
                if r.keypoints is None or r.boxes is None or len(r.boxes)==0:
                    return None
                confs=r.boxes.conf.detach().cpu().numpy() if r.boxes.conf is not None else np.ones(len(r.boxes))
                idx=int(np.argmax(confs))
                xy=r.keypoints.xy[idx].detach().cpu().numpy()
                if getattr(r.keypoints,"conf",None) is not None:
                    kc=r.keypoints.conf[idx].detach().cpu().numpy()
                else:
                    data=r.keypoints.data[idx].detach().cpu().numpy()
                    kc=data[:,2] if data.shape[1]>=3 else np.ones(len(xy))
                return {"xy":xy,"conf":kc,"person_conf":float(confs[idx])}
            except Exception as exc:
                last=exc
                if d != self.candidates[-1]:
                    print(f"      Pose failed on {d}; trying fallback...")
                    continue
                raise RuntimeError(f"Pose inference failed: {last}") from last
        return None


def _point(pose: dict[str, Any], name: str, min_conf: float = .35):
    idx = COCO[name]
    xy = pose.get("xy", [])
    conf = pose.get("conf", [])
    if idx >= len(xy) or idx >= len(conf):
        return None
    point_conf = _safe_float(conf[idx], 0.0)
    if point_conf < float(min_conf):
        return None
    point = np.asarray(xy[idx], dtype=float)
    if point.size < 2 or not np.all(np.isfinite(point[:2])):
        return None
    return point[:2]


def _conf(pose: dict[str, Any], name: str) -> float:
    idx = COCO[name]
    conf = pose.get("conf", [])
    if idx >= len(conf):
        return 0.0
    return float(clamp(_safe_float(conf[idx], 0.0), 0.0, 1.0))


def _line_angle_deg(v: np.ndarray) -> float:
    angle = math.degrees(math.atan2(float(v[1]), float(v[0])))
    while angle > 90:
        angle -= 180
    while angle < -90:
        angle += 180
    return angle


def _angle_diff_180(a: float, b: float) -> float:
    """Smallest unsigned difference between two unoriented line angles."""
    d = abs((float(a) - float(b) + 90.0) % 180.0 - 90.0)
    return float(d)


def _posture_metrics(pose: dict[str, Any], cfg: VisionConfig | None = None) -> dict[str, Any] | None:
    """Camera-rotation-resistant upper-body posture geometry.

    v9 intentionally stops treating the first few frames as a definition of
    "good posture".  The main features are structural relationships that remain
    meaningful even when the laptop camera is slightly tilted:
      * shoulders should be close to perpendicular to the torso axis;
      * shoulders and hips should be roughly parallel when both hips are visible;
      * the head/nose should stay centered over the torso/shoulders.

    A single visible hip can still produce diagnostics, but two hips are preferred
    and carry materially higher reliability.
    """
    cfg = cfg or VisionConfig()
    mc = float(cfg.posture_min_keypoint_conf)
    hip_mc = min(mc, 0.30)

    ls = _point(pose, "left_shoulder", mc)
    rs = _point(pose, "right_shoulder", mc)
    lh = _point(pose, "left_hip", hip_mc)
    rh = _point(pose, "right_hip", hip_mc)
    nose = _point(pose, "nose", mc)
    if ls is None or rs is None:
        return None
    if lh is None and rh is None:
        # Shoulder-head fallback for upper-body crops. This is deliberately a
        # partial posture score, not a fabricated full-body assessment.
        shoulder_vec = rs - ls
        shoulder_width = float(np.linalg.norm(shoulder_vec))
        if shoulder_width < 18.0:
            return None
        shoulder_unit = shoulder_vec / max(shoulder_width, 1e-6)
        sm = (ls + rs) / 2.0
        shoulder_angle = _line_angle_deg(shoulder_vec)
        head_lateral_offset = None
        if nose is not None:
            rel = nose - sm
            head_lateral_offset = abs(float(np.dot(rel, shoulder_unit))) / max(shoulder_width, 1.0)
        core_names = ["left_shoulder", "right_shoulder"] + (["nose"] if nose is not None else [])
        quality = float(np.mean([_conf(pose, n) for n in core_names]))
        if nose is None:
            quality *= 0.82
        return {
            "posture_mode": "SHOULDER_HEAD",
            "shoulder_tilt_deg": float(shoulder_angle),
            "hip_tilt_deg": None,
            "torso_angle_deg": None,
            "torso_axis_error_deg": None,
            "torso_orthogonality_error_deg": None,
            "shoulder_hip_parallel_error_deg": None,
            "head_offset_norm": None if head_lateral_offset is None else float(head_lateral_offset),
            "head_lateral_offset_norm": None if head_lateral_offset is None else float(head_lateral_offset),
            "head_torso_line_offset_norm": None,
            "head_height_ratio": None,
            "shoulder_width_px": shoulder_width,
            "hip_width_px": None,
            "torso_length_px": None,
            "pose_quality": quality,
            "hip_visibility_count": 0,
            "left_shoulder_conf": _conf(pose, "left_shoulder"),
            "right_shoulder_conf": _conf(pose, "right_shoulder"),
            "left_hip_conf": _conf(pose, "left_hip"),
            "right_hip_conf": _conf(pose, "right_hip"),
            "nose_conf": _conf(pose, "nose"),
        }

    shoulder_vec = rs - ls
    shoulder_width = float(np.linalg.norm(shoulder_vec))
    if shoulder_width < 18.0:
        return None
    shoulder_unit = shoulder_vec / max(shoulder_width, 1e-6)
    sm = (ls + rs) / 2.0

    hip_visibility = int(lh is not None) + int(rh is not None)
    hip_angle = None
    hip_width = None
    if lh is not None and rh is not None:
        hip_vec = rh - lh
        hip_width = float(np.linalg.norm(hip_vec))
        if hip_width < 12.0:
            return None
        hm = (lh + rh) / 2.0
        hip_angle = _line_angle_deg(hip_vec)
    else:
        # One hip can support a coarse torso axis for diagnostics.  Do not infer
        # that the resulting frame is as trustworthy as a two-hip observation.
        pelvis_half = 0.34 * shoulder_width
        if lh is not None:
            hm = lh + shoulder_unit * pelvis_half
        else:
            hm = rh - shoulder_unit * pelvis_half

    torso_vec = sm - hm
    torso_len = float(np.linalg.norm(torso_vec))
    if torso_len < 18.0:
        return None
    torso_unit = torso_vec / max(torso_len, 1e-6)

    shoulder_angle = _line_angle_deg(shoulder_vec)
    torso_angle = _line_angle_deg(torso_vec)

    # Rotation-invariant: ideal shoulder/torso angle is 90 degrees regardless of
    # whether the physical camera itself is rolled a few degrees.
    dot = float(np.clip(abs(np.dot(shoulder_unit, torso_unit)), 0.0, 1.0))
    shoulder_torso_angle = math.degrees(math.acos(dot))
    torso_orthogonality_error = abs(90.0 - shoulder_torso_angle)

    shoulder_hip_parallel_error = None
    if hip_angle is not None:
        shoulder_hip_parallel_error = _angle_diff_180(shoulder_angle, hip_angle)

    # Head centering is measured in the body's own coordinate system rather than
    # the image x-axis, so camera roll does not create a fake head-offset error.
    head_lateral_offset = None
    head_torso_line_offset = None
    head_height_ratio = None
    if nose is not None:
        rel = nose - sm
        head_lateral_offset = abs(float(np.dot(rel, shoulder_unit))) / max(shoulder_width, 1.0)
        # Perpendicular distance from nose to the hip->shoulder torso line.
        rel_from_hip = nose - hm
        cross = abs(float(torso_unit[0] * rel_from_hip[1] - torso_unit[1] * rel_from_hip[0]))
        head_torso_line_offset = cross / max(shoulder_width, 1.0)
        head_height_ratio = abs(float(np.dot(rel, torso_unit))) / max(shoulder_width, 1.0)

    core_names = ["left_shoulder", "right_shoulder"]
    if lh is not None:
        core_names.append("left_hip")
    if rh is not None:
        core_names.append("right_hip")
    if nose is not None:
        core_names.append("nose")
    qualities = [_conf(pose, n) for n in core_names]
    quality = float(np.mean(qualities)) if qualities else 0.0
    if hip_visibility == 1:
        quality *= 0.72
    if nose is None:
        quality *= 0.88

    return {
        "shoulder_tilt_deg": float(shoulder_angle),
        "hip_tilt_deg": None if hip_angle is None else float(hip_angle),
        "torso_angle_deg": float(torso_angle),
        "torso_axis_error_deg": float(torso_orthogonality_error),  # compatibility name
        "torso_orthogonality_error_deg": float(torso_orthogonality_error),
        "shoulder_hip_parallel_error_deg": None if shoulder_hip_parallel_error is None else float(shoulder_hip_parallel_error),
        "head_offset_norm": None if head_lateral_offset is None else float(head_lateral_offset),  # compatibility name
        "head_lateral_offset_norm": None if head_lateral_offset is None else float(head_lateral_offset),
        "head_torso_line_offset_norm": None if head_torso_line_offset is None else float(head_torso_line_offset),
        "head_height_ratio": None if head_height_ratio is None else float(head_height_ratio),
        "shoulder_width_px": shoulder_width,
        "hip_width_px": hip_width,
        "torso_length_px": torso_len,
        "pose_quality": quality,
        "hip_visibility_count": hip_visibility,
        "left_shoulder_conf": _conf(pose, "left_shoulder"),
        "right_shoulder_conf": _conf(pose, "right_shoulder"),
        "left_hip_conf": _conf(pose, "left_hip"),
        "right_hip_conf": _conf(pose, "right_hip"),
        "nose_conf": _conf(pose, "nose"),
    }


class PostureCalibrator:
    """v9 structural posture scorer with a warm-up baseline used only for context.

    The old implementation subtracted the first frames from every posture feature.
    That could make an initially slouched or tilted pose score as excellent.  v9
    never normalizes away structural misalignment.  Warm-up only estimates the
    presenter's normal whole-body lean for diagnostics/smoothing; the grade itself
    is driven by camera-rotation-resistant body geometry.
    """

    def __init__(self, cfg: VisionConfig):
        self.cfg = cfg
        self.samples: list[dict[str, float]] = []
        self.baseline: dict[str, float] | None = None

    @property
    def ready(self) -> bool:
        return self.baseline is not None

    def add(self, metrics: dict[str, Any], roll: float, *, face_forward: bool = True) -> bool:
        if self.ready:
            return True
        if not face_forward:
            return False
        if float(metrics.get("pose_quality", 0.0)) < self.cfg.posture_reliable_quality:
            return False
        # Require both hips for the warm-up baseline. One-hip frames can still be
        # scored later, but should not define the reference lean.
        if int(metrics.get("hip_visibility_count", 0)) < 2:
            return False
        torso_value = metrics.get("torso_angle_deg")
        if torso_value is None:
            return False
        torso = _safe_float(torso_value, math.nan)
        shoulder = _safe_float(metrics.get("shoulder_tilt_deg"), math.nan)
        roll_value = _safe_float(roll, math.nan)
        if not all(math.isfinite(v) for v in (torso, shoulder, roll_value)):
            return False
        sample = {
            "torso_angle_deg": torso,
            "shoulder_tilt_deg": shoulder,
            "roll_deg": roll_value,
        }
        self.samples.append(sample)
        if len(self.samples) >= self.cfg.posture_calibration_samples:
            self.baseline = {k: float(np.median([x[k] for x in self.samples])) for k in sample}
            return True
        return False

    def score(self, metrics: dict[str, Any], roll: float) -> tuple[float | None, dict[str, float]]:
        quality = _safe_float(metrics.get("pose_quality"), 0.0)
        if quality < self.cfg.posture_reliable_quality:
            return None, {}

        mode = str(metrics.get("posture_mode", "FULL_BODY"))
        orth_value = metrics.get("torso_orthogonality_error_deg", metrics.get("torso_axis_error_deg"))
        orth = _safe_float(orth_value, 0.0)
        parallel = metrics.get("shoulder_hip_parallel_error_deg")
        head_lat = metrics.get("head_lateral_offset_norm", metrics.get("head_offset_norm"))
        head_line = metrics.get("head_torso_line_offset_norm")

        # Structural components. Each component is continuous; no single angle causes
        # an instant zero unless it is very far outside a realistic presentation range.
        shoulder_score = piecewise_linear(
            _safe_float(metrics.get("shoulder_tilt_deg"), 90.0),
            [(0,96),(4,94),(8,88),(12,78),(18,64),(24,50),(32,34),(42,16),(55,0)],
        )
        torso_score = piecewise_linear(
            orth,
            [(0,96),(3,93),(6,88),(10,78),(15,64),(20,50),(28,34),(38,18),(50,0)],
        )

        head_score = None
        if head_lat is not None or head_line is not None:
            h1 = piecewise_linear(
                _safe_float(head_lat, 0.0),
                [(0,96),(.04,93),(.08,87),(.13,77),(.20,62),(.29,46),(.40,28),(.55,8)],
            ) if head_lat is not None else None
            h2 = piecewise_linear(
                _safe_float(head_line, 0.0),
                [(0,96),(.04,93),(.08,87),(.13,77),(.20,62),(.29,46),(.40,28),(.55,8)],
            ) if head_line is not None else None
            vals=[x for x in (h1,h2) if x is not None]
            head_score=float(.45*np.mean(vals)+.55*np.min(vals)) if vals else None

        parallel_score = None
        if parallel is not None:
            parallel_score = piecewise_linear(
                _safe_float(parallel, 0.0),
                [(0,96),(4,91),(8,83),(13,72),(19,58),(27,42),(36,24),(48,7)],
            )

        if mode == "SHOULDER_HEAD":
            # Upper-body mode is explicitly narrower in scope. It can score shoulder
            # and head alignment, but it cannot claim full-body posture quality.
            available = [(shoulder_score, .55)]
            if head_score is not None:
                available.append((head_score, .45))
            base_score = sum(v*w for v,w in available) / max(sum(w for _,w in available), 1e-6)
            observed_components = [v for v,_ in available]
        else:
            # Full-body: torso is the primary structural feature; shoulder, head and
            # shoulder/hip parallelism provide independent corroborating evidence.
            available = [(torso_score, .35), (shoulder_score, .25)]
            if head_score is not None:
                available.append((head_score, .20))
            if parallel_score is not None:
                available.append((parallel_score, .20))
            base_score = sum(v*w for v,w in available) / max(sum(w for _,w in available), 1e-6)
            observed_components = [v for v,_ in available]

        # Bottleneck factor prevents one excellent component from hiding a clearly bad
        # component. This is deliberately softer than a hard minimum.
        weakest = min(observed_components) if observed_components else 0.0
        score = clamp(0.70 * base_score + 0.30 * weakest)

        # Evidence modifier: lack of visible hips lowers certainty, not the structural
        # score itself. One-hip frames remain useful but should not look as reliable as
        # two-hip full-body observations.
        hip_count = int(metrics.get("hip_visibility_count", 0) or 0)
        evidence_factor = 1.0
        if mode == "FULL_BODY" and hip_count < 2:
            evidence_factor = 0.90
        elif mode == "SHOULDER_HEAD":
            evidence_factor = 0.88

        score = clamp(score * evidence_factor)

        rel_roll = _angle_diff_180(
            _safe_float(roll),
            _safe_float(metrics.get("shoulder_tilt_deg"), 0.0),
        )

        lean_delta = 0.0
        if self.baseline is not None and metrics.get("torso_angle_deg") is not None:
            raw_torso = _safe_float(metrics.get("torso_angle_deg"), math.nan)
            base_torso = _safe_float(self.baseline.get("torso_angle_deg"), math.nan)
            if math.isfinite(raw_torso) and math.isfinite(base_torso):
                lean_delta = _angle_diff_180(raw_torso, base_torso)

        details = {
            "posture_mode": mode,
            "shoulder_tilt_deg": _safe_float(metrics.get("shoulder_tilt_deg"), 0.0),
            "torso_axis_error_deg": orth,
            "torso_orthogonality_error_deg": orth,
            "shoulder_hip_parallel_error_deg": _safe_float(parallel, 0.0),
            "head_offset_delta": _safe_float(head_lat, 0.0),
            "head_lateral_offset_norm": _safe_float(head_lat, 0.0),
            "head_torso_line_offset_norm": _safe_float(head_line, 0.0),
            "relative_head_roll_deg": float(rel_roll),
            "whole_body_lean_change_deg": float(lean_delta),
            "pose_quality": quality,
            "evidence_factor": float(evidence_factor),
            "shoulder_alignment_score": float(shoulder_score),
            "torso_alignment_score": float(torso_score),
            "orthogonality_score": float(torso_score),
            "head_alignment_score": float(head_score if head_score is not None else 0.0),
            "hip_parallel_score": float(parallel_score if parallel_score is not None else 0.0),
            "posture_base_score": float(base_score),
            "posture_weakest_component": float(weakest),
            "posture_bottleneck_score": float(score),
        }
        return score, details

    def diagnose(self, details: dict[str, float]) -> str:
        if not details:
            return "LOW CONFIDENCE"
        issues=[]
        if details.get("posture_mode") == "SHOULDER_HEAD":
            if details.get("head_lateral_offset_norm",0.0) > .16:
                issues.append("HEAD OFF-CENTER")
            if details.get("shoulder_tilt_deg",0.0) > 18.0:
                issues.append("SHOULDER TILT")
        elif details.get("torso_orthogonality_error_deg",0.0) > 14.0:
            issues.append("TORSO ALIGNMENT")
        if max(details.get("head_lateral_offset_norm",0.0), details.get("head_torso_line_offset_norm",0.0)) > .20:
            issues.append("HEAD OFF-CENTER")
        if details.get("shoulder_hip_parallel_error_deg",0.0) > 18.0:
            issues.append("SHOULDER/HIP ALIGNMENT")
        if not issues:
            return "GOOD ALIGNMENT"
        return issues[0]


def _posture_score(shoulder, torso, roll, cfg, *, baseline: dict[str, float] | None = None):
    """Backward-compatible helper retained for old imports/tests.

    New code uses PostureCalibrator; this helper is intentionally conservative.
    """
    shoulder = abs(float(shoulder))
    torso = abs(float(torso))
    roll = abs(float(roll))
    a=piecewise_linear(shoulder,[(0,100),(8,95),(18,72),(30,35),(50,0)])
    b=piecewise_linear(torso,[(0,100),(8,95),(16,75),(28,40),(45,0)])
    c=piecewise_linear(roll,[(0,100),(10,95),(22,70),(35,35),(55,0)])
    return clamp(.2*a+.6*b+.2*c)


class GestureTracker:
    """Arm-motion tracker that favors sustained intentional movement over jitter."""

    def __init__(self, cfg: VisionConfig):
        self.cfg = cfg
        self.prev_smoothed: dict[str, np.ndarray] | None = None
        self.visible_frames = 0
        self.active_frames = 0
        self.event_count = 0
        self.motion_values: list[float] = []
        self.current_active = False
        self.cooldown = 0
        self._start_run = 0
        self._release_run = 0

    def _normalized_points(self, pose: dict[str, Any]) -> dict[str, np.ndarray] | None:
        mc = self.cfg.gesture_min_keypoint_conf
        ls = _point(pose, "left_shoulder", self.cfg.posture_min_keypoint_conf)
        rs = _point(pose, "right_shoulder", self.cfg.posture_min_keypoint_conf)
        if ls is None or rs is None:
            return None
        width = float(np.linalg.norm(rs - ls))
        if width < 16.0:
            return None
        center = (ls + rs) / 2.0
        pts: dict[str, np.ndarray] = {}
        for name in ("left_elbow", "right_elbow", "left_wrist", "right_wrist"):
            pt = _point(pose, name, mc)
            if pt is not None:
                pts[name] = (pt - center) / width
        return pts if len(pts) >= 2 else None

    def update(self, pose: dict[str, Any]) -> dict[str, Any]:
        pts = self._normalized_points(pose)
        if pts is None:
            self.prev_smoothed = None
            self.current_active = False
            self._start_run = self._release_run = 0
            return {"visible": False, "active": False, "motion_norm": 0.0, "point_count": 0}

        self.visible_frames += 1
        alpha = float(np.clip(self.cfg.gesture_ema_alpha, 0.05, 1.0))
        if self.prev_smoothed is None:
            self.prev_smoothed = {k:v.copy() for k,v in pts.items()}
            return {"visible": True, "active": False, "motion_norm": 0.0, "point_count": len(pts)}

        smoothed: dict[str,np.ndarray] = {}
        moves: list[float] = []
        for name, pt in pts.items():
            prev = self.prev_smoothed.get(name)
            if prev is None:
                smoothed[name] = pt.copy(); continue
            cur = alpha*pt + (1.0-alpha)*prev
            smoothed[name] = cur
            moves.append(float(np.linalg.norm(cur-prev)))
        self.prev_smoothed = smoothed
        if not moves:
            return {"visible": True, "active": self.current_active, "motion_norm": 0.0, "point_count": len(smoothed)}

        # 75th percentile is robust to one jittery wrist but still responds when
        # multiple arm points move together.
        motion = float(np.percentile(np.asarray(moves,dtype=float), 75))
        self.motion_values.append(motion)
        if self.cooldown > 0: self.cooldown -= 1

        if not self.current_active:
            if motion >= self.cfg.gesture_motion_threshold_norm:
                self._start_run += 1
            else:
                self._start_run = 0
            if self._start_run >= max(1,int(self.cfg.gesture_start_frames)):
                self.current_active = True
                self._start_run = 0
                self._release_run = 0
                if self.cooldown <= 0:
                    self.event_count += 1
                    self.cooldown = max(0,int(self.cfg.gesture_event_cooldown_frames))
        else:
            if motion < self.cfg.gesture_release_threshold_norm:
                self._release_run += 1
            else:
                self._release_run = 0
            if self._release_run >= max(1,int(self.cfg.gesture_release_frames)):
                self.current_active = False
                self._release_run = 0

        if self.current_active: self.active_frames += 1
        return {"visible": True, "active": self.current_active, "motion_norm": motion, "point_count": len(smoothed)}

    def summary(self, attempts: int) -> dict[str, Any]:
        visible_pct = 100.0*self.visible_frames/max(1,attempts)
        active_pct_visible = 100.0*self.active_frames/max(1,self.visible_frames-1)
        p90 = float(np.percentile(self.motion_values,90)) if self.motion_values else 0.0
        mean = safe_mean(self.motion_values)
        reliable = self.visible_frames >= self.cfg.gesture_min_reliable_frames
        if not reliable:
            level = "NOT ENOUGH DATA"
        elif self.event_count == 0 and active_pct_visible < 8:
            level = "LITTLE MOVEMENT"
        elif active_pct_visible < 35:
            level = "SOME MOVEMENT"
        else:
            level = "FREQUENT MOVEMENT"
        return {"reliable":reliable,"visible_frames":self.visible_frames,"visible_percent":visible_pct,
                "active_frames":self.active_frames,"active_percent_visible":active_pct_visible,
                "event_count":self.event_count,"motion_mean_norm":mean,"motion_p90_norm":p90,"level":level}


def _gesture_score(active,visible):
    # Informational only. v6 also avoids inflated 95-100 gesture scores.
    a=piecewise_linear(active,[(0,40),(5,52),(15,72),(30,84),(45,88),(70,75),(100,52)])
    v=piecewise_linear(visible,[(0,30),(20,48),(50,70),(80,88),(100,92)])
    return clamp(.65*a+.35*v)


def _sustained_state_stats(states: list[str], target: str, sample_fps: float, grace_seconds: float) -> tuple[float, int, float]:
    """Return sustained seconds, episode count and percent of sampled session.

    Short glances are ignored instead of being scored as failures.  This makes head
    orientation behave like presentation coaching rather than eye-contact policing.
    """
    if not states:
        return 0.0, 0, 0.0
    fps = max(float(sample_fps), 0.1)
    min_frames = max(1, int(math.ceil(grace_seconds * fps)))
    total_frames = 0
    episodes = 0
    i = 0
    while i < len(states):
        if states[i] != target:
            i += 1
            continue
        j = i + 1
        while j < len(states) and states[j] == target:
            j += 1
        run = j - i
        if run >= min_frames:
            episodes += 1
            total_frames += run
        i = j
    seconds = total_frames / fps
    pct = 100.0 * total_frames / len(states)
    return seconds, episodes, pct


def _temporal_violation_stats(
    states: list[str],
    target: str,
    sample_fps: float,
    sustain_seconds: float,
    repeat_window_seconds: float = 10.0,
    repeat_count: int = 3,
) -> dict[str, Any]:
    """Qualify sustained and repeated short violations without reset-loop exploits."""
    fps = max(_safe_float(sample_fps, 0.1), 0.1)
    min_frames = max(1, int(math.ceil(float(sustain_seconds) * fps)))
    window_frames = max(min_frames, int(math.ceil(float(repeat_window_seconds) * fps)))
    runs: list[tuple[int, int]] = []
    i = 0
    while i < len(states):
        if states[i] != target:
            i += 1
            continue
        j = i + 1
        while j < len(states) and states[j] == target:
            j += 1
        runs.append((i, j))
        i = j
    sustained = {idx for idx, (a, b) in enumerate(runs) if b - a >= min_frames}
    repeated: set[int] = set()
    for idx, (a, _) in enumerate(runs):
        recent: list[int] = []
        j = idx
        while j >= 0 and a - runs[j][0] <= window_frames:
            recent.append(j)
            j -= 1
        if len(recent) >= max(2, int(repeat_count)):
            repeated.update(recent[:int(repeat_count)])
    effective = sustained | repeated
    raw_frames = sum(b - a for a, b in runs)
    effective_frames = sum(runs[k][1] - runs[k][0] for k in effective)
    return {
        "raw_seconds": raw_frames / fps,
        "effective_seconds": effective_frames / fps,
        "raw_percent": 100.0 * raw_frames / max(1, len(states)),
        "effective_percent": 100.0 * effective_frames / max(1, len(states)),
        "episode_count": len(runs),
        "sustained_episode_count": len(sustained),
        "repeat_window_episode_count": len(repeated),
        "repeat_triggered": bool(repeated),
    }


def _orientation_score(yaw_delta: float, pitch_delta: float) -> float:
    """Score presentation orientation with a forgiving screen-reading plateau."""
    yaw = abs(_safe_float(yaw_delta, 0.0))
    pitch = abs(_safe_float(pitch_delta, 0.0))
    yaw_score = piecewise_linear(
        yaw,
        [(0,98), (10,97), (20,94), (27,85), (32,72), (40,52), (55,26), (70,0)],
    )
    pitch_score = piecewise_linear(
        pitch,
        [(0,98), (8,97), (16,94), (24,84), (32,66), (40,45), (50,20), (65,0)],
    )
    avg = 0.55 * yaw_score + 0.45 * pitch_score
    return clamp(0.50 * avg + 0.50 * min(yaw_score, pitch_score))



def _calibrated_gaze_states(
    samples: list[tuple[float, float] | None],
    cfg: VisionConfig,
    state_hints: list[str | None] | None = None,
) -> dict[str, Any]:
    """Convert head-pose samples into calibrated, continuous attention evidence."""
    hints = state_hints if state_hints is not None else [None] * len(samples)
    if len(hints) != len(samples):
        raise ValueError("state_hints length must match samples length")
    visible_head = [
        x for x, hint in zip(samples, hints)
        if x is not None and hint not in {"held", "away"}
    ]
    ncal = min(len(visible_head), max(3, int(cfg.gaze_calibration_samples)))
    if ncal:
        # Stability-aware calibration: central, low-motion samples define camera bias.
        early = visible_head[: max(ncal * 4, ncal)]
        candidates: list[tuple[float, tuple[float, float]]] = []
        for i, sample in enumerate(early):
            yaw_i, pitch_i = float(sample[0]), float(sample[1])
            motion = 0.0
            if i > 0:
                py, pp = early[i - 1]
                motion = math.hypot(yaw_i - float(py), pitch_i - float(pp))
            centrality = abs(yaw_i) / 35.0 + abs(pitch_i) / 30.0
            stability_cost = min(motion / 12.0, 3.0)
            candidates.append((centrality + 0.55 * stability_cost, sample))
        candidates.sort(key=lambda item: item[0])
        keep_n = max(3, min(ncal, len(candidates)))
        base = [sample for _, sample in candidates[:keep_n]]
        by = float(np.median([x[0] for x in base]))
        bp = float(np.median([x[1] for x in base]))
        by = float(np.clip(by, -cfg.gaze_baseline_yaw_clip_deg, cfg.gaze_baseline_yaw_clip_deg))
        pitch_clip = max(float(cfg.gaze_baseline_pitch_clip_deg), 25.0)
        bp = float(np.clip(bp, -pitch_clip, pitch_clip))
    else:
        by = bp = 0.0

    forward = looking = away = direct = slight = off_axis = held = 0
    states: list[str] = []
    soft_scores: list[float] = []
    deltas: list[tuple[float,float] | None] = []
    for item, hint in zip(samples, hints):
        # Preserve frame-level soft-decay semantics. A held sample is not allowed
        # to be reclassified as engaged/slight/off-axis from the stale coordinates.
        if hint == "held":
            held += 1
            states.append("held")
            deltas.append(None if item is None else (0.0, 0.0))
            continue
        if hint == "away":
            away += 1
            states.append("away")
            deltas.append(None)
            continue
        if item is None:
            away += 1
            states.append("away")
            deltas.append(None)
            continue
        yaw, pitch = item
        dy = float(yaw) - by
        dp = float(pitch) - bp
        # The Gaze/Head-pose pitch convention may have either sign. Looking at the
        # screen is therefore treated symmetrically inside the configured vertical
        # tolerance window. Outside that window, the remaining pitch deviation is
        # scored normally.
        abs_dp = abs(dp)
        compensated_dp = max(0.0, abs_dp - cfg.screen_downward_pitch_tolerance_deg)
        compensated_dy = dy
        deltas.append((compensated_dy, compensated_dp))
        score = _orientation_score(compensated_dy, compensated_dp)
        soft_scores.append(score)
        if score >= 88:
            direct += 1
        if score >= 72:
            forward += 1
            states.append("engaged")
        elif score >= 62:
            looking += 1
            slight += 1
            states.append("slight_off")
        else:
            looking += 1
            off_axis += 1
            states.append("off_axis")
    return {
        "baseline_yaw": by, "baseline_pitch": bp,
        "forward": forward, "looking": looking, "away": away, "direct": direct,
        "slight_off": slight, "off_axis": off_axis, "held": held,
        "states": states, "soft_scores": soft_scores, "deltas": deltas,
    }


def _robust_posture_score(values: list[float]) -> float:
    if not values:
        return 0.0
    arr = np.asarray(values, dtype=float)
    # v6 is more conservative: sustained weaker posture matters more than a few
    # perfect frames. Median still protects against keypoint glitches.
    return clamp(0.60 * float(np.median(arr)) + 0.40 * float(np.percentile(arr, 25)))


def analyze_video(
    video_path: str | Path,
    *,
    face_model: str | Path,
    head_pose_model: str | Path,
    landmarks_model: str | Path | None = None,
    gaze_model: str | Path | None = None,
    pose_model_dir: str | Path = "",
    device: str,
    pose_device: str,
    cache_dir: str | Path,
    cfg: VisionConfig | None = None,
) -> dict[str,Any]:
    cfg=cfg or VisionConfig()
    total_start=time.perf_counter()
    head=OpenVINOHeadTracker(
        Path(face_model),Path(head_pose_model),device,Path(cache_dir),
        Path(landmarks_model) if landmarks_model else None,
        Path(gaze_model) if gaze_model else None,
    )
    pose=PoseTracker(Path(pose_model_dir),pose_device,cfg.pose_confidence,cfg.pose_imgsz)
    posture_cal = PostureCalibrator(cfg)

    cap=cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")
    source_fps=float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
    total_src=int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration=total_src/source_fps if total_src>0 else 0.0
    step=max(1,int(round(source_fps/max(cfg.sample_fps,.1))))

    sampled=forward=looking=away=direct=0
    face_counts=[]; yaws=[]; pitches=[]; rolls=[]
    orientation_states: list[str] = []
    last_orientation: tuple[float, float] | None = None
    face_missing_run = 0
    orientation_samples: list[tuple[float, float] | None] = []
    head_pose_samples: list[tuple[float, float] | None] = []
    gaze_used_frames=0
    gaze_reliability_values: list[float] = []
    gaze_rejected_disagreement=0
    pose_backed_presence_frames=0
    pose_backed_flags: list[bool] = []
    posture_measurements: list[tuple[dict[str,Any],float,bool]]=[]
    posture_timeline: list[dict[str,Any] | None] = []
    pose_quality_values=[]
    pose_valid=pose_attempts=0
    gesture_tracker=GestureTracker(cfg)
    kp_visible={name:0 for name in ("left_shoulder","right_shoulder","left_hip","right_hip","left_elbow","right_elbow","left_wrist","right_wrist")}
    idx=0
    inf_start=time.perf_counter()
    while True:
        ok,frame=cap.read()
        if not ok:
            break
        if idx%step!=0:
            idx+=1
            continue
        sampled+=1
        posture_timeline.append(None)
        faces=head.detect_faces(frame,cfg.face_confidence)
        face_counts.append(len(faces))
        current_roll=0.0
        current_forward=False
        if not faces:
            # Soft-decay guardrail: a single missed face frame is not equivalent to
            # being out of frame. Hold the last reliable orientation for a short
            # grace window, then transition to true AWAY.
            face_missing_run += 1
            if last_orientation is not None and face_missing_run <= max(1, int(round(cfg.away_grace_seconds * cfg.sample_fps))):
                orientation_samples.append(last_orientation)
                orientation_states.append("held")
                head_pose_samples.append(None)
            else:
                away += 1
                orientation_states.append("away")
                orientation_samples.append(None)
                head_pose_samples.append(None)
        else:
            face_missing_run = 0
            face=max(faces,key=lambda f:(f[2]-f[0])*(f[3]-f[1]))
            yaw,pitch,roll=head.head_pose(frame,face)
            current_roll=roll
            yaws.append(yaw); pitches.append(pitch); rolls.append(roll)
            head_pose_samples.append((float(yaw), float(pitch)))
            gaze_limit = max(float(cfg.gaze_head_disagreement_limit_deg), 45.0)
            gaze_result=head.gaze_angles(frame,face,(yaw,pitch,roll), gaze_limit)
            if gaze_result is not None:
                gy,gp,grel=gaze_result
                # Only trust gaze when the eye crops are large enough. Blend a small
                # amount of head pose for robustness against momentary eye-model noise.
                blend=float(np.clip(0.35+0.25*grel,0.35,0.60))
                oy=blend*gy+(1.0-blend)*yaw
                op=blend*gp+(1.0-blend)*pitch
                orientation_samples.append((float(oy),float(op)))
                gaze_used_frames+=1
                gaze_reliability_values.append(float(grel))
            else:
                orientation_samples.append((float(yaw), float(pitch)))
            last_orientation = orientation_samples[-1]
            # Temporary orientation is used only while collecting pose samples. Final
            # camera-attention states are recalculated after camera-bias calibration.
            current_forward = abs(orientation_samples[-1][0])<=30.0 and abs(orientation_samples[-1][1])<=22.0
            if current_forward:
                forward+=1
                orientation_states.append("engaged")
            else:
                looking+=1
                orientation_states.append("off_axis")

        pose_backed_flags.append(False)
        if sampled%max(1,cfg.pose_every_n_samples)==0:
            pose_attempts += 1
            p=pose.infer(frame)
            if p is not None:
                if not faces:
                    # Face detector can miss a frame while the person/body tracker
                    # still clearly sees the presenter. Do not call that "out of frame".
                    pose_backed_presence_frames += 1
                    pose_backed_flags[-1] = True
                    # Pose-backed presence is tracked separately; final gaze aggregation
                    # owns away/held counts.
                # Record what the pose model actually sees. This makes it possible
                # to distinguish "in frame" from "keypoint confidence too low".
                for name in kp_visible:
                    if "elbow" in name or "wrist" in name:
                        threshold = cfg.gesture_min_keypoint_conf
                    elif "hip" in name:
                        threshold = min(float(cfg.posture_min_keypoint_conf), 0.30)
                    else:
                        threshold = cfg.posture_min_keypoint_conf
                    if _point(p, name, threshold) is not None:
                        kp_visible[name] += 1

                gesture_tracker.update(p)
                pm=_posture_metrics(p,cfg)
                if pm is not None:
                    pose_valid+=1
                    pose_quality_values.append(_safe_float(pm.get("pose_quality"), 0.0))
                    posture_measurements.append((pm,current_roll,current_forward))
                    posture_timeline[-1] = {
                        "metrics": pm,
                        "roll": current_roll,
                        "face_forward": current_forward,
                    }
                    # Only centered/engaged frames are allowed to contribute to the
                    # camera-relative warm-up. Off-axis frames can still be scored structurally.
                    posture_cal.add(pm,current_roll,face_forward=current_forward)
        idx+=1
    cap.release()
    inf_seconds=time.perf_counter()-inf_start
    total=time.perf_counter()-total_start
    if sampled==0:
        raise RuntimeError("Video contained no readable frames")

    # A missed face is not equivalent to an absent presenter when pose confirms a
    # person/body. Reuse the last reliable orientation for those samples before the
    # final gaze aggregation. This keeps presence/attention distributions consistent.
    for i, (item, backed) in enumerate(zip(orientation_samples, pose_backed_flags)):
        if item is None and backed and last_orientation is not None:
            orientation_samples[i] = last_orientation
            orientation_states[i] = "held"
    # If a face was missing for a short run without pose confirmation, preserve the
    # last orientation inside the configured grace window.
    grace_frames = max(1, int(round(cfg.away_grace_seconds * cfg.sample_fps)))
    recent_none = 0
    for i in range(len(orientation_samples)):
        if orientation_samples[i] is None:
            recent_none += 1
        else:
            recent_none = 0
        if orientation_samples[i] is None and recent_none <= grace_frames and i > 0:
            prev = orientation_samples[i - 1]
            if prev is not None:
                orientation_samples[i] = prev
                orientation_states[i] = "held"

    # If forward-only calibration could not finish (short clip), allow a fallback
    # calibration from reliable frames. This still removes camera tilt while keeping
    # the rotation-invariant torso metric absolute.
    if not posture_cal.ready:
        for pm,roll,face_forward in posture_measurements:
            posture_cal.add(pm,roll,face_forward=bool(face_forward))
            if posture_cal.ready:
                break

    posture_scores=[]; posture_details=[]
    posture_scored_timeline: list[float | None] = []
    last_posture_score: float | None = None
    max_hold_frames = max(1, int(math.ceil(3.0 * max(_safe_float(cfg.sample_fps, 0.1), 0.1))))
    hold_remaining = 0

    for item in posture_timeline:
        if item is not None:
            score, details = posture_cal.score(item["metrics"], item["roll"])
            if score is not None:
                safe_score = _safe_float(score, math.nan)
                if math.isfinite(safe_score):
                    posture_scores.append(safe_score)
                    posture_details.append(details)
                    posture_scored_timeline.append(safe_score)
                    last_posture_score = safe_score
                    hold_remaining = max_hold_frames
                    continue
            posture_scored_timeline.append(None)
        else:
            if last_posture_score is not None and hold_remaining > 0:
                posture_scored_timeline.append(last_posture_score)
                hold_remaining -= 1
            else:
                posture_scored_timeline.append(None)

    held_posture_scores = [x for x in posture_scored_timeline if x is not None]
    if held_posture_scores:
        posture_scores = [float(x) for x in held_posture_scores]


    # Camera-attention v5: calibrate systematic camera/head-pose bias, then
    # recompute all states using the calibrated relative angles.
    gaze_hints = [
        state if state in {"held", "away"} else None
        for state in orientation_states
    ]
    gaze = _calibrated_gaze_states(orientation_samples, cfg, gaze_hints)
    gaze_baseline_yaw = float(gaze["baseline_yaw"])
    gaze_baseline_pitch = float(gaze["baseline_pitch"])
    forward = int(gaze["forward"])
    looking = int(gaze["looking"])
    slight_off = int(gaze.get("slight_off",0))
    off_axis = int(gaze.get("off_axis",0))
    away = int(gaze["away"])
    held = int(gaze.get("held", 0))
    direct = int(gaze["direct"])
    orientation_states = list(gaze["states"])

    visible=max(0,sampled-away)
    f_pct=100*forward/sampled
    # "looking away" means clearly off-axis; held is its own visible/uncertain state.
    l_pct=100*off_axis/sampled
    slight_pct=100*slight_off/sampled
    a_pct=100*away/sampled
    held_pct=100*held/sampled
    distribution_total_pct = float(f_pct + slight_pct + l_pct + a_pct + held_pct)
    direct_pct=100*direct/visible if visible else 0.0
    vf_pct=100*forward/visible if visible else 0.0

    gaze_violation = _temporal_violation_stats(
        orientation_states, "off_axis", cfg.sample_fps,
        sustain_seconds=2.5, repeat_window_seconds=10.0, repeat_count=3,
    )
    away_violation = _temporal_violation_stats(
        orientation_states, "away", cfg.sample_fps,
        sustain_seconds=max(1.0, _safe_float(cfg.away_grace_seconds, 0.9)),
        repeat_window_seconds=10.0, repeat_count=3,
    )
    sustained_look_s = float(gaze_violation["effective_seconds"])
    look_episodes = int(gaze_violation["sustained_episode_count"] + gaze_violation["repeat_window_episode_count"])
    sustained_look_pct_session = float(gaze_violation["effective_percent"])
    sustained_away_s = float(away_violation["effective_seconds"])
    away_episodes = int(away_violation["sustained_episode_count"] + away_violation["repeat_window_episode_count"])
    sustained_away_pct = float(away_violation["effective_percent"])
    sustained_look_pct_visible = 100.0 * sustained_look_s / max(
        visible / max(_safe_float(cfg.sample_fps, 0.1), .1), 1e-6
    )

    baseline_yaw = float(gaze["baseline_yaw"])
    baseline_pitch = float(gaze["baseline_pitch"])
    head_turn_states: list[str] = []
    for item in head_pose_samples:
        if item is None:
            head_turn_states.append("neutral")
            continue
        hy, hp = item
        rel_yaw = abs(_safe_float(hy) - baseline_yaw)
        rel_pitch = abs(_safe_float(hp) - baseline_pitch)
        head_turn_states.append("turn" if rel_yaw >= 32.0 or rel_pitch >= 25.0 else "neutral")
    head_turn_violation = _temporal_violation_stats(
        head_turn_states, "turn", cfg.sample_fps,
        sustain_seconds=3.5, repeat_window_seconds=10.0, repeat_count=3,
    )


    yaw_std=safe_std(yaws); pitch_std=safe_std(pitches)
    # Head stability uses HEAD POSE only (not eye gaze), so natural eye movements do not look like unstable head motion.
    # Work on consecutive visible samples and ignore very large transition frames.
    motion=[]
    prev=None
    for item in head_pose_samples:
        if item is None:
            prev=None; continue
        if prev is not None:
            d=math.hypot(float(item[0])-float(prev[0]), float(item[1])-float(prev[1]))
            if d <= 30.0:
                motion.append(d)
        prev=item
    head_motion_p75=float(np.percentile(motion,75)) if motion else 0.0
    head_motion_median=float(np.median(motion)) if motion else 0.0
    med_score=piecewise_linear(head_motion_median,[(0,94),(2,91),(4,86),(7,78),(11,67),(16,52),(24,32),(35,10)])
    p75_score=piecewise_linear(head_motion_p75,[(0,94),(3,90),(6,83),(10,73),(15,60),(22,43),(30,25)])
    head_stability=clamp(.55*med_score+.45*p75_score)

    # Presence measures whether the presenter is actually in frame. 95+ requires
    # near-continuous visibility; a few percent missing is noticeable.
    visible_pct=100.0*visible/max(1,sampled)
    raw_presence_score=piecewise_linear(visible_pct,[(0,0),(40,25),(60,45),(75,62),(85,74),(90,82),(95,88),(98,92),(100,95)])
    sustained_presence_score=piecewise_linear(sustained_away_pct,[(0,95),(1,92),(3,86),(5,79),(10,66),(20,48),(35,28),(55,10),(100,0)])
    presence_score=clamp(.68*raw_presence_score+.32*sustained_presence_score)

    soft_scores=np.asarray(gaze.get("soft_scores",[]),dtype=float)
    if soft_scores.size:
        orientation_mean=float(np.mean(soft_scores))
        orientation_p25=float(np.percentile(soft_scores,25))
        orientation_robust=clamp(.65*orientation_mean+.35*orientation_p25)
    else:
        orientation_mean=orientation_p25=orientation_robust=0.0
    sustained_engagement_score=piecewise_linear(
        sustained_look_pct_visible,
        [(0,94),(3,91),(8,85),(15,76),(25,64),(40,49),(60,30),(80,12),(100,0)],
    )
    engagement_score=clamp(.75*orientation_robust+.25*sustained_engagement_score)
    if gaze_violation["repeat_triggered"]:
        engagement_score = clamp(engagement_score - 6.0)
    if head_turn_violation["effective_percent"] > 0.0:
        engagement_score = clamp(
            engagement_score
            - min(8.0, 0.18 * float(head_turn_violation["effective_percent"]))
        )

    camera_attention=clamp(.18*presence_score+.62*engagement_score+.20*min(presence_score,engagement_score))

    reliability = len(posture_scores)/max(1,pose_attempts)
    mean_pose_quality = safe_mean(pose_quality_values)
    posture_raw=_robust_posture_score(posture_scores)
    posture_good_pct=100*sum(x>=75 for x in posture_scores)/max(1,len(posture_scores))
    posture_bad_pct=100*sum(x<55 for x in posture_scores)/max(1,len(posture_scores))

    posture_violation_states = [
        "bad" if (x is not None and x < 65.0) else "neutral"
        for x in posture_scored_timeline
    ]
    posture_violation = _temporal_violation_stats(
        posture_violation_states, "bad", cfg.sample_fps,
        sustain_seconds=4.0, repeat_window_seconds=10.0, repeat_count=3,
    )
    # Consistency matters: a few excellent frames should not produce a 95 posture
    # score when a substantial part of the talk is only average. Detection/calibration
    # itself is unchanged from v4/v5.
    posture_good_time_score=piecewise_linear(
        posture_good_pct,
        [(0,30),(20,45),(40,60),(60,72),(80,84),(100,94)],
    )
    posture_bad_time_score=piecewise_linear(
        posture_bad_pct,
        [(0,94),(5,88),(10,78),(20,64),(30,50),(45,33),(60,18),(80,5),(100,0)],
    )

    # The session score is the robust structural score moderated by consistency.
    # Do not let a handful of excellent frames dominate a long mediocre session.
    posture_consistency = 0.55 * posture_good_time_score + 0.45 * posture_bad_time_score
    posture = clamp(0.70 * posture_raw + 0.30 * posture_consistency)
    if posture_violation["effective_percent"] > 0.0:
        posture_penalty = piecewise_linear(
            float(posture_violation["effective_percent"]),
            [(0,0),(5,2),(10,5),(20,10),(35,16),(50,23),(70,31),(100,40)],
        )
        posture = clamp(posture - posture_penalty)

    def _detail_mean(key: str) -> float:
        vals = [
            _safe_float(d.get(key), math.nan)
            for d in posture_details
            if d.get(key) is not None
        ]
        vals = [v for v in vals if math.isfinite(v)]
        return safe_mean(vals)

    posture_component_means = {
        "shoulder": _detail_mean("shoulder_alignment_score"),
        "torso": _detail_mean("torso_alignment_score"),
        "head": _detail_mean("head_alignment_score"),
        "hip_parallel": _detail_mean("hip_parallel_score"),
        "base": _detail_mean("posture_base_score"),
        "bottleneck": _detail_mean("posture_bottleneck_score"),
    }

    gesture_summary = gesture_tracker.summary(pose_attempts)
    hand_pct = float(gesture_summary["visible_percent"])
    gesture_pct = float(gesture_summary["active_percent_visible"])
    gesture = _gesture_score(gesture_pct, hand_pct)

    # v3's reliability gate was too strict for real laptop webcams. v4 requires
    # only a few calibrated frames and reports confidence separately.
    full_body_count = sum(1 for pm, _, _ in posture_measurements if str(pm.get("posture_mode","FULL_BODY")) == "FULL_BODY")
    upper_body_count = sum(1 for pm, _, _ in posture_measurements if str(pm.get("posture_mode","FULL_BODY")) == "SHOULDER_HEAD")
    posture_is_reliable = (
        reliability >= .15
        and mean_pose_quality >= cfg.posture_reliable_quality
        and len(posture_scores) >= cfg.posture_min_reliable_frames
    )
    if not posture_is_reliable and upper_body_count >= 3 and mean_pose_quality >= (cfg.posture_reliable_quality * 0.82):
        posture_is_reliable = True

    # v8 overall avoids counting presence/engagement twice: camera_attention already
    # contains both. Gesture remains informational and never changes the grade.
    components=[(camera_attention,.60),(head_stability,.15)]
    if posture_is_reliable:
        components.append((posture,.25))
    total_w=sum(w for _,w in components)
    overall=clamp(sum(v*w for v,w in components)/max(total_w,1e-6))
    # Confidence is evidence quality, not a bonus score. v5 effectively started at
    # 70 even for short/partial samples. v6 grows from zero using duration, face/head
    # coverage and pose evidence, and is capped below 100.
    evidence_duration=piecewise_linear(duration,[(0,0.0),(5,.20),(15,.45),(30,.65),(60,.80),(120,.90),(240,.94)])
    face_coverage=visible/max(1,sampled)
    head_coverage=min(1.0,len(yaws)/max(1,sampled))
    gaze_coverage=gaze_used_frames/max(1,visible)
    # Head pose fallback is useful, but actual eye-gaze evidence makes camera-attention
    # materially more trustworthy. Confidence reflects that distinction.
    attention_sensor_evidence=float(np.clip(0.62+0.38*gaze_coverage,0.0,1.0)) if visible else 0.0
    core_coverage=(.50*face_coverage+.30*head_coverage+.20*attention_sensor_evidence)
    pose_evidence=min(1.0,reliability/.55) if posture_is_reliable else 0.0
    if posture_is_reliable:
        vision_confidence=clamp(100*(.42*evidence_duration+.36*core_coverage+.22*pose_evidence),0,95)
    else:
        vision_confidence=clamp(100*(.54*evidence_duration+.46*core_coverage),0,90)

    scores={
        "presence":round(presence_score,1),
        "engagement":round(engagement_score,1),
        "camera_attention":round(camera_attention,1),
        "head_stability":round(head_stability,1),
        # Do not manufacture a posture/gesture number when the camera cannot
        # measure it reliably. This is more honest than a misleading default score.
        "posture":round(posture,1) if posture_is_reliable else None,
        # Gesture amount is style/context dependent, so report it as activity/events
        # rather than pretending there is one universally correct numeric grade.
        "gesture":None,
        "score_confidence":round(vision_confidence,1),
        "overall":round(overall,1),
    }

    def avg_detail(key: str) -> float:
        return safe_mean([float(d[key]) for d in posture_details if key in d])

    metrics={
        "duration_seconds":round(duration,3),
        "source_fps":round(source_fps,3),
        "sample_fps_target":cfg.sample_fps,
        "sampled_frames":sampled,
        "forward_frames":forward,
        "looking_away_frames":off_axis,
        "slight_off_frames":slight_off,
        "away_frames":away,
        "forward_percent":round(f_pct,2),
        "looking_away_percent":round(l_pct,2),
        "slight_off_percent":round(slight_pct,2),
        "away_percent":round(a_pct,2),
        "held_orientation_percent":round(held_pct,2),
        "gaze_state_counts": {
            "VISIBLE_FORWARD": int(forward),
            "SLIGHTLY_OFF": int(slight_off),
            "LOOKING_AWAY": int(off_axis),
            "HELD_SOFT_DECAY": int(held),
            "AWAY_FROM_FRAME": int(away),
        },
        "orientation_distribution_total_percent": round(distribution_total_pct, 2),
        "pose_backed_presence_percent":round(100.0*pose_backed_presence_frames/max(1,sampled),2),
        "visible_forward_percent":round(vf_pct,2),
        "direct_forward_percent":round(direct_pct,2),
        "gaze_baseline_yaw_deg":round(gaze_baseline_yaw,3),
        "gaze_baseline_pitch_deg":round(gaze_baseline_pitch,3),
        "sustained_looking_away_seconds":round(sustained_look_s,2),
        "sustained_looking_away_percent_visible":round(sustained_look_pct_visible,2),
        "looking_away_episode_count":look_episodes,
        "gaze_buffer_threshold_seconds":2.5,
        "gaze_repeat_window_seconds":10.0,
        "gaze_repeat_triggered":bool(gaze_violation["repeat_triggered"]),
        "gaze_repeat_episode_count":int(gaze_violation["repeat_window_episode_count"]),
        "gaze_accumulated_violation_percent":round(float(gaze_violation["effective_percent"]),2),
        "head_turn_buffer_threshold_seconds":3.5,
        "head_turn_repeat_triggered":bool(head_turn_violation["repeat_triggered"]),
        "head_turn_accumulated_violation_percent":round(float(head_turn_violation["effective_percent"]),2),
        "sustained_away_seconds":round(sustained_away_s,2),
        "sustained_away_percent":round(sustained_away_pct,2),
        "away_episode_count":away_episodes,
        "average_face_count":round(safe_mean(face_counts),3),
        "average_abs_yaw_deg":round(safe_mean([abs(x) for x in yaws]),3),
        "average_abs_pitch_deg":round(safe_mean([abs(x) for x in pitches]),3),
        "average_abs_roll_deg":round(safe_mean([abs(x) for x in rolls]),3),
        "yaw_std_deg":round(yaw_std,3),
        "pitch_std_deg":round(pitch_std,3),
        "head_motion_median_deg":round(head_motion_median,3),
        "head_motion_p75_deg":round(head_motion_p75,3),
        "orientation_score_mean":round(orientation_mean,2),
        "orientation_score_p25":round(orientation_p25,2),
        "camera_attention_method":"OpenVINO gaze+head orientation with stability-aware calibration and temporal anti-exploit buffering",
        "gaze_estimation_used_percent":round(100.0*gaze_used_frames/max(1,visible),2),
        "gaze_estimation_mean_reliability":round(safe_mean(gaze_reliability_values),3),
        "gaze_head_blend_range":"0.35-0.60; head-pose remains the stability anchor",
        "screen_pitch_tolerance_deg":round(cfg.screen_downward_pitch_tolerance_deg,1),
        "screen_yaw_tolerance_deg":round(cfg.screen_yaw_tolerance_deg,1),
        "attention_sensor_evidence":round(float(attention_sensor_evidence),3),
        "pose_valid_frames":pose_valid,
        "pose_attempts":pose_attempts,
        "pose_reliability":round(reliability,3),
        "mean_pose_keypoint_quality":round(mean_pose_quality,3),
        "posture_calibrated":bool(posture_cal.ready),
        "posture_score_available":bool(posture_is_reliable),
        "posture_calibration_samples":len(posture_cal.samples),
        "posture_good_percent":round(posture_good_pct,2),
        "posture_bad_percent":round(posture_bad_pct,2),
        "posture_hold_max_seconds":3.0,
        "posture_violation_threshold_seconds":4.0,
        "posture_accumulated_violation_percent":round(float(posture_violation["effective_percent"]),2),
        "posture_repeat_triggered":bool(posture_violation["repeat_triggered"]),
        "posture_components":posture_component_means,
        "posture_aggregation_method":"70% robust structural score + 30% session consistency; soft bottleneck 70/30 within each frame; temporal violation penalty",
        "average_torso_axis_error_deg":round(avg_detail("torso_axis_error_deg"),3),
        "average_torso_orthogonality_error_deg":round(avg_detail("torso_orthogonality_error_deg"),3),
        "average_shoulder_hip_parallel_error_deg":round(avg_detail("shoulder_hip_parallel_error_deg"),3),
        "average_head_lateral_offset_norm":round(avg_detail("head_lateral_offset_norm"),4),
        "average_head_torso_line_offset_norm":round(avg_detail("head_torso_line_offset_norm"),4),
        "average_relative_head_roll_deg":round(avg_detail("relative_head_roll_deg"),3),
        "average_whole_body_lean_change_deg":round(avg_detail("whole_body_lean_change_deg"),3),
        "posture_scoring_method":"25% shoulder + 35% torso + 20% head + 20% hip parallelism; soft bottleneck; 3s hold; 4s/repetition temporal penalty; shoulder-head fallback",
        "arm_keypoint_visible_percent":round(hand_pct,2),
        "gesture_activity_percent":round(gesture_pct,2),
        "gesture_level":gesture_summary["level"],
        "gesture_event_count":int(gesture_summary["event_count"]),
        "gesture_motion_mean_norm":round(float(gesture_summary["motion_mean_norm"]),4),
        "gesture_motion_p90_norm":round(float(gesture_summary["motion_p90_norm"]),4),
        "gesture_reliable":bool(gesture_summary["reliable"]),
        "gesture_used_in_overall_score":False,
        "keypoint_visibility_percent":{
            name: round(100.0*count/max(1,pose_attempts),2)
            for name,count in kp_visible.items()
        },
    }

    posture_mode_counts = {}
    for pm, _, _ in posture_measurements:
        mode_name = str(pm.get("posture_mode", "FULL_BODY"))
        posture_mode_counts[mode_name] = posture_mode_counts.get(mode_name, 0) + 1
    metrics["posture_mode_distribution"] = posture_mode_counts
    feedback=[]
    if presence_score < 70:
        feedback.append(f"You were not consistently visible in frame (presence {presence_score:.0f}/100).")
    if gaze_violation["repeat_triggered"]:
        feedback.append("Repeated short look-away periods accumulated into a camera-attention warning; reconnect with the audience more consistently.")
    elif engagement_score < 60:
        feedback.append("Your head orientation was frequently well off the camera/audience axis; re-center more often around key points.")
    elif engagement_score < 75:
        feedback.append("Head orientation was mixed: several off-axis periods reduced camera attention.")
    elif engagement_score >= 86:
        feedback.append("Head orientation stayed well centered overall; brief natural glances were not heavily penalized.")
    if head_stability<60:
        feedback.append("Large head-direction changes were frequent; make transitions a little more controlled.")
    elif head_turn_violation["repeat_triggered"]:
        feedback.append("Several prolonged head turns were detected; use shorter, more deliberate slide-facing turns.")
    if not posture_is_reliable:
        feedback.append("Posture could not be scored reliably enough from the pose keypoints. Check keypoint_visibility_percent to see whether a shoulder/hip confidence was the limiting factor.")
    elif posture<65 and posture_bad_pct>25:
        feedback.append("Upper-body alignment was weak for a sustained part of the talk: shoulder/torso geometry and head centering were frequently outside the preferred range.")
    elif posture<75:
        feedback.append("Posture was mixed. Keep the head centered over the torso and maintain more consistent shoulder/hip alignment.")
    if posture_violation["repeat_triggered"]:
        feedback.append("Repeated posture deviations accumulated across the session; brief recoveries did not reset the posture violation history.")

    # Gesture can be analyzed independently from posture: hips may be occluded while
    # elbows/wrists are still perfectly usable.
    if not gesture_summary["reliable"]:
        feedback.append("Arm keypoints were not visible often enough for reliable gesture analysis; try framing elbows and hands when possible.")
    elif gesture_summary["level"] == "LITTLE MOVEMENT":
        feedback.append("Little hand/arm movement was detected; this is a style observation and is not penalized.")
    elif gesture_summary["level"] == "SOME MOVEMENT":
        feedback.append("Some intentional-looking hand/arm movement was detected during the presentation.")
    elif gesture_summary["level"] == "FREQUENT MOVEMENT":
        feedback.append("Frequent hand/arm movement was detected; review whether it supports your key points rather than distracts.")

    effective=duration if duration>0 else sampled/max(cfg.sample_fps,.1)
    return {
        "vision_score":round(overall,1),
        "metrics":metrics,
        "scores":scores,
        "feedback":feedback[:6],
        "benchmark":{
            "vision_inference_seconds":round(inf_seconds,3),
            "total_vision_analysis_seconds":round(total,3),
            "video_realtime_factor_x":round(effective/max(total,1e-6),2),
            "vision_requested_device":device,
            "face_used_device":head.face_device,
            "head_pose_used_device":head.head_device,
            "landmarks_used_device":head.landmarks_device,
            "gaze_used_device":head.gaze_device,
            "pose_requested_device":pose_device,
            "pose_used_device":pose.used_device or "NO_POSE_FRAME",
            "pose_imgsz":cfg.pose_imgsz,
        },
    }
