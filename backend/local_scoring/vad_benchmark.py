"""Quantitative benchmark for Clarivo's speech-activity decision.

Runs the production ``_speech_activity`` over the synthetic clip suite in
``synthetic_audio.py`` (exact frame-level labels) and reports:

* frame-level precision / recall / F1 / false-positive rate / false-negative
  rate for the speech-vs-silence decision;
* absolute error on the aggregate metrics the user actually sees - speaking
  time, inner pause count, longest pause;
* how many clips fall through to ``NO_SPEECH_DETECTED``, and how many of those
  genuinely contain no speech.

That last number is the one that matters most: a clip wrongly classified as
silent loses *every* voice score, so a false "no speech" is far more damaging
to the product than a few percent of frame error.

Usage (from ``backend/``)::

    python -m local_scoring.vad_benchmark
    python -m local_scoring.vad_benchmark --json out.json
    python -m local_scoring.vad_benchmark --compare baseline.json

Nothing here needs OpenVINO, a model download, or a recording - only NumPy and
librosa - so it runs in CI and on a fresh checkout.
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

import numpy as np

from .config import AudioConfig
from .synthetic_audio import SyntheticClip, all_clips


def _confusion(predicted: np.ndarray, truth: np.ndarray) -> dict[str, int]:
    n = min(len(predicted), len(truth))
    predicted, truth = predicted[:n], truth[:n]
    return {
        "tp": int(np.sum(predicted & truth)),
        "fp": int(np.sum(predicted & ~truth)),
        "fn": int(np.sum(~predicted & truth)),
        "tn": int(np.sum(~predicted & ~truth)),
    }


def _rates(counts: dict[str, int]) -> dict[str, float]:
    tp, fp, fn, tn = counts["tp"], counts["fp"], counts["fn"], counts["tn"]
    precision = tp / (tp + fp) if (tp + fp) else (1.0 if tp == 0 and fp == 0 else 0.0)
    recall = tp / (tp + fn) if (tp + fn) else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "false_positive_rate": round(fp / (fp + tn), 4) if (fp + tn) else 0.0,
        "false_negative_rate": round(fn / (fn + tp), 4) if (fn + tp) else 0.0,
    }


def evaluate_clip(clip: SyntheticClip, cfg: AudioConfig) -> dict[str, Any]:
    from .audio_analyzer import _classify_speech_state, _speech_activity

    started = time.perf_counter()
    raw = _speech_activity(np.asarray(clip.audio, dtype=np.float32), clip.sample_rate, cfg)
    elapsed = time.perf_counter() - started

    predicted = np.asarray(raw.pop("speech_frame_mask"), dtype=bool)
    frame_seconds = float(raw.pop("frame_seconds"))
    truth = clip.frame_labels(frame_seconds)

    counts = _confusion(predicted, truth)
    rates = _rates(counts)

    gt_speech = clip.speech_seconds
    gt_pauses = clip.inner_pauses(cfg.silence_min_ms / 1000.0)
    predicted_pauses = list(raw.get("pause_durations") or [])

    # The gate that decides whether the user gets any voice score at all.
    # Mirrors the production web path: Cloudflare Whisper supplies the
    # transcript, so text_reliability is 1.0 and a word count is available.
    # ~2.4 words/second is a normal presentation rate and is only used to give
    # the gate a plausible transcript length for the speech that exists.
    simulated_words = int(gt_speech * 2.4)
    state = _classify_speech_state(
        raw, 1.0, cfg, word_count=simulated_words, transcript_supplied=True
    )
    # A clip is *expected* to be scored only when it carries enough speech to
    # score. Counting the deliberately-too-short clip as a failure would
    # penalise correct behaviour.
    should_be_scored = gt_speech >= cfg.min_speech_seconds_for_scoring
    has_speech = gt_speech > 0.0

    return {
        "clip": clip.name,
        "tags": list(clip.tags),
        "description": clip.description,
        "duration_seconds": round(clip.duration_seconds, 3),
        "ground_truth_speech_seconds": round(gt_speech, 3),
        "predicted_speech_seconds": round(float(raw["speaking_time_seconds"]), 3),
        "speaking_time_abs_error_seconds": round(abs(float(raw["speaking_time_seconds"]) - gt_speech), 3),
        "ground_truth_pause_count": len(gt_pauses),
        "predicted_pause_count": len(predicted_pauses),
        "pause_count_abs_error": abs(len(predicted_pauses) - len(gt_pauses)),
        "ground_truth_longest_pause_seconds": round(max(gt_pauses, default=0.0), 3),
        "predicted_longest_pause_seconds": round(float(raw["longest_pause_seconds"]), 3),
        "longest_pause_abs_error_seconds": round(
            abs(float(raw["longest_pause_seconds"]) - max(gt_pauses, default=0.0)), 3
        ),
        "threshold_dbfs": round(float(raw["speech_threshold_dbfs"]), 2),
        "noise_floor_dbfs": round(float(raw["noise_floor_dbfs"]), 2),
        "speech_snr_db": round(float(raw["speech_snr_db"]), 2),
        "vad_mode": str(raw.get("vad_mode", "")),
        "speech_state": state,
        "state_correct": (state == "SPEECH_DETECTED") == should_be_scored,
        "false_no_speech": bool(should_be_scored and state == "NO_SPEECH_DETECTED"),
        "false_speech": bool(not has_speech and state == "SPEECH_DETECTED"),
        "analysis_seconds": round(elapsed, 4),
        "realtime_factor_x": round(clip.duration_seconds / max(elapsed, 1e-9), 1),
        **counts,
        **rates,
    }


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pooled = {k: sum(int(r[k]) for r in rows) for k in ("tp", "fp", "fn", "tn")}
    speaking_errors = [r["speaking_time_abs_error_seconds"] for r in rows]
    pause_errors = [r["pause_count_abs_error"] for r in rows]
    longest_errors = [r["longest_pause_abs_error_seconds"] for r in rows]
    speech_clips = [r for r in rows if r["ground_truth_speech_seconds"] > 0]

    per_tag: dict[str, Any] = {}
    for tag in sorted({t for r in rows for t in r["tags"]}):
        tagged = [r for r in rows if tag in r["tags"]]
        tag_counts = {k: sum(int(r[k]) for r in tagged) for k in ("tp", "fp", "fn", "tn")}
        per_tag[tag] = {
            "clips": len(tagged),
            **_rates(tag_counts),
            "speaking_time_mae_seconds": round(
                statistics.mean(r["speaking_time_abs_error_seconds"] for r in tagged), 3
            ),
            "false_no_speech_clips": sum(1 for r in tagged if r["false_no_speech"]),
        }

    # Frame metrics restricted to clips the product actually scores. A clip the
    # gate declares N/A never produces a number for the user, so its frame
    # errors cannot reach them - they are reported separately rather than mixed
    # into the headline figure in either direction.
    scored = [r for r in rows if r["speech_state"] == "SPEECH_DETECTED"]
    pooled_scored = {k: sum(int(r[k]) for r in scored) for k in ("tp", "fp", "fn", "tn")}

    return {
        "clip_count": len(rows),
        "frame_level": {**pooled, **_rates(pooled)},
        "frame_level_scored_clips_only": {
            "clips": len(scored), **pooled_scored, **_rates(pooled_scored),
        },
        "speaking_time_mae_seconds": round(statistics.mean(speaking_errors), 3),
        "speaking_time_max_error_seconds": round(max(speaking_errors), 3),
        "speaking_time_mae_scored_clips_seconds": round(
            statistics.mean([r["speaking_time_abs_error_seconds"] for r in scored]), 3
        ) if scored else 0.0,
        "pause_count_mae": round(statistics.mean(pause_errors), 3),
        "longest_pause_mae_seconds": round(statistics.mean(longest_errors), 3),
        "speech_state_accuracy": round(
            sum(1 for r in rows if r["state_correct"]) / max(1, len(rows)), 4
        ),
        "false_no_speech_clips": sum(1 for r in rows if r["false_no_speech"]),
        "false_speech_clips": sum(1 for r in rows if r["false_speech"]),
        "clips_containing_speech": len(speech_clips),
        "mean_realtime_factor_x": round(statistics.mean(r["realtime_factor_x"] for r in rows), 1),
        "per_tag": per_tag,
    }


def run(cfg: AudioConfig | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cfg = cfg or AudioConfig()
    rows = [evaluate_clip(clip, cfg) for clip in all_clips()]
    return rows, summarise(rows)


def format_report(rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = [
        "# Clarivo VAD / speech-activity benchmark (synthetic clips, exact labels)",
        "",
        f"Clips: {summary['clip_count']}  |  clips containing speech: {summary['clips_containing_speech']}",
        "",
        "## Frame-level speech decision",
        "",
        "| Precision | Recall | F1 | FPR | FNR |",
        "|---|---|---|---|---|",
        "| {precision} | {recall} | {f1} | {false_positive_rate} | {false_negative_rate} |".format(
            **summary["frame_level"]
        ),
        "",
        "Restricted to the clips the product actually scores "
        f"({summary['frame_level_scored_clips_only']['clips']} of {summary['clip_count']}; "
        "a clip gated to N/A never shows the user a number):",
        "",
        "| Precision | Recall | F1 | FPR | FNR |",
        "|---|---|---|---|---|",
        "| {precision} | {recall} | {f1} | {false_positive_rate} | {false_negative_rate} |".format(
            **summary["frame_level_scored_clips_only"]
        ),
        "",
        "## Derived metrics the user sees",
        "",
        f"- speaking-time MAE: **{summary['speaking_time_mae_seconds']} s** "
        f"(worst clip {summary['speaking_time_max_error_seconds']} s; "
        f"{summary['speaking_time_mae_scored_clips_seconds']} s over scored clips only)",
        f"- pause-count MAE: **{summary['pause_count_mae']}**",
        f"- longest-pause MAE: **{summary['longest_pause_mae_seconds']} s**",
        f"- speech/no-speech state accuracy: **{summary['speech_state_accuracy']}**",
        f"- clips with speech wrongly reported as silent: **{summary['false_no_speech_clips']}**",
        f"- silent clips wrongly reported as speech: **{summary['false_speech_clips']}**",
        f"- mean analysis speed: **{summary['mean_realtime_factor_x']}x realtime**",
        "",
        "## By clip family",
        "",
        "| Family | Clips | Precision | Recall | F1 | Speaking-time MAE (s) | False 'no speech' |",
        "|---|---|---|---|---|---|---|",
    ]
    for tag, stats in summary["per_tag"].items():
        lines.append(
            f"| {tag} | {stats['clips']} | {stats['precision']} | {stats['recall']} | "
            f"{stats['f1']} | {stats['speaking_time_mae_seconds']} | {stats['false_no_speech_clips']} |"
        )

    lines += ["", "## Per-clip detail", "",
              "| Clip | GT speech (s) | Pred (s) | Err (s) | Recall | Threshold (dBFS) | VAD mode | State |",
              "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        # ASCII only: this prints to a Windows console that defaults to cp1252.
        flag = " (!)" if r["false_no_speech"] else ""
        lines.append(
            f"| {r['clip']} | {r['ground_truth_speech_seconds']} | {r['predicted_speech_seconds']} | "
            f"{r['speaking_time_abs_error_seconds']} | {r['recall']} | {r['threshold_dbfs']} | "
            f"{r['vad_mode']} | {r['speech_state']}{flag} |"
        )
    return "\n".join(lines)


def format_comparison(baseline: dict[str, Any], current: dict[str, Any]) -> str:
    def row(label: str, path: list[str], better: str, digits: int = 3) -> str:
        b, c = baseline, current
        for key in path:
            b, c = (b or {}).get(key), (c or {}).get(key)
        if b is None or c is None:
            return f"| {label} | - | - | - |"
        delta = round(float(c) - float(b), digits)
        arrow = "" if delta == 0 else ("improved" if (delta > 0) == (better == "up") else "REGRESSED")
        return f"| {label} | {b} | {c} | {delta:+} {arrow} |"

    return "\n".join([
        "## Before / after",
        "",
        "| Metric | Before | After | Change |",
        "|---|---|---|---|",
        row("Frame precision", ["frame_level", "precision"], "up", 4),
        row("Frame precision (scored clips)", ["frame_level_scored_clips_only", "precision"], "up", 4),
        row("Frame recall (scored clips)", ["frame_level_scored_clips_only", "recall"], "up", 4),
        row("Frame recall", ["frame_level", "recall"], "up", 4),
        row("Frame F1", ["frame_level", "f1"], "up", 4),
        row("Frame FNR", ["frame_level", "false_negative_rate"], "down", 4),
        row("Speaking-time MAE (s)", ["speaking_time_mae_seconds"], "down"),
        row("Speaking-time MAE, scored clips (s)", ["speaking_time_mae_scored_clips_seconds"], "down"),
        row("Speaking-time worst error (s)", ["speaking_time_max_error_seconds"], "down"),
        row("Pause-count MAE", ["pause_count_mae"], "down"),
        row("Longest-pause MAE (s)", ["longest_pause_mae_seconds"], "down"),
        row("Speech-state accuracy", ["speech_state_accuracy"], "up", 4),
        row("False 'no speech' clips", ["false_no_speech_clips"], "down", 0),
        row("False 'speech' clips", ["false_speech_clips"], "down", 0),
        row("Mean realtime factor (x)", ["mean_realtime_factor_x"], "up", 1),
    ])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", type=Path, help="write the full result to this JSON file")
    parser.add_argument("--compare", type=Path, help="print a before/after table against this JSON file")
    args = parser.parse_args()

    rows, summary = run()
    print(format_report(rows, summary))

    if args.compare and args.compare.exists():
        baseline = json.loads(args.compare.read_text(encoding="utf-8"))
        print()
        print(format_comparison(baseline.get("summary", baseline), summary))

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({"summary": summary, "clips": rows}, indent=2), encoding="utf-8"
        )
        print(f"\nSaved {args.json}")


if __name__ == "__main__":
    main()
