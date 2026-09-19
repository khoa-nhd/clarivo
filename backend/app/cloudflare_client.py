"""Shared transport for every Cloudflare Workers AI call.

Before this module, ``cloudflare_provider`` and ``drill_engine`` each carried
their own copy of the request builder, the tool-call extractor and the retry
loop. Three problems followed from that:

* **Duplicated extraction.** Two near-identical ``_extract_tool_arguments``
  implementations had already drifted apart, so a response shape handled in one
  file was not necessarily handled in the other.

* **Multiplied retries.** ``drill_engine`` wrapped a function that already
  retried twice inside a loop that retried twice, and the inner loop retried on
  *any* exception - including a 401. One logical request could therefore issue
  four paid inference calls, each carrying the full transcript and reference,
  before reporting a failure that was obvious on the first. Retries are now
  split into two budgets with different justifications (see ``run_tool_call``),
  and a failure that no retry can fix ends the request immediately.

* **A new TLS handshake per call.** Every request built a fresh connection.
  A pooled ``Session`` reuses the connection across the several calls a single
  session makes (content evaluation, drill generation, per-round Q&A scoring,
  learning-state update, finalisation).

Retries are also now selective. Re-sending a long prompt after a 401 or a
malformed-request 400 cannot succeed; it only doubles the latency the user
waits before seeing the error. Only transport failures, 5xx and 429 are worth
retrying, and 429 waits before trying again instead of hammering immediately.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from typing import Any

import requests
from requests.adapters import HTTPAdapter


class CloudflareAIError(RuntimeError):
    """Any Workers AI failure."""


class CloudflareAuthError(CloudflareAIError):
    """Credentials are missing, invalid, or lack permission. Never retried."""


class CloudflareRateLimitError(CloudflareAIError):
    """Rate limited or out of quota."""


class CloudflareSchemaError(CloudflareAIError):
    """The call succeeded but the model did not return the required tool call."""


class _TransportFault(CloudflareAIError):
    """Internal: a fault a verbatim re-send could plausibly fix."""


_session_lock = threading.Lock()
_session: requests.Session | None = None


def _http() -> requests.Session:
    """Process-wide pooled session.

    ``pool_maxsize`` is above 1 because the frontend fires content, audio and
    vision analysis concurrently, and FastAPI runs the sync handlers in a thread
    pool - so several of these calls really can be in flight at once.
    """
    global _session
    with _session_lock:
        if _session is None:
            session = requests.Session()
            adapter = HTTPAdapter(pool_connections=4, pool_maxsize=8, max_retries=0)
            session.mount("https://", adapter)
            _session = session
        return _session


def reset_session() -> None:
    """Drop the pooled session. Used by tests."""
    global _session
    with _session_lock:
        if _session is not None:
            _session.close()
        _session = None


def credentials() -> tuple[str, str, str]:
    account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
    auth_token = os.getenv("CLOUDFLARE_AUTH_TOKEN", "").strip()
    model = os.getenv("CLOUDFLARE_MODEL", "@cf/qwen/qwen3-30b-a3b-fp8").strip()
    if not account_id or not auth_token:
        raise CloudflareAuthError(
            "AI_PROVIDER=cloudflare but CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_AUTH_TOKEN is missing."
        )
    return account_id, auth_token, model


def decode_arguments(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return None
        return decoded if isinstance(decoded, dict) else None
    return None


def extract_tool_arguments(payload: dict[str, Any], tool_name: str) -> dict[str, Any] | None:
    """Pull the tool arguments out of any response shape Workers AI returns.

    Handles the native ``result.tool_calls[]`` form, the OpenAI-compatible
    ``result.choices[].message.tool_calls[].function`` form, and a provider that
    puts the structured object straight into ``result.response``.
    """
    result: Any = payload.get("result", payload)
    if not isinstance(result, dict):
        return None

    calls = result.get("tool_calls")
    if isinstance(calls, list):
        for call in calls:
            if not isinstance(call, dict) or call.get("name") not in (None, tool_name):
                continue
            args = decode_arguments(call.get("arguments"))
            if args is not None:
                return args

    choices = result.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            for call in message.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                function = call.get("function")
                if isinstance(function, dict):
                    if function.get("name") not in (None, tool_name):
                        continue
                    args = decode_arguments(function.get("arguments"))
                else:
                    args = decode_arguments(call.get("arguments"))
                if args is not None:
                    return args

    response_value = result.get("response")
    return response_value if isinstance(response_value, dict) else None


def extract_text(payload: dict[str, Any]) -> object:
    """Fallback extraction when the model answered in prose instead of a tool call."""
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


def _classify(status_code: int, payload: dict[str, Any]) -> CloudflareAIError:
    messages: list[str] = []
    for error in payload.get("errors", []) or []:
        if isinstance(error, dict) and error.get("message"):
            messages.append(str(error["message"]))
    detail = "; ".join(messages) or str(payload.get("message") or f"HTTP {status_code}")
    lowered = detail.lower()

    if status_code in (401, 403) or "authentication" in lowered or "unauthorized" in lowered:
        return CloudflareAuthError(detail)
    if status_code == 429 or "rate limit" in lowered or "too many requests" in lowered:
        return CloudflareRateLimitError(detail)
    if "quota" in lowered or "neurons" in lowered or "daily" in lowered:
        return CloudflareRateLimitError(detail)
    return CloudflareAIError(detail)


def _is_retryable(error: Exception, status_code: int | None) -> bool:
    """Whether re-sending the same prompt could plausibly produce a different result.

    Determined from the failure itself, not from the type the error was wrapped
    in: transport faults are re-raised as ``CloudflareAIError`` for callers, so
    the caller's own type is not enough to classify them here.
    """
    if isinstance(error, CloudflareAuthError):
        return False
    if isinstance(error, (CloudflareRateLimitError, CloudflareSchemaError)):
        return True
    if status_code is not None:
        return status_code >= 500
    return False


def _backoff_seconds(attempt: int, base: float) -> float:
    # Exponential with jitter, so concurrent analyses do not retry in lockstep.
    return min(base * (2 ** attempt), 8.0) * (0.5 + random.random() * 0.5)


def run_tool_call(
    *,
    tool_name: str,
    tool_description: str,
    parameters: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    retry_prompts: list[str] | None = None,
    transport_retries: int = 1,
    require_tool_call: bool = True,
) -> tuple[dict[str, Any] | None, object, str]:
    """Run one structured request, retrying only where a retry can help.

    Two independent budgets, because the two failures are different:

    * ``transport_retries`` covers faults that say nothing about the prompt -
      a dropped connection, a timeout, a 5xx, a 429. The identical request is
      re-sent, so no prompt change is needed and the attempt does not consume a
      schema retry.
    * ``retry_prompts`` covers the model answering in the wrong shape. Each
      entry is appended to the prompt for one further attempt, so its length is
      the schema-retry budget.

    Keeping them separate is what stops one transport blip from eating the
    schema retry a malformed response will need, and stops a schema retry from
    silently multiplying into several paid calls.

    Returns ``(tool_arguments, raw_text, model)``.
    """
    account_id, auth_token, model = credentials()
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
    timeout = float(os.getenv("AI_TIMEOUT_SECONDS", "120"))
    temperature = float(os.getenv("AI_TEMPERATURE", "0.1"))
    backoff_base = float(os.getenv("AI_RETRY_BACKOFF_SECONDS", "1.0"))

    schema_attempts = 1 + len(retry_prompts or [])
    session = _http()
    headers = {"Authorization": f"Bearer {auth_token}", "Content-Type": "application/json"}
    last_error: Exception | None = None

    def _send(prompt: str) -> tuple[dict[str, Any] | None, object]:
        """One request. Raises; never retries."""
        try:
            response = session.post(
                url,
                headers=headers,
                json={
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "tools": [
                        {
                            "name": tool_name,
                            "description": tool_description,
                            "parameters": parameters,
                        }
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "stream": False,
                },
                timeout=timeout,
            )
        except requests.Timeout as exc:
            raise _TransportFault("Cloudflare AI request timed out.") from exc
        except requests.RequestException as exc:
            raise _TransportFault(f"Could not reach Cloudflare AI: {exc}") from exc

        status_code = response.status_code
        try:
            payload = response.json()
        except ValueError as exc:
            raise CloudflareAIError(
                f"Cloudflare returned a non-JSON response (HTTP {status_code})."
            ) from exc

        if not response.ok or payload.get("success") is False:
            error = _classify(status_code, payload)
            if status_code >= 500:
                raise _TransportFault(str(error))
            raise error

        structured = extract_tool_arguments(payload, tool_name)
        raw = extract_text(payload)
        if structured is None and require_tool_call:
            raise CloudflareSchemaError(
                "The model did not return the required structured tool call."
            )
        return structured, raw

    for schema_attempt in range(schema_attempts):
        prompt = user_prompt
        if schema_attempt > 0 and retry_prompts:
            prompt = f"{user_prompt}\n\n{retry_prompts[schema_attempt - 1]}"

        # Transport budget is per prompt attempt and is spent only on faults
        # that a verbatim re-send could fix.
        for transport_attempt in range(1 + max(0, transport_retries)):
            try:
                structured, raw = _send(prompt)
                return structured, raw, model
            except _TransportFault as exc:
                last_error = CloudflareAIError(str(exc))
                last_error.__cause__ = exc.__cause__ or exc
            except CloudflareRateLimitError as exc:
                last_error = exc
            except CloudflareAIError as exc:
                # Auth failures and malformed-request errors: a re-send cannot
                # help, and neither can a reworded prompt.
                last_error = exc
                if not _is_retryable(exc, None):
                    raise
                break

            if transport_attempt < max(0, transport_retries):
                time.sleep(_backoff_seconds(transport_attempt, backoff_base))
            else:
                break

        # Only a schema failure is worth a reworded prompt; a transport fault
        # that survived its own budget will not be fixed by rewording.
        if not isinstance(last_error, CloudflareSchemaError):
            break

    assert last_error is not None
    raise last_error
