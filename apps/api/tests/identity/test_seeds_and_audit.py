"""Dev seed guard/behaviour, audit coverage of security actions, SMS OTP send caps."""

from __future__ import annotations

from typing import Any

import pytest

from app.core import audit as core_audit
from app.seeds import dev_users
from tests.identity.factory import GOOD_PASSWORD, grant, make_user, staff_login


def test_dev_seed_refuses_production(monkeypatch) -> None:
    from app.core.config import reset_settings_cache

    monkeypatch.setenv("APP_ENV", "production")
    reset_settings_cache()
    try:
        with pytest.raises(dev_users.ProductionRefused):
            dev_users.guard()
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        reset_settings_cache()


async def test_dev_seed_creates_synthetic_users_that_can_log_in(browser, db) -> None:
    secrets = await dev_users.seed(db)
    again = await dev_users.seed(db)  # idempotent
    assert "admin@dev.techdrona.local" in secrets and again == {}
    r = await browser.login("student@dev.techdrona.local", dev_users.DEV_PASSWORD)
    assert r.status_code == 200 and r.json()["result"] == "authenticated"
    me = (await browser.get("/me")).json()
    assert "organizations" not in me  # single-company: organizations are never exposed


@pytest.fixture
def audited(monkeypatch) -> list[str]:
    actions: list[str] = []
    real = core_audit.audit

    async def spy(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> Any:
        actions.append(action)
        return await real(session, actor, action, *a, **kw)

    import app.modules.identity.router as ir
    import app.modules.rbac.service as rsvc
    import app.modules.sessions.login as sl
    import app.modules.sessions.resolver as sr
    import app.modules.sessions.router as srt

    for mod in (ir, rsvc, sl, sr, srt):
        monkeypatch.setattr(mod, "audit", spy)
    return actions


async def test_security_actions_are_audited(browser, db, mail, audited) -> None:
    u = await make_user(db, with_totp=True)
    await grant(db, u.id, "super_admin")
    target = await make_user(db)
    await staff_login(browser, u)
    await browser.post("/auth/step-up", {"method": "totp", "code": u.code()})
    await browser.post(
        "/rbac/grants",
        {
            "user_id": str(target.id),
            "role_key": "trainer",
            "scope_type": "course",
            "scope_id": "0193a0f1-2b3c-7d4e-8f50-61a2b3c4d5e6",
            "reason": "faculty",
        },
        headers={"Idempotency-Key": "audit-grant-01"},
    )
    await browser.post(
        "/auth/password/change",
        {"current_password": GOOD_PASSWORD, "new_password": "audited-lantern-harbour-11"},
    )
    await browser.post("/auth/logout")
    for a in (
        "auth.login.succeeded",
        "auth.step_up.succeeded",
        "rbac.grant.created",
        "auth.password.changed",
        "auth.logout",
    ):
        assert a in audited, (a, audited)


async def test_sms_otp_send_cap(browser, db, sms) -> None:
    u = await make_user(db, phone="+919876543221")
    await browser.login(u.email)
    other = browser.fork(ua="Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0")
    r = await other.login(u.email)
    assert {"channel": "sms", "destination_masked": "+91 98xxxxxx21"} in r.json()["channels"]
    for _ in range(3):
        assert (await other.post("/auth/device-verification/send", {"channel": "sms"})).status_code == 200
    r = await other.post("/auth/device-verification/send", {"channel": "sms"})
    assert (
        r.status_code == 429 and r.json()["code"] == "otp_send_limited" and int(r.headers["Retry-After"]) > 0
    )
    code = sms.sent[-1].text.split()[0]
    r = await other.post("/auth/device-verification/verify", {"code": code})
    assert r.status_code == 200 and r.json()["result"] == "authenticated"
    devices = (await other.get("/me/devices")).json()["data"]
    assert len(devices) == 2
