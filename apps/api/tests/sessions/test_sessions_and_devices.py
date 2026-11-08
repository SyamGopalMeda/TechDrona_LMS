"""Sessions & devices: new-device OTP, device cap + replacement quota, session-cap chooser,
same-device replacement, idle/absolute timeouts per tier, stolen-cookie replay, SES-01..12,
remember-device re-issue (AUTH-28)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.db import system_context
from app.core.security import get_keyring
from app.modules.identity import clock
from app.modules.sessions.models import AuthSession, Device, SessionNetworkObservation, UserDevice
from tests.identity.factory import ANDROID, FIREFOX_LINUX, Browser, grant, make_user, staff_login, step_up
from tests.identity.fixtures import last_code

EDGE = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Edg/130.0"
)
SAFARI_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Safari/605.1.15"


def _at(monkeypatch, seconds: float) -> None:
    base = clock.utcnow()
    monkeypatch.setattr(clock, "now", lambda: base + timedelta(seconds=seconds))


async def _verify_new_device(b: Browser, mail, email: str, **extra) -> object:
    r = await b.login(email)
    assert r.status_code == 200 and r.json()["result"] == "device_verification_required", r.text
    assert (
        r.json()["channels"][0]["channel"] == "email"
        and "****@" in r.json()["channels"][0]["destination_masked"]
    )
    r = await b.post("/auth/device-verification/send", {"channel": "email"})
    assert r.status_code == 200, r.text
    return await b.post("/auth/device-verification/verify", {"code": last_code(mail), **extra})


async def test_new_device_requires_otp_then_trusted(browser, db, mail) -> None:
    u = await make_user(db)
    assert (await browser.login(u.email)).json()["result"] == "authenticated"  # first device: trusted
    other = browser.fork(ua=FIREFOX_LINUX)
    r = await other.login(u.email)
    assert r.json()["result"] == "device_verification_required"
    assert (await other.get("/me")).json()["next_step"] == "device_verification"
    await other.post("/auth/device-verification/send", {"channel": "email"})
    code = last_code(mail)
    bad = "000000" if code != "000000" else "111111"
    r = await other.post("/auth/device-verification/verify", {"code": bad})
    assert r.status_code == 400 and r.json()["code"] == "otp_invalid" and r.json()["attempts_remaining"] == 4
    r = await other.post("/auth/device-verification/verify", {"code": code})
    assert r.status_code == 200 and r.json()["result"] == "authenticated", r.text
    await system_context(db, "t")
    uds = (await db.execute(select(UserDevice).where(UserDevice.user_id == u.id))).scalars().all()
    assert sorted(ud.trust_status for ud in uds) == ["trusted", "trusted"]
    assert {ud.verification_method for ud in uds} == {None, "email_otp"}
    # device rows store only HMACs of the cookie value, with the key version
    devs = (
        (await db.execute(select(Device).where(Device.id.in_([ud.device_id for ud in uds])))).scalars().all()
    )
    ring = get_keyring("device")
    assert any(ring.verify(other.device, d.device_key_hash, d.key_version) for d in devs)
    assert all(other.device.encode() not in d.device_key_hash for d in devs)


async def test_otp_attempts_exceeded(browser, db, mail) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    other = browser.fork(ua=FIREFOX_LINUX)
    await other.login(u.email)
    await other.post("/auth/device-verification/send", {"channel": "email"})
    code = last_code(mail)
    bad = "000000" if code != "000000" else "111111"
    for _ in range(4):
        await other.post("/auth/device-verification/verify", {"code": bad})
    r = await other.post("/auth/device-verification/verify", {"code": bad})
    assert r.status_code == 429 and r.json()["code"] == "otp_attempts_exceeded"
    r = await other.post("/auth/device-verification/verify", {"code": code})
    assert r.status_code == 429


async def test_session_cap_chooser_and_evicted_session_rejected(browser, db, mail) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    b2 = browser.fork(ua=FIREFOX_LINUX)
    assert (await _verify_new_device(b2, mail, u.email)).json()["result"] == "authenticated"
    b3 = browser.fork(ua=ANDROID)
    r = await _verify_new_device(b3, mail, u.email)
    assert r.status_code == 409 and r.json()["code"] == "session_cap_reached"
    assert r.json()["max_concurrent"] == 2 and len(r.json()["sessions"]) == 2
    assert all("has_active_attempt" in s for s in r.json()["sessions"])
    assert b3.session  # pending session cookie is set
    r = await b3.get("/me")
    assert r.status_code == 401 and r.json()["next_step"] == "session_choice"
    first_id = (await browser.get("/me")).json()["session"]["id"]
    r = await b3.post("/auth/session-choice", {"end_session_id": first_id})
    assert r.status_code == 200 and r.json()["result"] == "authenticated", r.text
    r = await browser.get("/me")
    assert (
        r.status_code == 401
        and r.json()["code"] == "session_revoked"
        and r.json()["reason"] == "session_cap_evicted"
    )
    inbox = (await b3.get("/me/notifications")).json()["data"]
    assert inbox[0]["template_key"] == "session.revoked"


async def test_session_choice_cancel_and_window_expiry(browser, db, mail, monkeypatch) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    b2 = browser.fork(ua=FIREFOX_LINUX)
    await _verify_new_device(b2, mail, u.email)
    b3 = browser.fork(ua=ANDROID)
    await _verify_new_device(b3, mail, u.email)
    _at(monkeypatch, 6 * 60)  # > 5 min choice window
    r = await b3.post("/auth/session-choice", {"cancel": True})
    assert r.status_code == 401 and r.json()["code"] == "session_expired"
    b4 = browser.fork(ua=ANDROID)
    b4.device = b3.device  # b3's device is trusted (OTP passed); its pending session expired
    monkeypatch.setattr(clock, "now", clock.utcnow)
    r = await b4.login(u.email)
    assert r.status_code == 409 and r.json()["code"] == "session_cap_reached"
    r = await b4.post("/auth/session-choice", {"cancel": True})
    assert r.status_code == 200 and r.json()["result"] == "cancelled"
    assert (await b4.get("/me")).status_code == 401


async def test_same_device_relogin_replaces_old_session(browser, db) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    old = browser.session
    await browser.login(u.email)
    assert browser.session != old
    stale = browser.fork()
    stale.session, stale.device = old, browser.device
    r = await stale.get("/me")
    assert r.status_code == 401 and r.json()["reason"] == "replaced_same_device"


async def test_device_cap_and_replacement_quota(browser, db, mail, monkeypatch) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    devices = []
    for ua in (FIREFOX_LINUX, ANDROID):
        b = browser.fork(ua=ua)
        r = await _verify_new_device(b, mail, u.email)
        assert r.status_code in (200, 409)
        await b.post("/auth/logout") if r.status_code == 200 else None
        devices.append(b)
    # 3 trusted devices now; a 4th is refused after OTP
    b4 = browser.fork(ua=SAFARI_MAC)
    r = await _verify_new_device(b4, mail, u.email)
    assert r.status_code == 409 and r.json()["code"] == "device_cap_reached", r.text
    assert r.json()["max_trusted"] == 3 and len(r.json()["devices"]) == 3
    victim = r.json()["devices"][0]["user_device_id"]
    # retry with a slot freed (no new code needed: this pending login already passed OTP)
    r = await b4.post("/auth/device-verification/verify", {"remove_user_device_id": victim})
    assert r.status_code in (200, 409), r.text
    assert r.status_code == 200 or r.json()["code"] == "session_cap_reached"
    # second replacement
    b5 = browser.fork(ua=EDGE)
    r = await _verify_new_device(b5, mail, u.email)
    assert r.json()["code"] == "device_cap_reached"
    r = await b5.post(
        "/auth/device-verification/verify",
        {"remove_user_device_id": r.json()["devices"][0]["user_device_id"]},
    )
    assert r.status_code in (200, 409)
    # third replacement within 30 days: quota (2) exhausted
    b6 = browser.fork(
        ua="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17.0 Mobile Safari/604.1"
    )
    r = await _verify_new_device(b6, mail, u.email)
    assert r.json()["code"] == "device_cap_reached" and r.json()["replacements_used"] == 2
    r = await b6.post(
        "/auth/device-verification/verify",
        {"remove_user_device_id": r.json()["devices"][0]["user_device_id"]},
    )
    assert r.status_code == 409 and r.json()["code"] == "device_replacement_quota_exhausted"
    assert r.json()["next_replacement_at"]


async def test_idle_timeout_and_engaged_activity(browser, db, monkeypatch) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    _at(monkeypatch, 50 * 60)
    assert (await browser.get("/me")).status_code == 200  # GET without navigation: neutral
    _at(monkeypatch, 61 * 60)
    r = await browser.get("/me")
    assert r.status_code == 401 and r.json() == {
        **r.json(),
        "code": "session_expired",
        "reason": "idle_timeout",
    }

    browser2 = browser.fork()
    browser2.device = browser.device
    monkeypatch.setattr(clock, "now", clock.utcnow)
    await browser2.login(u.email)
    _at(monkeypatch, 50 * 60)
    assert (
        await browser2.patch("/me/profile", {"branch": "CSE"})
    ).status_code == 200  # engaged write extends
    _at(monkeypatch, 100 * 60)
    assert (await browser2.get("/me")).status_code == 200
    _at(monkeypatch, 25 * 3600)
    r = await browser2.get("/me")
    assert r.status_code == 401 and r.json()["reason"] in ("absolute_timeout", "idle_timeout")


async def test_staff_and_privileged_timeouts(browser, db, monkeypatch) -> None:
    sup = await make_user(db, with_totp=True)
    await grant(db, sup.id, "super_admin")
    r = await staff_login(browser, sup)
    s = r.json()["session"]
    assert s["tier"] == "privileged"
    from datetime import datetime

    idle = datetime.fromisoformat(s["idle_expires_at"].replace("Z", "+00:00"))
    absolute = datetime.fromisoformat(s["absolute_expires_at"].replace("Z", "+00:00"))
    assert timedelta(minutes=14) < idle - clock.utcnow() <= timedelta(minutes=15)
    assert timedelta(hours=7, minutes=59) < absolute - clock.utcnow() <= timedelta(hours=8)
    _at(monkeypatch, 16 * 60)
    assert (await browser.get("/me")).json()["code"] == "session_expired"


async def test_stolen_cookie_replay_revokes_only_that_session(browser, db, mail) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    other = browser.fork(ua=FIREFOX_LINUX)
    await _verify_new_device(other, mail, u.email)
    attacker = Browser(browser.client, ua=browser.ua, ip="198.51.100.9")
    attacker.session = browser.session  # stolen cookie, different device cookie
    attacker.device = "A" * 22
    r = await attacker.get("/me")
    assert (
        r.status_code == 401
        and r.json()["code"] == "session_revoked"
        and r.json()["reason"] == "device_mismatch"
    )
    # the replayed session is dead for the victim's browser too (blocked); the other session survives
    r = await browser.get("/me")
    assert r.status_code == 401
    assert (await other.get("/me")).status_code == 200
    await system_context(db, "t")
    rows = (await db.execute(select(AuthSession).where(AuthSession.user_id == u.id))).scalars().all()
    assert sorted((s.status, s.end_reason) for s in rows) == [
        ("active", None),
        ("blocked", "device_mismatch"),
    ]


async def test_user_agent_drift_revokes(browser, db) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    browser.ua = FIREFOX_LINUX
    r = await browser.get("/me")
    assert r.status_code == 401 and r.json()["reason"] == "device_mismatch"


async def test_list_and_revoke_own_sessions_and_devices(browser, db, mail) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    other = browser.fork(ua=FIREFOX_LINUX, ip="198.51.100.20")
    await _verify_new_device(other, mail, u.email)
    r = await browser.get("/me/sessions")
    data = r.json()["data"]
    assert len(data) == 2 and sum(d["is_current"] for d in data) == 1
    assert {d["ip"] for d in data} == {"203.0.113.10", "198.51.100.20"}
    other_id = next(d["session_id"] for d in data if not d["is_current"])
    assert (await browser.delete(f"/me/sessions/{other_id}")).status_code == 200
    assert (await other.get("/me")).json()["reason"] == "user_revoked_other"
    devices = (await browser.get("/me/devices")).json()
    assert devices["limits"]["max_trusted"] == 3 and devices["limits"]["trusted_counted"] == 2
    cur = next(d for d in devices["data"] if d["is_current"])
    assert (
        await browser.patch(f"/me/devices/{cur['user_device_id']}", {"user_label": "My laptop"})
    ).status_code == 200
    gone = next(d for d in devices["data"] if not d["is_current"])
    r = await browser.delete(f"/me/devices/{gone['user_device_id']}")
    assert r.status_code == 200
    assert (await browser.get("/me/devices")).json()["limits"]["trusted_counted"] == 1
    policy = (await browser.get("/me/device-policy")).json()
    assert policy["sessions"]["max_concurrent"] == 2 and policy["devices"]["max_replacements_per_30d"] == 2
    hist = (await browser.get("/me/login-history")).json()
    assert hist["attempts"] and hist["ended_sessions"]
    # someone else's session id -> 404
    stranger = await make_user(db)
    sb = browser.fork(ua=SAFARI_MAC)
    await sb.login(stranger.email)
    sid = (await sb.get("/me")).json()["session"]["id"]
    assert (await browser.delete(f"/me/sessions/{sid}")).status_code == 404


async def test_revoke_others_keeps_current(browser, db, mail) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    other = browser.fork(ua=FIREFOX_LINUX)
    await _verify_new_device(other, mail, u.email)
    r = await browser.post("/me/sessions/revoke-others")
    assert r.json()["revoked"] == 1
    assert (await browser.get("/me")).status_code == 200 and (await other.get("/me")).status_code == 401


async def test_network_observation_on_cluster_change(browser, db) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    browser.ip = "49.36.112.18"
    assert (await browser.patch("/me/profile", {"branch": "ECE"})).status_code == 200
    await system_context(db, "t")
    obs = (
        (await db.execute(select(SessionNetworkObservation).where(SessionNetworkObservation.user_id == u.id)))
        .scalars()
        .all()
    )
    assert [o.net_cluster for o in obs] == ["AS0:49.36.0.0/16"]


async def test_remember_device_reissue_fixed_ceiling(browser, db, monkeypatch) -> None:
    u = await make_user(db)
    r = await browser.login(u.email, remember_device=True)
    assert browser.remember
    first_remember = browser.remember
    _at(monkeypatch, 25 * 3600)  # session absolutely expired
    assert (await browser.get("/me")).status_code == 401
    r = await browser.post("/auth/remember/refresh", {"remember_token": browser.remember})
    assert r.status_code == 200, r.text
    assert r.json()["session"]["created_via"] == "remember_device" and r.json()["session"]["aal"] == 1
    assert browser.remember != first_remember  # rotated
    assert (await browser.get("/me")).status_code == 200
    # the superseded token is useless; and after 30 days the ceiling holds
    r = await browser.post("/auth/remember/refresh", {"remember_token": first_remember})
    assert r.status_code == 401 and r.json()["code"] == "remember_invalid"
    _at(monkeypatch, 31 * 24 * 3600)
    r = await browser.post("/auth/remember/refresh", {"remember_token": browser.remember})
    assert r.status_code == 401
    # wrong device cookie
    monkeypatch.setattr(clock, "now", clock.utcnow)


async def test_support_admin_kill_requires_reason_and_step_up(browser, db, monkeypatch) -> None:
    """Support duties are Admin's since the single-company role consolidation (D2)."""
    victim = await make_user(db)
    vb = browser.fork(ua=ANDROID)
    await vb.login(victim.email)
    agent = await make_user(db, with_totp=True)
    await grant(db, agent.id, "super_admin")
    await staff_login(browser, agent)
    r = await browser.get(f"/users/{victim.id}/sessions")
    assert r.status_code == 403 and r.json()["code"] == "reason_code_required"
    r = await browser.get(f"/users/{victim.id}/sessions", params={"reason_code": "ticket"})
    assert r.status_code == 200 and r.json()["data"][0]["ip"].endswith("/24")  # M2: masked IP
    _at(monkeypatch, 11 * 60)
    browser.activity = "navigation"
    await browser.get("/me")
    r = await browser.post(
        f"/users/{victim.id}/sessions/revoke", {"all": True, "reason_code": "ticket", "reason": "lost phone"}
    )
    assert (
        r.status_code == 401
        and r.json()["code"] == "step_up_required"
        and r.json()["step_up"]["max_age_seconds"] == 300  # privileged tier
    )
    await step_up(browser, agent)
    r = await browser.post(
        f"/users/{victim.id}/sessions/revoke", {"all": True, "reason_code": "ticket", "reason": "lost phone"}
    )
    assert r.status_code == 200 and r.json()["revoked"] == 1
    assert (await vb.get("/me")).status_code == 401
    # a student cannot use staff endpoints
    sb = browser.fork(ua=ANDROID)
    sb.device = vb.device
    await sb.login(victim.email)
    r = await sb.get(f"/users/{agent.id}/sessions", params={"reason_code": "ticket"})
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"


async def test_admin_device_reset_beyond_quota_is_audited(browser, db, mail, monkeypatch) -> None:
    """The support quota (1 reset) still applies to holders of ``device.reset`` without
    ``device.reset.beyond_quota``; Admin holds both (D2), so a second reset succeeds and is
    audited as beyond quota."""
    from app.modules.sessions import router as srouter

    audited: list[dict] = []
    real_audit = srouter.audit

    async def spy(session, actor, action, *a, **kw):  # type: ignore[no-untyped-def]
        if action == "session.device.support_reset":
            audited.append(kw.get("after") or {})
        return await real_audit(session, actor, action, *a, **kw)

    monkeypatch.setattr(srouter, "audit", spy)
    victim = await make_user(db)
    vb = browser.fork(ua=ANDROID)
    await vb.login(victim.email)
    v2 = browser.fork(ua=FIREFOX_LINUX)
    await _verify_new_device(v2, mail, victim.email)
    agent = await make_user(db, with_totp=True)
    await grant(db, agent.id, "super_admin")
    await staff_login(browser, agent)
    devs = (await browser.get(f"/users/{victim.id}/devices", params={"reason_code": "ticket"})).json()["data"]
    body = {"reason_code": "ticket", "reason": "laptop replaced"}
    r = await browser.post(f"/users/{victim.id}/devices/{devs[0]['user_device_id']}/reset", body)
    assert r.status_code == 200, r.text
    await step_up(browser, agent)
    r = await browser.post(f"/users/{victim.id}/devices/{devs[1]['user_device_id']}/reset", body)
    assert r.status_code == 200, r.text
    assert [c.get("beyond_quota") for c in audited] == [False, True]
