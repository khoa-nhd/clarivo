from __future__ import annotations

import json
import os
from typing import Any

import requests


class CloudflareAIError(RuntimeError):
    pass


TOOL_NAME = "submit_evaluation"


def _evaluation_tool() -> dict[str, Any]:
    """Schema used for Workers AI traditional function calling.

    The evaluator prompt remains the source of truth for scoring. This tool only
    constrains the transport format so a stray quote cannot break json.loads().
    """
    categories = [
        "correctness",
        "completeness",
        "logical_flow",
        "clarity",
        "examples",
        "jumped_steps",
        "audience_fit",
    ]
    score_properties = {
        name: {"type": "integer", "minimum": 0, "maximum": 100}
        for name in categories
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
                    "required": categories,
                },
                "issues": {
                    "type": "array",
                    "maxItems": 6,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "category": {"type": "string", "enum": categories},
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
    return (
        "\n\nSTRUCTURED OUTPUT TRANSPORT OVERRIDE:\n"
        f"The API provides exactly one function tool named {TOOL_NAME}. "
        "After completing the evaluation, CALL THAT TOOL EXACTLY ONCE. "
        "Put the complete required evaluation object in the tool arguments. "
        "Do not return the evaluation as normal assistant prose or a markdown code block. "
        "The tool argument schema is the required output format."
    )


def _decode_arguments(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


def _extract_tool_arguments(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Accept Workers AI native and OpenAI-like tool-call response shapes."""
    result: Any = payload.get("result", payload)

    # Native Workers AI traditional function-calling response:
    # {"result": {"tool_calls": [{"name": ..., "arguments": {...}}]}}
    if isinstance(result, dict):
        tool_calls = result.get("tool_calls")
        if isinstance(tool_calls, list):
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                if call.get("name") not in (None, TOOL_NAME):
                    continue
                args = _decode_arguments(call.get("arguments"))
                if args is not None:
                    return args

        # Some compatible APIs nest tool calls in choices[].message.tool_calls[].
        choices = result.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                message = choice.get("message")
                if not isinstance(message, dict):
                    continue
                calls = message.get("tool_calls")
                if not isinstance(calls, list):
                    continue
                for call in calls:
                    if not isinstance(call, dict):
                        continue
                    function = call.get("function")
                    if isinstance(function, dict):
                        if function.get("name") not in (None, TOOL_NAME):
                            continue
                        args = _decode_arguments(function.get("arguments"))
                    else:
                        args = _decode_arguments(call.get("arguments"))
                    if args is not None:
                        return args

        # Defensive support if a provider returns the structured object directly.
        response_value = result.get("response")
        if isinstance(response_value, dict):
            return response_value

    return None


def _extract_model_output(payload: dict[str, Any]) -> object:
    """Fallback extraction for non-tool text responses."""
    result: object = payload.get("result", payload)

    if isinstance(result, dict):
        if "response" in result:
            return result["response"]

        choices = result.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                message = first.get("message")
                if isinstance(message, dict) and "content" in message:
                    return message["content"]
                if "text" in first:
                    return first["text"]

    return result


def _post_inference(
    *,
    account_id: str,
    auth_token: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    timeout: float,
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"

    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json",
            },
            json={
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt + _transport_override(),
                    },
                    {"role": "user", "content": user_prompt},
                ],
                # Traditional Workers AI function-calling format.
                "tools": [_evaluation_tool()],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise CloudflareAIError("Cloudflare AI request timed out. Retry this session.") from exc
    except requests.RequestException as exc:
        raise CloudflareAIError(f"Could not reach Cloudflare AI: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise CloudflareAIError(
            f"Cloudflare returned a non-JSON response (HTTP {response.status_code})."
        ) from exc

    if not response.ok or payload.get("success") is False:
        messages: list[str] = []
        for error in payload.get("errors", []) or []:
            if isinstance(error, dict) and error.get("message"):
                messages.append(str(error["message"]))
        message = "; ".join(messages) or (
            f"Cloudflare AI request failed (HTTP {response.status_code})."
        )
        raise CloudflareAIError(message)

    return payload


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
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    auth_token = os.getenv("CLOUDFLARE_AUTH_TOKEN", "").strip()
    model = os.getenv("CLOUDFLARE_MODEL", "@cf/qwen/qwen3-30b-a3b-fp8").strip()
    timeout = float(os.getenv("AI_TIMEOUT_SECONDS", "120"))
    max_tokens = int(os.getenv("AI_MAX_TOKENS", "3000"))
    temperature = float(os.getenv("AI_TEMPERATURE", "0.1"))

    if not account_id or not auth_token:
        raise CloudflareAIError(
            "AI_PROVIDER=cloudflare but CLOUDFLARE_ACCOUNT_ID or "
            "CLOUDFLARE_AUTH_TOKEN is missing."
        )

    effective_user_prompt = user_prompt
    if retry_note:
        effective_user_prompt += (
            "\n\nRETRY FORMAT INSTRUCTION:\n"
            + retry_note
            + f"\nYou must call {TOOL_NAME} exactly once with every required field."
        )

    payload = _post_inference(
        account_id=account_id,
        auth_token=auth_token,
        model=model,
        system_prompt=system_prompt,
        user_prompt=effective_user_prompt,
        timeout=timeout,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    structured = _extract_tool_arguments(payload)
    raw = _extract_model_output(payload)
    return structured, raw, model


# Kept for compatibility with any local code that imported run_qwen directly.
def run_qwen(system_prompt: str, user_prompt: str) -> tuple[object, str]:
    structured, raw, model = run_qwen_structured(system_prompt, user_prompt)
    return (structured if structured is not None else raw), model
