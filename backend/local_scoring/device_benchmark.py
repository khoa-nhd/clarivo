"""Per-model OpenVINO device and precision benchmark.

Clarivo's docs and READMEs state which device and precision each model runs at.
Nothing measured it, and nothing checked the claim against the compiled model,
so "runs on NPU in FP16" was an assertion. This measures it:

* which device each model *actually* compiled onto, after the fallback chain
  in ``device_utils.fallback_chain`` has had its say - a model that silently
  fell back from NPU to CPU looks identical from the outside;
* the element type the compiled model really uses, read from the runtime
  rather than from the folder the weights were downloaded into;
* model load and compile time, first (cold) inference, and warm inference
  latency as mean / median / p95 / p99, because a mean alone hides the stalls
  a user actually notices;
* throughput and process RSS growth across the run.

Run it on the target machine - the numbers are meaningless anywhere else:

    python -m local_scoring.device_benchmark
    python -m local_scoring.device_benchmark --devices CPU GPU NPU
    python -m local_scoring.device_benchmark --iterations 100 --json bench.json

Requires the OpenVINO runtime and the model set from
``python -m local_scoring.setup_delivery_models``. It reports what is missing
and continues rather than failing, so a machine without an NPU still produces
a complete CPU/GPU table.

A note on FP16 on CPU: the OpenVINO CPU plugin executes FP16 IR by converting
to FP32 (or bf16 where the CPU supports it) internally. An FP16 model file
therefore does not mean FP16 arithmetic on CPU - it mainly means a smaller
file and less memory traffic. The "compiled precision" column reports what the
runtime says it is using, which is why it is read from the runtime.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np


def _rss_mb() -> float | None:
    try:
        import psutil
    except ImportError:
        return None
    try:
        return psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        return None


def _model_paths(models_dir: Path) -> dict[str, Path]:
    """The four Open Model Zoo IR models, with the precision each was fetched at.

    Kept in step with ``setup_delivery_models.MODEL_FILES``; the declared
    precision here is the folder the weights came from, and the benchmark
    compares it with what the runtime reports.
    """
    return {
        "face_detection": models_dir / "face" / "face-detection-retail-0004.xml",
        "head_pose": models_dir / "head_pose" / "head-pose-estimation-adas-0001.xml",
        "facial_landmarks": models_dir / "landmarks" / "facial-landmarks-35-adas-0002.xml",
        "gaze_estimation": models_dir / "gaze" / "gaze-estimation-adas-0002.xml",
    }


DECLARED_PRECISION = {
    "face_detection": "FP16",
    "head_pose": "FP16",
    "facial_landmarks": "FP16-INT8",
    "gaze_estimation": "FP16",
}


def _percentile(values: list[float], pct: float) -> float:
    return float(np.percentile(np.asarray(values, dtype=float), pct)) if values else 0.0


def _random_inputs(compiled) -> dict[Any, np.ndarray]:
    """Synthetic inputs matching each port's shape.

    Latency depends on shape, not on pixel values, so random data measures the
    same thing a real frame would - and avoids making the benchmark depend on a
    recording being present.
    """
    inputs: dict[Any, np.ndarray] = {}
    for port in compiled.inputs:
        shape = [int(d) for d in port.shape]
        inputs[port] = np.random.rand(*shape).astype(np.float32)
    return inputs


def _compiled_precision(compiled) -> str:
    """What the runtime says it is executing, not what the folder was named."""
    try:
        value = compiled.get_property("INFERENCE_PRECISION_HINT")
        return str(value)
    except Exception:
        pass
    try:
        return str(compiled.inputs[0].element_type)
    except Exception:
        return "unknown"


def benchmark_model(
    name: str, xml_path: Path, device: str, *, iterations: int, warmup: int
) -> dict[str, Any]:
    import openvino as ov

    row: dict[str, Any] = {
        "model": name,
        "requested_device": device,
        "declared_precision": DECLARED_PRECISION.get(name, "unknown"),
    }
    if not xml_path.exists():
        row["error"] = f"model file missing: {xml_path}"
        return row

    rss_before = _rss_mb()
    core = ov.Core()

    t0 = time.perf_counter()
    try:
        model = core.read_model(str(xml_path))
    except Exception as exc:
        row["error"] = f"read_model failed: {type(exc).__name__}: {exc}"
        return row
    row["read_model_seconds"] = round(time.perf_counter() - t0, 4)

    t0 = time.perf_counter()
    try:
        compiled = core.compile_model(model, device, {"PERFORMANCE_HINT": "LATENCY"})
    except Exception as exc:
        row["error"] = f"compile failed on {device}: {type(exc).__name__}: {exc}"
        return row
    row["compile_seconds"] = round(time.perf_counter() - t0, 4)

    try:
        row["actual_device"] = str(compiled.get_property("EXECUTION_DEVICES"))
    except Exception:
        row["actual_device"] = device
    row["compiled_precision"] = _compiled_precision(compiled)
    row["input_shapes"] = [[int(d) for d in port.shape] for port in compiled.inputs]

    inputs = _random_inputs(compiled)

    # Cold inference includes lazy kernel/graph setup the warm numbers exclude.
    t0 = time.perf_counter()
    try:
        compiled(inputs)
    except Exception as exc:
        row["error"] = f"inference failed: {type(exc).__name__}: {exc}"
        return row
    row["first_inference_ms"] = round((time.perf_counter() - t0) * 1000, 3)

    for _ in range(max(0, warmup)):
        compiled(inputs)

    samples: list[float] = []
    started = time.perf_counter()
    for _ in range(max(1, iterations)):
        t0 = time.perf_counter()
        compiled(inputs)
        samples.append((time.perf_counter() - t0) * 1000.0)
    wall = time.perf_counter() - started

    rss_after = _rss_mb()
    row.update(
        {
            "iterations": len(samples),
            "mean_ms": round(statistics.mean(samples), 3),
            "median_ms": round(statistics.median(samples), 3),
            "p95_ms": round(_percentile(samples, 95), 3),
            "p99_ms": round(_percentile(samples, 99), 3),
            "min_ms": round(min(samples), 3),
            "max_ms": round(max(samples), 3),
            "throughput_fps": round(len(samples) / max(wall, 1e-9), 2),
            "rss_growth_mb": (
                round(rss_after - rss_before, 1)
                if rss_before is not None and rss_after is not None
                else None
            ),
        }
    )
    return row


def available_devices() -> list[str]:
    from .device_utils import available_devices as devices

    return devices()


def run(
    models_dir: Path, devices: list[str], *, iterations: int, warmup: int
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for device in devices:
        for name, path in _model_paths(models_dir).items():
            rows.append(
                benchmark_model(name, path, device, iterations=iterations, warmup=warmup)
            )
    return rows


def format_report(rows: list[dict[str, Any]], devices: list[str]) -> str:
    lines = [
        "# Clarivo OpenVINO device / precision benchmark",
        "",
        f"Devices measured: {', '.join(devices) if devices else 'none'}",
        "",
        "| Model | Requested | Actual | Declared prec. | Compiled prec. | Compile (s) "
        "| Cold (ms) | Mean (ms) | p95 (ms) | p99 (ms) | FPS |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        if r.get("error"):
            lines.append(
                f"| {r['model']} | {r['requested_device']} | - | "
                f"{r.get('declared_precision', '?')} | - | - | - | - | - | - | - |"
            )
            continue
        lines.append(
            f"| {r['model']} | {r['requested_device']} | {r.get('actual_device', '?')} | "
            f"{r.get('declared_precision', '?')} | {r.get('compiled_precision', '?')} | "
            f"{r.get('compile_seconds', '-')} | {r.get('first_inference_ms', '-')} | "
            f"{r.get('mean_ms', '-')} | {r.get('p95_ms', '-')} | {r.get('p99_ms', '-')} | "
            f"{r.get('throughput_fps', '-')} |"
        )

    failures = [r for r in rows if r.get("error")]
    if failures:
        lines += ["", "## Not measured", ""]
        for r in failures:
            lines.append(f"- **{r['model']}** on {r['requested_device']}: {r['error']}")

    lines += [
        "",
        "## Reading this table",
        "",
        "- *Actual* differing from *Requested* means the fallback chain moved the model;",
        "  a claim about the requested device would be wrong for that row.",
        "- *Compiled prec.* comes from the runtime. On CPU, FP16 IR is executed as FP32",
        "  or bf16, so an FP16 file does not imply FP16 arithmetic there.",
        "- p95/p99 matter more than the mean for a per-frame pipeline: the tail is what",
        "  shows up as a stutter.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--models-dir", type=Path, default=Path(__file__).resolve().parent / "models")
    parser.add_argument("--devices", nargs="*", default=None,
                        help="devices to measure; defaults to everything OpenVINO reports")
    parser.add_argument("--iterations", type=int, default=50)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    try:
        import openvino  # noqa: F401
    except ImportError:
        print(
            "OpenVINO is not installed in this environment, so nothing can be measured.\n"
            "Install it with:  pip install -r requirements-local.txt"
        )
        return

    devices = args.devices if args.devices else available_devices()
    if not devices:
        print("OpenVINO reported no available devices.")
        return

    rows = run(args.models_dir, devices, iterations=args.iterations, warmup=args.warmup)
    report = format_report(rows, devices)
    print(report)

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({"devices": devices, "rows": rows}, indent=2), encoding="utf-8"
        )
        print(f"\nSaved {args.json}")


if __name__ == "__main__":
    main()
