"""identity endpoints over HTTP on Firestore with no Postgres (``http`` fixture: the real app,
``DATABASE_URL`` empty, so any Postgres use by a route fails the test).

Covers: sign-up -> verify email -> /me; login failures + back-off; MFA (TOTP + recovery code);
new-device OTP; session cap + session choice; logout; password forgot/reset (single use) and
change; step-up; consents; profile; TOTP enrol/confirm/delete; recovery codes; remember-device
refresh; guardian consent (minor sign-up) end to end.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Any

import pyotp
import pytest

from tests.identity.factory import NOTICE, REQUIRED_CONSENTS
from tests.identity.fs.conftest import PASSWORD, fs_user

NEW_PASSWORD = "Amber-lighthouse-quartz-77"


@pytest.fixture
def stores(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Extra switches for these flows (requested before ``http``): notifications (security
    notices) on Firestore; strict login (device codes and MFA on, no exempt emails)."""
    monkeypatch.setenv("TD_STORE_NOTIFICATIONS", "firestore")
    monkeypatch.setenv("TD_DEVICE_CODE_OFF", "false")
    monkeypatch.setenv("TD_MFA_EXEMPT_EMAILS", "")
    monkeypatch.setenv("TD_SIMPLE_AUTH", "false")
    # notifications.notify's Firestore path still reads the caller's Postgres RLS scope
    # (``core.db.rls_scope``), which a stack without Postgres cannot answer (reported to the
    # notifications/platform agents): record the notices instead.
    from app.modules.identity import router as identity_router

    sent: list[str] = []

    async def _notify(_session: Any, _user_id: Any, template_key: str, **_kw: Any) -> None:
        sent.append(template_key)

    monkeypatch.setattr(identity_router, "notify", _notify)
    yield


def last_code(http: Any) -> str:
    m = re.search(r"\b(\d{6})\b", http.mail.sent[-1].text)
    assert m, http.mail.sent[-1].text
    return m.group(1)


def last_link(http: Any, kind: str) -> str:
    from urllib.parse import unquote

    text = http.mail.sent[-1].text
    m = re.search(rf"/{kind}/([^\s/?#]+)", text)
    assert m, text
    return unquote(m.group(1))


def signup_body(email: str, dob: str = "2000-04-12", **kw: Any) -> dict[str, Any]:
    return {
        "full_name": "Ananya Reddy",
        "email": email,
        "date_of_birth": dob,
        "password": PASSWORD,
        "consents": REQUIRED_CONSENTS,
        **kw,
    }


async def _email_step_up(http: Any) -> None:
    r = await http.post("/auth/step-up/options", {"send_otp_via": "email"})
    assert r.status_code == 200, r.text
    r = await http.post("/auth/step-up", {"method": "email_otp", "code": last_code(http)})
    assert r.status_code == 200, r.text


async def test_signup_verify_email_and_me(stores: None, http: Any) -> None:
    r = await http.post("/auth/signup", signup_body("ananya@x.in"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "pending_verification" and body["session"]["status"] == "active"
    token = last_link(http, "verify/email")
    me = await http.get("/me")
    assert me.status_code == 200, me.text
    assert me.json()["user"]["email_verified"] is False
    assert me.json()["profile"]["full_name"] == "Ananya Reddy"
    v = await http.post("/auth/verify/email", {"token": token})
    assert v.status_code == 200 and v.json() == {"result": "verified", "status": "active"}, v.text
    assert (await http.post("/auth/verify/email", {"token": token})).status_code == 400  # single use
    me = await http.get("/me")
    assert me.json()["user"]["email_verified"] is True and me.json()["user"]["status"] == "active"
    # duplicate email: same 201 shape, no second account
    other = http.fork()
    dup = await other.post("/auth/signup", signup_body("ananya@x.in"))
    assert dup.status_code == 201 and dup.json()["session"] is None


async def test_login_failures_backoff_and_logout(stores: None, http: Any) -> None:
    u = await fs_user("bo@x.in")
    r = await http.login(u.email, "wrong-password-123")
    assert r.status_code == 401 and r.json()["code"] == "invalid_credentials"
    r = await http.login(u.email, u.password)
    assert r.status_code == 429 and r.json()["code"] == "throttled", r.text
    from app.modules.identity.repo_firestore import system_repo

    cred = await system_repo().get_credential(u.id)
    assert cred is not None and cred.consecutive_failures == 1  # persisted at the end of the request
    # unknown identifier: same answer
    assert (await http.fork().login("nobody@x.in", "whatever-123")).json()["code"] == "invalid_credentials"


async def test_login_me_logout(stores: None, http: Any) -> None:
    u = await fs_user("lo@x.in")
    r = await http.login(u.email, u.password)
    assert r.status_code == 200 and r.json()["result"] == "authenticated", r.text
    assert r.json()["redirect"] == "/app"
    me = await http.get("/me")
    assert me.status_code == 200 and me.json()["user"]["id"] == str(u.id)
    out = await http.post("/auth/logout")
    assert out.status_code == 200 and out.json()["result"] == "logged_out"
    assert (await http.get("/me")).status_code == 401


async def test_mfa_totp_and_recovery_code(stores: None, http: Any) -> None:
    secret = pyotp.random_base32()
    u = await fs_user("mfa@x.in", totp_secret=secret)
    r = await http.login(u.email, u.password)
    assert r.status_code == 200 and r.json()["result"] == "mfa_required", r.text
    assert (await http.get("/me")).status_code == 401  # pending login (login_incomplete)
    bad = await http.post("/auth/mfa/verify", {"method": "totp", "code": "000000"})
    assert bad.status_code == 400
    ok = await http.post("/auth/mfa/verify", {"method": "totp", "code": u.code()})
    assert ok.status_code == 200 and ok.json()["result"] == "authenticated", ok.text
    assert (await http.get("/me")).json()["mfa"]["level"] == "totp"
    # recovery codes (step-up: the MFA login counts as a fresh step-up)
    rc = await http.post("/me/mfa/recovery-codes")
    assert rc.status_code == 201, rc.text
    codes = rc.json()["codes"]
    factors = (await http.get("/me/mfa/factors")).json()["data"]
    assert {f["type"] for f in factors} == {"totp", "recovery_codes"}
    # second device: sign in with a recovery code instead of TOTP
    b2 = http.fork()
    r = await b2.login(u.email, u.password)
    assert r.json()["result"] == "mfa_required"
    ok = await b2.post("/auth/mfa/verify", {"method": "recovery_code", "code": codes[0]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["result"] in ("authenticated", "device_verification_required")
    b3 = http.fork()
    await b3.login(u.email, u.password)
    again = await b3.post("/auth/mfa/verify", {"method": "recovery_code", "code": codes[0]})
    assert again.status_code == 400  # single use


async def test_new_device_otp_session_cap_and_choice(stores: None, http: Any) -> None:
    u = await fs_user("dev@x.in")
    assert (await http.login(u.email, u.password)).json()["result"] == "authenticated"  # first device
    b2 = http.fork()
    r = await b2.login(u.email, u.password)
    assert r.json()["result"] == "device_verification_required", r.text
    s = await b2.post("/auth/device-verification/send", {"channel": "email"})
    assert s.status_code == 200, s.text
    v = await b2.post("/auth/device-verification/verify", {"code": last_code(http)})
    assert v.status_code == 200 and v.json()["result"] == "authenticated", v.text
    # third device: OTP, then the 2-session student cap asks which session to end
    b3 = http.fork()
    assert (await b3.login(u.email, u.password)).json()["result"] == "device_verification_required"
    await b3.post("/auth/device-verification/send", {"channel": "email"})
    v = await b3.post("/auth/device-verification/verify", {"code": last_code(http)})
    assert v.status_code == 409 and v.json()["code"] == "session_cap_reached", v.text
    victim = v.json()["sessions"][0]["session_id"]
    c = await b3.post("/auth/session-choice", {"end_session_id": victim})
    assert c.status_code == 200 and c.json()["result"] == "authenticated", c.text
    from app.modules.sessions.repo_firestore import system_repo

    ended = await system_repo().get_session(__import__("uuid").UUID(victim))
    assert ended is not None and ended.end_reason == "session_cap_evicted"
    devs = (await b3.get("/me/devices")).json()
    assert devs  # the devices endpoint answers on Firestore too


async def test_password_forgot_reset_and_change(stores: None, http: Any) -> None:
    u = await fs_user("pw@x.in")
    r = await http.post("/auth/password/forgot", {"identifier": u.email})
    assert r.status_code == 202
    token = last_link(http, "reset-password")
    same = await http.post("/auth/password/reset", {"token": token, "new_password": u.password})
    assert same.status_code == 400 and same.json()["errors"][0]["code"] == "password_reuse_not_allowed"
    ok = await http.post("/auth/password/reset", {"token": token, "new_password": NEW_PASSWORD})
    assert ok.status_code == 200, ok.text
    assert (
        await http.post("/auth/password/reset", {"token": token, "new_password": PASSWORD + "x"})
    ).status_code == 400
    assert (await http.login(u.email, NEW_PASSWORD)).json()["result"] == "authenticated"
    ch = await http.post(
        "/auth/password/change", {"current_password": NEW_PASSWORD, "new_password": "Teal-orchard-violin-58"}
    )
    assert ch.status_code == 200, ch.text
    assert (await http.get("/me")).status_code == 200  # current session kept (token rotated)
    assert (await http.fork().login(u.email, NEW_PASSWORD)).status_code == 401


async def test_step_up_consents_and_profile(stores: None, http: Any) -> None:
    u = await fs_user("st@x.in")
    await http.login(u.email, u.password)
    opts = await http.post("/auth/step-up/options", {})
    assert opts.json()["allowed_methods"] == ["email_otp"]
    await _email_step_up(http)
    assert (await http.get("/me")).json()["session"]["last_step_up_at"] is not None
    cs = await http.get("/me/consents")
    states = {c["purpose"]: c["state"] for c in cs.json()["data"]}
    assert states["terms"] == "granted" and states["marketing_email"] == "not_granted"
    r = await http.post(
        "/me/consents", {"purpose": "marketing_email", "action": "granted", "notice_version": NOTICE}
    )
    assert r.status_code == 201, r.text
    states = {c["purpose"]: c["state"] for c in (await http.get("/me/consents")).json()["data"]}
    assert states["marketing_email"] == "granted"
    p = await http.patch("/me/profile", {"display_name": "Annie", "graduation_year": 2026})
    assert p.status_code == 200, p.text
    prof = (await http.get("/me")).json()["profile"]
    assert prof["display_name"] == "Annie" and prof["graduation_year"] == 2026


async def test_totp_enrol_confirm_delete(stores: None, http: Any) -> None:
    u = await fs_user("en@x.in")
    await http.login(u.email, u.password)
    first = await http.post("/me/mfa/totp", {})
    assert first.status_code == 401 and first.json()["code"] == "step_up_required", (
        first.text
    )  # students: step-up first
    await _email_step_up(http)
    b = await http.post("/me/mfa/totp", {"label": "Phone"})
    assert b.status_code == 201, b.text
    secret, fid = b.json()["secret"], b.json()["factor_id"]
    bad = await http.post(f"/me/mfa/totp/{fid}/confirm", {"code": "000000"})
    assert bad.status_code == 400
    ok = await http.post(f"/me/mfa/totp/{fid}/confirm", {"code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200 and ok.json()["confirmed"] is True, ok.text
    factors = (await http.get("/me/mfa/factors")).json()["data"]
    assert [f["confirmed"] for f in factors] == [True]
    d = await http.delete(f"/me/mfa/factors/{fid}")
    assert d.status_code == 200, d.text
    assert (await http.get("/me/mfa/factors")).json()["data"] == []


async def test_remember_device_refresh(stores: None, http: Any) -> None:
    u = await fs_user("rm@x.in")
    r = await http.post(
        "/auth/login", {"identifier": u.email, "password": u.password, "remember_device": True}
    )
    assert r.json()["result"] == "authenticated", r.text
    assert http.remember, "remember cookie issued"
    b = http.fork(device=http.device)  # same browser profile, session cookie gone
    rr = await b.post("/auth/remember/refresh", {"remember_token": http.remember})
    assert rr.status_code == 200 and rr.json()["result"] == "authenticated", rr.text
    assert b.remember and b.remember != http.remember  # rotated on use
    old = await http.fork(device=http.device).post(
        "/auth/remember/refresh", {"remember_token": http.remember}
    )
    assert old.status_code in (401, 403) and old.json()["code"] == "remember_invalid"


async def test_minor_signup_guardian_consent(stores: None, http: Any) -> None:
    r = await http.post(
        "/auth/signup",
        signup_body(
            "kid@x.in",
            dob="2012-05-01",
            guardian={"name": "Parent", "email": "parent@x.in", "relationship": "parent"},
        ),
    )
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "pending_guardian_consent"
    uid = r.json()["user_id"]
    gmail = next(m for m in http.mail.sent if m.to == "parent@x.in")
    gtoken = gmail.text.split("/guardian-consent/")[1].split()[0]
    view = await http.get(f"/auth/guardian-consent/{gtoken}")
    assert view.status_code == 200 and view.json()["child_first_name"] == "Ananya", view.text
    assert (await http.post(f"/auth/guardian-consent/{gtoken}/verify-contact")).status_code == 200
    code = last_code(http)
    bad = await http.post(
        f"/auth/guardian-consent/{gtoken}/decision",
        {"otp_code": "000000" if code != "000000" else "111111", "decision": "consent", "declaration": True},
        headers={"Idempotency-Key": "guardian-bad-1"},
    )
    assert bad.status_code == 400 and bad.json()["code"] == "otp_invalid", bad.text
    ok = await http.post(
        f"/auth/guardian-consent/{gtoken}/decision",
        {"otp_code": code, "decision": "consent", "declaration": True},
        headers={"Idempotency-Key": "guardian-ok-1"},
    )
    assert ok.status_code == 200 and ok.json()["status"] == "verified", ok.text
    from uuid import UUID

    from app.modules.identity.repo_firestore import system_repo

    gc = await system_repo().latest_guardian_consent(UUID(uid))
    assert gc is not None and gc.status == "verified" and gc.expires_at is not None
    child = await system_repo().get_user(UUID(uid))
    assert child is not None and child.status in ("active", "pending_verification")
    assert (await http.get(f"/auth/guardian-consent/{gtoken}")).status_code == 404  # single use


async def test_erasure_and_reencrypt_on_firestore(fs: Any) -> None:
    from app.core.db import NO_POSTGRES
    from app.modules.identity import erasure, reencrypt_totp
    from app.modules.identity import service as ids

    secret = pyotp.random_base32()
    u = await fs_user("er@x.in", totp_secret=secret)
    changed, failed = await reencrypt_totp.reencrypt_all(NO_POSTGRES, apply=False)
    assert failed == 0 and changed == 0
    out = await erasure.erase_user(NO_POSTGRES, u.id)
    assert out["users_tombstoned"] == 1 and out["profiles_scrubbed"] == 1
    assert out["deleted"]["user_credentials"] == 1 and out["deleted"]["mfa_factors"] == 1
    assert await ids.find_user(NO_POSTGRES, "email", "er@x.in") is None
    again = await erasure.erase_user(NO_POSTGRES, u.id)  # idempotent
    assert again["users_tombstoned"] == 0 and again["deleted"]["user_credentials"] == 0
