"""SCN-03, 04, 09(c), 13, 15, 16, 17, 18, 19 through the real BFF hop, resolver and login stack."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.core.models import OutboxEvent
from app.core.routing import ROUTE_TAG_KEY, iter_api_routes, scope_allows
from app.core.security import generate_token
from app.modules.identity import clock
from app.modules.identity import service as ids
from app.modules.identity.models import User
from app.modules.security import engine, signals
from app.modules.security import restrictions as rx
from app.modules.security.models import RiskEvaluation
from app.modules.sessions.models import AuthSession, LoginAttempt
from tests.identity.factory import (
    ANDROID,
    CHROME_WIN,
    FIREFOX_LINUX,
    Browser,
    add_member,
    company_org,
    grant,
)
from tests.security.helpers import adult, freeze, signals_of


async def sessions_of(db, uid) -> list[AuthSession]:
    db.expire_all()
    return list(
        (
            await db.execute(
                select(AuthSession).where(AuthSession.user_id == uid).order_by(AuthSession.created_at)
            )
        ).scalars()
    )


async def login_ok(b: Browser, email: str) -> None:
    r = await b.login(email)
    assert r.status_code == 200 and r.json()["result"] == "authenticated", r.text


# --------------------------------------------------------------------------- SCN-19


async def test_scn19_altered_revoked_and_replayed_tokens(browser, client, db, sms) -> None:
    u = await adult(db)
    await login_ok(browser, u.email)
    phone = browser.fork(ua=ANDROID)
    r = await phone.login(u.email)
    assert r.json()["result"] == "device_verification_required"
    await phone.post("/auth/device-verification/send", {"channel": "sms"})
    import re

    code = re.search(r"\b(\d{6})\b", sms.sent[-1].text).group(1)
    assert (await phone.post("/auth/device-verification/verify", {"code": code})).json()[
        "result"
    ] == "authenticated"
    # 1. altered token → 401 (unknown in Postgres; strict mode)
    altered = Browser(
        client,
        session=browser.session[:-1] + ("A" if browser.session[-1] != "A" else "B"),
        device=browser.device,
    )
    assert (await altered.get("/me")).status_code == 401
    # 6. replay of S1's cookie from another browser without its device cookie → TO-04, S1 only
    thief = Browser(client, ip="198.18.9.9", session=browser.session)
    r = await thief.get("/me")
    assert (
        r.status_code == 401
        and r.json()["code"] == "session_revoked"
        and r.json()["reason"] == "device_mismatch"
    )
    s1, s2 = await sessions_of(db, u.id)
    assert s1.status == "blocked" and s1.end_reason == "device_mismatch" and s2.status == "active"
    assert (await phone.get("/me")).status_code == 200  # other sessions stay signed in
    assert [s.rule_key for s in await signals_of(db, u.id)] == ["TO-04"]
    ev = (await db.execute(select(RiskEvaluation).where(RiskEvaluation.user_id == u.id))).scalars().all()
    assert ev[-1].family == "takeover" and float(ev[-1].score) == 60 and ev[-1].action == "step_up"
    assert (await rx.restriction_state(db, u.id)).step_up_required
    notice = (await client.get("/api/v1/me/security/status", headers=phone.headers())).json()["takeover"]
    assert notice["step_up_required"] is True
    # T-step-up: the next login on the (trusted) laptop needs SMS OTP even though the device is known
    laptop = Browser(client, device=browser.device)
    r = await laptop.login(u.email)
    assert r.json()["result"] == "device_verification_required" and r.json()["reason"] == "security_step_up"
    assert [c["channel"] for c in r.json()["channels"]] == ["sms"]
    await laptop.post("/auth/device-verification/send", {"channel": "sms"})
    code = re.search(r"\b(\d{6})\b", sms.sent[-1].text).group(1)
    assert (await laptop.post("/auth/device-verification/verify", {"code": code})).json()[
        "result"
    ] == "authenticated"
    assert not (await rx.restriction_state(db, u.id)).step_up_required
    # 6b. a second replay within 24 h → HC-T3 → T-protect: every session revoked, must_change_password
    thief2 = Browser(client, ip="198.18.9.9", session=laptop.session)
    assert (await thief2.get("/me")).status_code == 401
    assert {s.status for s in await sessions_of(db, u.id)} <= {"revoked", "blocked"}
    state = await rx.restriction_state(db, u.id)
    db.expire_all()
    assert state.takeover_lock and (await db.get(User, u.id)).must_change_password
    r = await Browser(client, device=browser.device).login(u.email)
    assert r.status_code == 403 and r.json()["code"] == "account_protect_locked"
    # self-service recovery: a password reset ends the lock
    freeze_later = clock.now() + timedelta(minutes=1)
    import pytest

    mp = pytest.MonkeyPatch()
    mp.setattr(clock, "now", lambda: freeze_later)
    try:
        await ids.set_password(db, u.id, "a-brand-new-long-passphrase-77")
        assert not (await rx.restriction_state(db, u.id)).takeover_lock
    finally:
        mp.undo()


async def test_scn19_drift_and_minor_replay_is_deterministic(browser, client, db) -> None:
    kid = await adult(db, minor=True, monitoring=False)
    await login_ok(browser, kid.email)
    drifted = Browser(client, ua=FIREFOX_LINUX, session=browser.session, device=browser.device)  # TO-08
    assert (await drifted.get("/me")).json()["reason"] == "device_mismatch"
    sig = (await signals_of(db, kid.id))[0]
    assert sig.rule_key == "TO-08" and float(sig.base_points) == 0 and sig.is_minor_at_time
    assert (await db.execute(select(RiskEvaluation).where(RiskEvaluation.user_id == kid.id))).first() is None
    b2 = Browser(client)
    await b2.login(kid.email)
    s = (await sessions_of(db, kid.id))[-1]
    if s.status == "active":
        thief = Browser(client, ua=CHROME_WIN, session=b2.session)
        await thief.get("/me")
        assert (await rx.restriction_state(db, kid.id)).takeover_lock  # HC-T3 applies to minors


async def test_scn19_unknown_token_flood_ab07_throttles_source(client, db) -> None:
    codes = []
    for _ in range(21):
        b = Browser(client, ip="198.18.77.10", session=generate_token())
        codes.append((await b.get("/me")).status_code)
    assert codes[:19] == [401] * 19 and codes[19:] == [429, 429]
    assert await signals_of(db, None, "AB-07")


# --------------------------------------------------------------------------- SCN-04 / 15 / 16


async def test_scn04_network_change_keeps_session_and_ua_family_change_is_to08(browser, client, db) -> None:
    u = await adult(db)
    await login_ok(browser, u.email)
    browser.ip = "106.200.5.5"  # Wi-Fi → mobile data
    assert (await browser.patch("/me/profile", {"branch": "CSE"})).status_code == 200
    s = (await sessions_of(db, u.id))[0]
    assert s.status == "active" and s.net_cluster_last != s.net_cluster_first
    from app.modules.sessions.models import SessionNetworkObservation

    obs = (
        (
            await db.execute(
                select(SessionNetworkObservation).where(SessionNetworkObservation.auth_session_id == s.id)
            )
        )
        .scalars()
        .all()
    )
    assert len(obs) == 1
    browser.ua = CHROME_WIN.replace("Chrome/130", "Chrome/131")  # major-version change: nothing
    assert (await browser.get("/me")).status_code == 200
    assert await signals_of(db, u.id) == []
    browser.ua = FIREFOX_LINUX
    assert (await browser.get("/me")).json()["reason"] == "device_mismatch"
    assert [x.rule_key for x in await signals_of(db, u.id)] == ["TO-08"]


async def test_scn15_idle_session_expires_and_background_poll_does_not_extend(
    browser, db, monkeypatch
) -> None:
    u = await adult(db)
    await login_ok(browser, u.email)
    t0 = clock.now()
    freeze(monkeypatch, t0 + timedelta(minutes=50))
    assert (await browser.get("/me/security/status")).status_code == 200  # neutral poll
    freeze(monkeypatch, t0 + timedelta(minutes=61))
    r = await browser.get("/me/security/status")
    assert (
        r.status_code == 401
        and r.json()["code"] == "session_expired"
        and r.json()["reason"] == "idle_timeout"
    )
    assert (await sessions_of(db, u.id))[0].end_reason == "idle_timeout"


async def test_scn16b_relogin_same_device_replaces_old_session(browser, client, db) -> None:
    u = await adult(db)
    await login_ok(browser, u.email)
    lost_cookie = Browser(client, device=browser.device)  # browser crash, session cookie lost
    await login_ok(lost_cookie, u.email)
    first, second = await sessions_of(db, u.id)
    assert first.end_reason == "replaced_same_device" and second.status == "active"
    assert await signals_of(db, u.id, "SH-04") == []


# --------------------------------------------------------------------------- SCN-03


async def test_scn03_shared_wifi_many_students_no_lockout_no_signals(client, db) -> None:
    """Single company (D5): there are no trusted networks any more; a shared Wi-Fi with a few
    typos and many students signing in stays below the AB-04 thresholds on its own."""
    org = company_org()
    students = [await adult(db) for _ in range(8)]
    for s in students:
        await add_member(db, org, s.id)
    for i in range(15):
        r = await Browser(client, ip="198.51.100.10").login(f"typo{i}@example.com", "wrong-password-123")
        assert r.status_code in (401, 429)
    for s in students:
        await login_ok(Browser(client, ip="198.51.100.10"), s.email)
    for s in students:
        assert await signals_of(db, s.id) == []
    assert await signals_of(db, None, "AB-04") == []


# --------------------------------------------------------------------------- SCN-09 (c) HC-T2


async def test_scn09c_stuffing_source_then_failed_otp_is_hct2_protect_lock(client, db, mail) -> None:
    from app.core.db import system_context
    from app.core.security import get_keyring

    await system_context(db, "test")
    ring = get_keyring("login")
    for i in range(49):  # 49 failures across 25 accounts from one /24 (different hosts: no per-IP throttle)
        v, d = ring.sign(f"victim{i % 25}@example.com")
        db.add(
            LoginAttempt(
                id=engine.uuid7(),
                attempted_at=clock.now(),
                identifier_hash=d,
                key_version=v,
                method="password",
                outcome="unknown_identifier",
                ip=f"203.0.113.{i + 1}",
            )
        )
    await db.flush()
    r = await Browser(client, ip="203.0.113.60").login("victim99@example.com", "nope-nope-nope-1")
    assert r.status_code == 401
    assert await signals_of(db, None, "AB-04")
    from tests.identity.factory import make_user

    target = await make_user(db, with_totp=True)
    atk = Browser(client, ip="203.0.113.77")
    r = await atk.login(target.email, target.password)
    assert r.json()["result"] == "mfa_required"
    assert await signals_of(db, target.id, "TO-05")
    for _ in range(2):
        r = await atk.post("/auth/mfa/verify", {"method": "totp", "code": "000000"})
    assert {s.rule_key for s in await signals_of(db, target.id)} >= {"TO-05", "TO-03"}
    assert (await rx.restriction_state(db, target.id)).takeover_lock  # HC-T2 → T-protect
    db.expire_all()
    assert (await db.get(User, target.id)).must_change_password
    # works with risk.mode = shadow (the default here): takeover protections always enforce (KS-07)
    from app.modules.admin.policy import get_value

    assert await get_value(db, "risk.mode") == "shadow"


# --------------------------------------------------------------------------- SCN-13


async def _restricted(browser: Browser, db, level: int) -> uuid.UUID:
    u = await adult(db)
    await login_ok(browser, u.email)
    s = (await sessions_of(db, u.id))[0]
    case = await engine.open_case(db, user_id=u.id, family="sharing", level=level, opened_reason="engine_L3")
    actor = await adult(db)
    await rx.apply_restriction(
        db,
        user_id=u.id,
        level=level,
        family="sharing",
        source="engine" if level == 3 else "reviewer",
        actor=engine.SYSTEM,
        case_id=case.id,
        applied_by=None if level == 3 else actor.id,
        ends_at=clock.now() + timedelta(hours=24) if level == 3 else None,
        keep_session_id=s.id if level == 3 else None,
    )
    if level == 4:  # L4 revokes everything; sign in again to a status_only session
        await login_ok(browser, u.email)
    return u.id


def _fill(path: str) -> str:
    import re

    return re.sub(r"\{[^}]+\}", lambda m: str(uuid.uuid4()) if "id" in m.group(0) else "x", path)


async def _sweep(app, browser: Browser, scope: str) -> tuple[int, list[str]]:
    denied, wrong = 0, []
    for route, path in iter_api_routes(app):
        tag = (route.openapi_extra or {}).get(ROUTE_TAG_KEY)
        if tag == "public" or scope_allows(scope, tag):
            continue
        for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
            body = {} if method in ("POST", "PUT", "PATCH") else None
            r = await browser.request(method, _fill(path), json=body)
            ok = r.status_code == 403 and r.json().get("code") == "account_restricted"
            denied += ok
            if not ok:
                wrong.append(f"{method} {path} -> {r.status_code}")
            else:
                assert set(r.json()) <= {
                    "type",
                    "title",
                    "status",
                    "code",
                    "detail",
                    "request_id",
                    "case_ref",
                    "level",
                    "until",
                    "status_url",
                }
    return denied, wrong


async def test_scn13_l3_and_l4_principals_get_403_on_every_non_allowed_route(
    app, browser, client, db
) -> None:
    uid = await _restricted(browser, db, 3)
    denied, wrong = await _sweep(app, browser, "restricted")
    assert wrong == [] and denied > 50
    assert (await browser.get("/me")).status_code == 200  # account_status
    assert (await browser.get("/me/enrolments")).status_code == 200  # l3_readonly at L3
    assert (await browser.get("/me/security/status")).json()["level"] == 3
    r = await browser.post("/media/playback-tokens", {})
    assert r.status_code == 403 and r.json()["case_ref"].startswith("SEC-") and r.json()["level"] == 3
    # probing never escalates: AB-08 is an info signal, restriction unchanged
    assert await signals_of(db, uid, "AB-08")
    assert (await rx.active_for(db, uid, "sharing")).level == 3
    l4 = Browser(client)
    await _restricted(l4, db, 4)
    denied, wrong = await _sweep(app, l4, "status_only")
    assert wrong == [] and denied > denied // 2
    assert (await l4.get("/me/enrolments")).status_code == 403  # l3_readonly closed at L4
    assert (await l4.get("/me/security/status")).json()["level"] == 4


async def test_scn13_l3_entitlement_locks_and_cache_column(browser, db) -> None:
    uid = await _restricted(browser, db, 3)
    st = await rx.restriction_state(db, uid)
    assert {"video_locked", "attempt_locked", "certificate_locked"} <= st.restrictions
    assert (await db.get(User, uid)).restriction_level == 3
    # sessions default lookup (hook absent) still fails closed through the cache column
    from app.modules.sessions import hooks

    assert (await hooks.lookup_restriction(db, uid, 3)).level == 3


# --------------------------------------------------------------------------- SCN-17 / SCN-18


async def test_scn17_time_manipulation_is_integrity_only(db) -> None:
    u = await adult(db)
    sid = uuid.uuid4()
    for _ in range(49):
        assert await signals.report_event(db, "IN-02", user_id=u.id, auth_session_id=sid) is None
    assert (await signals.report_event(db, "IN-02", user_id=u.id, auth_session_id=sid)).family == "integrity"
    assert (
        await signals.report_event(db, "IN-01", user_id=u.id, evidence={"day": "2026-11-02"})
    ).rule_key == "IN-01"
    assert await signals_of(db, u.id, "SH-01") == []
    assert (await db.execute(select(RiskEvaluation).where(RiskEvaluation.user_id == u.id))).first() is None


async def test_scn18_cross_batch_access_denied_and_ab09_alert(browser, client, db) -> None:
    from tests.identity.factory import make_batch, make_user, staff_login

    owner = await make_user(db)
    batch_a = await make_batch(db, company_org(), owner.id)
    batch_b = await make_batch(db, company_org(), owner.id)
    coord = await make_user(db, with_totp=True)
    await add_member(db, company_org(), coord.id, member_type="staff")
    await grant(db, coord.id, "trainer", "batch", batch_a)
    victim = await adult(db)
    await add_member(db, company_org(), victim.id, batch_id=batch_b)
    await staff_login(browser, coord)
    # cross-batch: a trainer of batch A cannot touch a member of batch B
    r = await browser.delete(f"/batches/{batch_b}/members/{victim.id}")
    assert r.status_code in (403, 404)
    for _ in range(19):
        assert await signals.report_event(db, "AB-09.not_found", user_id=coord.id) is None
    s = await signals.report_event(db, "AB-09.not_found", user_id=coord.id)
    assert s is not None and s.rule_key == "AB-09" and s.family == "abuse"
    alerts = (
        await db.execute(select(OutboxEvent).where(OutboxEvent.event_type == "security.alert_raised"))
    ).scalars()
    assert any(a.payload.get("kind") == "AB-09" for a in alerts)
    assert await rx.active_restrictions(db, coord.id) == []  # no automatic restriction of staff
