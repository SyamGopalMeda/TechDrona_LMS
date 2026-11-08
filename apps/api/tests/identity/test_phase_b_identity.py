"""Audit Phase B regressions (identity/sessions): SEC-02/03 rate limits, SEC-05 signup
enumeration, SEC-08 token rotation, E2E-12 TOTP replay + protect-lock password reuse,
INV-16 mobile OTP send/verify (AUTH-04/05)."""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

from sqlalchemy import func, select

from app.core.db import system_context
from app.modules.identity import totp
from app.modules.sessions.models import LoginAttempt
from tests.identity.factory import FIREFOX_LINUX, GOOD_PASSWORD, REQUIRED_CONSENTS, make_user, staff_login
from tests.identity.fixtures import last_code, last_link_token


def _signup(email: str | None = None, **kw: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "full_name": "Ananya Reddy",
        "date_of_birth": "2000-04-12",
        "password": GOOD_PASSWORD,
        "consents": REQUIRED_CONSENTS,
        **kw,
    }
    if email:
        body["email"] = email
    return body


# --------------------------------------------------------------------------- SEC-02


async def test_sec02_signup_limited_per_ip_device_and_per_contact(browser, db, mail) -> None:
    statuses = []
    for i in range(7):  # a scripted client dropping cookies: same IP, no device cookie
        bot = browser.fork(ip="203.0.113.99")
        r = await bot.post("/auth/signup", _signup(f"ipcap{i}@example.com"))
        statuses.append(r.status_code)
    assert statuses == [201] * 5 + [429, 429], statuses
    assert int(r.headers["Retry-After"]) > 0 and r.json()["code"] == "rate_limited"

    existing = await make_user(db)
    sent_before = len(mail.sent)
    codes = []
    for i in range(5):
        other = browser.fork(ip=f"198.51.100.{i + 1}")  # distinct IPs: only the contact rule applies
        codes.append((await other.post("/auth/signup", _signup(existing.email))).status_code)
    assert codes == [201, 201, 201, 429, 429], codes
    # the "already registered" mail is sent at most once per contact per day (no flood)
    owner_mails = [m for m in mail.sent[sent_before:] if m.to == existing.email]
    assert len(owner_mails) == 1 and owner_mails[0].template_key == "auth.already_registered"


async def test_sec02_forgot_reset_and_verify_email_limited_per_ip(browser, db, mail) -> None:
    u = await make_user(db)
    forgot = [
        (await browser.post("/auth/password/forgot", {"identifier": f"n{i}@example.com"})).status_code
        for i in range(6)
    ]
    assert forgot == [202] * 5 + [429]
    ident = browser.fork(ip="198.51.100.20")
    per_ident = [
        (
            await ident.fork(ip=f"198.51.100.{30 + i}").post("/auth/password/forgot", {"identifier": u.email})
        ).status_code
        for i in range(4)
    ]
    assert per_ident == [202, 202, 202, 429]
    reset = [
        (await browser.post("/auth/password/reset", {"token": "x" * 32, "new_password": "p"})).status_code
        for _ in range(11)
    ]
    assert reset == [400] * 10 + [429]
    verify = [(await browser.post("/auth/verify/email", {"token": "y" * 32})).status_code for _ in range(21)]
    assert verify == [400] * 20 + [429]


async def test_sec02_limits_skipped_when_client_ip_unknown(browser, db, mail) -> None:
    """Without an attributable IP (no trusted proxy hop) per-IP rules do not pool all users."""
    anon = browser.fork(ip="")
    statuses = [
        (await anon.post("/auth/password/forgot", {"identifier": f"z{i}@example.com"})).status_code
        for i in range(7)
    ]
    assert statuses == [202] * 7


# --------------------------------------------------------------------------- SEC-03


async def test_sec03_password_change_limited_per_user(browser, db) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    wrong = {"current_password": "not-the-password-1", "new_password": "a-brand-new-password-77"}
    statuses = [(await browser.post("/auth/password/change", wrong)).status_code for _ in range(6)]
    assert statuses == [401] * 5 + [429]
    ok = {"current_password": GOOD_PASSWORD, "new_password": "a-brand-new-password-77"}
    assert (await browser.post("/auth/password/change", ok)).status_code == 429  # still in the window


# --------------------------------------------------------------------------- SEC-05


async def test_sec05_duplicate_signup_matches_timing_and_cookies(browser, db, mail, monkeypatch) -> None:
    from app.modules.identity import router as idr

    monkeypatch.setattr(idr, "SIGNUP_MIN_SECONDS", 1.0)
    existing = await make_user(db)
    # Warm-up (not measured): the first signup of a process pays one-off costs (thread pool,
    # Argon2 and mail adapter start-up) that would otherwise be charged to whichever branch
    # happens to run first.
    warm = await make_user(db)
    await browser.fork(ip="198.51.100.76").post("/auth/signup", _signup(warm.email))
    t0 = time.perf_counter()
    r = await browser.fork(ip="198.51.100.77").post("/auth/signup", _signup(existing.email))
    dup_s = time.perf_counter() - t0
    assert r.status_code == 201 and r.json()["session"] is None
    cookies = [c.split("=", 1)[0] for c in r.headers.get_list("set-cookie")]
    assert cookies == ["__Host-td_device"]  # device cookie like a fresh signup
    t0 = time.perf_counter()
    r = await browser.fork(ip="198.51.100.78").post("/auth/signup", _signup("fresh-sec05@example.com"))
    new_s = time.perf_counter() - t0
    assert r.status_code == 201
    # Both outcomes are padded to the same floor (+ jitter): timing no longer separates them.
    assert dup_s >= 1.0 and new_s >= 1.0
    assert abs(dup_s - new_s) < 0.5, (dup_s, new_s)


# --------------------------------------------------------------------------- SEC-08


async def test_sec08_token_rotated_when_pending_login_becomes_active(browser, db, mail) -> None:
    u = await make_user(db)
    assert (await browser.login(u.email)).json()["result"] == "authenticated"
    other = browser.fork(ua=FIREFOX_LINUX)
    assert (await other.login(u.email)).json()["result"] == "device_verification_required"
    pending_token = other.session
    await other.post("/auth/device-verification/send", {"channel": "email"})
    r = await other.post("/auth/device-verification/verify", {"code": last_code(mail)})
    assert r.status_code == 200 and r.json()["result"] == "authenticated"
    assert other.session and other.session != pending_token
    assert (await other.get("/me")).status_code == 200
    stale = other.fork(ua=FIREFOX_LINUX)
    stale.device, stale.session = other.device, pending_token
    assert (await stale.get("/me")).status_code == 401


# --------------------------------------------------------------------------- E2E-12


async def _mfa_failures(db: Any, user_id: Any) -> int:
    await system_context(db, "t")
    return int(
        (
            await db.execute(
                select(func.count()).where(
                    LoginAttempt.user_id == user_id, LoginAttempt.outcome == "mfa_failed"
                )
            )
        ).scalar_one()
    )


async def test_e2e12_totp_replay_is_refused_without_counting_a_failure(browser, db) -> None:
    staff = await make_user(db, with_totp=True)
    from tests.identity.factory import grant

    await grant(db, staff.id, "super_admin")
    await staff_login(browser, staff)
    code = staff.code()
    assert (await browser.post("/auth/step-up", {"method": "totp", "code": code})).status_code == 200
    for _ in range(3):
        r = await browser.post("/auth/step-up", {"method": "totp", "code": code})
        assert r.status_code == 400 and r.json()["reason"] == "code_already_used", r.text
    assert await _mfa_failures(db, staff.id) == 0
    r = await browser.post(
        "/auth/step-up", {"method": "totp", "code": "000000" if code != "000000" else "111111"}
    )
    assert r.status_code == 400 and r.json().get("reason") is None
    assert await _mfa_failures(db, staff.id) == 1


def test_e2e12_is_replay_detects_used_steps_only() -> None:
    secret = totp.random_base32()
    step = totp.current_step()
    code = totp.hotp(secret, step)
    assert totp.is_replay(secret, code, last_used_step=step)
    assert not totp.is_replay(secret, code, last_used_step=step - 2)
    assert not totp.is_replay(secret, code, last_used_step=None)
    assert not totp.is_replay(secret, "12345x", last_used_step=step)


async def test_e2e12_protect_lock_recovery_requires_a_new_password(browser, db, mail, monkeypatch) -> None:
    from app.modules.identity import router as idr

    u = await make_user(db)
    assert (await browser.post("/auth/password/forgot", {"identifier": u.email})).status_code == 202
    token = last_link_token(mail)

    async def locked(*_a: Any, **_k: Any) -> Any:
        return SimpleNamespace(takeover_lock=True, level=0)

    monkeypatch.setattr(idr, "lookup_restriction", locked)
    r = await browser.post("/auth/password/reset", {"token": token, "new_password": GOOD_PASSWORD})
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "password_reuse_not_allowed"
    r = await browser.post(
        "/auth/password/reset", {"token": token, "new_password": "fresh-lantern-harbour-55"}
    )
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- INV-16 (AUTH-04/05)


async def test_inv16_mobile_otp_send_verify_and_caps(browser, db, sms) -> None:
    from app.modules.identity.models import User

    u = await make_user(db)
    await system_context(db, "t")
    user = await db.get(User, u.id)
    user.phone_e164, user.phone_verified_at = "+919812345670", None
    await db.flush()
    await browser.login(u.email)
    r = await browser.post("/auth/verify/mobile/send-otp")
    assert r.status_code == 200 and r.json()["sent_to"].endswith("70"), r.text
    code = __import__("re").search(r"\b(\d{6})\b", sms.sent[-1].text).group(1)
    assert sms.sent[-1].template_key == "otp"
    bad = "000000" if code != "000000" else "111111"
    r = await browser.post("/auth/verify/mobile", {"code": bad})
    assert r.status_code == 400 and r.json()["code"] == "otp_invalid"
    r = await browser.post("/auth/verify/mobile", {"code": code})
    assert r.status_code == 200 and r.json()["result"] == "verified"
    r = await browser.post("/auth/verify/mobile/send-otp")  # already verified
    assert r.status_code == 409


async def test_inv16_mobile_otp_hourly_send_cap(browser, db, sms) -> None:
    from app.modules.identity.models import User

    u = await make_user(db)
    await system_context(db, "t")
    user = await db.get(User, u.id)
    user.phone_e164, user.phone_verified_at = "+919812345671", None
    await db.flush()
    await browser.login(u.email)
    statuses = [(await browser.post("/auth/verify/mobile/send-otp")).status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]  # otp.sms.max_per_number_per_hour = 3
    assert browser.last.json()["code"] == "otp_send_limited" and int(browser.last.headers["Retry-After"]) > 0


# ------------------------------------------- FR-ORG-002 -> platform key (single-company, WS1)


async def test_platform_require_mfa_students_forces_enrolment(browser, db, monkeypatch) -> None:
    """``auth.require_mfa_students`` (platform policy, default off) replaces the per-org
    ``settings.require_mfa_students``; staff MFA stays tier-based."""
    from app.modules.admin import policy as pol
    from tests.security.helpers import set_policy

    key = "auth.require_mfa_students"
    if key not in pol.REGISTRY:  # until the admin module registers the key (WS3 request)
        monkeypatch.setitem(pol.REGISTRY, key, pol.PolicyKey(key, False, "bool"))

    w = await make_user(db)  # policy off by default: no MFA requirement for students
    third = browser.fork(ip="198.51.100.91")
    await third.login(w.email)
    assert (await third.get("/me/consents")).status_code == 200

    await set_policy(db, "auth.require_mfa_students", True)
    u = await make_user(db)  # a public learner: no organization needed any more
    assert (await browser.login(u.email)).json()["result"] == "authenticated"
    r = await browser.get("/me/consents")
    assert r.status_code == 403 and r.json()["code"] == "mfa_enrolment_required"
    assert r.json()["enrol_url"].startswith("/app/settings/security")
    # enrolment routes stay reachable
    r = await browser.post("/me/mfa/totp", {})
    assert r.status_code != 403 and r.json().get("code") != "mfa_enrolment_required", r.text
    # a student with a factor is asked for it at login and then passes
    v = await make_user(db, with_totp=True)
    other = browser.fork(ip="198.51.100.90")
    r = await other.login(v.email)
    assert r.json()["result"] == "mfa_required"
    r = await other.post("/auth/mfa/verify", {"method": "totp", "code": v.code()})
    assert r.json()["result"] == "authenticated"
    assert (await other.get("/me/consents")).status_code == 200
