"""Anthropic adapter over httpx.MockTransport (never the real provider) + production gate."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.core.startup_checks import production_problems
from app.modules.ai.adapters import (
    AIConfigurationError,
    AIProviderError,
    AIRequest,
    AnthropicAdapter,
    FakeAIAdapter,
    cost_estimate,
    get_ai_adapter,
    set_ai_adapter,
)

REQ = AIRequest(
    feature="tutor",
    model="claude-sonnet-5-5",
    system="sys",
    messages=[{"role": "user", "content": "SECRET learner text"}],
    max_tokens=100,
    json_schema={"type": "object"},
    effort="low",
)
OK = {
    "model": "claude-sonnet-5-5",
    "stop_reason": "end_turn",
    "content": [{"type": "text", "text": '{"reply_md": "hi"}'}],
    "usage": {"input_tokens": 12, "output_tokens": 7},
}


def _adapter(handler: Any, sleeps: list[float] | None = None, **kw: Any) -> AnthropicAdapter:
    async def _sleep(s: float) -> None:
        (sleeps if sleeps is not None else []).append(s)

    return AnthropicAdapter("sk-test", transport=httpx.MockTransport(handler), sleep=_sleep, **kw)


async def test_request_shape_and_parse() -> None:
    seen: list[httpx.Request] = []

    def h(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=OK)

    out = await _adapter(h).complete(REQ)
    assert (out.text, out.tokens_in, out.tokens_out, out.model) == (
        '{"reply_md": "hi"}',
        12,
        7,
        "claude-sonnet-5-5",
    )
    r = seen[0]
    assert r.url.path == "/v1/messages" and r.headers["x-api-key"] == "sk-test"
    assert r.headers["anthropic-version"] == "2023-06-01"
    body = json.loads(r.content)
    assert body["model"] == "claude-sonnet-5-5" and body["system"] == "sys" and body["max_tokens"] == 100
    assert body["output_config"] == {
        "effort": "low",
        "format": {"type": "json_schema", "schema": {"type": "object"}},
    }
    assert "temperature" not in body


async def test_retries_429_and_5xx_then_succeeds() -> None:
    statuses = iter([429, 503, 200])
    sleeps: list[float] = []

    def h(req: httpx.Request) -> httpx.Response:
        s = next(statuses)
        return httpx.Response(
            s, json=OK if s == 200 else {}, headers={"retry-after": "1"} if s == 429 else {}
        )

    out = await _adapter(h, sleeps, max_retries=2).complete(REQ)
    assert out.tokens_out == 7 and sleeps == [1.0, 1.0]


async def test_gives_up_after_retries() -> None:
    calls = []

    def h(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(529, json={"error": {"type": "overloaded_error"}})

    with pytest.raises(AIProviderError):
        await _adapter(h, max_retries=1).complete(REQ)
    assert len(calls) == 2


async def test_connection_error_and_4xx_and_refusal() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("nope")

    with pytest.raises(AIProviderError):
        await _adapter(boom, max_retries=0).complete(REQ)

    calls = []

    def bad(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(
            400, json={"error": {"type": "invalid_request_error", "message": "SECRET learner text"}}
        )

    with pytest.raises(AIProviderError) as e:
        await _adapter(bad).complete(REQ)
    assert len(calls) == 1 and "SECRET" not in str(e.value)  # 4xx not retried, body not echoed

    with pytest.raises(AIProviderError):
        await _adapter(lambda r: httpx.Response(200, json={**OK, "stop_reason": "refusal"})).complete(REQ)


async def test_no_prompt_text_in_logs(capsys: Any) -> None:
    await _adapter(lambda r: httpx.Response(200, json=OK)).complete(REQ)
    captured = capsys.readouterr()
    assert "SECRET" not in captured.out + captured.err


def test_adapter_requires_key_and_https() -> None:
    with pytest.raises(AIConfigurationError):
        AnthropicAdapter("")
    with pytest.raises(AIConfigurationError):
        AnthropicAdapter("k", base_url="http://insecure")


def test_cost_estimate() -> None:
    assert str(cost_estimate("anthropic", "claude-sonnet-5-5", 1_000_000, 100_000)) == "3.000000"
    assert cost_estimate("fake", "claude-sonnet-5-5", 10, 10) == 0


def _prod(**kw: Any) -> Settings:
    return Settings(
        APP_ENV="prod", TD_DISABLE_API_DOCS=True, TD_COOKIE_SECURE=True, TD_SERVICE_TOKEN="f" * 64, **kw
    )


def test_production_gate(monkeypatch: Any) -> None:
    def has(problems: list[str]) -> bool:
        return any("ai provider" in p for p in problems)

    monkeypatch.setenv("AI_PROVIDER", "fake")
    assert has(production_problems(_prod()))
    with pytest.raises(AIConfigurationError):
        get_ai_adapter(_prod())
    set_ai_adapter(FakeAIAdapter())
    try:
        with pytest.raises(AIConfigurationError):
            get_ai_adapter(_prod())
    finally:
        set_ai_adapter(None)
    monkeypatch.setenv("AI_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "REPLACE_ME")
    assert has(production_problems(_prod()))  # missing / placeholder key refused
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-" + "x" * 40)
    assert not has(production_problems(_prod()))
    assert isinstance(get_ai_adapter(_prod()), AnthropicAdapter)  # constructed, never called
    monkeypatch.setenv("AI_PROVIDER", "disabled")
    assert not has(production_problems(_prod()))
    with pytest.raises(AIProviderError):
        get_ai_adapter(_prod())
    monkeypatch.setenv("AI_PROVIDER", "fake")
    assert isinstance(get_ai_adapter(Settings(APP_ENV="test")), FakeAIAdapter)
