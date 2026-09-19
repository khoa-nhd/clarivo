"""Tests for the shared Workers AI transport.

The behaviour being pinned: a retry is only worth issuing when it can plausibly
succeed. Every retry re-sends the full transcript and reference content, so an
unnecessary one costs the user a second 10-30 second wait and costs the project
a second paid inference call - and re-sending a prompt after a 401 cannot
succeed no matter how many times it is tried.
"""

import json

import pytest
import requests

from app import cloudflare_client as cc


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text_body: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self._text_body = text_body

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        if self._text_body is not None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.calls.append({"url": url, "json": json})
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _tool_payload(args: dict) -> dict:
    return {"success": True, "result": {"tool_calls": [{"name": "t", "arguments": args}]}}


@pytest.fixture(autouse=True)
def _credentials(monkeypatch):
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "acct")
    monkeypatch.setenv("CLOUDFLARE_AUTH_TOKEN", "token")
    monkeypatch.setenv("AI_RETRY_BACKOFF_SECONDS", "0")
    cc.reset_session()
    yield
    cc.reset_session()


def _run(monkeypatch, responses, retry_prompts=None, require_tool_call=True):
    session = FakeSession(responses)
    monkeypatch.setattr(cc, "_http", lambda: session)
    result = cc.run_tool_call(
        tool_name="t",
        tool_description="d",
        parameters={"type": "object"},
        system_prompt="sys",
        user_prompt="user",
        max_tokens=100,
        retry_prompts=retry_prompts,
        require_tool_call=require_tool_call,
    )
    return result, session


def test_successful_tool_call_is_returned_without_retry(monkeypatch):
    (structured, _raw, _model), session = _run(
        monkeypatch, [FakeResponse(200, _tool_payload({"a": 1}))]
    )
    assert structured == {"a": 1}
    assert len(session.calls) == 1


def test_auth_failure_is_never_retried(monkeypatch):
    with pytest.raises(cc.CloudflareAuthError):
        _run(
            monkeypatch,
            [FakeResponse(401, {"success": False, "errors": [{"message": "Unauthorized"}]})],
            retry_prompts=["try again"],
        )


def test_auth_failure_does_not_consume_the_retry_budget(monkeypatch):
    session = FakeSession(
        [FakeResponse(403, {"success": False, "errors": [{"message": "Forbidden"}]})]
    )
    monkeypatch.setattr(cc, "_http", lambda: session)
    with pytest.raises(cc.CloudflareAuthError):
        cc.run_tool_call(
            tool_name="t", tool_description="d", parameters={}, system_prompt="s",
            user_prompt="u", max_tokens=10, retry_prompts=["a", "b"],
        )
    assert len(session.calls) == 1, "a 401/403 must not be re-sent"


def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    (structured, _raw, _model), session = _run(
        monkeypatch,
        [
            FakeResponse(429, {"success": False, "errors": [{"message": "Rate limit exceeded"}]}),
            FakeResponse(200, _tool_payload({"ok": True})),
        ],
        retry_prompts=["retry"],
    )
    assert structured == {"ok": True}
    assert len(session.calls) == 2


def test_transport_error_is_retried(monkeypatch):
    (structured, _raw, _model), session = _run(
        monkeypatch,
        [requests.ConnectionError("boom"), FakeResponse(200, _tool_payload({"ok": 1}))],
        retry_prompts=["retry"],
    )
    assert structured == {"ok": 1}
    assert len(session.calls) == 2


def test_missing_tool_call_is_retried_with_the_retry_prompt(monkeypatch):
    (structured, _raw, _model), session = _run(
        monkeypatch,
        [
            FakeResponse(200, {"success": True, "result": {"response": "sorry, prose"}}),
            FakeResponse(200, _tool_payload({"ok": 2})),
        ],
        retry_prompts=["OBEY THE SCHEMA"],
    )
    assert structured == {"ok": 2}
    assert len(session.calls) == 2
    assert "OBEY THE SCHEMA" in session.calls[1]["json"]["messages"][1]["content"]
    assert "OBEY THE SCHEMA" not in session.calls[0]["json"]["messages"][1]["content"]


def test_retry_budget_is_bounded_by_the_prompt_list(monkeypatch):
    session = FakeSession([FakeResponse(500, {"success": False}) for _ in range(5)])
    monkeypatch.setattr(cc, "_http", lambda: session)
    with pytest.raises(cc.CloudflareAIError):
        cc.run_tool_call(
            tool_name="t", tool_description="d", parameters={}, system_prompt="s",
            user_prompt="u", max_tokens=10, retry_prompts=["one"],
        )
    assert len(session.calls) == 2, "one retry prompt means at most two calls"


def test_prose_response_is_allowed_when_tool_call_is_not_required(monkeypatch):
    (structured, raw, _model), session = _run(
        monkeypatch,
        [FakeResponse(200, {"success": True, "result": {"response": "some text"}})],
        require_tool_call=False,
    )
    assert structured is None
    assert raw == "some text"
    assert len(session.calls) == 1


def test_openai_shaped_tool_call_is_extracted():
    payload = {
        "success": True,
        "result": {
            "choices": [
                {"message": {"tool_calls": [
                    {"function": {"name": "t", "arguments": json.dumps({"x": 5})}}
                ]}}
            ]
        },
    }
    assert cc.extract_tool_arguments(payload, "t") == {"x": 5}


def test_missing_credentials_raise_auth_error(monkeypatch):
    monkeypatch.delenv("CLOUDFLARE_AUTH_TOKEN", raising=False)
    with pytest.raises(cc.CloudflareAuthError):
        cc.credentials()


def test_transport_and_schema_budgets_are_independent(monkeypatch):
    """A transport blip must not consume the retry a malformed response needs."""
    session = FakeSession([
        requests.ConnectionError("blip"),                               # transport, retried
        FakeResponse(200, {"success": True, "result": {"response": "prose"}}),  # schema miss
        FakeResponse(200, _tool_payload({"ok": True})),                  # reworded prompt works
    ])
    monkeypatch.setattr(cc, "_http", lambda: session)
    structured, _raw, _model = cc.run_tool_call(
        tool_name="t", tool_description="d", parameters={}, system_prompt="s",
        user_prompt="u", max_tokens=10,
        retry_prompts=["FOLLOW THE SCHEMA"], transport_retries=1,
    )
    assert structured == {"ok": True}
    assert len(session.calls) == 3
    # The transport retry re-sent the prompt verbatim; only the schema retry reworded it.
    assert session.calls[0]["json"]["messages"][1]["content"] == "u"
    assert session.calls[1]["json"]["messages"][1]["content"] == "u"
    assert "FOLLOW THE SCHEMA" in session.calls[2]["json"]["messages"][1]["content"]


def test_schema_failure_costs_two_calls_not_four(monkeypatch):
    """The drill path's budget: one schema retry, not a multiplied nest of them."""
    session = FakeSession([
        FakeResponse(200, {"success": True, "result": {"response": "prose"}}) for _ in range(6)
    ])
    monkeypatch.setattr(cc, "_http", lambda: session)
    with pytest.raises(cc.CloudflareSchemaError):
        cc.run_tool_call(
            tool_name="t", tool_description="d", parameters={}, system_prompt="s",
            user_prompt="u", max_tokens=10,
            retry_prompts=["retry"], transport_retries=1,
        )
    assert len(session.calls) == 2, "a schema miss must not spend the transport budget too"


def test_a_persistent_transport_fault_does_not_trigger_a_reworded_retry(monkeypatch):
    session = FakeSession([requests.ConnectionError("down") for _ in range(6)])
    monkeypatch.setattr(cc, "_http", lambda: session)
    with pytest.raises(cc.CloudflareAIError):
        cc.run_tool_call(
            tool_name="t", tool_description="d", parameters={}, system_prompt="s",
            user_prompt="u", max_tokens=10,
            retry_prompts=["retry"], transport_retries=1,
        )
    assert len(session.calls) == 2, "rewording cannot fix an unreachable endpoint"
