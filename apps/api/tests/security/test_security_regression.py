"""TS-SEC regression checks (Stage 10 QA): secrets never logged, session/device/reset tokens
stored hashed only, cookie flags, OTP send/verify and login rate limits.

Related regression tests that live with their modules (re-run by the full suite):

* webhook invalid signature — ``tests/commerce/test_checkout_webhooks.py::test_invalid_signature_is_400_and_logged``
* hidden test cases never returned — ``tests/coding/test_flow.py::test_submit_judges_all_cases_hidden_are_verdict_only``,
  ``::test_other_users_submission_is_404_staff_sees_source_not_hidden``
* answer keys hidden before review — ``tests/assessments/test_attempts.py::test_delivery_schemas_have_no_key_fields``,
  ``::test_start_returns_layout_without_keys_and_binds_session``,
  ``::test_scoring_with_negative_marking_and_review_phases``
* login back-off / hard stop — ``tests/identity/test_login_and_passwords.py``
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from sqlalchemy import select

from app.core.config import reset_settings_cache
from app.core.db import system_context
from app.core.security import hash_token
from app.modules.identity.models import PasswordResetToken
from app.modules.sessions.models import AuthSession
from tests.identity.factory import FIREFOX_LINUX, make_user
from tests.identity.fixtures import last_code, last_link_token


async def test_no_secrets_tokens_or_otps_in_logs_during_auth_flows(
    browser: Any, db: Any, mail: Any, capfd: Any, caplog: Any
) -> None:
    """Login, device OTP, TOTP MFA, forgot/reset password and logout: none of the passwords,
    OTP codes, TOTP codes, reset tokens or cookie values ever reach the logs."""
    caplog.set_level(logging.DEBUG)
    secrets: list[str] = []

    u = await make_user(db)
    secrets.append(u.password)
    r = await browser.login(u.email)
    assert r.status_code == 200 and r.json()["result"] == "authenticated", r.text
    secrets += [browser.session or "", browser.device or ""]

    # new device -> email OTP
    other = browser.fork(ua=FIREFOX_LINUX)
    r = await other.login(u.email)
    assert r.json()["result"] == "device_verification_required", r.text
    assert (await other.post("/auth/device-verification/send", {"channel": "email"})).status_code == 200
    otp = last_code(mail)
    secrets.append(otp)
    r = await other.post("/auth/device-verification/verify", {"code": otp})
    assert r.status_code == 200, r.text
    secrets += [other.session or "", other.device or ""]

    # TOTP MFA login
    staff = await make_user(db, with_totp=True)
    b2 = browser.fork()
    r = await b2.login(staff.email)
    assert r.json()["result"] == "mfa_required"
    pending = b2.session or ""
    code = staff.code()
    secrets += [pending, code]
    r = await b2.post("/auth/mfa/verify", {"method": "totp", "code": code})
    assert r.status_code == 200, r.text
    secrets.append(b2.session or "")

    # forgot / reset password
    assert (await browser.post("/auth/password/forgot", {"identifier": u.email})).status_code == 202
    token = last_link_token(mail)
    new_pw = "quiet-meadow-copper-31"
    secrets += [token, new_pw]
    r = await browser.post("/auth/password/reset", {"token": token, "new_password": new_pw})
    assert r.status_code == 200, r.text
    # wrong password attempt (value must not be logged either)
    bad_pw = "definitely-wrong-password-77"
    secrets.append(bad_pw)
    await browser.fork().login(u.email, bad_pw)
    await b2.post("/auth/logout")

    out, err = capfd.readouterr()
    logged = out + err + "\n".join(f"{r.getMessage()} {r.__dict__}" for r in caplog.records)
    assert "auth/login" in logged or "/auth/" in logged, "request logs were not captured"
    leaked = [s for s in secrets if s and s in logged]
    assert not leaked, f"secrets found in logs: {[s[:4] + '...' for s in leaked]}"


async def test_session_and_reset_tokens_are_stored_hashed_only(browser: Any, db: Any, mail: Any) -> None:
    u = await make_user(db)
    assert (await browser.login(u.email)).status_code == 200
    raw = browser.session
    assert raw
    await system_context(db, "t")
    s = (await db.execute(select(AuthSession).where(AuthSession.user_id == u.id))).scalar_one()
    assert s.token_hash == hash_token(raw)
    row_text = " ".join(str(v) for v in s.__dict__.values())
    assert raw not in row_text and raw.encode() not in s.token_hash
    assert (await browser.post("/auth/password/forgot", {"identifier": u.email})).status_code == 202
    token = last_link_token(mail)
    await system_context(db, "t")
    prt = (
        await db.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == u.id))
    ).scalar_one()
    assert prt.token_hash == hash_token(token)
    assert token not in " ".join(str(v) for v in prt.__dict__.values())


@pytest.fixture
def secure_cookies(monkeypatch: Any) -> Any:
    monkeypatch.setenv("TD_COOKIE_SECURE", "true")
    reset_settings_cache()
    yield
    monkeypatch.delenv("TD_COOKIE_SECURE")
    reset_settings_cache()


def _cookie(resp: Any, name: str) -> str:
    found = [c for c in resp.headers.get_list("set-cookie") if c.startswith(f"{name}=")]
    assert found, resp.headers.get_list("set-cookie")
    return found[-1]


async def test_cookie_flags(browser: Any, db: Any, secure_cookies: Any) -> None:
    """__Host- prefix, Secure (production setting), HttpOnly, SameSite=Lax, Path=/, no Domain;
    logout clears with Max-Age=0."""
    u = await make_user(db)
    r = await browser.login(u.email)
    assert r.status_code == 200
    for name in ("__Host-td_session", "__Host-td_device"):
        c = _cookie(r, name)
        attrs = [a.strip() for a in c.split(";")]
        assert "Secure" in attrs and "HttpOnly" in attrs and "SameSite=Lax" in attrs and "Path=/" in attrs
        assert not any(a.lower().startswith("domain=") for a in attrs)
    out = await browser.post("/auth/logout")
    assert out.status_code in (200, 204), out.text
    cleared = _cookie(out, "__Host-td_session")
    assert "Max-Age=0" in cleared and cleared.startswith("__Host-td_session=;")


async def test_otp_send_and_verify_are_rate_limited(browser: Any, db: Any, mail: Any) -> None:
    """Email OTP sends per destination are capped (otp.email.max_per_hour, default 10) and a
    refused send emails nothing. (Wrong-code lockout: tests/sessions/test_sessions_and_devices.py
    ::test_otp_attempts_exceeded.)"""
    u = await make_user(db)
    assert (await browser.login(u.email)).json()["result"] == "authenticated"  # first device trusted
    other = browser.fork(ua=FIREFOX_LINUX)
    r = await other.login(u.email)
    assert r.json()["result"] == "device_verification_required"
    statuses = []
    for _ in range(12):
        statuses.append(
            (await other.post("/auth/device-verification/send", {"channel": "email"})).status_code
        )
    assert statuses[0] == 200 and statuses[-1] == 429, statuses
    last = other.last
    assert last.json()["code"] == "otp_send_limited" and int(last.headers["Retry-After"]) >= 1
    sent_before = len(mail.sent)
    await other.post("/auth/device-verification/send", {"channel": "email"})
    assert len(mail.sent) == sent_before  # no email for a refused send


async def test_login_rate_limit_per_source_ip(browser: Any, db: Any) -> None:
    """Pre-auth IP window: a burst of failures from one source IP is throttled for every
    identifier (no oracle), with Retry-After."""
    codes = []
    for i in range(40):
        r = await browser.login(f"nobody{i}@example.com", "wrong-password-xx-1")
        codes.append(r.status_code)
        if r.status_code == 429:
            break
    assert codes[-1] == 429, codes
    assert browser.last.json()["code"] == "throttled" and browser.last.headers.get("Retry-After")
