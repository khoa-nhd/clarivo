"""Quantitative evaluation harness for the audio/vision local-scoring pipeline.

Clarivo's audio and vision analyzers are entirely heuristic: every scoring curve
and component weight is hand-tuned with no labeled ground truth to check against
(see the AI 2026 Bảng B rubric's "kiểm thử định lượng" requirement). This module
is the missing piece: it runs the *unchanged* production analyzers
(`local_scoring.audio_analyzer.analyze_audio`, `local_scoring.vision_analyzer.analyze_video`)
against a small set of self-recorded, hand-labeled clips and reports how far the
predictions are from the ground truth, so accuracy work is measured, not guessed.

Directory layout expected under `--data-dir` (default: eval_data/ next to this file):

    eval_data/
      clips/
        clip001.mp4
        clip002.webm
      labels/
        clip001.json
        clip002.json

Each `labels/<name>.json` must have a stem matching a file in `clips/` and follows
this schema (all `ground_truth` fields optional; omit what you did not label):

    {
      "clip_id": "clip001",
      "notes": "free text, e.g. camera distance / lighting / accent",
      "ground_truth": {
        "transcript": "the exact words spoken, hand-corrected",
        "duration_seconds": 42.0,
        "wpm": 128,
        "filler_count": 5,
        "speaking_time_seconds": 34.0,
        "long_pause_count": 2,
        "posture_class": "good",       // good | leaning | slouched
        "attention_class": "on_camera" // on_camera | mixed | off_camera
      }
    }

Supplying `ground_truth.transcript` lets the audio analyzer skip local ASR
entirely (same "external transcript" path the production API uses), so audio
evaluation needs no OpenVINO Whisper setup - only `librosa` to decode the clip.
Vision evaluation needs the OpenVINO face/head/pose models set up via
`python -m local_scoring.setup_delivery_models` and is skipped with a clear
message if they are not present.

Usage (run from the `backend/` directory so the `local_scoring`/`app` packages
resolve):

    python -m local_scoring.eval_harness
    python -m local_scoring.eval_harness --data-dir local_scoring/eval_data --skip-vision
    python -m local_scoring.eval_harness --selftest   # pure logic check, no clips/models needed

Regression tests (`backend/tests/test_eval_harness.py`) exercise the pure
metric-computation functions below directly, and separately run this harness
end-to-end against any real labeled clips that exist, skipping gracefully when
none have been recorded yet.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

THIS_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = THIS_DIR / "eval_data"
DEFAULT_REPORT_DIR = THIS_DIR.parent / "local_scoring" / "eval_reports"
CLIP_EXTENSIONS = (".mp4", ".webm", ".mov", ".m4v")

POSTURE_CLASSES = ("good", "leaning", "slouched")
ATTENTION_CLASSES = ("on_camera", "mixed", "off_camera")


@dataclass
class ClipCase:
    clip_id: str
    video_path: Path
    audio_path: Path | None
    notes: str
    ground_truth: dict[str, Any]


@dataclass
class ClipResult:
    clip_id: str
    notes: str
    errors: list[str] = field(default_factory=list)
    audio_prediction: dict[str, Any] | None = None
    vision_prediction: dict[str, Any] | None = None
    audio_errors: dict[str, float] = field(default_factory=dict)
    vision_correct: dict[str, bool] = field(default_factory=dict)


def load_cases(data_dir: Path) -> list[ClipCase]:
    labels_dir = data_dir / "labels"
    clips_dir = data_dir / "clips"
    if not labels_dir.exists():
        return []

    cases: list[ClipCase] = []
    for label_path in sorted(labels_dir.glob("*.json")):
        payload = json.loads(label_path.read_text(encoding="utf-8"))
        stem = label_path.stem
        video_path = next(
            (clips_dir / f"{stem}{ext}" for ext in CLIP_EXTENSIONS if (clips_dir / f"{stem}{ext}").exists()),
            None,
        )
        if video_path is None:
            print(f"[eval_harness] WARNING: no clip file found for label {label_path.name} (looked for {stem}.mp4/.webm/.mov in {clips_dir})", file=sys.stderr)
            continue
        audio_override = payload.get("audio_file")
        audio_path = (data_dir / audio_override) if audio_override else None
        cases.append(ClipCase(
            clip_id=payload.get("clip_id", stem),
            video_path=video_path,
            audio_path=audio_path,
            notes=payload.get("notes", ""),
            ground_truth=payload.get("ground_truth", {}),
        ))
    return cases


# ---------------------------------------------------------------------------
# Pure metric functions (no I/O; independently unit-tested).
# ---------------------------------------------------------------------------

def bucket_posture(posture_score: float | None) -> str | None:
    """Map the analyzer's continuous posture score onto the 3-way ground-truth
    class scheme used for hand labeling. Thresholds are a labeling convenience,
    not part of production scoring."""
    if posture_score is None:
        return None
    if posture_score >= 70:
        return "good"
    if posture_score >= 40:
        return "leaning"
    return "slouched"


def bucket_attention(attention_score: float | None) -> str | None:
    if attention_score is None:
        return None
    if attention_score >= 75:
        return "on_camera"
    if attention_score >= 40:
        return "mixed"
    return "off_camera"


def audio_point_errors(prediction_metrics: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, float]:
    """Absolute-error metrics for every audio ground-truth field that was labeled."""
    errors: dict[str, float] = {}
    duration = float(ground_truth.get("duration_seconds") or prediction_metrics.get("duration_seconds") or 0.0)

    if "wpm" in ground_truth and prediction_metrics.get("wpm") is not None:
        errors["wpm_abs_error"] = abs(float(prediction_metrics["wpm"]) - float(ground_truth["wpm"]))

    if "filler_count" in ground_truth and prediction_metrics.get("fillers_per_minute") is not None and duration > 0:
        predicted_count = float(prediction_metrics["fillers_per_minute"]) * (duration / 60.0)
        errors["filler_count_abs_error"] = abs(predicted_count - float(ground_truth["filler_count"]))

    if "speaking_time_seconds" in ground_truth and prediction_metrics.get("speaking_time_seconds") is not None:
        errors["speaking_time_abs_error_seconds"] = abs(
            float(prediction_metrics["speaking_time_seconds"]) - float(ground_truth["speaking_time_seconds"])
        )

    if "long_pause_count" in ground_truth and prediction_metrics.get("long_pause_count") is not None:
        errors["long_pause_count_abs_error"] = abs(
            float(prediction_metrics["long_pause_count"]) - float(ground_truth["long_pause_count"])
        )

    return errors


def vision_class_matches(prediction_scores: dict[str, Any], ground_truth: dict[str, Any]) -> dict[str, bool]:
    """Bucketed-class agreement for every vision ground-truth field that was labeled."""
    matches: dict[str, bool] = {}
    if "posture_class" in ground_truth:
        predicted = bucket_posture(prediction_scores.get("posture"))
        if predicted is not None:
            matches["posture_class_correct"] = predicted == ground_truth["posture_class"]
    if "attention_class" in ground_truth:
        predicted = bucket_attention(prediction_scores.get("camera_attention"))
        if predicted is not None:
            matches["attention_class_correct"] = predicted == ground_truth["attention_class"]
    return matches


def aggregate(results: list[ClipResult]) -> dict[str, Any]:
    """Roll per-clip errors/matches into MAE / accuracy summary metrics."""
    audio_error_keys = sorted({k for r in results for k in r.audio_errors})
    vision_match_keys = sorted({k for r in results for k in r.vision_correct})

    summary: dict[str, Any] = {"clip_count": len(results), "audio": {}, "vision": {}}
    for key in audio_error_keys:
        values = [r.audio_errors[key] for r in results if key in r.audio_errors]
        if values:
            summary["audio"][key] = {
                "mae": round(statistics.mean(values), 3),
                "max": round(max(values), 3),
                "n": len(values),
            }
    for key in vision_match_keys:
        values = [r.vision_correct[key] for r in results if key in r.vision_correct]
        if values:
            summary["vision"][key] = {
                "accuracy": round(sum(1 for v in values if v) / len(values), 3),
                "n": len(values),
            }
    return summary


# ---------------------------------------------------------------------------
# Analyzer invocation (real I/O; requires librosa / OpenVINO as applicable).
# ---------------------------------------------------------------------------

def _run_audio(case: ClipCase, cfg) -> tuple[dict[str, Any] | None, str | None]:
    from local_scoring.audio_analyzer import analyze_audio
    from local_scoring.config import AudioConfig

    transcript = case.ground_truth.get("transcript")
    source_path = case.audio_path or case.video_path
    try:
        result = analyze_audio(
            source_path,
            whisper_model_dir=DEFAULT_DATA_DIR / "unused-eval-harness",
            device="CPU",
            language="en",
            cache_dir=DEFAULT_REPORT_DIR / "cache",
            transcript=transcript,
            cfg=cfg or AudioConfig(),
        )
        return result, None
    except Exception as exc:  # noqa: BLE001 - report and continue with other clips
        hint = "" if case.audio_path else " (try labeling an 'audio_file' with a pre-extracted WAV if librosa cannot decode this container)"
        return None, f"audio analysis failed: {exc}{hint}"


def _run_vision(case: ClipCase, cfg) -> tuple[dict[str, Any] | None, str | None]:
    try:
        from app.local_delivery import models_dir, models_ready, _model_paths, _device_choice
    except ImportError as exc:
        return None, f"could not import app.local_delivery ({exc}); run from the backend/ directory"

    if not models_ready():
        return None, "OpenVINO vision models are not set up; run: python -m local_scoring.setup_delivery_models"

    from local_scoring.vision_analyzer import analyze_video
    from local_scoring.config import VisionConfig

    paths = _model_paths(models_dir())
    try:
        result = analyze_video(
            case.video_path,
            face_model=paths["face"],
            head_pose_model=paths["head"],
            landmarks_model=paths["landmarks"],
            gaze_model=paths["gaze"],
            pose_model_dir=paths["pose"],
            device=_device_choice("RECOMMENDED", "vision"),
            pose_device=_device_choice("RECOMMENDED", "pose"),
            cache_dir=DEFAULT_REPORT_DIR / "cache",
            cfg=cfg or VisionConfig(),
        )
        return result, None
    except Exception as exc:  # noqa: BLE001
        return None, f"vision analysis failed: {exc}"


def run_harness(data_dir: Path, *, skip_audio: bool = False, skip_vision: bool = False, audio_cfg=None, vision_cfg=None) -> tuple[list[ClipResult], dict[str, Any]]:
    cases = load_cases(data_dir)
    results: list[ClipResult] = []

    for case in cases:
        result = ClipResult(clip_id=case.clip_id, notes=case.notes)

        if not skip_audio:
            audio_out, audio_err = _run_audio(case, audio_cfg)
            if audio_err:
                result.errors.append(audio_err)
            elif audio_out:
                result.audio_prediction = audio_out["metrics"]
                result.audio_errors = audio_point_errors(audio_out["metrics"], case.ground_truth)

        if not skip_vision:
            vision_out, vision_err = _run_vision(case, vision_cfg)
            if vision_err:
                result.errors.append(vision_err)
            elif vision_out:
                result.vision_prediction = vision_out["scores"]
                result.vision_correct = vision_class_matches(vision_out["scores"], case.ground_truth)

        results.append(result)

    return results, aggregate(results)


def format_report(results: list[ClipResult], summary: dict[str, Any]) -> str:
    lines = [f"# Clarivo local-scoring evaluation report", "", f"Clips evaluated: {summary['clip_count']}", ""]

    if summary["audio"]:
        lines += ["## Audio accuracy (mean absolute error vs. hand-labeled ground truth)", "", "| Metric | MAE | Max error | n |", "|---|---|---|---|"]
        for key, stats in summary["audio"].items():
            lines.append(f"| {key} | {stats['mae']} | {stats['max']} | {stats['n']} |")
        lines.append("")

    if summary["vision"]:
        lines += ["## Vision accuracy (bucketed-class agreement vs. hand-labeled ground truth)", "", "| Metric | Accuracy | n |", "|---|---|---|"]
        for key, stats in summary["vision"].items():
            lines.append(f"| {key} | {stats['accuracy']} | {stats['n']} |")
        lines.append("")

    lines += ["## Per-clip detail", ""]
    for r in results:
        lines.append(f"### {r.clip_id}")
        if r.notes:
            lines.append(f"_{r.notes}_")
        if r.errors:
            for e in r.errors:
                lines.append(f"- ERROR: {e}")
        for k, v in r.audio_errors.items():
            lines.append(f"- {k}: {round(v, 2)}")
        for k, v in r.vision_correct.items():
            lines.append(f"- {k}: {'match' if v else 'MISMATCH'}")
        if not r.errors and not r.audio_errors and not r.vision_correct:
            lines.append("- (no labeled ground-truth fields to compare)")
        lines.append("")

    return "\n".join(lines)


def _selftest() -> None:
    """Exercise the pure metric/report logic with synthetic data - no clips,
    no librosa, no OpenVINO required. Run with `--selftest`."""
    prediction_metrics = {"wpm": 140.0, "fillers_per_minute": 3.0, "speaking_time_seconds": 30.0, "long_pause_count": 1, "duration_seconds": 40.0}
    ground_truth = {"wpm": 132, "filler_count": 3, "speaking_time_seconds": 28.0, "long_pause_count": 2}
    errors = audio_point_errors(prediction_metrics, ground_truth)
    assert abs(errors["wpm_abs_error"] - 8.0) < 1e-6, errors
    assert abs(errors["filler_count_abs_error"] - 1.0) < 1e-6, errors
    assert abs(errors["speaking_time_abs_error_seconds"] - 2.0) < 1e-6, errors
    assert abs(errors["long_pause_count_abs_error"] - 1.0) < 1e-6, errors

    prediction_scores = {"posture": 82.0, "camera_attention": 55.0}
    gt2 = {"posture_class": "good", "attention_class": "mixed"}
    matches = vision_class_matches(prediction_scores, gt2)
    assert matches["posture_class_correct"] is True, matches
    assert matches["attention_class_correct"] is True, matches

    gt3 = {"posture_class": "slouched", "attention_class": "on_camera"}
    mismatches = vision_class_matches(prediction_scores, gt3)
    assert mismatches["posture_class_correct"] is False
    assert mismatches["attention_class_correct"] is False

    result = ClipResult(clip_id="selftest", notes="synthetic", audio_errors=errors, vision_correct=matches)
    summary = aggregate([result])
    assert summary["clip_count"] == 1
    assert summary["audio"]["wpm_abs_error"]["mae"] == 8.0
    assert summary["vision"]["posture_class_correct"]["accuracy"] == 1.0

    report_text = format_report([result], summary)
    assert "wpm_abs_error" in report_text
    assert "posture_class_correct" in report_text

    print("eval_harness selftest: ALL CHECKS PASSED")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--skip-audio", action="store_true")
    parser.add_argument("--skip-vision", action="store_true")
    parser.add_argument("--selftest", action="store_true", help="run the pure-logic self-check and exit (no clips/models needed)")
    args = parser.parse_args()

    if args.selftest:
        _selftest()
        return

    cases = load_cases(args.data_dir)
    if not cases:
        print(f"[eval_harness] No labeled clips found under {args.data_dir}. "
              f"Record clips into eval_data/clips/ and label them into eval_data/labels/ "
              f"(see the module docstring or eval_data/README.md for the schema).")
        return

    results, summary = run_harness(args.data_dir, skip_audio=args.skip_audio, skip_vision=args.skip_vision)
    report = format_report(results, summary)

    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "latest_report.md").write_text(report, encoding="utf-8")
    (args.report_dir / "latest_report.json").write_text(
        json.dumps({"summary": summary, "results": [r.__dict__ for r in results]}, indent=2, default=str),
        encoding="utf-8",
    )
    print(report)
    print(f"\nSaved to {args.report_dir / 'latest_report.md'} and latest_report.json")


if __name__ == "__main__":
    main()
