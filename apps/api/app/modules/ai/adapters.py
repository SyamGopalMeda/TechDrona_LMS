"""Provider adapter layer (the only code in Tech Drona that talks to a model provider).

``get_ai_adapter()`` selects by ``AI_PROVIDER`` (read from the environment / .env, like the
judge gateway's Judge0 settings):

* ``fake`` (default) → ``FakeAIAdapter``: deterministic, schema-valid output, never calls a
  network. Refused when APP_ENV is production (startup gate + factory).
* ``anthropic`` → ``AnthropicAdapter`` (Messages API over httpx). Needs ``ANTHROPIC_API_KEY``;
  a missing / placeholder key is refused by the production startup gate and makes every AI call
  answer ``ai_unavailable`` elsewhere.
* ``disabled`` → no adapter; every AI call answers ``ai_unavailable`` (explicit opt-out that
  production accepts).

Other settings: ``AI_DEFAULT_MODEL`` (default ``claude-sonnet-5-5``), ``AI_ALLOWED_MODELS``
(comma list), ``ANTHROPIC_BASE_URL``, ``AI_TIMEOUT_S``, ``AI_MAX_RETRIES``.

Logging: only metadata (feature, model, status, token counts) — prompts and learner text are
never logged at any level.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

import httpx
import structlog

from app.core.config import Settings, get_settings
from app.core.security import load_env_mapping

log = structlog.get_logger("app.ai")

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_ALLOWED_MODELS = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-haiku-5-5")
ANTHROPIC_VERSION = "2023-06-01"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# USD per 1M tokens (input, output) — estimates for the usage ledger only.
PRICING: dict[str, tuple[Decimal, Decimal]] = {
    "claude-sonnet-5-5": (Decimal("2.00"), Decimal("10.00")),
    "claude-opus-5-5": (Decimal("4.00"), Decimal("20.00")),
    "claude-haiku-5-5": (Decimal("0.10"), Decimal("0.50")),
}


def cost_estimate(provider: str, model: str, tokens_in: int, tokens_out: int) -> Decimal:
    if provider == "fake":
        return Decimal("0")
    pin, pout = PRICING.get(model, PRICING[DEFAULT_MODEL])
    return ((pin * tokens_in + pout * tokens_out) / Decimal(1_000_000)).quantize(Decimal("0.000001"))


class AIProviderError(RuntimeError):
    """Provider unreachable / rejected the request / not configured (→ ``ai_unavailable``)."""


class AIConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AIRequest:
    feature: str
    model: str
    system: str
    messages: list[dict[str, str]]
    max_tokens: int = 4096
    json_schema: dict[str, Any] | None = None
    effort: str = "medium"
    # Non-sensitive hints for the fake adapter (counts, types); never sent to a provider.
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AICompletion:
    text: str
    tokens_in: int
    tokens_out: int
    model: str
    stop_reason: str | None = None


class AIAdapter(Protocol):
    provider: str
    is_fake: bool

    async def complete(self, req: AIRequest) -> AICompletion: ...


# --------------------------------------------------------------------------- configuration


@dataclass(frozen=True, slots=True)
class AIConfig:
    provider: str  # fake | anthropic | disabled
    api_key_configured: bool
    default_model: str
    allowed_models: tuple[str, ...]

    @property
    def configured(self) -> bool:
        return self.provider == "fake" or (self.provider == "anthropic" and self.api_key_configured)


def _placeholder(v: str | None) -> bool:
    s = (v or "").strip()
    return not s or "REPLACE" in s.upper() or "PLACEHOLDER" in s.upper()


def load_config() -> AIConfig:
    env = load_env_mapping()
    provider = (env.get("AI_PROVIDER") or "fake").strip().lower()
    default_model = (env.get("AI_DEFAULT_MODEL") or DEFAULT_MODEL).strip()
    allowed = tuple(
        m.strip()
        for m in (env.get("AI_ALLOWED_MODELS") or ",".join(DEFAULT_ALLOWED_MODELS)).split(",")
        if m.strip()
    )
    if default_model not in allowed:
        allowed = (default_model, *allowed)
    return AIConfig(
        provider=provider,
        api_key_configured=not _placeholder(env.get("ANTHROPIC_API_KEY")),
        default_model=default_model,
        allowed_models=allowed,
    )


def production_problem(s: Settings) -> bool:
    """Startup gate check: fake provider, unknown provider or anthropic without a key."""
    cfg = load_config()
    if cfg.provider == "disabled":
        return False
    if cfg.provider == "anthropic":
        return not cfg.api_key_configured
    return True  # fake or unknown


# --------------------------------------------------------------------------- Anthropic


class AnthropicAdapter:
    """Anthropic Messages API (``POST /v1/messages``) over httpx with bounded retries."""

    provider = "anthropic"
    is_fake = False

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "https://api.anthropic.com",
        timeout_s: float = 60.0,
        max_retries: int = 2,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        structured_output: bool = True,
    ) -> None:
        if not api_key:
            raise AIConfigurationError("ANTHROPIC_API_KEY not configured")
        if not base_url.startswith("https://") and transport is None:
            raise AIConfigurationError("the model provider must be reached over https")
        self._base = base_url.rstrip("/")
        self._headers = {
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "anthropic-beta": FALLBACK_BETA,
            "content-type": "application/json",
        }
        self._timeout = httpx.Timeout(timeout_s, connect=10.0)
        self._retries = max(0, max_retries)
        self._transport = transport
        self._sleep = sleep
        self._structured = structured_output

    def body(self, req: AIRequest) -> dict[str, Any]:
        output_config: dict[str, Any] = {"effort": req.effort}
        if req.json_schema is not None and self._structured:
            output_config["format"] = {"type": "json_schema", "schema": req.json_schema}
        return {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "system": req.system,
            "messages": req.messages,
            "output_config": output_config,
            "fallbacks": "default",  # server-side refusal fallback (beta header above)
        }

    async def complete(self, req: AIRequest) -> AICompletion:
        body = self.body(req)
        last = "unknown"
        for attempt in range(self._retries + 1):
            delay = min(8.0, 0.5 * (2**attempt))
            try:
                async with httpx.AsyncClient(
                    base_url=self._base,
                    headers=self._headers,
                    timeout=self._timeout,
                    transport=self._transport,
                ) as c:
                    r = await c.post("/v1/messages", json=body)
            except httpx.HTTPError as e:
                last = type(e).__name__
                log.warning(
                    "ai.provider_error", feature=req.feature, model=req.model, error=last, attempt=attempt
                )
            else:
                if r.status_code == 429 or r.status_code >= 500:
                    last = f"http_{r.status_code}"
                    ra = r.headers.get("retry-after")
                    if ra and ra.replace(".", "", 1).isdigit():
                        delay = min(8.0, float(ra))
                    log.warning(
                        "ai.provider_retry", feature=req.feature, model=req.model, status=r.status_code
                    )
                elif r.status_code >= 400:
                    # Never echo the body (may quote the prompt); status + error type only.
                    etype = _error_type(r)
                    log.warning(
                        "ai.provider_rejected", feature=req.feature, status=r.status_code, error=etype
                    )
                    raise AIProviderError(f"provider rejected the request ({r.status_code} {etype})")
                else:
                    return self._parse(req, r)
            if attempt < self._retries:
                await self._sleep(delay)
        raise AIProviderError(f"provider unavailable ({last})")

    @staticmethod
    def _parse(req: AIRequest, r: httpx.Response) -> AICompletion:
        try:
            data = r.json()
        except ValueError as e:
            raise AIProviderError("provider returned a non-JSON body") from e
        stop = data.get("stop_reason")
        usage = data.get("usage") or {}
        tin = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0)
        tout = int(usage.get("output_tokens") or 0)
        text = "".join(b.get("text", "") for b in data.get("content") or [] if b.get("type") == "text")
        log.info(
            "ai.completion",
            feature=req.feature,
            model=data.get("model", req.model),
            stop_reason=stop,
            tokens_in=tin,
            tokens_out=tout,
        )
        if stop == "refusal":
            raise AIProviderError("the model declined this request")
        return AICompletion(
            text=text,
            tokens_in=tin,
            tokens_out=tout,
            model=str(data.get("model") or req.model),
            stop_reason=stop,
        )


def _error_type(r: httpx.Response) -> str:
    try:
        return str((r.json().get("error") or {}).get("type") or "error")
    except ValueError:
        return "error"


# --------------------------------------------------------------------------- fake


class FakeAIAdapter:
    """DEV/TEST ONLY. Deterministic, schema-valid output from ``req.meta``; no network.

    Refused in production (``register_fake_adapter`` + ``get_ai_adapter``)."""

    provider = "fake"
    is_fake = True

    def __init__(self) -> None:
        self.calls: list[AIRequest] = []

    async def complete(self, req: AIRequest) -> AICompletion:
        self.calls.append(req)
        payload = _fake_payload(req)
        text = json.dumps(payload)
        tin = sum(len(m.get("content", "")) for m in req.messages) // 4 + len(req.system) // 4
        return AICompletion(
            text=text,
            tokens_in=max(1, tin),
            tokens_out=max(1, len(text) // 4),
            model=req.model,
            stop_reason="end_turn",
        )


def _fake_payload(req: AIRequest) -> dict[str, Any]:
    m = req.meta
    if req.feature == "question_generation":
        qt = m.get("question_type", "mcq")
        topic = m.get("topic") or "the topic"
        diff = m.get("difficulty", "medium")
        items = []
        for i in range(int(m.get("count", 1))):
            d = diff if diff != "mixed" else ("easy", "medium", "hard")[i % 3]
            item: dict[str, Any] = {
                "question_type": qt,
                "stem_md": f"[Draft {i + 1}] Question about {topic}.",
                "difficulty": d,
                "tags": [str(topic).lower()[:40], d],
                "explanation_md": f"Explanation for draft {i + 1}.",
                "options": [],
                "test_cases": [],
            }
            if qt == "mcq":
                item["options"] = [{"text": f"Option {c}", "is_correct": c == "A"} for c in "ABCD"]
            elif qt in ("poll", "survey"):
                item["options"] = [{"text": f"Choice {c}", "is_correct": False} for c in "ABC"]
            elif qt == "code":
                item["starter_code"] = "def solve(data):\n    pass\n"
                item["test_cases"] = [
                    {"input": "1", "expected_output": "1", "hidden": False},
                    {"input": "2", "expected_output": "2", "hidden": True},
                ]
            items.append(item)
        return {"questions": items}
    if req.feature == "grading":
        mx = Decimal(str(m.get("max_marks", "10")))
        rubric = m.get("rubric") or []
        return {
            "marks": str((mx / 2).quantize(Decimal("0.01"))),
            "feedback_md": "Draft feedback: the response covers the main idea; add more detail.",
            "confidence": 0.5,
            "criteria": [
                {
                    "criterion": str(r.get("criterion") or r.get("title") or f"Criterion {i + 1}"),
                    "marks": "0",
                    "comment": "Review manually.",
                }
                for i, r in enumerate(rubric)
                if isinstance(r, dict)
            ],
        }
    if req.feature == "tutor":
        mode = m.get("mode", "guide")
        reply = (
            "**Where to look:** re-read the problem's constraints.\n\n"
            "**Next step:** try a small example by hand."
            if mode == "guide"
            else "**Concept:** this question is about breaking the problem into smaller steps."
        )
        return {"reply_md": reply, "contains_full_solution": False}
    if req.feature == "path_generation":
        n = int(m.get("approx_steps", 3))
        hours = int(m.get("target_hours", n))
        title = m.get("title") or "Learning path"
        kinds = ("article", "video", "assignment", "assessment")
        return {
            "title": title,
            "description": f"A draft path for {title}.",
            "steps": [
                {
                    "title": f"Step {i + 1}: {title}",
                    "step_type": "article" if m.get("style") == "textbook" else kinds[i % len(kinds)],
                    "est_hours": max(1, hours // max(1, n)),
                    "credits": 1,
                    "description_md": f"Draft content outline for step {i + 1}.",
                }
                for i in range(n)
            ],
        }
    return {}


# --------------------------------------------------------------------------- factory

_override: AIAdapter | None = None


def set_ai_adapter(adapter: AIAdapter | None) -> None:
    """Tests: pin an adapter instance (``None`` = select from settings)."""
    global _override
    _override = adapter


def get_ai_adapter(settings: Settings | None = None) -> AIAdapter:
    """Raises ``AIProviderError`` when AI is disabled / not configured and
    ``AIConfigurationError`` for the fake adapter in production."""
    s = settings or get_settings()
    if _override is not None:
        if _override.is_fake and s.is_production:
            raise AIConfigurationError("FakeAIAdapter is refused when APP_ENV is production")
        return _override
    cfg = load_config()
    if cfg.provider == "fake":
        if s.is_production:
            raise AIConfigurationError("FakeAIAdapter is refused when APP_ENV is production")
        return FakeAIAdapter()
    if cfg.provider == "anthropic":
        env = load_env_mapping()
        key = env.get("ANTHROPIC_API_KEY") or ""
        if _placeholder(key):
            raise AIProviderError("AI provider key is not configured")
        try:
            timeout = float(env.get("AI_TIMEOUT_S") or 60)
            retries = int(env.get("AI_MAX_RETRIES") or 2)
        except ValueError:
            timeout, retries = 60.0, 2
        return AnthropicAdapter(
            key,
            base_url=env.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com",
            timeout_s=timeout,
            max_retries=retries,
        )
    raise AIProviderError("AI is not enabled on this server")
