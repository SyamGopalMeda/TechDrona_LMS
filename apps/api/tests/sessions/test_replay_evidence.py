"""E2E-09: a UA/OS drift block records expected and observed UA family / OS in the audit row
and passes the observed values to the security sink (TO-08 evidence)."""

from __future__ import annotations

from typing import Any

from app.modules.sessions import resolver
from tests.identity.factory import FIREFOX_LINUX, make_user


async def test_e2e09_drift_block_records_expected_and_observed_ua(browser, db, monkeypatch) -> None:
    audits: list[dict[str, Any]] = []
    sink_calls: list[tuple[str, dict[str, Any] | None]] = []
    real_audit = resolver.audit

    async def spy_audit(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> Any:
        if action == "session.replay_blocked":
            audits.append(kw.get("after") or {})
        return await real_audit(session, actor, action, *a, **kw)

    class Sink:
        async def replay_blocked(
            self, session: Any, auth_session: Any, rule: str, observed: dict[str, Any] | None = None
        ) -> None:
            sink_calls.append((rule, observed))

        def __getattr__(self, name: str) -> Any:
            async def noop(*_a: Any, **_k: Any) -> Any:
                return False

            return noop

    monkeypatch.setattr(resolver, "audit", spy_audit)
    monkeypatch.setattr(resolver, "security_events", lambda: Sink())

    u = await make_user(db)
    await browser.login(u.email)
    browser.ua = FIREFOX_LINUX
    r = await browser.get("/me")
    assert r.status_code == 401 and r.json()["reason"] == "device_mismatch"

    (after,) = audits
    assert after["rule"] == "TO-08"
    assert after["expected_ua_family"] == "Chrome" and after["expected_os_family"] == "Windows"
    assert after["observed_ua_family"] == "Firefox" and after["observed_os_family"] == "Linux"
    assert sink_calls == [("TO-08", {"ua_family": "Firefox", "os_family": "Linux"})]
