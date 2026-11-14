"""identity on Firestore: every dispatched ``identity.service`` path, uniqueness, single use,
mappers and backfill/verify (emulator only; see conftest)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pyotp
import pytest

from app.core.firestore.errors import UniqueViolationError
from app.core.ids import uuid7
from app.modules.identity import service as ids
from app.modules.identity.crypto import encrypt_secret
from app.modules.identity.fs_codec import doc_obj, obj_doc, row_doc
from app.modules.identity.models import (
    Consent,
    GuardianConsent,
    MfaFactor,
    PasswordResetToken,
    User,
    UserCredential,
    UserProfile,
    VerificationToken,
)
from app.modules.identity.repo_firestore import IdentityRepo, system_repo
from tests.identity.fs.conftest import FakePgSession

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
S: Any = None  # the Postgres session is unused on the Firestore path


def _user(email: str | None = "a@x.in", **kw: Any) -> User:
    return User(id=uuid7(), email=email, status="active", is_minor=False, **kw)


def test_repo_is_scoped() -> None:
    from app.core.firestore.repository import assert_repository_scoped

    assert_repository_scoped(IdentityRepo)


def test_codec_round_trip_every_model() -> None:
    uid = uuid.uuid4()
    samples = [
        User(id=uid, email="a@x.in", status="active", is_minor=True, created_at=NOW, privacy_tier="minor"),
        UserProfile(user_id=uid, full_name="A", date_of_birth=date(2008, 2, 29), target_company_ids=[uid]),
        UserCredential(user_id=uid, password_hash="h", password_set_at=NOW, consecutive_failures=2),
        MfaFactor(
            id=uid, user_id=uid, factor_type="recovery_codes", recovery_code_hashes=[b"\x00\x01", b"\xff"]
        ),
        VerificationToken(
            id=uid,
            purpose="p",
            channel="email",
            destination_hmac=b"\x01",
            token_hash=b"\x02",
            created_ip="10.0.0.1",
        ),
        PasswordResetToken(id=uid, user_id=uid, token_hash=b"\x03", expires_at=NOW),
        Consent(id=uid, user_id=uid, purpose="terms", action="granted", notice_version="v1", channel="web"),
        GuardianConsent(
            id=uid, child_user_id=uid, guardian_name="G", relationship="parent", verification_method="otp"
        ),
    ]
    for obj in samples:
        doc = obj_doc(obj)
        back = doc_obj(type(obj), doc)
        assert obj_doc(back) == doc
        # the backfill mapper (row keyed by column name) gives the same document
        assert row_doc(type(obj), {k: getattr(obj, k, None) for k in doc}) == doc
    assert obj_doc(samples[1])["date_of_birth"] == "2008-02-29"
    assert obj_doc(samples[3])["recovery_code_hashes"] == ["0001", "ff"]


async def test_create_find_and_uniqueness(fs: Any) -> None:
    repo = system_repo()
    u = _user("a@x.in", phone_e164="+919999999999", username="td123456")
    await repo.create_user(u, UserProfile(user_id=u.id, full_name="Asha"))
    got = await ids.find_user(S, "email", "a@x.in")
    assert got is not None and got.id == u.id and got.privacy_tier == "adult" and got.locale == "en-IN"
    assert (await ids.find_user(S, "phone", "+919999999999")).id == u.id  # type: ignore[union-attr]
    assert (await ids.find_user(S, "username", "td123456")).id == u.id  # type: ignore[union-attr]
    assert await ids.find_user(S, "email", "nobody@x.in") is None
    assert (await repo.get_profile(u.id)).full_name == "Asha"  # type: ignore[union-attr]
    with pytest.raises(UniqueViolationError):
        await repo.create_user(_user("a@x.in"))
    # two concurrent sign-ups with one new email: exactly one commits
    res = await asyncio.gather(
        *(repo.create_user(_user("race@x.in")) for _ in range(4)), return_exceptions=True
    )
    assert sum(isinstance(r, User) for r in res) == 1
    assert all(isinstance(r, (User, UniqueViolationError)) for r in res)


async def test_contact_change_and_soft_delete_move_reservations(fs: Any) -> None:
    repo = system_repo()
    u = await repo.create_user(_user("old@x.in"))
    u.email = "new@x.in"
    await repo.save_user(u)
    assert await ids.find_user(S, "email", "old@x.in") is None
    assert (await ids.find_user(S, "email", "new@x.in")).id == u.id  # type: ignore[union-attr]
    await repo.create_user(_user("old@x.in"))  # the old address is free again
    with pytest.raises(UniqueViolationError):
        await repo.update_user(u.id, email="old@x.in")
    await repo.update_user(u.id, deleted_at=NOW, status="deleted")
    assert await ids.find_user(S, "email", "new@x.in") is None
    await repo.create_user(_user("new@x.in"))  # partial unique index: deleted rows free it


async def test_passwords(fs: Any) -> None:
    repo = system_repo()
    u = await repo.create_user(_user("p@x.in"))
    await ids.set_password(S, u.id, "correct horse battery", must_change_password=True)
    cred = await ids.get_credential(S, u.id)
    assert cred is not None and await ids.check_password(cred, "correct horse battery")
    assert not await ids.check_password(cred, "wrong")
    assert (await repo.get_user(u.id)).must_change_password is True  # type: ignore[union-attr]
    cred.consecutive_failures = 3
    await repo.save_credential(cred)
    await ids.set_password(S, u.id, "another long passphrase")
    cred2 = await ids.get_credential(S, u.id)
    assert cred2 is not None and cred2.consecutive_failures == 0 and cred2.hard_locked_at is None
    assert await ids.check_password(cred2, "another long passphrase")
    assert (await repo.get_user(u.id)).must_change_password is False  # type: ignore[union-attr]


async def test_consents_latest_wins_and_append_only(fs: Any) -> None:
    u = await system_repo().create_user(_user("c@x.in"))
    await ids.record_consent(S, u.id, "terms", "granted", "v1")
    await asyncio.sleep(0.01)
    await ids.record_consent(S, u.id, "terms", "withdrawn", "v2")
    await ids.record_consent(S, u.id, "marketing_email", "granted", "v1")
    await ids.record_consent(S, u.id, "terms", "granted", "v9", context_ref=uuid.uuid4())  # scoped: ignored
    cur = await ids.current_consents(S, u.id)
    assert list(cur) == ["marketing_email", "terms"]
    assert cur["terms"]["state"] == "withdrawn" and cur["terms"]["notice_version"] == "v2"
    from app.core.firestore.errors import StoreAccessDeniedError

    any_id = (await system_repo().consents_for(u.id))[0].id
    with pytest.raises(StoreAccessDeniedError):
        await fs_store().update("consents", str(any_id), {"action": "x"})


async def test_consent_gate_reads_only_the_required_purposes(fs: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cost: the per-request consent gate (``sessions.hooks.missing_consents``) reads only the
    rows of the three required purposes, with the same answer as the whole ledger; a withdrawal
    is seen on the very next check (nothing is cached across requests)."""
    from app.modules.sessions.hooks import REQUIRED_PURPOSES, missing_consents

    u = await system_repo().create_user(_user("gate@x.in"))
    for p in ("terms", "privacy_notice", "core_service", "marketing_email", "analytics_personalisation"):
        await ids.record_consent(S, u.id, p, "granted", "v1")
    await ids.record_consent(S, u.id, "core_service", "granted", "v9", context_ref=uuid.uuid4())  # scoped: ignored
    full = await ids.current_consents(S, u.id)
    part = await ids.current_consents(S, u.id, REQUIRED_PURPOSES)
    assert part == {k: v for k, v in full.items() if k in REQUIRED_PURPOSES} and list(part) == sorted(part)

    read: list[str] = []
    real = IdentityRepo._objs

    async def spy(self: Any, model: Any, collection: str, **kw: Any) -> Any:
        rows = await real(self, model, collection, **kw)
        if collection == "consents":
            read.extend(r.purpose for r in rows)
        return rows

    monkeypatch.setattr(IdentityRepo, "_objs", spy)
    assert await missing_consents(S, u.id) is None
    assert sorted(read) == sorted(["terms", "privacy_notice", "core_service", "core_service"])
    await asyncio.sleep(0.01)
    await ids.record_consent(S, u.id, "privacy_notice", "withdrawn", "v2")
    assert await missing_consents(S, u.id) == (["privacy_notice"], "current")


def fs_store() -> Any:
    from app.core.firestore.store import ScopedStore

    return ScopedStore.system("test")


async def test_link_token_single_use(fs: Any) -> None:
    u = await system_repo().create_user(_user("l@x.in"))
    raw = await ids.issue_link_token(
        S, user_id=u.id, purpose="email_verify", channel="email", destination="l@x.in", ttl=timedelta(hours=1)
    )
    assert await ids.consume_link_token(S, raw, "other_purpose") is None
    # consume_link_token looks the token up (Postgres: under FOR UPDATE); mark_token_consumed
    # consumes it -- exactly once under concurrency
    toks = await asyncio.gather(*(ids.consume_link_token(S, raw, "email_verify") for _ in range(3)))
    assert all(t is not None and t.user_id == u.id for t in toks)
    claims = await asyncio.gather(*(ids.mark_token_consumed(S, t) for t in toks if t is not None))
    assert sum(claims) == 1
    assert await ids.consume_link_token(S, raw, "email_verify") is None
    expired = await ids.issue_link_token(
        S,
        user_id=u.id,
        purpose="email_verify",
        channel="email",
        destination="l@x.in",
        ttl=timedelta(seconds=-1),
    )
    assert await ids.consume_link_token(S, expired, "email_verify") is None


async def test_otp_flow(fs: Any) -> None:
    u = await system_repo().create_user(_user("o@x.in"))
    first, _first_code = await ids.create_otp(
        S, user_id=u.id, purpose="phone_verify", channel="sms", destination="+919000000000"
    )
    tok, code = await ids.create_otp(
        S, user_id=u.id, purpose="phone_verify", channel="sms", destination="+919000000000"
    )
    old = await system_repo().get_token(first.id)
    assert old is not None and old.expires_at <= datetime.now(UTC)  # earlier OTP expired by the re-issue
    bad = "000000" if code != "000000" else "111111"
    chk = await ids.check_otp(S, purpose="phone_verify", code=bad, user_id=u.id)
    assert not chk.ok and chk.problem is not None and chk.problem.ext.get("attempts_remaining") == 4
    assert (await system_repo().get_token(tok.id)).attempts == 1  # type: ignore[union-attr]
    ok = await ids.check_otp(S, purpose="phone_verify", code=code, user_id=u.id)
    assert ok.ok and ok.token is not None and ok.token.id == tok.id
    again = await ids.check_otp(S, purpose="phone_verify", code=code, user_id=u.id)
    assert not again.ok  # consumed
    # send caps: 3 SMS / hour per number (2 issued above -> one more allowed, then blocked)
    assert await ids.otp_send_allowed(S, "sms", "+919000000000") == 0
    await ids.create_otp(S, user_id=u.id, purpose="phone_verify", channel="sms", destination="+919000000000")
    assert await ids.otp_send_allowed(S, "sms", "+919000000000") > 0


async def test_otp_attempt_limit(fs: Any) -> None:
    sid = uuid.uuid4()
    _tok, code = await ids.create_otp(
        S, user_id=None, auth_session_id=sid, purpose="new_device_otp", channel="email", destination="d@x.in"
    )
    bad = "000000" if code != "000000" else "111111"
    for _ in range(4):
        r = await ids.check_otp(S, purpose="new_device_otp", code=bad, auth_session_id=sid)
        assert r.problem is not None and r.problem.code == "otp_invalid"
    r = await ids.check_otp(S, purpose="new_device_otp", code=bad, auth_session_id=sid)
    assert r.problem is not None and r.problem.code == "otp_attempts_exceeded"
    r = await ids.check_otp(S, purpose="new_device_otp", code=code, auth_session_id=sid)
    assert r.problem is not None and r.problem.code == "otp_attempts_exceeded"


async def test_totp_and_recovery_codes(fs: Any) -> None:
    repo = system_repo()
    u = await repo.create_user(_user("m@x.in"))
    secret = pyotp.random_base32()
    ct, wrapped = encrypt_secret(secret)
    f = MfaFactor(
        id=uuid7(),
        user_id=u.id,
        factor_type="totp",
        totp_secret_encrypted=ct,
        totp_wrapped_key=wrapped,
        totp_confirmed_at=NOW,
    )
    await repo.save_factor(f)
    stored = await repo.get_factor(f.id)
    assert stored is not None and stored.totp_secret_encrypted == ct  # ciphertext unchanged
    assert await ids.has_strong_factor(S, u.id)
    code = pyotp.TOTP(secret).now()
    assert await ids.check_totp_code(S, u.id, code) == "ok"
    assert await ids.check_totp_code(S, u.id, code) == "replayed"
    assert await ids.check_totp_code(S, u.id, "000000" if code != "000000" else "111111") == "invalid"

    pretty, hashes = ids.new_recovery_codes(3)
    await repo.save_factor(
        MfaFactor(id=uuid7(), user_id=u.id, factor_type="recovery_codes", recovery_code_hashes=hashes)
    )
    res = await asyncio.gather(*(ids.verify_recovery_code(S, u.id, pretty[0]) for _ in range(3)))
    assert sum(res) == 1
    assert await ids.verify_recovery_code(S, u.id, pretty[1])
    assert not await ids.verify_recovery_code(S, u.id, "nope-nope")
    f.revoked_at = NOW
    await repo.save_factor(f)
    assert [x.factor_type for x in await ids.active_factors(S, u.id)] == ["recovery_codes"]


async def test_reset_tokens_and_guardian(fs: Any) -> None:
    repo = system_repo()
    u = await repo.create_user(_user("r@x.in"))
    t = PasswordResetToken(
        id=uuid7(), user_id=u.id, token_hash=b"\x09" * 32, expires_at=NOW + timedelta(days=3650)
    )
    await repo.add_reset_token(t)
    assert await repo.reset_tokens_since(u.id, NOW - timedelta(days=1)) >= 0
    assert (await repo.reset_token_by_hash(b"\x09" * 32)).id == t.id  # type: ignore[union-attr]
    claims = await asyncio.gather(*(repo.claim_reset_token(t.id) for _ in range(3)))
    assert sum(claims) == 1
    g1 = GuardianConsent(
        id=uuid7(), child_user_id=u.id, guardian_name="G", relationship="parent", verification_method="otp"
    )
    await repo.save_guardian_consent(g1)
    await asyncio.sleep(0.01)
    g2 = GuardianConsent(
        id=uuid7(), child_user_id=u.id, guardian_name="H", relationship="parent", verification_method="otp"
    )
    await repo.save_guardian_consent(g2)
    assert (await repo.latest_guardian_consent(u.id)).id == g2.id  # type: ignore[union-attr]
    assert (await repo.get_guardian_consent(g1.id)).status == "pending"  # type: ignore[union-attr]


def _pg_rows() -> dict[str, list[dict[str, Any]]]:
    a, b = uuid.UUID(int=1), uuid.UUID(int=2)
    users = [
        {
            **{c: None for c in User.__table__.columns.keys()},
            "id": a,
            "email": "a@x.in",
            "status": "active",
            "is_minor": False,
            "privacy_tier": "adult",
            "restriction_level": 0,
            "must_change_password": False,
            "is_synthetic": True,
            "account_origin": "seed",
            "locale": "en-IN",
            "created_at": NOW,
            "updated_at": NOW,
            "username": "alpha",
        },
        {
            **{c: None for c in User.__table__.columns.keys()},
            "id": b,
            "email": "b@x.in",
            "status": "deleted",
            "is_minor": True,
            "privacy_tier": "minor",
            "restriction_level": 0,
            "must_change_password": False,
            "is_synthetic": True,
            "account_origin": "seed",
            "locale": "en-IN",
            "created_at": NOW,
            "updated_at": NOW,
            "deleted_at": NOW,
        },
    ]
    creds = [
        {
            "user_id": a,
            "password_hash": "h",
            "hash_params_version": 1,
            "password_set_at": NOW,
            "breach_checked_at": None,
            "consecutive_failures": 0,
            "hard_locked_at": None,
            "created_at": NOW,
            "updated_at": NOW,
        }
    ]
    mfa = [
        {
            **{c: None for c in MfaFactor.__table__.columns.keys()},
            "id": uuid.UUID(int=9),
            "user_id": a,
            "factor_type": "totp",
            "totp_secret_encrypted": b"\x01\x02",
            "is_primary": False,
            "created_at": NOW,
        }
    ]
    return {"users": users, "user_credentials": creds, "mfa_factors": mfa}


async def test_backfill_and_verify(fs: Any) -> None:
    from app.core.firestore.backfill import backfill, verify

    live = lambda r: r["deleted_at"] is None  # noqa: E731
    preds = {
        "email IS NOT NULL AND deleted_at IS NULL": lambda r: r["email"] is not None and live(r),
        "phone_e164 IS NOT NULL AND deleted_at IS NULL": lambda r: r["phone_e164"] is not None and live(r),
        "username IS NOT NULL AND deleted_at IS NULL": lambda r: r["username"] is not None and live(r),
    }
    pg = FakePgSession(_pg_rows(), preds)
    written = await backfill(pg, "identity", client=fs)  # type: ignore[arg-type]
    assert written["users"] == 2 and written["users_by_email"] == 1 and written["users_by_username"] == 1
    reports = await verify(pg, "identity", client=fs)  # type: ignore[arg-type]
    assert all(r.ok for r in reports), [r.as_dict() for r in reports if not r.ok]
    # the repository reads the backfilled data
    a = await ids.find_user(S, "email", "a@x.in")
    assert a is not None and a.username == "alpha" and a.privacy_tier == "adult"
    assert await ids.find_user(S, "email", "b@x.in") is None  # deleted row: no reservation
    f = (await system_repo().active_factors(a.id))[0]
    assert f.totp_secret_encrypted == b"\x01\x02"
    # verify detects drift
    await fs_store().run_transaction(lambda tx: tx.update("users", str(a.id), {"status": "suspended"}))
    bad = {r.collection: r for r in await verify(pg, "identity", client=fs)}  # type: ignore[arg-type]
    assert not bad["users"].ok and bad["users"].mismatched == [str(a.id)]
