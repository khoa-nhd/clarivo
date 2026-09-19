import sys
import types
from pathlib import Path

# Mirrors test_phase20_integration.py: the score logic under test does not need
# the real OpenVINO runtime, and importing local_scoring.audio_analyzer pulls in
# device_utils.py which imports openvino at module load time.
ov = types.ModuleType('openvino')
ov.Core = object
sys.modules.setdefault('openvino', ov)

from local_scoring.eval_harness import (
    aggregate,
    audio_point_errors,
    bucket_attention,
    bucket_posture,
    ClipResult,
    format_report,
    load_cases,
    vision_class_matches,
)


def test_bucket_posture_thresholds():
    assert bucket_posture(85) == "good"
    assert bucket_posture(70) == "good"
    assert bucket_posture(55) == "leaning"
    assert bucket_posture(40) == "leaning"
    assert bucket_posture(10) == "slouched"
    assert bucket_posture(None) is None


def test_bucket_attention_thresholds():
    assert bucket_attention(90) == "on_camera"
    assert bucket_attention(75) == "on_camera"
    assert bucket_attention(50) == "mixed"
    assert bucket_attention(10) == "off_camera"
    assert bucket_attention(None) is None


def test_audio_point_errors_only_scores_labeled_fields():
    prediction = {"wpm": 140.0, "fillers_per_minute": 3.0, "speaking_time_seconds": 30.0, "duration_seconds": 40.0}
    # long_pause_count intentionally not labeled -> must not appear in the errors dict.
    ground_truth = {"wpm": 132, "filler_count": 3, "speaking_time_seconds": 28.0}
    errors = audio_point_errors(prediction, ground_truth)
    assert set(errors) == {"wpm_abs_error", "filler_count_abs_error", "speaking_time_abs_error_seconds"}
    assert errors["wpm_abs_error"] == 8.0
    assert errors["filler_count_abs_error"] == 1.0
    assert errors["speaking_time_abs_error_seconds"] == 2.0


def test_vision_class_matches_detects_mismatch():
    prediction = {"posture": 20.0, "camera_attention": 90.0}
    ground_truth = {"posture_class": "good", "attention_class": "on_camera"}
    matches = vision_class_matches(prediction, ground_truth)
    assert matches["posture_class_correct"] is False
    assert matches["attention_class_correct"] is True


def test_aggregate_computes_mae_and_accuracy_across_clips():
    results = [
        ClipResult(clip_id="a", notes="", audio_errors={"wpm_abs_error": 4.0}, vision_correct={"posture_class_correct": True}),
        ClipResult(clip_id="b", notes="", audio_errors={"wpm_abs_error": 8.0}, vision_correct={"posture_class_correct": False}),
    ]
    summary = aggregate(results)
    assert summary["clip_count"] == 2
    assert summary["audio"]["wpm_abs_error"]["mae"] == 6.0
    assert summary["audio"]["wpm_abs_error"]["max"] == 8.0
    assert summary["vision"]["posture_class_correct"]["accuracy"] == 0.5


def test_format_report_includes_every_metric_key():
    result = ClipResult(clip_id="clip001", notes="test clip", audio_errors={"wpm_abs_error": 3.0}, vision_correct={"attention_class_correct": True})
    summary = aggregate([result])
    report = format_report([result], summary)
    assert "clip001" in report
    assert "wpm_abs_error" in report
    assert "attention_class_correct" in report


def test_load_cases_on_empty_dataset_returns_empty_list(tmp_path):
    assert load_cases(tmp_path) == []


def test_load_cases_reads_labels_and_matches_clip_files(tmp_path):
    (tmp_path / "labels").mkdir()
    (tmp_path / "clips").mkdir()
    (tmp_path / "clips" / "clip001.mp4").write_bytes(b"not a real video")
    (tmp_path / "labels" / "clip001.json").write_text(
        '{"clip_id": "clip001", "notes": "n", "ground_truth": {"wpm": 120}}',
        encoding="utf-8",
    )
    cases = load_cases(tmp_path)
    assert len(cases) == 1
    assert cases[0].clip_id == "clip001"
    assert cases[0].ground_truth == {"wpm": 120}
    assert cases[0].video_path.name == "clip001.mp4"


def test_load_cases_skips_labels_with_no_matching_clip(tmp_path, capsys):
    (tmp_path / "labels").mkdir()
    (tmp_path / "clips").mkdir()
    (tmp_path / "labels" / "orphan.json").write_text('{"ground_truth": {}}', encoding="utf-8")
    cases = load_cases(tmp_path)
    assert cases == []


def test_real_eval_dataset_end_to_end_or_skip():
    """Runs the harness against whatever real self-recorded clips exist under
    local_scoring/eval_data. Skips (not fails) until the team has actually
    recorded and labeled clips, per the dataset-building step in the project
    roadmap - this keeps CI green pre-dataset while still catching regressions
    once real clips are added."""
    import pytest

    data_dir = Path(__file__).resolve().parent.parent / "local_scoring" / "eval_data"
    cases = load_cases(data_dir)
    if not cases:
        pytest.skip("No labeled clips under local_scoring/eval_data yet; see eval_data/README.md")

    from local_scoring.eval_harness import run_harness

    results, summary = run_harness(data_dir)
    assert summary["clip_count"] == len(cases)
    # Every clip should produce either a prediction or a clearly reported error -
    # never a silent no-op - so a broken setup shows up as a visible failure.
    for result in results:
        assert result.errors or result.audio_errors or result.vision_correct or result.audio_prediction or result.vision_prediction
