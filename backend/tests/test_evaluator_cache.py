"""Tests for evaluation caching and the evidence fields.

The cache is content-addressed: a hit can only happen when every input that can
change the verdict is byte-identical, so it returns a previous answer to the
same question and never a stale answer to a changed one. These tests pin that
property, because a cache that returned a result for an edited transcript would
show the presenter feedback about words they had already removed.
"""

import pytest

from app import evaluator
from app.schemas import AnalysisRequest

BASE_TRANSCRIPT = (
    "Merge sort splits the list in half repeatedly until each piece holds one element, "
    "then merges the pieces back together in order. Because each merge pass touches every "
    "element once and there are log n passes, the running time is n log n."
)


def _request(**overrides) -> AnalysisRequest:
    fields = {
        "topic": "Explain Merge Sort",
        "target_audience": "Beginner",
        "transcript": BASE_TRANSCRIPT,
        "reference_content": None,
    }
    fields.update(overrides)
    return AnalysisRequest(**fields)


def _evaluation_payload() -> dict:
    return {
        "scores": {
            "correctness": 88, "completeness": 74, "logical_flow": 81,
            "clarity": 79, "examples": 55, "jumped_steps": 83, "audience_fit": 77,
        },
        "issues": [],
        "top_priorities": ["Add an example", "Explain why n log n", "Define merge"],
        "overall_feedback": "Solid outline with a missing worked example.",
        "revision_guidance": "Add one small worked example before stating the complexity.",
    }


@pytest.fixture
def cloudflare(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "cloudflare")
    monkeypatch.setenv("AI_CACHE_TTL_SECONDS", "3600")
    evaluator.clear_cache()

    calls: list[tuple] = []
    payload = _evaluation_payload()

    def fake_run(system_prompt, user_prompt, *, retry_note=None):
        calls.append((system_prompt, user_prompt, retry_note))
        return payload, None, "fake-model"

    monkeypatch.setattr(evaluator, "run_qwen_structured", fake_run)
    yield calls, payload
    evaluator.clear_cache()


def test_identical_request_is_served_from_cache(cloudflare):
    calls, _ = cloudflare
    first = evaluator.evaluate_explanation(_request())
    second = evaluator.evaluate_explanation(_request())

    assert len(calls) == 1, "an identical re-run must not cost a second inference call"
    assert first.scores == second.scores
    assert first.meta.cached is False
    assert second.meta.cached is True


def test_edited_transcript_is_not_served_from_cache(cloudflare):
    calls, _ = cloudflare
    evaluator.evaluate_explanation(_request())
    evaluator.evaluate_explanation(_request(transcript=BASE_TRANSCRIPT + " One extra sentence here."))
    assert len(calls) == 2


@pytest.mark.parametrize(
    "override",
    [
        {"target_audience": "Expert"},
        {"topic": "Explain Quick Sort"},
        {"reference_content": "Merge sort is a stable, comparison-based divide and conquer sort."},
    ],
)
def test_any_changed_input_bypasses_the_cache(cloudflare, override):
    calls, _ = cloudflare
    evaluator.evaluate_explanation(_request())
    evaluator.evaluate_explanation(_request(**override))
    assert len(calls) == 2


def test_cache_can_be_disabled(monkeypatch, cloudflare):
    calls, _ = cloudflare
    monkeypatch.setenv("AI_CACHE_TTL_SECONDS", "0")
    evaluator.evaluate_explanation(_request())
    evaluator.evaluate_explanation(_request())
    assert len(calls) == 2


def test_expired_entries_are_not_served(monkeypatch, cloudflare):
    calls, _ = cloudflare
    evaluator.evaluate_explanation(_request())
    monkeypatch.setenv("AI_CACHE_TTL_SECONDS", "0.0001")
    import time

    time.sleep(0.01)
    evaluator.evaluate_explanation(_request())
    assert len(calls) == 2


def test_dimension_evidence_and_reference_check_reach_the_response(cloudflare):
    calls, payload = cloudflare
    payload["dimension_evidence"] = {
        "correctness": {
            "evidence": ["the running time is n log n"],
            "reasoning": "The stated complexity matches the described algorithm.",
            "confidence": "high",
        },
        "examples": {"evidence": [], "reasoning": "No example given.", "confidence": "insufficient_evidence"},
    }
    payload["reference_check"] = {
        "reference_available": False,
        "supported_claims": [],
        "missing_from_transcript": [],
        "contradicted_by_reference": [],
        "unsupported_by_reference": [],
    }

    result = evaluator.evaluate_explanation(_request())
    assert result.dimension_evidence is not None
    assert result.dimension_evidence["correctness"].confidence == "high"
    assert result.dimension_evidence["examples"].confidence == "insufficient_evidence"
    assert result.reference_check is not None
    assert result.reference_check.reference_available is False


def test_evidence_is_optional(cloudflare):
    """A model that omits the supplementary fields still yields a usable result."""
    result = evaluator.evaluate_explanation(_request())
    assert result.dimension_evidence is None
    assert result.reference_check is None
    assert result.scores.correctness == 88
