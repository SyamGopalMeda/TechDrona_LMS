"""AUTH-01/02/03, ME-01, ME-05/06, guardian consent (AUTH-25..27), password policy."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select

from app.core.db import system_context
from app.modules.identity.models import Consent, GuardianConsent, User, UserCredential
from app.modules.identity.passwords import password_problems
from app.modules.sessions.models import AuthSession
from tests.identity.factory import GOOD_PASSWORD, NOTICE, REQUIRED_CONSENTS
from tests.identity.fixtures import last_code, last_link_token


def _signup(email: str, dob: str = "2000-04-12", **kw):
    return {
        "full_name": "Ananya Reddy",
        "email": email,
        "date_of_birth": dob,
        "password": GOOD_PASSWORD,
        "consents": REQUIRED_CONSENTS,
        **kw,
    }


async def test_signup_adult_creates_user_session_and_verification_email(browser, db, mail) -> None:
    r = await browser.post(
        "/auth/signup",
        _signup(
            "ananya@example.com",
            consents=[
                *REQUIRED_CONSENTS,
                {"purpose": "marketing_email", "notice_version": NOTICE, "granted": False},
            ],
        ),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_minor"] is False and body["status"] == "pending_verification"
    assert body["next_steps"] == ["verify_email"] and body["session"]["tier"] == "student"
    assert browser.session and browser.device  # cookies issued
    await system_context(db, "t")
    user = await db.get(User, __import__("uuid").UUID(body["user_id"]))
    assert (
        user is not None and user.age_verification_method == "self_declared" and user.privacy_tier == "adult"
    )
    cred = await db.get(UserCredential, user.id)
    assert cred is not None and cred.password_hash.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    s = (await db.execute(select(AuthSession).where(AuthSession.user_id == user.id))).scalar_one()
    assert len(s.token_hash) == 32 and s.token_hash != browser.session.encode()  # only SHA-256 stored
    purposes = set((await db.execute(select(Consent.purpose).where(Consent.user_id == user.id))).scalars())
    assert purposes == {"terms", "privacy_notice", "core_service"}  # opt-outs not recorded as grants
    # verify email via the emailed link
    token = last_link_token(mail)
    r = await browser.post("/auth/verify/email", {"token": token})
    assert r.status_code == 200 and r.json()["status"] == "active"
    r = await browser.post("/auth/verify/email", {"token": token})  # single use
    assert r.status_code == 400
    me = await browser.get("/me")
    assert me.status_code == 200 and me.json()["user"]["email_verified"] is True
    assert me.headers["cache-control"] == "no-store"


async def test_signup_minor_flagged_and_restricted_until_guardian_consents(browser, db, mail) -> None:
    dob = date.today().replace(year=date.today().year - 15).isoformat()
    forbidden = {"purpose": "analytics_personalisation", "notice_version": NOTICE, "granted": True}
    r = await browser.post(
        "/auth/signup",
        _signup(
            "kid@example.com",
            dob=dob,
            consents=[*REQUIRED_CONSENTS, forbidden],
            guardian={"name": "Parent", "email": "parent@example.com", "relationship": "parent"},
        ),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["is_minor"] is True and body["status"] == "pending_guardian_consent"
    assert body["next_steps"][0] == "guardian_consent"
    uid = __import__("uuid").UUID(body["user_id"])
    await system_context(db, "t")
    purposes = set((await db.execute(select(Consent.purpose).where(Consent.user_id == uid))).scalars())
    assert "analytics_personalisation" not in purposes  # minors cannot grant C
    guardian_mail = next(m for m in mail.sent if m.to == "parent@example.com")
    gtoken = guardian_mail.text.split("/guardian-consent/")[1].split()[0]
    # default-tag routes are blocked for a minor pending guardian consent; account_status allowed
    assert (await browser.get("/me")).status_code == 200
    r = await browser.patch("/me/profile", {"branch": "CSE"})
    assert r.status_code == 403 and r.json()["code"] == "minor_consent_pending"
    # minors may not grant B/C/E/F/H later either
    r = await browser.post(
        "/me/consents", {"purpose": "marketing_email", "action": "granted", "notice_version": NOTICE}
    )
    assert r.status_code == 403
    # guardian flow
    view = await browser.get(f"/auth/guardian-consent/{gtoken}")
    assert view.status_code == 200 and view.json()["child_first_name"] == "Ananya"
    assert (await browser.post(f"/auth/guardian-consent/{gtoken}/verify-contact")).status_code == 200
    code = last_code(mail)
    bad = await browser.post(
        f"/auth/guardian-consent/{gtoken}/decision",
        {"otp_code": "000000" if code != "000000" else "111111", "decision": "consent", "declaration": True},
        headers={"Idempotency-Key": "guardian-bad-1"},
    )
    assert bad.status_code == 400 and bad.json()["code"] == "otp_invalid"
    ok = await browser.post(
        f"/auth/guardian-consent/{gtoken}/decision",
        {"otp_code": code, "decision": "consent", "declaration": True},
        headers={"Idempotency-Key": "guardian-ok-1"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "verified"
    await system_context(db, "t")
    gc = (await db.execute(select(GuardianConsent).where(GuardianConsent.child_user_id == uid))).scalar_one()
    assert gc.status == "verified" and gc.expires_at is not None
    user = await db.get(User, uid)
    assert user is not None and user.is_minor and user.status in ("active", "pending_verification")
    # link is single-use after the decision
    assert (await browser.get(f"/auth/guardian-consent/{gtoken}")).status_code == 404


async def test_signup_minor_requires_guardian_and_consents_required(browser) -> None:
    dob = date.today().replace(year=date.today().year - 16).isoformat()
    r = await browser.post("/auth/signup", _signup("kid2@example.com", dob=dob))
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "guardian_required"
    r = await browser.post("/auth/signup", _signup("x@example.com", consents=REQUIRED_CONSENTS[:2]))
    assert r.status_code == 403 and r.json()["code"] == "consent_required"
    assert r.json()["purposes"] == ["core_service"]


@pytest.mark.parametrize(
    ("password", "code"),
    [
        ("short-pass-1", "password_too_short"),
        ("password12345", "password_too_short"),
        ("correct-horse-battery-staple", "password_breached"),
        ("techdrona-is-the-best-123", "password_breached"),
        ("a" * 20, "password_breached"),
        ("x" * 129, "password_too_long"),
    ],
)
async def test_signup_password_policy(browser, password, code) -> None:
    r = await browser.post("/auth/signup", {**_signup("p@example.com"), "password": password})
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == code


def test_password_policy_mfa_allows_8_chars() -> None:
    assert password_problems("tiger-lily", has_mfa=True) == []
    assert password_problems("tiger-lily", has_mfa=False) == ["password_too_short"]
    assert password_problems("qwerty123", has_mfa=True) == ["password_breached"]
    assert password_problems("ananya-secret-2027-pass", context=("ananya",)) == [
        "password_contains_personal_info"
    ]


async def test_signup_existing_email_same_shape_no_enumeration(browser, db, mail) -> None:
    r1 = await browser.post("/auth/signup", _signup("dup@example.com"))
    assert r1.status_code == 201
    other = browser.fork()
    r2 = await other.post("/auth/signup", _signup("dup@example.com"))
    assert r2.status_code == 201 and r2.json()["next_steps"] == ["check_email"]
    assert set(r2.json()) == set(r1.json())
    assert mail.sent[-1].to == "dup@example.com" and "already have" in mail.sent[-1].subject
    await system_context(db, "t")
    assert len((await db.execute(select(User).where(User.email == "dup@example.com"))).scalars().all()) == 1


async def test_consents_read_and_withdraw(browser) -> None:
    await browser.post("/auth/signup", _signup("c@example.com"))
    r = await browser.get("/me/consents")
    states = {d["purpose"]: d["state"] for d in r.json()["data"]}
    assert states["terms"] == "granted" and states["marketing_email"] == "not_granted"
    r = await browser.post(
        "/me/consents", {"purpose": "marketing_email", "action": "granted", "notice_version": NOTICE}
    )
    assert r.status_code == 201 and r.json()["state"] == "granted"
    r = await browser.post(
        "/me/consents", {"purpose": "marketing_email", "action": "withdrawn", "notice_version": NOTICE}
    )
    assert r.status_code == 201
    states = {d["purpose"]: d["state"] for d in (await browser.get("/me/consents")).json()["data"]}
    assert states["marketing_email"] == "withdrawn"
    r = await browser.post(
        "/me/consents", {"purpose": "core_service", "action": "withdrawn", "notice_version": NOTICE}
    )
    assert r.status_code == 409


async def test_validation_errors_are_problem_json(browser) -> None:
    r = await browser.post("/auth/signup", {"full_name": "x", "unexpected": 1})
    assert r.status_code == 400 and r.headers["content-type"].startswith("application/problem+json")
    r = await browser.post("/auth/signup", _signup("bad-email"))
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "invalid_email"
    r = await browser.post("/auth/signup", _signup("future@example.com", dob="2999-01-01"))
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "invalid_date_of_birth"
