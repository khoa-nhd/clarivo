"""Quantitative benchmark for Clarivo's camera-attention event logic.

Feeds the synthetic orientation tracks from ``synthetic_vision.py`` through the
production calibration (``_calibrated_gaze_states``) and event rules
(``_temporal_violation_stats``) and reports:

* event-level precision / recall / F1 against the episodes that really occurred;
* detection latency - how long after a look-away starts before it is reported;
* false alarms on tracks where the presenter never actually looked away.

Latency matters as much as accuracy here. The rules deliberately ignore short
glances, so an event that fires instantly would mean the tolerance is broken,
and one that fires after 10 s would mean the feedback no longer describes what
the presenter did.

Usage (from ``backend/``)::

    python -m local_scoring.cv_temporal_benchmark
    python -m local_scoring.cv_temporal_benchmark --json out.json
    python -m local_scoring.cv_temporal_benchmark --compare baseline.json

Needs no OpenVINO runtime and no model weights.
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any

from .config import VisionConfig
from .synthetic_vision import OrientationSequence, attention_suite


def _predicted_episodes(states: list[str], target: str, sample_fps: float,
                        cfg: VisionConfig) -> list[tuple[float, float]]:
    """Runs of ``target`` the production rules would treat as real events."""
    from .vision_analyzer import _temporal_violation_stats
    import math

    min_frames = max(1, int(math.ceil(cfg.gaze_sustain_seconds * sample_fps)))
    window_frames = max(min_frames, int(math.ceil(cfg.gaze_repeat_window_seconds * sample_fps)))

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

    sustained = {k for k, (a, b) in enumerate(runs) if b - a >= min_frames}
    repeated: set[int] = set()
    for k, (a, _) in enumerate(runs):
        recent: list[int] = []
        j = k
        while j >= 0 and a - runs[j][0] <= window_frames:
            recent.append(j)
            j -= 1
        if len(recent) >= max(2, int(cfg.gaze_repeat_count)):
            repeated.update(recent[: int(cfg.gaze_repeat_count)])

    # Cross-check against the production aggregate so this helper cannot drift
    # away from the rule it is meant to be measuring.
    stats = _temporal_violation_stats(
        states, target, sample_fps,
        sustain_seconds=cfg.gaze_sustain_seconds,
        repeat_window_seconds=cfg.gaze_repeat_window_seconds,
        repeat_count=cfg.gaze_repeat_count,
    )
    effective = sorted(sustained | repeated)
    assert len(sustained) == stats["sustained_episode_count"], "event rule drifted from production"

    return [(runs[k][0] / sample_fps, runs[k][1] / sample_fps) for k in effective]


def _match(predicted: list[tuple[float, float]], truth: list[tuple[float, float]],
           tolerance_seconds: float) -> tuple[int, int, int, list[float]]:
    """Greedy overlap matching. Returns (tp, fp, fn, latencies)."""
    unmatched = list(range(len(truth)))
    tp = 0
    latencies: list[float] = []
    for p_start, p_end in predicted:
        hit = None
        for k in unmatched:
            t_start, t_end = truth[k]
            # Overlap, allowing the prediction to start a little late because
            # the sustain window is a deliberate delay, not an error.
            if p_start < t_end + tolerance_seconds and p_end > t_start - tolerance_seconds:
                hit = k
                break
        if hit is None:
            continue
        tp += 1
        latencies.append(max(0.0, p_start - truth[hit][0]))
        unmatched.remove(hit)
    return tp, len(predicted) - tp, len(unmatched), latencies


def evaluate_sequence(sequence: OrientationSequence, cfg: VisionConfig) -> dict[str, Any]:
    from .vision_analyzer import _calibrated_gaze_states

    samples = list(sequence.samples)
    # Mirror analyze_video: a missing face inside the grace window holds the last
    # orientation; beyond it the sample becomes a true "away".
    grace = max(1, int(round(cfg.away_grace_seconds * sequence.sample_fps)))
    hints: list[str | None] = []
    missing_run = 0
    last_seen: tuple[float, float] | None = None
    held_samples: list[tuple[float, float] | None] = []
    for item in samples:
        if item is None:
            missing_run += 1
            if last_seen is not None and missing_run <= grace:
                held_samples.append(last_seen)
                hints.append("held")
            else:
                held_samples.append(None)
                hints.append("away")
        else:
            missing_run = 0
            last_seen = item
            held_samples.append(item)
            hints.append(None)

    gaze = _calibrated_gaze_states(held_samples, cfg, hints)
    states = list(gaze["states"])

    predicted = _predicted_episodes(states, "off_axis", sequence.sample_fps, cfg)
    truth, tolerated = sequence.reportable_episodes(
        sustain_seconds=cfg.gaze_sustain_seconds,
        repeat_window_seconds=cfg.gaze_repeat_window_seconds,
        repeat_count=cfg.gaze_repeat_count,
    )
    tp, fp, fn, latencies = _match(predicted, truth, tolerance_seconds=cfg.gaze_sustain_seconds + 1.0)

    engaged = sum(1 for s in states if s == "engaged")
    away = sum(1 for s in states if s == "away")

    return {
        "sequence": sequence.name,
        "tags": list(sequence.tags),
        "description": sequence.description,
        "duration_seconds": round(sequence.duration_seconds, 2),
        "true_events": len(truth),
        "tolerated_glances": len(tolerated),
        "predicted_events": len(predicted),
        "tp": tp, "fp": fp, "fn": fn,
        "detection_latencies_seconds": [round(x, 2) for x in latencies],
        "mean_detection_latency_seconds": round(statistics.mean(latencies), 2) if latencies else None,
        "engaged_percent": round(100.0 * engaged / max(1, len(states)), 1),
        "away_percent": round(100.0 * away / max(1, len(states)), 1),
        "baseline_yaw_deg": round(float(gaze["baseline_yaw"]), 2),
        "baseline_pitch_deg": round(float(gaze["baseline_pitch"]), 2),
        "true_camera_bias_yaw_deg": round(sequence.camera_bias_yaw, 2),
        "camera_bias_yaw_error_deg": round(
            abs(float(gaze["baseline_yaw"]) - sequence.camera_bias_yaw), 2
        ),
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    tp = sum(r["tp"] for r in rows)
    fp = sum(r["fp"] for r in rows)
    fn = sum(r["fn"] for r in rows)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    latencies = [x for r in rows for x in r["detection_latencies_seconds"]]
    clean = [r for r in rows if r["true_events"] == 0]

    return {
        "sequence_count": len(rows),
        "event_level": {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        },
        "mean_detection_latency_seconds": round(statistics.mean(latencies), 2) if latencies else None,
        "max_detection_latency_seconds": round(max(latencies), 2) if latencies else None,
        "false_alarms_on_clean_sequences": sum(r["fp"] for r in clean),
        "clean_sequence_count": len(clean),
        "mean_camera_bias_error_deg": round(
            statistics.mean(r["camera_bias_yaw_error_deg"] for r in rows), 2
        ),
        "max_camera_bias_error_deg": round(
            max((r["camera_bias_yaw_error_deg"] for r in rows), default=0.0), 2
        ),
    }


def run(cfg: VisionConfig | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cfg = cfg or VisionConfig()
    rows = [evaluate_sequence(s, cfg) for s in attention_suite()]
    return rows, summarise(rows)


def format_report(rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    ev = summary["event_level"]
    lines = [
        "# Clarivo camera-attention event benchmark (synthetic tracks, exact labels)",
        "",
        f"Sequences: {summary['sequence_count']}",
        "",
        "## Look-away event detection",
        "",
        "| Precision | Recall | F1 | TP | FP | FN |",
        "|---|---|---|---|---|---|",
        f"| {ev['precision']} | {ev['recall']} | {ev['f1']} | {ev['tp']} | {ev['fp']} | {ev['fn']} |",
        "",
        f"- mean detection latency: **{summary['mean_detection_latency_seconds']} s** "
        f"(worst {summary['max_detection_latency_seconds']} s)",
        f"- false alarms on sequences with no real look-away: "
        f"**{summary['false_alarms_on_clean_sequences']}** "
        f"over {summary['clean_sequence_count']} clean sequences",
        f"- camera mounting-bias recovery error: mean "
        f"**{summary['mean_camera_bias_error_deg']} deg**, worst "
        f"**{summary['max_camera_bias_error_deg']} deg**",
        "",
        "## Per-sequence detail",
        "",
        "| Sequence | Reportable | Tolerated | Predicted | TP | FP | FN | Latency (s) | Bias err | Engaged % |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['sequence']} | {r['true_events']} | {r['tolerated_glances']} | {r['predicted_events']} | {r['tp']} | "
            f"{r['fp']} | {r['fn']} | {r['mean_detection_latency_seconds']} | "
            f"{r['camera_bias_yaw_error_deg']} | {r['engaged_percent']} |"
        )
    return "\n".join(lines)


def format_comparison(baseline: dict[str, Any], current: dict[str, Any]) -> str:
    def row(label: str, path: list[str], better: str, digits: int = 3) -> str:
        b, c = baseline, current
        for key in path:
            b, c = (b or {}).get(key), (c or {}).get(key)
        if b is None or c is None:
            return f"| {label} | {b} | {c} | - |"
        delta = round(float(c) - float(b), digits)
        arrow = "" if delta == 0 else ("improved" if (delta > 0) == (better == "up") else "REGRESSED")
        return f"| {label} | {b} | {c} | {delta:+} {arrow} |"

    return "\n".join([
        "## Before / after",
        "",
        "| Metric | Before | After | Change |",
        "|---|---|---|---|",
        row("Event precision", ["event_level", "precision"], "up", 4),
        row("Event recall", ["event_level", "recall"], "up", 4),
        row("Event F1", ["event_level", "f1"], "up", 4),
        row("False alarms (clean tracks)", ["false_alarms_on_clean_sequences"], "down", 0),
        row("Mean detection latency (s)", ["mean_detection_latency_seconds"], "down", 2),
        row("Mean camera-bias error (deg)", ["mean_camera_bias_error_deg"], "down", 2),
        row("Worst camera-bias error (deg)", ["max_camera_bias_error_deg"], "down", 2),
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--compare", type=Path)
    parser.add_argument(
        "--pre-fix-config",
        action="store_true",
        help=(
            "run with the settings that were in force before the calibration and "
            "hysteresis fixes, to reproduce the 'before' column"
        ),
    )
    args = parser.parse_args()

    cfg = VisionConfig()
    if args.pre_fix_config:
        cfg = VisionConfig(
            gaze_calibration_use_full_session=False,
            orientation_hysteresis_points=0.0,
        )
    rows, summary = run(cfg)
    print(format_report(rows, summary))

    if args.compare and args.compare.exists():
        baseline = json.loads(args.compare.read_text(encoding="utf-8"))
        print()
        print(format_comparison(baseline.get("summary", baseline), summary))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"summary": summary, "sequences": rows}, indent=2), encoding="utf-8")
        print(f"\nSaved {args.json}")


if __name__ == "__main__":
    main()
