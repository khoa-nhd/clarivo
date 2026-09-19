from pathlib import Path

from app.content_eval_benchmark import (
    ContentResult,
    aggregate,
    format_report,
    load_cases,
    score_abs_errors,
)


def test_score_abs_errors_only_scores_labeled_fields():
    predicted = {"correctness": 82, "completeness": 60, "logical_flow": 75, "clarity": 88, "examples": 40, "jumped_steps": 90, "audience_fit": 70}
    human = {"correctness": 80, "completeness": 70}
    errors = score_abs_errors(predicted, human)
    assert errors == {"correctness": 2.0, "completeness": 10.0}


def test_aggregate_computes_mae_and_overall():
    results = [
        ContentResult(case_id="a", predicted_scores={"correctness": 84}, human_scores={"correctness": 80}, abs_errors={"correctness": 4.0}),
        ContentResult(case_id="b", predicted_scores={"correctness": 70}, human_scores={"correctness": 80}, abs_errors={"correctness": 10.0}),
    ]
    summary = aggregate(results)
    assert summary["case_count"] == 2
    assert summary["metrics"]["correctness"]["mae"] == 7.0
    assert summary["metrics"]["correctness"]["max"] == 10.0
    assert summary["overall_mae"] == 7.0


def test_format_report_includes_case_and_metric_names():
    result = ContentResult(case_id="case1", predicted_scores={"clarity": 82}, human_scores={"clarity": 80}, abs_errors={"clarity": 2.0})
    summary = aggregate([result])
    report = format_report([result], summary)
    assert "case1" in report
    assert "clarity" in report


def test_load_cases_on_empty_dataset_returns_empty_list(tmp_path):
    assert load_cases(tmp_path) == []


def test_load_cases_reads_valid_case_and_skips_invalid(tmp_path, capsys):
    (tmp_path / "good.json").write_text(
        '{"case_id": "good", "topic": "T", "transcript": "some transcript text", "human_scores": {"clarity": 80}}',
        encoding="utf-8",
    )
    (tmp_path / "bad.json").write_text('{"topic": "T"}', encoding="utf-8")  # missing required "transcript"
    cases = load_cases(tmp_path)
    assert len(cases) == 1
    assert cases[0].case_id == "good"
    assert cases[0].human_scores == {"clarity": 80}


def test_real_content_dataset_end_to_end_or_skip():
    """Runs the benchmark against whatever real labeled cases exist under
    app/eval_data/content. Skips (not fails) until the team has actually
    labeled cases, mirroring test_eval_harness.py's audio/vision equivalent."""
    import pytest

    data_dir = Path(__file__).resolve().parent.parent / "app" / "eval_data" / "content"
    cases = load_cases(data_dir)
    if not cases:
        pytest.skip("No labeled cases under app/eval_data/content yet; see eval_data/content/README.md")

    from app.content_eval_benchmark import run_benchmark

    results, summary = run_benchmark(data_dir)
    assert summary["case_count"] == len(cases)
    for result in results:
        assert result.errors or result.predicted_scores is not None
