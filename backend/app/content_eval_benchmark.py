"""Quantitative benchmark for the LLM content evaluator (`app.evaluator`).

Same motivation as `local_scoring/eval_harness.py`, applied to the semantic
(Qwen-based) side: `correctness/completeness/logical_flow/clarity/examples/
jumped_steps/audience_fit` are currently only validated by "did the model
return a well-formed response", never checked against what a human rater
would actually score. This module runs the unchanged production evaluator
against a small set of transcripts with human-assigned reference scores and
reports the agreement (MAE + correlation) per metric, giving the "làm chủ AI"
/ baseline-comparison rubric row real evidence instead of an assertion.

Directory layout expected under `--data-dir` (default: eval_data/content next
to this file), one JSON file per labeled case:

    eval_data/content/
      merge_sort_beginner_01.json
      photosynthesis_advanced_02.json

Case schema:

    {
      "case_id": "merge_sort_beginner_01",
      "topic": "Explain Merge Sort",
      "target_audience": "Beginner",
      "reference_content": "optional grounding text, same as the product's Topic Library field",
      "transcript": "the presenter's transcript, exactly as the content evaluator would receive it",
      "human_scores": {
        "correctness": 80, "completeness": 70, "logical_flow": 75,
        "clarity": 85, "examples": 60, "jumped_steps": 90, "audience_fit": 80
      }
    }

`human_scores` fields are all optional - the benchmark only compares whatever
was actually hand-rated. A real, meaningful run needs `AI_PROVIDER=cloudflare`
with credentials configured (the default `AI_PROVIDER=mock` returns fixed
placeholder scores, useful only for exercising the harness's own plumbing).

Usage (run from `backend/`):

    python -m app.content_eval_benchmark
    python -m app.content_eval_benchmark --selftest   # pure logic check, no AI calls
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
DEFAULT_DATA_DIR = THIS_DIR / "eval_data" / "content"
DEFAULT_REPORT_DIR = THIS_DIR / "eval_reports"
SCORE_KEYS = ("correctness", "completeness", "logical_flow", "clarity", "examples", "jumped_steps", "audience_fit")


@dataclass
class ContentCase:
    case_id: str
    topic: str
    target_audience: str
    reference_content: str | None
    transcript: str
    human_scores: dict[str, int]


@dataclass
class ContentResult:
    case_id: str
    errors: list[str] = field(default_factory=list)
    predicted_scores: dict[str, int] | None = None
    human_scores: dict[str, int] = field(default_factory=dict)
    abs_errors: dict[str, float] = field(default_factory=dict)


def load_cases(data_dir: Path) -> list[ContentCase]:
    if not data_dir.exists():
        return []
    cases: list[ContentCase] = []
    for path in sorted(data_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        try:
            cases.append(ContentCase(
                case_id=payload.get("case_id", path.stem),
                topic=payload["topic"],
                target_audience=payload.get("target_audience", "Beginner"),
                reference_content=payload.get("reference_content"),
                transcript=payload["transcript"],
                human_scores=payload.get("human_scores", {}),
            ))
        except KeyError as exc:
            print(f"[content_eval_benchmark] WARNING: {path.name} missing required field {exc}; skipped", file=sys.stderr)
    return cases


# ---------------------------------------------------------------------------
# Pure metric functions (no I/O; independently unit-tested).
# ---------------------------------------------------------------------------

def score_abs_errors(predicted: dict[str, int], human: dict[str, int]) -> dict[str, float]:
    """Absolute error per metric that was both predicted and hand-labeled."""
    return {
        key: abs(float(predicted[key]) - float(human[key]))
        for key in SCORE_KEYS
        if key in human and predicted.get(key) is not None
    }


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    try:
        return round(statistics.correlation(xs, ys), 3)
    except statistics.StatisticsError:
        return None


def aggregate(results: list[ContentResult]) -> dict[str, Any]:
    summary: dict[str, Any] = {"case_count": len(results), "metrics": {}}
    for key in SCORE_KEYS:
        errors = [r.abs_errors[key] for r in results if key in r.abs_errors]
        if not errors:
            continue
        predicted_vals = [float(r.predicted_scores[key]) for r in results if r.predicted_scores and key in r.abs_errors]
        human_vals = [float(r.human_scores[key]) for r in results if key in r.abs_errors]
        summary["metrics"][key] = {
            "mae": round(statistics.mean(errors), 2),
            "max": round(max(errors), 2),
            "n": len(errors),
            "pearson_r": _pearson(predicted_vals, human_vals),
        }
    if summary["metrics"]:
        summary["overall_mae"] = round(statistics.mean(m["mae"] for m in summary["metrics"].values()), 2)
    return summary


def format_report(results: list[ContentResult], summary: dict[str, Any]) -> str:
    lines = ["# Clarivo content-evaluator benchmark report", "", f"Cases evaluated: {summary['case_count']}", ""]
    if summary.get("metrics"):
        lines += [f"Overall mean MAE across metrics: {summary.get('overall_mae')}", "",
                   "| Metric | MAE | Max error | Pearson r | n |", "|---|---|---|---|---|"]
        for key, stats in summary["metrics"].items():
            lines.append(f"| {key} | {stats['mae']} | {stats['max']} | {stats['pearson_r']} | {stats['n']} |")
        lines.append("")

    lines += ["## Per-case detail", ""]
    for r in results:
        lines.append(f"### {r.case_id}")
        if r.errors:
            for e in r.errors:
                lines.append(f"- ERROR: {e}")
        for key in SCORE_KEYS:
            if key in r.abs_errors:
                lines.append(f"- {key}: predicted={r.predicted_scores[key]} human={r.human_scores[key]} abs_error={round(r.abs_errors[key], 1)}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Evaluator invocation (real I/O; calls the configured AI_PROVIDER).
# ---------------------------------------------------------------------------

def _run_case(case: ContentCase) -> tuple[dict[str, int] | None, str | None]:
    from .evaluator import evaluate_explanation
    from .schemas import AnalysisRequest

    try:
        request = AnalysisRequest(
            topic=case.topic,
            target_audience=case.target_audience,
            transcript=case.transcript,
            reference_content=case.reference_content,
        )
        result = evaluate_explanation(request)
        return result.scores.model_dump(), None
    except Exception as exc:  # noqa: BLE001 - report and continue with other cases
        return None, f"evaluation failed: {exc}"


def run_benchmark(data_dir: Path) -> tuple[list[ContentResult], dict[str, Any]]:
    cases = load_cases(data_dir)
    results: list[ContentResult] = []
    for case in cases:
        result = ContentResult(case_id=case.case_id, human_scores=case.human_scores)
        predicted, error = _run_case(case)
        if error:
            result.errors.append(error)
        else:
            result.predicted_scores = predicted
            result.abs_errors = score_abs_errors(predicted, case.human_scores)
        results.append(result)
    return results, aggregate(results)


def _selftest() -> None:
    """Exercise the pure metric/report logic with synthetic data - no AI calls
    required. Run with `--selftest`."""
    predicted = {"correctness": 82, "completeness": 60, "logical_flow": 75, "clarity": 88, "examples": 40, "jumped_steps": 90, "audience_fit": 70}
    human = {"correctness": 80, "completeness": 70, "logical_flow": 75, "clarity": 80, "examples": 55}
    errors = score_abs_errors(predicted, human)
    assert set(errors) == {"correctness", "completeness", "logical_flow", "clarity", "examples"}, errors
    assert errors["correctness"] == 2.0
    assert errors["completeness"] == 10.0
    assert errors["logical_flow"] == 0.0

    result = ContentResult(case_id="case1", predicted_scores=predicted, human_scores=human, abs_errors=errors)
    summary = aggregate([result])
    assert summary["case_count"] == 1
    assert summary["metrics"]["correctness"]["mae"] == 2.0
    assert "overall_mae" in summary

    report = format_report([result], summary)
    assert "case1" in report and "correctness" in report

    print("content_eval_benchmark selftest: ALL CHECKS PASSED")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        _selftest()
        return

    cases = load_cases(args.data_dir)
    if not cases:
        print(f"[content_eval_benchmark] No labeled cases found under {args.data_dir}. "
              f"See the module docstring for the case schema.")
        return

    results, summary = run_benchmark(args.data_dir)
    report = format_report(results, summary)

    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "latest_content_report.md").write_text(report, encoding="utf-8")
    (args.report_dir / "latest_content_report.json").write_text(
        json.dumps({"summary": summary, "results": [r.__dict__ for r in results]}, indent=2, default=str),
        encoding="utf-8",
    )
    print(report)
    print(f"\nSaved to {args.report_dir / 'latest_content_report.md'} and latest_content_report.json")


if __name__ == "__main__":
    main()
