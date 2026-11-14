"""Google sign-in via Firebase Auth (docs/firebase/MIGRATION-PLAN.md §5.1, P1).

Token verification is exercised with locally generated RSA keys/certificates (no network);
the endpoint tests install a fake verifier, so Google is never called.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy import select

from app.core.db import system_context
from app.modules.identity import google
from app.modules.identity.models import Consent, GuardianConsent, User, UserCredential
from app.modules.sessions.models import AuthSession, LoginAttempt
from tests.identity.factory import REQUIRED_CONSENTS, grant, make_user

PROJECT = "techdrona-lms"
ISS = f"https://securetoken.google.com/{PROJECT}"


# --------------------------------------------------------------------------- helpers


def _claims(email: str, **over: Any) -> dict[str, Any]:
    now = int(time.time())
    c: dict[str, Any] = {
        "iss": ISS,
        "aud": PROJECT,
        "sub": "fb-" + uuid.uuid4().hex[:20],
        "iat": now,
        "exp": now + 3600,
        "auth_time": now,
        "email": email,
        "email_verified": True,
        "name": "Meera Iyer",
        "firebase": {"sign_in_provider": "google.com", "identities": {"email": [email]}},
    }
    c.update(over)
    return c


class FakeVerifier:
    """Maps opaque test tokens to claims (signature checks are covered separately below)."""

    def __init__(self) -> None:
        self.tokens: dict[str, dict[str, Any]] = {}

    def issue(self, email: str, **over: Any) -> str:
        tok = "test-id-token." + uuid.uuid4().hex * 4
        self.tokens[tok] = _claims(email, **over)
        return tok

    async def verify(self, token: str) -> dict[str, Any]:
        if token not in self.tokens:
            raise google.TokenRejected("unknown_test_token")
        return self.tokens[token]


@pytest.fixture
def fake() -> Iterator[FakeVerifier]:
    v = FakeVerifier()
    google.set_verifier(v, PROJECT)
    yield v
    google.set_verifier(None)


def _signup(**kw: Any) -> dict[str, Any]:
    return {"full_name": "Meera Iyer", "date_of_birth": "2001-05-20", "consents": REQUIRED_CONSENTS, **kw}


# --------------------------------------------------------------------------- token verification


def _keypair(cn: str = "test") -> tuple[rsa.RSAPrivateKey, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    return key, cert.public_bytes(serialization.Encoding.PEM).decode()


@pytest.fixture(scope="module")
def keys() -> dict[str, Any]:
    k1, c1 = _keypair("k1")
    k2, c2 = _keypair("k2")
    return {"k1": k1, "c1": c1, "k2": k2, "c2": c2}


def _sign(key: Any, kid: str, claims: dict[str, Any], alg: str = "RS256") -> str:
    return jwt.encode(claims, key, algorithm=alg, headers={"kid": kid})


async def test_verifier_accepts_valid_token_and_checks_aud_iss_exp_kid(keys) -> None:
    fetches = 0

    async def fetch() -> tuple[dict[str, str], int]:
        nonlocal fetches
        fetches += 1
        return {"k1": keys["c1"]}, 3600

    v = google.FirebaseTokenVerifier(PROJECT, fetch_certs=fetch)
    good = _claims("a@example.com")
    claims = await v.verify(_sign(keys["k1"], "k1", good))
    assert claims["sub"] == good["sub"] and fetches == 1

    bad_cases = {
        "aud": _claims("a@example.com", aud="other-project"),
        "iss": _claims("a@example.com", iss="https://securetoken.google.com/other"),
        "exp": _claims("a@example.com", exp=int(time.time()) - 3600, iat=int(time.time()) - 7200),
        "iat_future": _claims("a@example.com", iat=int(time.time()) + 3600),
    }
    for label, c in bad_cases.items():
        with pytest.raises(google.TokenRejected):
            await v.verify(_sign(keys["k1"], "k1", c))
        assert label  # each case rejected
    missing_auth_time = _claims("a@example.com")
    del missing_auth_time["auth_time"]
    with pytest.raises(google.TokenRejected):
        await v.verify(_sign(keys["k1"], "k1", missing_auth_time))

    # signed by a key that is not one of Google's certs (kid k1 claimed, signature by k2)
    with pytest.raises(google.TokenRejected):
        await v.verify(_sign(keys["k2"], "k1", good))
    # unknown kid: one forced refresh, then rejected
    before = fetches
    with pytest.raises(google.TokenRejected, match="unknown_kid"):
        await v.verify(_sign(keys["k2"], "k2", good))
    assert fetches == before + 1
    # HS256 / alg confusion and garbage
    with pytest.raises(google.TokenRejected, match="bad_alg"):
        await v.verify(jwt.encode(good, "secret-" * 8, algorithm="HS256", headers={"kid": "k1"}))
    with pytest.raises(google.TokenRejected):
        await v.verify("not-a-jwt")


async def test_verifier_fails_closed_when_certs_unavailable(keys) -> None:
    async def fetch() -> tuple[dict[str, str], int]:
        raise OSError("network down")

    v = google.FirebaseTokenVerifier(PROJECT, fetch_certs=fetch)
    with pytest.raises(google.TokenRejected, match="certs_unavailable"):
        await v.verify(_sign(keys["k1"], "k1", _claims("a@example.com")))


def test_identity_rules_provider_email_verified_and_freshness() -> None:
    now = datetime.now(UTC)
    ok = google.identity_from_claims(
        _claims("a@example.com"), project_id=PROJECT, now=now, max_auth_age=timedelta(minutes=5)
    )
    assert ok.email == "a@example.com" and ok.name == "Meera Iyer"
    bad = [
        _claims("a@example.com", firebase={"sign_in_provider": "password"}),
        _claims("a@example.com", email_verified=False),
        _claims("a@example.com", email_verified="true"),
        {**_claims("a@example.com"), "email": None},
        _claims("a@example.com", auth_time=int(time.time()) - 600),
        _claims("a@example.com", aud="x"),
        _claims("a@example.com", sub=""),
    ]
    for c in bad:
        with pytest.raises(google.TokenRejected):
            google.identity_from_claims(c, project_id=PROJECT, now=now, max_auth_age=timedelta(minutes=5))


# --------------------------------------------------------------------------- endpoint


async def test_new_student_needs_details_then_account_is_created_and_signed_in(browser, db, fake) -> None:
    r = await browser.post("/auth/login/google", {"id_token": fake.issue("Meera.Iyer@Example.com")})
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["code"] == "google_signup_required" and body["suggested_name"] == "Meera Iyer"
    assert set(body["required_consents"]) == {"terms", "privacy_notice", "core_service"}
    assert browser.session is None

    marketing = {"purpose": "marketing_email", "notice_version": "2026-11-01", "granted": True}
    r = await browser.post(
        "/auth/login/google",
        {
            "id_token": fake.issue("meera.iyer@example.com"),
            "remember_device": True,
            "signup": _signup(consents=[*REQUIRED_CONSENTS, marketing]),
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["result"] == "authenticated" and body["new_account"] is True
    assert body["session"]["created_via"] == "sso" and body["session"]["tier"] == "student"
    assert body["redirect"] == "/app"
    assert browser.session and browser.device and browser.remember

    await system_context(db, "t")
    user = (await db.execute(select(User).where(User.email == "meera.iyer@example.com"))).scalar_one()
    assert user.status == "active" and user.email_verified_at is not None and user.account_origin == "sso"
    assert user.is_minor is False
    assert await db.get(UserCredential, user.id) is None  # no password: Google proves the email
    purposes = set((await db.execute(select(Consent.purpose).where(Consent.user_id == user.id))).scalars())
    assert purposes == {"terms", "privacy_notice", "core_service", "marketing_email"}
    s = (await db.execute(select(AuthSession).where(AuthSession.user_id == user.id))).scalar_one()
    assert s.status == "active" and s.amr == ["google"]
    attempt = (await db.execute(select(LoginAttempt).where(LoginAttempt.user_id == user.id))).scalar_one()
    assert attempt.method == "sso" and attempt.outcome == "success"
    me = await browser.get("/me")
    assert me.status_code == 200 and me.json()["user"]["email_verified"] is True


async def test_existing_verified_student_signs_in_and_token_is_single_use(browser, db, fake) -> None:
    u = await make_user(db, email="ravi.g@example.com")
    tok = fake.issue("ravi.g@example.com")
    r = await browser.post("/auth/login/google", {"id_token": tok})
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "authenticated" and r.json()["new_account"] is False
    await system_context(db, "t")
    assert await db.get(UserCredential, u.id) is not None  # password kept for a verified account

    replay = browser.fork()
    r = await replay.post("/auth/login/google", {"id_token": tok})
    assert r.status_code == 401 and r.json()["code"] == "google_token_invalid"
    assert replay.session is None


async def test_student_with_totp_still_needs_mfa(browser, db, fake) -> None:
    await make_user(db, email="totp.student@example.com", with_totp=True)
    r = await browser.post("/auth/login/google", {"id_token": fake.issue("totp.student@example.com")})
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "mfa_required"


async def test_staff_cannot_use_google_sign_in(browser, db, fake) -> None:
    u = await make_user(db, email="trainer.g@example.com", with_totp=True)
    await grant(db, u.id, "trainer")
    r = await browser.post("/auth/login/google", {"id_token": fake.issue("trainer.g@example.com")})
    assert r.status_code == 403 and r.json()["code"] == "google_signin_not_allowed"
    assert browser.session is None
    await system_context(db, "t")
    assert (await db.execute(select(AuthSession).where(AuthSession.user_id == u.id))).first() is None
    attempt = (await db.execute(select(LoginAttempt).where(LoginAttempt.user_id == u.id))).scalar_one()
    assert attempt.outcome == "restricted" and attempt.failure_reason == "google_staff"


async def test_staff_google_sign_in_when_enabled_still_requires_mfa(browser, db, fake, monkeypatch) -> None:
    """TD_GOOGLE_SIGNIN_STAFF (central login): Google replaces the password step only."""
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "TD_GOOGLE_SIGNIN_STAFF", True)
    u = await make_user(db, email="trainer.g2@example.com", with_totp=True)
    await grant(db, u.id, "trainer")
    r = await browser.post("/auth/login/google", {"id_token": fake.issue("trainer.g2@example.com")})
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "mfa_required"  # the staff authenticator code still follows


async def test_unverified_account_is_claimed_password_and_sessions_removed(browser, db, fake) -> None:
    # Someone registered this address with a password but never verified it (pre-hijack).
    planter = browser.fork(ip="198.51.100.7")
    u = await make_user(db, email="claimed@example.com", status="pending_verification")
    await system_context(db, "t")
    (await db.get(User, u.id)).email_verified_at = None  # type: ignore[union-attr]
    await db.flush()
    r = await planter.login("claimed@example.com")
    assert r.status_code == 200, r.text
    assert planter.session

    r = await browser.post("/auth/login/google", {"id_token": fake.issue("claimed@example.com")})
    assert r.status_code == 200, r.text
    await system_context(db, "t")
    user = await db.get(User, u.id)
    await db.refresh(user)
    assert user is not None and user.email_verified_at is not None and user.status == "active"
    assert await db.get(UserCredential, u.id) is None
    assert (await planter.get("/me")).status_code == 401  # the planter's session is gone
    assert (await planter.login("claimed@example.com")).status_code == 401  # and the password


async def test_signup_rules_consents_age_and_guardian(browser, db, fake, mail) -> None:
    r = await browser.post(
        "/auth/login/google",
        {"id_token": fake.issue("noconsent@example.com"), "signup": _signup(consents=REQUIRED_CONSENTS[:1])},
    )
    assert r.status_code == 403 and r.json()["code"] == "consent_required"

    kid_dob = date.today().replace(year=date.today().year - 15).isoformat()
    r = await browser.post(
        "/auth/login/google",
        {"id_token": fake.issue("kid.g@example.com"), "signup": _signup(date_of_birth=kid_dob)},
    )
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "guardian_required"

    analytics = {"purpose": "analytics_product", "notice_version": "2026-11-01", "granted": True}
    r = await browser.post(
        "/auth/login/google",
        {
            "id_token": fake.issue("kid.g@example.com"),
            "signup": _signup(
                date_of_birth=kid_dob,
                consents=[*REQUIRED_CONSENTS, analytics],
                guardian={"name": "Parent", "email": "parent.g@example.com", "relationship": "parent"},
            ),
        },
    )
    assert r.status_code == 200, r.text
    await system_context(db, "t")
    kid = (await db.execute(select(User).where(User.email == "kid.g@example.com"))).scalar_one()
    assert kid.is_minor and kid.status == "pending_guardian_consent"
    purposes = set((await db.execute(select(Consent.purpose).where(Consent.user_id == kid.id))).scalars())
    assert "analytics_product" not in purposes  # minors cannot grant analytics
    gc = (
        await db.execute(select(GuardianConsent).where(GuardianConsent.child_user_id == kid.id))
    ).scalar_one()
    assert gc.status == "pending"
    assert any(m.to == "parent.g@example.com" for m in mail.sent)


async def test_rejected_tokens_and_kill_switch(browser, db, fake, monkeypatch) -> None:
    r = await browser.post(
        "/auth/login/google",
        {"id_token": fake.issue("p@example.com", firebase={"sign_in_provider": "password"})},
    )
    assert r.status_code == 401 and r.json()["code"] == "google_token_invalid"
    r = await browser.post(
        "/auth/login/google", {"id_token": fake.issue("p@example.com", email_verified=False)}
    )
    assert r.status_code == 401
    stale = int(time.time()) - 600
    r = await browser.post("/auth/login/google", {"id_token": fake.issue("p@example.com", auth_time=stale)})
    assert r.status_code == 401
    r = await browser.post("/auth/login/google", {"id_token": "x" * 120})
    assert r.status_code == 401

    google.set_verifier(None)
    monkeypatch.setattr(
        google, "settings", lambda: google.GoogleSignInSettings(TD_GOOGLE_SIGNIN_ENABLED=False)
    )
    r = await browser.post("/auth/login/google", {"id_token": "x" * 120})
    assert r.status_code == 503 and r.json()["code"] == "google_signin_unavailable"
