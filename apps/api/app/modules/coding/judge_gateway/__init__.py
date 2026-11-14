"""judge-gateway (ADR-0005): the only code that talks to a judge. Runs in ``worker-judge``.

``get_judge_adapter()`` selects by ``JUDGE_PROVIDER``:

* ``fake`` → ``FakeJudgeAdapter`` (never executes code; refused when APP_ENV is production);
* ``judge0_cloud`` / ``judge0`` → ``Judge0Adapter`` (https, ``JUDGE0_BASE_URL``/``JUDGE0_URL``,
  ``JUDGE0_API_KEY``, ``JUDGE0_AUTH_HEADER``);
* ``judge0_selfhosted`` → ``Judge0Adapter`` against the isolated phase-2 endpoint;
* ``disabled`` → no judge: run/submit answer 503 "code checking is not available yet" and nothing
  is queued (owner 2026-11-14: no fake verdicts until a real judge is connected).
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.security import load_env_mapping
from app.modules.coding.judge_gateway.base import (
    JudgeAdapter,
    JudgeJob,
    JudgeLimits,
    JudgeRunResult,
    JudgeTimeout,
    JudgeUnavailable,
    run_jobs,
)
from app.modules.coding.judge_gateway.fake import FakeJudgeAdapter
from app.modules.coding.judge_gateway.judge0 import Judge0Adapter


class JudgeConfigurationError(RuntimeError):
    pass


_override: JudgeAdapter | None = None


def set_judge_adapter(adapter: JudgeAdapter | None) -> None:
    """Tests / worker bootstrap: pin an adapter instance (``None`` = select from settings)."""
    global _override
    _override = adapter


def judge_enabled(settings: Settings | None = None) -> bool:
    """False when ``JUDGE_PROVIDER=disabled`` (and no test adapter is pinned)."""
    if _override is not None:
        return True
    return (settings or get_settings()).JUDGE_PROVIDER.lower() != "disabled"


def provider_name(settings: Settings | None = None) -> str:
    """Value for ``code_submissions.judge_provider`` (API side; no adapter construction)."""
    if _override is not None:
        return _override.provider
    p = (settings or get_settings()).JUDGE_PROVIDER.lower()
    if p in ("fake", "disabled"):
        return p
    if p == "judge0_selfhosted":
        return "judge0_selfhosted"
    return "judge0_cloud"


def get_judge_adapter(settings: Settings | None = None) -> JudgeAdapter:
    if _override is not None:
        if _override.is_fake and (settings or get_settings()).is_production:
            raise JudgeConfigurationError("FakeJudgeAdapter is refused when APP_ENV is production")
        return _override
    s = settings or get_settings()
    p = s.JUDGE_PROVIDER.lower()
    if p == "disabled":
        raise JudgeConfigurationError("The judge is disabled (JUDGE_PROVIDER=disabled)")
    if p == "fake":
        if s.is_production:
            raise JudgeConfigurationError("FakeJudgeAdapter is refused when APP_ENV is production")
        return FakeJudgeAdapter()
    env = load_env_mapping()
    base = env.get("JUDGE0_BASE_URL") or env.get("JUDGE0_URL") or ""
    key = env.get("JUDGE0_API_KEY") or ""
    if not base or not key or "REPLACE" in key or base.endswith(".invalid"):
        raise JudgeConfigurationError("JUDGE0_BASE_URL/JUDGE0_API_KEY not configured")
    provider = "judge0_selfhosted" if p == "judge0_selfhosted" else "judge0_cloud"
    return Judge0Adapter(
        base, key, auth_header=env.get("JUDGE0_AUTH_HEADER") or "X-Auth-Token", provider=provider
    )


__all__ = [
    "FakeJudgeAdapter",
    "Judge0Adapter",
    "JudgeAdapter",
    "JudgeConfigurationError",
    "JudgeJob",
    "JudgeLimits",
    "JudgeRunResult",
    "JudgeTimeout",
    "JudgeUnavailable",
    "get_judge_adapter",
    "judge_enabled",
    "provider_name",
    "run_jobs",
    "set_judge_adapter",
]
