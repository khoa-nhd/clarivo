from __future__ import annotations

import argparse
import os
import shutil
import urllib.request
from pathlib import Path

OMZ_2023 = "https://storage.openvinotoolkit.org/repositories/open_model_zoo/2023.0/models_bin/1"
OMZ_2021 = "https://storage.openvinotoolkit.org/repositories/open_model_zoo/2021.4/models_bin/1"
MODEL_FILES = {
    "face/face-detection-retail-0004.xml": f"{OMZ_2023}/face-detection-retail-0004/FP16/face-detection-retail-0004.xml",
    "face/face-detection-retail-0004.bin": f"{OMZ_2023}/face-detection-retail-0004/FP16/face-detection-retail-0004.bin",
    "head_pose/head-pose-estimation-adas-0001.xml": f"{OMZ_2021}/head-pose-estimation-adas-0001/FP16/head-pose-estimation-adas-0001.xml",
    "head_pose/head-pose-estimation-adas-0001.bin": f"{OMZ_2021}/head-pose-estimation-adas-0001/FP16/head-pose-estimation-adas-0001.bin",
    "landmarks/facial-landmarks-35-adas-0002.xml": f"{OMZ_2021}/facial-landmarks-35-adas-0002/FP16-INT8/facial-landmarks-35-adas-0002.xml",
    "landmarks/facial-landmarks-35-adas-0002.bin": f"{OMZ_2021}/facial-landmarks-35-adas-0002/FP16-INT8/facial-landmarks-35-adas-0002.bin",
    "gaze/gaze-estimation-adas-0002.xml": f"{OMZ_2023}/gaze-estimation-adas-0002/FP16/gaze-estimation-adas-0002.xml",
    "gaze/gaze-estimation-adas-0002.bin": f"{OMZ_2023}/gaze-estimation-adas-0002/FP16/gaze-estimation-adas-0002.bin",
}
POSE_MODEL = "yolo26s-pose.pt"
POSE_FOLDER = "yolo26s-pose_openvino_model"
POSE_IMGSZ = 512


def download(url: str, dst: Path) -> None:
    if dst.exists() and dst.stat().st_size > 0:
        print(f"[ok] {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(dst.suffix + ".part")
    print(f"[download] {dst.name}")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dst)


def setup(models: Path, skip_pose: bool = False) -> None:
    models.mkdir(parents=True, exist_ok=True)
    for rel, url in MODEL_FILES.items():
        download(url, models / rel)

    if skip_pose:
        return

    pose_dir = models / POSE_FOLDER
    if pose_dir.exists() and any(pose_dir.glob("*.xml")):
        print(f"[ok] {pose_dir}")
        return

    from ultralytics import YOLO

    old = Path.cwd()
    os.chdir(models)
    try:
        print(f"[download/export] {POSE_MODEL} -> OpenVINO FP16 @ {POSE_IMGSZ}")
        model = YOLO(POSE_MODEL)
        exported = Path(
            model.export(
                format="openvino",
                imgsz=POSE_IMGSZ,
                half=True,
                dynamic=False,
            )
        )
        src = exported.resolve()
        dst = (models / POSE_FOLDER).resolve() if models.is_absolute() else (old / models / POSE_FOLDER).resolve()
        if src != dst:
            if dst.exists():
                shutil.rmtree(dst)
            src.rename(dst)
    finally:
        os.chdir(old)


def main() -> None:
    ap = argparse.ArgumentParser(description="Download only the OpenVINO models used by Clarivo web delivery analysis.")
    ap.add_argument("--models", default=str(Path(__file__).resolve().parent / "models"))
    ap.add_argument("--skip-pose", action="store_true")
    args = ap.parse_args()

    try:
        import openvino as ov
        core = ov.Core()
        print("OpenVINO devices:", ", ".join(core.available_devices))
    except Exception as exc:
        print("OpenVINO device query failed:", exc)

    setup(Path(args.models).resolve(), args.skip_pose)
    print("\nDelivery models ready.")


if __name__ == "__main__":
    main()
