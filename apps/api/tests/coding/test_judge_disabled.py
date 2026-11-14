"""JUDGE_PROVIDER=disabled (owner 2026-11-14): no fake verdicts; run/submit refuse with 503."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.errors import ProblemError
from app.modules.coding import judge_gateway as jg
from app.modules.coding import service


def _settings(provider: str) -> Settings:
    return Settings(_env_file=None, APP_ENV="test", JUDGE_PROVIDER=provider)  # type: ignore[call-arg]


def test_disabled_judge_has_no_adapter() -> None:
    s = _settings("disabled")
    assert not jg.judge_enabled(s)
    assert jg.provider_name(s) == "disabled"
    with pytest.raises(jg.JudgeConfigurationError):
        jg.get_judge_adapter(s)


def test_fake_judge_still_enabled_for_tests() -> None:
    assert jg.judge_enabled(_settings("fake"))


async def test_create_submission_refuses_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "judge_enabled", lambda: False)
    with pytest.raises(ProblemError) as e:
        await service.create_submission(
            None,  # type: ignore[arg-type]
            user_id=None,  # type: ignore[arg-type]
            organization_id=None,
            problem=None,  # type: ignore[arg-type]
            language_key="python",
            mode="submit",
            source_code="print(1)",
            idempotency_key="k",
        )
    assert e.value.code == "service_unavailable"


async def test_process_pending_is_idle_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """The scheduler sweep must not fail every minute (and must count as idle) while disabled:
    no adapter is built and no submission is read."""
    from app.modules.coding import worker

    def boom(*a: object, **k: object) -> None:
        raise AssertionError("must not be called while the judge is disabled")

    jg.set_judge_adapter(None)
    monkeypatch.setattr(worker, "judge_enabled", lambda: False)
    monkeypatch.setattr(worker, "get_judge_adapter", boom)
    monkeypatch.setattr(worker, "pending_ids", boom)
    monkeypatch.setattr(worker, "get_sessionmaker", boom)
    assert await worker.process_pending() == {}
