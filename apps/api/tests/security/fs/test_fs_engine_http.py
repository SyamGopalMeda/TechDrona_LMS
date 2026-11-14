"""Security pass 2 over HTTP on Firestore with no Postgres: the login hot path (sessions ->
``SecurityEventSink`` -> signals -> takeover evaluation) through the real FastAPI app, and the
evaluations review route."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.core.db import NO_POSTGRES
from app.modules.identity import clock
from app.modules.security import engine
from tests.firestore.conftest import fs_client  # noqa: F401
from tests.identity.fs.conftest import fs, fs_user, http  # noqa: F401


@pytest.fixture
def stores(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Requested before ``http``: security/admin/notifications on Firestore, account protection
    on, login back-off off (so ten failures reach the TO-01 threshold)."""
    from app.modules.identity import policy

    for m in ("security", "admin", "notifications"):
        monkeypatch.setenv(f"TD_STORE_{m.upper()}", "firestore")
    monkeypatch.setenv("TD_ACCOUNT_PROTECTION_OFF", "false")
    monkeypatch.setenv("TD_SIMPLE_AUTH", "false")
    monkeypatch.setenv("TD_DEVICE_CODE_OFF", "true")
    monkeypatch.setitem(policy.DEFAULTS, "login.backoff_base_seconds", 0)
    monkeypatch.setitem(policy.DEFAULTS, "login.ip_failed_limit_per_10min", 1000)
    yield


@pytest.fixture
def sink(http: Any, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    from app.modules.security.signals import SecurityEventSink
    from app.modules.sessions import hooks

    monkeypatch.setattr(hooks, "_security_events", SecurityEventSink())
    return http


async def test_failed_logins_raise_to01_and_takeover_evaluation(stores: None, sink: Any) -> None:
    u = await fs_user("victim@example.com")
    for i in range(10):
        r = await sink.fork().login(u.email, f"wrong-password-{i:03d}")
        assert r.status_code in (401, 429), r.text
    since = clock.now() - timedelta(hours=1)
    sigs = await engine.user_signals(NO_POSTGRES, u.id, "takeover", since)
    assert [s.rule_key for s in sigs] == ["TO-01"]
    assert sigs[0].evidence == {"failures": 10} and sigs[0].base_points == Decimal("20.00")
    evs = await engine.evaluations_for(NO_POSTGRES, u.id, "takeover", None, None)
    assert [(e.trigger, e.score, e.action, e.mode) for e in evs] == [
        ("login", Decimal("20.00"), "none", "enforce")
    ]
    assert evs[0].explanation_keys == ["to01.failed_burst"]
    # an 11th failure inside the 15-minute window adds no second TO-01
    await sink.fork().login(u.email, "wrong-password-xyz")
    assert len(await engine.user_signals(NO_POSTGRES, u.id, "takeover", since)) == 1
    # the account still signs in (score below step-up)
    r = await sink.fork().login(u.email, u.password)
    assert r.status_code == 200, r.text
