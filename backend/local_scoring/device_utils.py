from __future__ import annotations

from pathlib import Path
from typing import Any
import openvino as ov


def available_devices() -> list[str]:
    return list(ov.Core().available_devices)


def has_device(devices: list[str], prefix: str) -> bool:
    p = prefix.upper()
    return any(d.upper() == p or d.upper().startswith(p + ".") for d in devices)


def recommended_devices() -> dict[str, str]:
    devices = available_devices()
    # Best split for modern Intel Core Ultra laptops: Whisper on NPU, CV on GPU.
    if has_device(devices, "NPU") and has_device(devices, "GPU"):
        return {"asr": "NPU", "vision": "GPU", "pose": "GPU"}
    if has_device(devices, "GPU"):
        return {"asr": "GPU", "vision": "GPU", "pose": "GPU"}
    return {"asr": "CPU", "vision": "CPU", "pose": "CPU"}


def fallback_chain(requested: str, *, include_auto: bool = False) -> list[str]:
    req = (requested or "AUTO").upper()
    devices = available_devices()
    out: list[str] = []

    def add(d: str) -> None:
        if d not in out:
            out.append(d)

    if req == "AUTO":
        if include_auto:
            add("AUTO")
        rec = recommended_devices()
        add(rec["asr"])
        if has_device(devices, "GPU"):
            add("GPU")
        if has_device(devices, "NPU"):
            add("NPU")
        add("CPU")
    else:
        add(req)
        if req == "NPU" and has_device(devices, "GPU"):
            add("GPU")
        add("CPU")
    return out


def create_core(cache_dir: Path | None = None) -> ov.Core:
    core = ov.Core()
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            core.set_property({"CACHE_DIR": str(cache_dir)})
        except Exception:
            pass
    return core


def device_info() -> list[dict[str, Any]]:
    core = ov.Core()
    rows = []
    for d in core.available_devices:
        try:
            name = core.get_property(d, "FULL_DEVICE_NAME")
        except Exception:
            name = ""
        rows.append({"id": d, "name": str(name)})
    return rows
