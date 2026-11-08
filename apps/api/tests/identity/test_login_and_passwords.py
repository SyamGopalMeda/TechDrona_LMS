"""AUTH-06 login, back-off and hard stop, MFA (AUTH-11, ME-07..13), step-up (AUTH-19/20),
password reset (AUTH-16/17) and change (AUTH-18), logout (AUTH-15)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select, update

from app.core.db import system_context
from app.core.security import hash_token
from app.modules.identity import clock, totp
from app.modules.identity.contacts import identifier_digest
from app.modules.identity.models import PasswordResetToken, UserCredential
from app.modules.sessions.models import AuthSession, LoginAttempt
from tests.identity.factory import GOOD_PASSWORD, grant, make_user, staff_login, step_up
from tests.identity.fixtures import last_link_token


def _shift(monkeypatch, seconds: float) -> None:
    base = clock.utcnow()  # absolute offset from the real clock
    monkeypatch.setattr(clock, "now", lambda: base + timedelta(seconds=seconds))


async def test_login_success_records_hmac_attempt_and_sets_cookies(browser, db) -> None:
    u = await make_user(db)
    r = await browser.login(u.email)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (
        body["result"] == "authenticated"
        and body["session"]["tier"] == "student"
        and body["redirect"] == "/app"
    )
    cookies = r.headers.get_list("set-cookie")
    assert any(
        c.startswith("__Host-td_session=") and "HttpOnly" in c and "SameSite=Lax" in c and "Max-Age=" in c
        for c in cookies
    )
    assert any(c.startswith("__Host-td_device=") for c in cookies)
    me = await browser.get("/me")
    assert me.status_code == 200 and me.json()["user"]["id"] == str(u.id)
    await system_context(db, "t")
    rows = (await db.execute(select(LoginAttempt).where(LoginAttempt.user_id == u.id))).scalars().all()
    assert [a.outcome for a in rows] == ["success"]
    version, digest = identifier_digest("email", u.email)
    assert rows[0].identifier_hash == digest and rows[0].key_version == version
    assert u.email.encode() not in rows[0].identifier_hash


async def test_invalid_credentials_identical_for_unknown_and_known(browser, db, monkeypatch) -> None:
    u = await make_user(db)
    r1 = await browser.login(u.email, "wrong-password-value-xx")
    _shift(monkeypatch, 3600)
    r2 = await browser.login("nobody-here@example.com", "wrong-password-value-xx")
    assert r1.status_code == r2.status_code == 401
    b1, b2 = r1.json(), r2.json()
    b1.pop("request_id"), b2.pop("request_id")
    assert b1 == b2 and b1["code"] == "invalid_credentials"


async def test_per_account_backoff_doubles_and_applies_to_unknown(browser, db, monkeypatch) -> None:
    u = await make_user(db)
    assert (await browser.login(u.email, "bad-password-number-1")).status_code == 401
    r = await browser.login(u.email)  # correct password, but inside the 1 s back-off window
    assert r.status_code == 429 and r.json()["code"] == "throttled" and int(r.headers["Retry-After"]) >= 1
    _shift(monkeypatch, 2)
    assert (await browser.login(u.email, "bad-password-number-2")).status_code == 401
    _shift(monkeypatch, 2.5)  # 2 failures -> 2 s window still open
    r = await browser.login(u.email)
    assert r.status_code == 429
    _shift(monkeypatch, 6)
    r = await browser.login(u.email)
    assert r.status_code == 200, r.text
    # unknown identifiers get the same throttle shape
    monkeypatch.setattr(clock, "now", clock.utcnow)
    await browser.login("ghost@example.com", "whatever-password-123")
    r = await browser.login("ghost@example.com", "whatever-password-123")
    assert r.status_code == 429 and r.json()["code"] == "throttled"
    await system_context(db, "t")
    blocked = (
        (await db.execute(select(LoginAttempt).where(LoginAttempt.outcome == "throttled"))).scalars().all()
    )
    assert blocked and all(a.pre_auth_blocked for a in blocked)
    cred = await db.get(UserCredential, u.id)
    assert cred is not None and cred.consecutive_failures == 0  # reset by the successful login


async def test_hard_disable_after_limit_and_reset_clears(browser, db, mail, monkeypatch) -> None:
    u = await make_user(db)
    await system_context(db, "t")
    await db.execute(
        update(UserCredential).where(UserCredential.user_id == u.id).values(consecutive_failures=49)
    )
    await db.flush()
    r = await browser.login(u.email, "bad-password-again-49")
    assert r.status_code == 401
    assert any("paused" in m.subject for m in mail.sent)
    _shift(monkeypatch, 3600)
    r = await browser.login(u.email)  # correct password: still the identical 401
    assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"
    monkeypatch.setattr(clock, "now", clock.utcnow)
    assert (await browser.post("/auth/password/forgot", {"identifier": u.email})).status_code == 202
    token = last_link_token(mail)
    new_pw = "brand-new-lantern-harbour-77"
    assert (
        await browser.post("/auth/password/reset", {"token": token, "new_password": new_pw})
    ).status_code == 200
    _shift(monkeypatch, 7200)
    r = await browser.login(u.email, new_pw)
    assert r.status_code == 200, r.text


async def test_password_reset_single_use_expiry_and_revokes_sessions(browser, db, mail, monkeypatch) -> None:
    u = await make_user(db)
    assert (await browser.login(u.email)).status_code == 200
    old_session = browser.session
    r = await browser.post("/auth/password/forgot", {"identifier": u.email})
    assert r.status_code == 202
    r_unknown = await browser.post("/auth/password/forgot", {"identifier": "nobody@example.com"})
    assert r_unknown.status_code == 202 and r_unknown.json() == r.json()  # generic response
    token = last_link_token(mail)
    await system_context(db, "t")
    row = (
        await db.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == u.id))
    ).scalar_one()
    assert row.token_hash == hash_token(token) and timedelta(
        minutes=15
    ) <= row.expires_at - row.created_at <= timedelta(minutes=30)
    r = await browser.post("/auth/password/reset", {"token": token, "new_password": "short"})
    assert r.status_code == 400
    r = await browser.post("/auth/password/reset", {"token": token, "new_password": "fresh-garnet-window-58"})
    assert r.status_code == 200
    r = await browser.post("/auth/password/reset", {"token": token, "new_password": "fresh-garnet-window-59"})
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "invalid_or_expired"  # single use
    browser.session = old_session
    r = await browser.get("/me")
    assert r.status_code == 401 and r.json()["code"] == "session_revoked"
    # expired token
    await browser.post("/auth/password/forgot", {"identifier": u.email})
    token2 = last_link_token(mail)
    _shift(monkeypatch, 31 * 60)
    r = await browser.post(
        "/auth/password/reset", {"token": token2, "new_password": "fresh-garnet-window-60"}
    )
    assert r.status_code == 400


async def test_password_change_revokes_other_sessions_and_rotates_current(browser, db) -> None:
    u = await make_user(db)
    other = browser.fork(ua="Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0")
    assert (await browser.login(u.email)).status_code == 200
    # second device needs OTP; trust it directly through the API flow
    r = await other.login(u.email)
    assert r.json()["result"] == "device_verification_required"
    before = browser.session
    r = await browser.post(
        "/auth/password/change",
        {"current_password": "nope-nope-nope-nope", "new_password": "another-good-passphrase-1"},
    )
    assert r.status_code == 401
    r = await browser.post(
        "/auth/password/change",
        {"current_password": GOOD_PASSWORD, "new_password": "another-good-passphrase-1"},
    )
    assert r.status_code == 200 and r.json()["other_sessions_revoked"] == 1
    assert browser.session != before  # rotated
    assert (await browser.get("/me")).status_code == 200
    browser_old = browser.fork()
    browser_old.session, browser_old.device = before, browser.device
    assert (await browser_old.get("/me")).status_code == 401
    assert (await other.get("/me")).status_code == 401


async def test_totp_mfa_login_and_recovery_code(browser, db) -> None:
    u = await make_user(db, with_totp=True)
    r = await browser.login(u.email)
    assert r.status_code == 200 and r.json() == {
        "result": "mfa_required",
        "methods": ["totp", "recovery_code"],
    }
    pending = browser.session
    r = await browser.get("/me")
    assert r.status_code == 401 and r.json()["code"] == "login_incomplete" and r.json()["next_step"] == "mfa"
    r = await browser.post("/auth/mfa/verify", {"method": "totp", "code": "000000"})
    assert r.status_code == 400 and r.json()["code"] == "otp_invalid"
    code = u.code()
    r = await browser.post("/auth/mfa/verify", {"method": "totp", "code": code})
    assert r.status_code == 200 and r.json()["result"] == "authenticated"
    assert browser.session != pending  # rotated on MFA completion
    assert (await browser.get("/me")).json()["session"]["aal"] == 2
    # replay of the same TOTP code (same step) is refused
    r = await browser.post("/auth/step-up", {"method": "totp", "code": code})
    assert r.status_code == 400
    # recovery codes (needs fresh step-up: the MFA login set it)
    r = await browser.post("/me/mfa/recovery-codes")
    assert r.status_code == 201, r.text
    codes = r.json()["codes"]
    other = browser.fork()
    other.device = browser.device
    r = await other.login(u.email)
    assert r.json()["result"] == "mfa_required"
    r = await other.post("/auth/mfa/verify", {"method": "recovery_code", "code": codes[0]})
    assert r.status_code == 200, r.text
    third = browser.fork()
    third.device = browser.device
    await third.login(u.email)
    r = await third.post("/auth/mfa/verify", {"method": "recovery_code", "code": codes[0]})  # single use
    assert r.status_code == 400


async def test_staff_must_enrol_mfa_then_can_work(browser, db) -> None:
    u = await make_user(db)
    await grant(db, u.id, "evaluator")
    r = await browser.login(u.email)
    assert r.status_code == 200 and r.json()["session"]["tier"] == "staff"
    r = await browser.get("/me")
    assert r.status_code == 403 and r.json()["code"] == "mfa_enrolment_required"
    r = await browser.post("/me/mfa/totp", {"label": "phone"})  # first staff factor: no step-up
    assert r.status_code == 201, r.text
    secret = r.json()["secret"]
    assert r.json()["otpauth_uri"].startswith("otpauth://totp/")
    factor_id = r.json()["factor_id"]
    wrong = "000000" if totp.totp(secret) != "000000" else "111111"
    r = await browser.post(f"/me/mfa/totp/{factor_id}/confirm", {"code": wrong})
    assert r.status_code == 400 and r.json()["code"] == "otp_invalid"
    r = await browser.post(f"/me/mfa/totp/{factor_id}/confirm", {"code": totp.totp(secret)})
    assert r.status_code == 200, r.text
    assert (await browser.get("/me")).status_code == 200
    factors = (await browser.get("/me/mfa/factors")).json()["data"]
    assert factors[0]["confirmed"] and "secret" not in factors[0]
    # staff cannot remove the last factor
    r = await browser.delete(f"/me/mfa/factors/{factors[0]['factor_id']}")
    assert r.status_code == 409


async def test_step_up_student_otp_methods_and_totp_for_staff(browser, db, mail) -> None:
    """SEC-09: students step up with TOTP/SMS OTP/email OTP (api-spec §1.6, AUTH-19), not a
    password; password remains only when the account has no other usable method."""
    u = await make_user(db)
    await browser.login(u.email)
    opts = await browser.post("/auth/step-up/options", {"purpose": "contact_change"})
    assert opts.json()["allowed_methods"] == ["email_otp"]
    r = await browser.post("/auth/step-up", {"method": "password", "password": GOOD_PASSWORD})
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "method_not_allowed_for_tier"
    r = await browser.post("/auth/step-up/options", {"purpose": "contact_change", "send_otp_via": "email"})
    assert r.status_code == 200
    from tests.identity.fixtures import last_code

    r = await browser.post("/auth/step-up", {"method": "email_otp", "code": last_code(mail)})
    assert r.status_code == 200 and r.json()["valid_for_seconds"]["student_action"] == 900
    # Fallback: no email, no verified mobile, no TOTP -> password is the only method.
    from app.modules.identity.models import User

    await system_context(db, "test.factory")
    await db.execute(
        update(User)
        .where(User.id == u.id)
        .values(email=None, phone_e164=f"+9198{u.id.int % 10**8:08d}", phone_verified_at=None)
    )
    opts = await browser.post("/auth/step-up/options", {"purpose": "contact_change"})
    assert opts.json()["allowed_methods"] == ["password"]
    r = await browser.post("/auth/step-up", {"method": "password", "password": "wrong-wrong-wrong-1"})
    assert r.status_code == 400
    r = await browser.post("/auth/step-up", {"method": "password", "password": GOOD_PASSWORD})
    assert r.status_code == 200
    staff = await make_user(db, with_totp=True)
    await grant(db, staff.id, "super_admin")
    sb = browser.fork()
    await staff_login(sb, staff)
    r = await sb.post("/auth/step-up", {"method": "password", "password": GOOD_PASSWORD})
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "method_not_allowed_for_tier"
    await step_up(sb, staff)


async def test_step_up_freshness_enforced_on_sensitive_route(browser, db, monkeypatch) -> None:
    u = await make_user(db, with_totp=True)
    await browser.login(u.email)
    await browser.post("/auth/mfa/verify", {"method": "totp", "code": u.code()})
    _shift(monkeypatch, 16 * 60)
    browser.activity = "navigation"
    r = await browser.post("/me/mfa/recovery-codes")
    assert r.status_code == 401 and r.json()["code"] == "step_up_required"
    assert r.json()["step_up"]["max_age_seconds"] == 900
    r = await browser.post("/auth/step-up", {"method": "totp", "code": u.code()})
    assert r.status_code == 200
    assert (await browser.post("/me/mfa/recovery-codes")).status_code == 201


async def test_logout_then_reuse_rejected(browser, db) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    token = browser.session
    r = await browser.post("/auth/logout")
    assert r.status_code == 200 and "cookies" in r.headers["clear-site-data"]
    browser.session = token
    r = await browser.get("/me")
    assert r.status_code == 401 and r.json()["code"] == "session_revoked"
    await system_context(db, "t")
    s = (await db.execute(select(AuthSession).where(AuthSession.user_id == u.id))).scalar_one()
    assert s.status == "revoked" and s.end_reason == "user_logout" and s.ended_at is not None


async def test_unknown_token_unauthenticated(browser) -> None:
    browser.session = "x" * 43
    r = await browser.get("/me")
    assert r.status_code == 401 and r.json()["code"] == "unauthenticated"
