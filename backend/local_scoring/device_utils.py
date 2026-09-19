from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    import openvino as ov


def _ov():
    """Import the OpenVINO runtime lazily.

    The audio pipeline's DSP stage (VAD, pause/pace/filler metrics) is pure
    NumPy/librosa and is the only stage the production web route runs, because
    the transcript comes from Cloudflare Whisper.  Importing ``openvino`` at
    module scope made that stage - and every test or benchmark touching it -
    hard-depend on a runtime it never calls.  Import on first real use instead.
    """
    import openvino as ov

    return ov


@lru_cache(maxsize=1)
def _available_devices_cached() -> tuple[str, ...]:
    try:
        return tuple(_ov().Core().available_devices)
    except Exception:
        # No OpenVINO runtime, or no enumerable device. Callers treat an empty
        # list as "only CPU is assumable", which is the correct degradation.
        return ()


def available_devices() -> list[str]:
    """Available OpenVINO devices.

    Cached: ``fallback_chain`` is called once per model compile and once per
    ASR/pose retry, and every call previously constructed a fresh ``ov.Core``
    just to enumerate a device list that cannot change inside one process.
    """
    return list(_available_devices_cached())


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


def create_core(cache_dir: Path | None = None) -> "ov.Core":
    core = _ov().Core()
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            core.set_property({"CACHE_DIR": str(cache_dir)})
        except Exception:
            pass
    return core


def device_info() -> list[dict[str, Any]]:
    core = _ov().Core()
    rows = []
    for d in core.available_devices:
        try:
            name = core.get_property(d, "FULL_DEVICE_NAME")
        except Exception:
            name = ""
        rows.append({"id": d, "name": str(name)})
    return rows
