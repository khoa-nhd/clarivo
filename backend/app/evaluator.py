from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from typing import Any

from pydantic import ValidationError

from legacy_ai.schemas import CompactEvaluation

from .cloudflare_provider import run_qwen_structured
from .mock_provider import run_mock
from .parser import parse_ai_json
from .prompt import build_evaluation_prompts
from .schemas import AnalysisMeta, AnalysisRequest, AnalysisResult

# Bounded, TTL'd, content-addressed cache of completed evaluations.
_result_cache: "OrderedDict[str, tuple[float, AnalysisResult]]" = OrderedDict()
_cache_lock = threading.Lock()


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
            "dimension_evidence": data.get("dimension_evidence"),
            "reference_check": data.get("reference_check"),
            "meta": AnalysisMeta(
                provider=provider,
                model=model,
                prompt_version=prompt_version,
            ).model_dump(),
        }
    )


def _request_fingerprint(request: AnalysisRequest, prompt_version: str, model: str) -> str:
    """Stable identity for one evaluation request.

    Covers every input that can change the verdict, plus the prompt version and
    model, so a rubric or model change invalidates the cache automatically.
    """
    payload = json.dumps(
        {
            "topic": request.topic,
            "audience": request.target_audience,
            "transcript": request.transcript,
            "reference": request.reference_content or "",
            "prompt_version": prompt_version,
            "model": model,
            "temperature": os.getenv("AI_TEMPERATURE", "0.1"),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> AnalysisResult | None:
    """Look up an identical earlier evaluation.

    Keyed on the full content of the request, so a hit is by construction the
    same question - this returns a previous answer to the same input, never a
    stale answer to a changed one. Editing a single word of the transcript
    changes the key and forces a fresh evaluation.

    The main beneficiary is the retry button: re-running an unchanged session
    otherwise costs another full inference call and another 10-30 s wait.
    """
    ttl = float(os.getenv("AI_CACHE_TTL_SECONDS", "3600"))
    if ttl <= 0:
        return None
    with _cache_lock:
        entry = _result_cache.get(key)
        if entry is None:
            return None
        stored_at, result = entry
        if time.time() - stored_at > ttl:
            del _result_cache[key]
            return None
        _result_cache.move_to_end(key)
        return result


def _cache_put(key: str, result: AnalysisResult) -> None:
    if float(os.getenv("AI_CACHE_TTL_SECONDS", "3600")) <= 0:
        return
    max_entries = int(os.getenv("AI_CACHE_MAX_ENTRIES", "32"))
    with _cache_lock:
        _result_cache[key] = (time.time(), result)
        _result_cache.move_to_end(key)
        while len(_result_cache) > max_entries:
            _result_cache.popitem(last=False)


def clear_cache() -> None:
    """Drop every cached evaluation. Used by tests."""
    with _cache_lock:
        _result_cache.clear()


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

    cache_key = _request_fingerprint(request, prompt_version, model)
    cached = _cache_get(cache_key)
    if cached is not None:
        marked = cached.model_copy(deep=True)
        if marked.meta is not None:
            marked.meta.cached = True
        return marked

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
                result = _public_result_from_legacy(
                    evaluation,
                    provider="cloudflare",
                    model=model,
                    prompt_version=prompt_version,
                )
                _cache_put(cache_key, result)
                return result
            except ValidationError as exc:
                last_error = exc
                continue

        # Compatibility fallback: if Cloudflare/model did not emit a tool call,
        # accept a valid legacy JSON response. Malformed text is NOT regex-repaired;
        # the next attempt asks the model for structured output again.
        try:
            parsed = parse_ai_json(raw)
            evaluation = _validate_candidate(parsed)
            result = _public_result_from_legacy(
                evaluation,
                provider="cloudflare",
                model=model,
                prompt_version=prompt_version,
            )
            _cache_put(cache_key, result)
            return result
        except (ValueError, ValidationError, TypeError) as exc:
            last_error = exc
            continue

    raise ValueError(
        "Qwen could not return a valid structured evaluation after automatic retry. "
        "Please retry this session."
    ) from last_error
