from __future__ import annotations

import os
from typing import Any

from .cloudflare_client import (
    CloudflareAIError,
    decode_arguments as _decode_arguments,
    extract_text as _extract_model_output,
    extract_tool_arguments,
    run_tool_call,
)

__all__ = [
    "CloudflareAIError",
    "TOOL_NAME",
    "run_qwen",
    "run_qwen_structured",
]

TOOL_NAME = "submit_evaluation"

CATEGORIES = [
    "correctness",
    "completeness",
    "logical_flow",
    "clarity",
    "examples",
    "jumped_steps",
    "audience_fit",
]


def _extract_tool_arguments(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Backwards-compatible wrapper over the shared extractor."""
    return extract_tool_arguments(payload, TOOL_NAME)


def _dimension_evidence_schema() -> dict[str, Any]:
    """Per-dimension justification for each score.

    A bare number is not reviewable: the presenter cannot tell whether
    "clarity 62" came from something they said or from the model's mood, and a
    maintainer cannot tell a rubric change from a regression. This attaches the
    transcript spans a score was actually derived from.

    Every field is optional. The seven scores remain the contract the UI relies
    on, and requiring a large extra object would turn a model that omits one
    sub-field into a failed evaluation and a second paid retry - a bad trade for
    supplementary detail.
    """
    entry = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "evidence": {
                "type": "array",
                "maxItems": 3,
                "items": {"type": "string"},
                "description": "Short spans copied verbatim from the transcript that drove this score.",
            },
            "reasoning": {
                "type": "string",
                "description": "One sentence linking the evidence to the score.",
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low", "insufficient_evidence"],
                "description": (
                    "Use insufficient_evidence when the transcript does not support "
                    "a confident judgement; never guess to fill the field."
                ),
            },
        },
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {name: entry for name in CATEGORIES},
    }


def _reference_check_schema() -> dict[str, Any]:
    """Explicit transcript-versus-reference comparison.

    The rubric already tells the model to compare against the reference, but the
    result of that comparison was only ever visible indirectly, folded into
    correctness and completeness. Reporting it separately lets a presenter see
    which specific claims were supported, missing or contradicted - and makes a
    hallucinated "missing concept" visible rather than buried in a score.
    """
    string_list = {"type": "array", "maxItems": 5, "items": {"type": "string"}}
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "supported_claims": string_list,
            "missing_from_transcript": string_list,
            "contradicted_by_reference": string_list,
            "unsupported_by_reference": string_list,
            "reference_available": {"type": "boolean"},
        },
    }


def evidence_enabled() -> bool:
    """Whether to ask the model for per-dimension evidence.

    A kill switch, not a feature flag. The evidence fields extend the tool
    schema sent to Workers AI, and that schema has not been exercised against
    the live Qwen deployment. If it turns out to be rejected in production, the
    seven scores the UI depends on would fail along with it - so it can be
    disabled by setting one environment variable, with no code change and no
    redeploy:

        AI_EVIDENCE_FIELDS=false

    Because the fields are optional in the schema and additive in the response,
    turning them off degrades the report to exactly the previous behaviour
    rather than breaking anything.
    """
    raw = os.getenv("AI_EVIDENCE_FIELDS")
    if raw is None or not raw.strip():
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _evaluation_tool() -> dict[str, Any]:
    """Schema used for Workers AI traditional function calling.

    The evaluator prompt remains the source of truth for scoring. This tool only
    constrains the transport format so a stray quote cannot break json.loads().
    """
    score_properties = {
        name: {"type": "integer", "minimum": 0, "maximum": 100}
        for name in CATEGORIES
    }

    return {
        "name": TOOL_NAME,
        "description": (
            "Submit the final Explanation Intelligence evaluation. "
            "Call this exactly once after evaluating the transcript."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "scores": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": score_properties,
                    "required": CATEGORIES,
                },
                "issues": {
                    "type": "array",
                    "maxItems": 6,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "category": {"type": "string", "enum": CATEGORIES},
                            "severity": {
                                "type": "string",
                                "enum": ["low", "medium", "high"],
                            },
                            "sentence": {
                                "anyOf": [
                                    {"type": "string"},
                                    {"type": "null"},
                                ]
                            },
                            "problem": {"type": "string"},
                            "suggestion": {"type": "string"},
                        },
                        "required": [
                            "category",
                            "severity",
                            "sentence",
                            "problem",
                            "suggestion",
                        ],
                    },
                },
                "top_priorities": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 5,
                    "items": {"type": "string"},
                },
                "overall_feedback": {"type": "string"},
                "revision_guidance": {"type": "string"},
                **(
                    {
                        "dimension_evidence": _dimension_evidence_schema(),
                        "reference_check": _reference_check_schema(),
                    }
                    if evidence_enabled()
                    else {}
                ),
            },
            "required": [
                "scores",
                "issues",
                "top_priorities",
                "overall_feedback",
                "revision_guidance",
            ],
        },
    }


def _transport_override() -> str:
    base = (
        "\n\nSTRUCTURED OUTPUT TRANSPORT OVERRIDE:\n"
        f"The API provides exactly one function tool named {TOOL_NAME}. "
        "After completing the evaluation, CALL THAT TOOL EXACTLY ONCE. "
        "Put the complete required evaluation object in the tool arguments. "
        "Do not return the evaluation as normal assistant prose or a markdown code block. "
        "The tool argument schema is the required output format."
    )
    if not evidence_enabled():
        # Kill switch engaged: do not ask for fields the schema no longer offers.
        return base
    return base + (
        "\n\nEVIDENCE REQUIREMENTS:\n"
        "Also fill dimension_evidence for every dimension you scored. For each one, quote at "
        "most three short spans copied verbatim from the transcript that your score is based on, "
        "add one sentence of reasoning, and state your confidence. "
        "If the transcript does not contain enough material to judge a dimension, set that "
        "dimension's confidence to insufficient_evidence and leave its evidence empty rather "
        "than inventing support for a number.\n"
        "Fill reference_check only from the supplied reference content. Set reference_available "
        "to false and leave the lists empty when no reference was supplied. Never state that "
        "the reference contains something it does not contain."
    )


def run_qwen_structured(
    system_prompt: str,
    user_prompt: str,
    *,
    retry_note: str | None = None,
) -> tuple[dict[str, Any] | None, object, str]:
    """Run Qwen using function calling.

    Returns (structured_payload_or_none, raw_fallback, model). The evaluator
    validates the structured payload with the preserved Pydantic schema and may
    retry once if the model failed to call the tool or violated the schema.
    """
    max_tokens = int(os.getenv("AI_MAX_TOKENS", "3000"))

    effective_user_prompt = user_prompt
    if retry_note:
        effective_user_prompt += (
            "\n\nRETRY FORMAT INSTRUCTION:\n"
            + retry_note
            + f"\nYou must call {TOOL_NAME} exactly once with every required field."
        )

    # The evaluator owns the schema-retry loop, so this call does not add one of
    # its own; a prose answer still comes back as raw text for the legacy JSON
    # fallback path rather than raising here.
    return run_tool_call(
        tool_name=TOOL_NAME,
        tool_description=_evaluation_tool()["description"],
        parameters=_evaluation_tool()["parameters"],
        system_prompt=system_prompt + _transport_override(),
        user_prompt=effective_user_prompt,
        max_tokens=max_tokens,
        retry_prompts=None,
        require_tool_call=False,
    )


# Kept for compatibility with any local code that imported run_qwen directly.
def run_qwen(system_prompt: str, user_prompt: str) -> tuple[object, str]:
    structured, raw, model = run_qwen_structured(system_prompt, user_prompt)
    return (structured if structured is not None else raw), model
