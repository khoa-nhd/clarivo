from __future__ import annotations

import os
from typing import Any

from pydantic import ValidationError

from legacy_ai.schemas import CompactEvaluation

from .cloudflare_provider import run_qwen_structured
from .mock_provider import run_mock
from .parser import parse_ai_json
from .prompt import build_evaluation_prompts
from .schemas import AnalysisMeta, AnalysisRequest, AnalysisResult


def _normalize_legacy_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Tolerate harmless field-name variations without changing the rubric."""
    payload = dict(payload)

    if "overall_feedback" not in payload and "feedback" in payload:
        payload["overall_feedback"] = payload.pop("feedback")

    issues = payload.get("issues")
    if isinstance(issues, list):
        cleaned_issues = []
        for issue in issues:
            if isinstance(issue, dict):
                issue = dict(issue)
                issue.pop("sentence_index", None)
            cleaned_issues.append(issue)
        payload["issues"] = cleaned_issues

    if not payload.get("revision_guidance"):
        priorities = payload.get("top_priorities")
        if isinstance(priorities, list) and priorities:
            payload["revision_guidance"] = "Revise the explanation by focusing on: " + "; ".join(
                str(item) for item in priorities[:3]
            )
        else:
            payload["revision_guidance"] = "Revise the explanation using the diagnostic issues above."

    return payload


def _public_result_from_legacy(
    evaluation: CompactEvaluation,
    *,
    provider: str,
    model: str,
    prompt_version: str,
) -> AnalysisResult:
    data = evaluation.model_dump(mode="json")
    return AnalysisResult.model_validate(
        {
            "scores": data["scores"],
            "issues": data["issues"],
            "top_priorities": data["top_priorities"],
            "feedback": data["overall_feedback"],
            "revision_guidance": data["revision_guidance"],
            "meta": AnalysisMeta(
                provider=provider,
                model=model,
                prompt_version=prompt_version,
            ).model_dump(),
        }
    )


def _validate_candidate(candidate: dict[str, Any]) -> CompactEvaluation:
    return CompactEvaluation.model_validate(_normalize_legacy_payload(candidate))


def evaluate_explanation(request: AnalysisRequest) -> AnalysisResult:
    provider = os.getenv("AI_PROVIDER", "mock").strip().lower()

    if provider == "mock":
        payload, model = run_mock(request)
        payload.setdefault(
            "revision_guidance",
            "Mock mode: connect Cloudflare to receive real revision guidance.",
        )
        payload["meta"] = AnalysisMeta(
            provider="mock",
            model=model,
            prompt_version="mock",
        ).model_dump()
        return AnalysisResult.model_validate(payload)

    if provider != "cloudflare":
        raise ValueError(f"Unsupported AI_PROVIDER: {provider}")

    system_prompt, user_prompt, prompt_version = build_evaluation_prompts(request)
    max_attempts = max(1, min(int(os.getenv("AI_MAX_ATTEMPTS", "2")), 3))

    last_error: Exception | None = None
    model = os.getenv("CLOUDFLARE_MODEL", "@cf/qwen/qwen3-30b-a3b-fp8")

    for attempt in range(1, max_attempts + 1):
        retry_note = None
        if attempt > 1:
            retry_note = (
                "The previous response was not accepted as a valid structured evaluation. "
                "Do not output free-form JSON text. Ensure scores are integers 0-100, "
                "issue fields match the schema, and top_priorities contains 3-5 strings."
            )

        structured, raw, model = run_qwen_structured(
            system_prompt,
            user_prompt,
            retry_note=retry_note,
        )

        # Primary path: structured function-call arguments. No json.loads() on
        # generated prose, so quotation marks inside feedback cannot corrupt JSON.
        if structured is not None:
            try:
                evaluation = _validate_candidate(structured)
                return _public_result_from_legacy(
                    evaluation,
                    provider="cloudflare",
                    model=model,
                    prompt_version=prompt_version,
                )
            except ValidationError as exc:
                last_error = exc
                continue

        # Compatibility fallback: if Cloudflare/model did not emit a tool call,
        # accept a valid legacy JSON response. Malformed text is NOT regex-repaired;
        # the next attempt asks the model for structured output again.
        try:
            parsed = parse_ai_json(raw)
            evaluation = _validate_candidate(parsed)
            return _public_result_from_legacy(
                evaluation,
                provider="cloudflare",
                model=model,
                prompt_version=prompt_version,
            )
        except (ValueError, ValidationError, TypeError) as exc:
            last_error = exc
            continue

    raise ValueError(
        "Qwen could not return a valid structured evaluation after automatic retry. "
        "Please retry this session."
    ) from last_error
