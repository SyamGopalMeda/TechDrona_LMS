"""Firestore repository of the identity module (``TD_STORE_IDENTITY=firestore``).

``service.py`` dispatches here when the switch is on; the Postgres code path is unchanged.
Rows come back as **transient** ORM instances (``fs_codec.doc_obj``) with the same attribute
types as SQLAlchemy rows. Mutating such an object does not persist anything: the repository's
``save_*`` methods (or the atomic service operations) write it.

Authorization: identity is resolved before a principal exists (sign-up, sign-in, reset links),
so Postgres runs these reads in ``system_context`` ("identity.*" jobs). The repository is built
from the named job ``identity.store`` and every method is ``@platform_only``.

Atomicity (replacing Postgres constraints / ``FOR UPDATE``):

* email / phone / username uniqueness: ``users_by_*`` lookup documents written in the same
  transaction as the user document (``create_user`` / ``save_user``).
* OTP issue: earlier open OTPs of the same binding expire in the same transaction as the insert.
* OTP check / link-token consume: read-check-write in one transaction (single use; the attempt
  counter is persisted even when the code is wrong, as the Postgres caller's commit did).
* TOTP step and recovery-code use: transactional, so one code cannot be accepted twice.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from app.core.errors import ProblemError
from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.repository import platform_only
from app.core.firestore.store import Doc, ScopedTransaction
from app.modules.identity import clock
from app.modules.identity.fs_base import AccessRepo, write_changes
from app.modules.identity.fs_codec import doc_obj, enc_value, obj_doc
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
from app.modules.identity.store_specs import (
    CONSENTS,
    CREDENTIALS,
    GUARDIANS,
    LOOKUPS,
    MFA,
    PROFILES,
    RESETS,
    USERS,
    VTOKENS,
    lookup_id,
    token_expire_at,
)

PERM = "user.read"
JOB = "identity.store"


def _uid(v: Any) -> str | None:
    return str(v) if v is not None else None


def _live_lookups(d: dict[str, Any] | None) -> dict[str, str]:
    """kind -> lookup doc id for the contacts a (live) user document holds."""
    if not d or d.get("deleted_at") is not None:
        return {}
    return {kind: lookup_id(kind, d[col]) for kind, (col, _c) in LOOKUPS.items() if d.get(col)}


def _user_doc(user: User) -> dict[str, Any]:
    d = AccessRepo.new_doc(user)
    d["privacy_tier"] = "minor" if d.get("is_minor") else "adult"
    return d


class IdentityRepo(AccessRepo):
    @classmethod
    def _token_doc(cls, tok: Any) -> dict[str, Any]:
        """Insert document of a token, with the R-TOKEN TTL field ``expire_at``."""
        return {**cls.new_doc(tok), "expire_at": token_expire_at(tok.expires_at)}

    # ------------------------------------------------------------------ users

    @platform_only(PERM)
    async def get_user(self, user_id: uuid.UUID) -> User | None:
        return await self._get_obj(User, USERS, str(user_id))

    @platform_only(PERM)
    async def get_users(self, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, User]:
        docs = await self.store.get_many(USERS, [str(u) for u in user_ids])
        return {uuid.UUID(k): doc_obj(User, d.data) for k, d in docs.items()}

    @platform_only(PERM)
    async def find_user(self, kind: str, value: str) -> User | None:
        """Live user by email / phone / username (``find_user``: ``deleted_at IS NULL``)."""
        if kind not in LOOKUPS or not value:
            return None
        _col, coll = LOOKUPS[kind]
        ref = await self.store.get(coll, lookup_id(kind, value))
        if ref is None:
            return None
        user = await self.get_user(uuid.UUID(ref["user_id"]))
        if user is None or user.deleted_at is not None or getattr(user, LOOKUPS[kind][0]) != value:
            return None
        return user

    async def _tx_write_user(
        self, tx: ScopedTransaction, user: User, current: Doc | None, profile: UserProfile | None = None
    ) -> Doc:
        uid = str(user.id)
        new = (
            _user_doc(user)
            if current is None
            else {**_user_doc(user), "created_at": current.get("created_at")}
        )
        old_l, new_l = _live_lookups(current.data if current else None), _live_lookups(new)
        # reads first (Firestore: all reads before writes)
        held: dict[str, Doc | None] = {}
        for kind, lid in new_l.items():
            if old_l.get(kind) != lid:
                held[kind] = await tx.get(LOOKUPS[kind][1], lid)
                if held[kind] is not None and held[kind]["user_id"] != uid:  # type: ignore[index]
                    raise UniqueViolationError(LOOKUPS[kind][1], lid)
        prof_cur = await tx.get(PROFILES, uid) if profile is not None else None
        stale = {k: lid for k, lid in old_l.items() if new_l.get(k) != lid}
        stale_docs = {k: await tx.get(LOOKUPS[k][1], lid) for k, lid in stale.items()}
        # writes
        for kind, lid in stale.items():
            d = stale_docs[kind]
            if d is not None and d["user_id"] == uid:
                await tx.delete_read(LOOKUPS[kind][1], lid, d.data)
        for kind in held:
            if held[kind] is None:
                await tx.create(LOOKUPS[kind][1], {"user_id": uid}, doc_id=new_l[kind])
        if current is None:
            doc = await tx.create(USERS, new, doc_id=uid)
        else:
            doc = await tx.update_read(USERS, current, write_changes(new))
        if profile is not None:
            await self._tx_upsert(tx, PROFILES, uid, profile, prof_cur)
        return doc

    @platform_only(PERM)
    async def create_user(self, user: User, profile: UserProfile | None = None) -> User:
        """Insert a user (+ profile) atomically with its email/phone/username reservations.

        ``UniqueViolationError`` when a live account already holds one of them."""

        async def fn(tx: ScopedTransaction) -> Doc:
            if await tx.get(USERS, str(user.id)) is not None:
                raise UniqueViolationError(USERS, str(user.id))
            return await self._tx_write_user(tx, user, None, profile)

        return doc_obj(User, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def save_user(self, user: User) -> User:
        """Persist every attribute of ``user``; contact changes move the uniqueness reservations
        (a soft delete frees them, like the partial unique indexes)."""

        async def fn(tx: ScopedTransaction) -> Doc:
            cur = await tx.get(USERS, str(user.id))
            return await self._tx_write_user(tx, user, cur)

        return doc_obj(User, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def update_user(self, user_id: uuid.UUID, **changes: Any) -> User:
        user = await self.get_user(user_id)
        if user is None:
            raise ProblemError("not_found")
        for k, v in changes.items():
            setattr(user, k, v)
        return await self.save_user(user)

    @platform_only(PERM)
    async def get_profile(self, user_id: uuid.UUID) -> UserProfile | None:
        return await self._get_obj(UserProfile, PROFILES, str(user_id))

    @platform_only(PERM)
    async def save_profile(self, profile: UserProfile) -> UserProfile:
        return await self._upsert(PROFILES, str(profile.user_id), profile)

    # ------------------------------------------------------------------ credentials

    @platform_only(PERM)
    async def get_credential(self, user_id: uuid.UUID) -> UserCredential | None:
        return await self._get_obj(UserCredential, CREDENTIALS, str(user_id))

    @platform_only(PERM)
    async def save_credential(self, cred: UserCredential) -> UserCredential:
        return await self._upsert(CREDENTIALS, str(cred.user_id), cred)

    @platform_only(PERM)
    async def set_password(self, user_id: uuid.UUID, pw_hash: str, *, must_change_password: bool) -> None:
        """``service.set_password``: credential upsert + ``users.must_change_password``, atomically."""
        uid = str(user_id)

        async def fn(tx: ScopedTransaction) -> None:
            cur = await tx.get(CREDENTIALS, uid)
            user = await tx.get(USERS, uid)
            now = clock.now()
            if cur is None:
                cred = UserCredential(
                    user_id=user_id, password_hash=pw_hash, password_set_at=now, breach_checked_at=now
                )
            else:
                cred = doc_obj(UserCredential, cur.data)
                cred.password_hash = pw_hash
                cred.password_set_at = now
                cred.breach_checked_at = now
                cred.consecutive_failures = 0
                cred.hard_locked_at = None
            await self._tx_upsert(tx, CREDENTIALS, uid, cred, cur)
            if user is not None and bool(user.get("must_change_password")) != must_change_password:
                await tx.update_read(USERS, user, {"must_change_password": must_change_password})

        await self.store.run_transaction(fn)

    # ------------------------------------------------------------------ consents

    @platform_only(PERM)
    async def consents_for(self, user_id: uuid.UUID) -> list[Consent]:
        return await self._objs(Consent, CONSENTS, user_id=user_id)

    async def _consent_rows(self, user_id: uuid.UUID, purposes: tuple[str, ...]) -> list[Consent]:
        """The user's consent rows of ``purposes`` only (equality + ``in``: no composite index).
        Falls back to the whole ledger if the project refuses the query (missing index), so the
        answer never changes."""
        from google.api_core import exceptions as gexc

        try:
            return await self._objs(
                Consent, CONSENTS, user_id=user_id, filters=(("purpose", "in", list(purposes)),)
            )
        except gexc.FailedPrecondition:
            import structlog

            structlog.get_logger("identity.store").warning("consent_purpose_query_unavailable")
            return [c for c in await self.consents_for(user_id) if c.purpose in purposes]

    @platform_only(PERM)
    async def current_consents(
        self, user_id: uuid.UUID, purposes: tuple[str, ...] | None = None
    ) -> dict[str, dict[str, Any]]:
        """``purposes``: only these purposes (the per-request consent gate needs three of them;
        reading only their rows bills fewer documents than the user's whole consent ledger)."""
        ledger = await self._consent_rows(user_id, purposes) if purposes else await self.consents_for(user_id)
        rows = [c for c in ledger if c.context_ref is None and c.organization_id is None]
        # Postgres: ORDER BY purpose, created_at DESC, id DESC; first row per purpose wins
        rows.sort(key=lambda c: (c.created_at, str(c.id)), reverse=True)
        out: dict[str, dict[str, Any]] = {}
        for c in rows:
            if c.purpose not in out:
                out[c.purpose] = {
                    "state": c.action,
                    "notice_version": c.notice_version,
                    "effective_at": c.created_at,
                }
        from app.modules.identity.textsort import text_key

        # Postgres: ORDER BY purpose (database collation)
        return dict(sorted(out.items(), key=lambda kv: text_key(kv[0])))

    @platform_only(PERM)
    async def add_consent(self, consent: Consent) -> Consent:
        d = await self.store.create(CONSENTS, self.new_doc(consent), doc_id=str(consent.id))
        return doc_obj(Consent, d.data)

    @platform_only(PERM)
    async def get_consent(self, consent_id: uuid.UUID) -> Consent | None:
        return await self._get_obj(Consent, CONSENTS, str(consent_id))

    # ------------------------------------------------------------------ guardian consents

    @platform_only(PERM)
    async def save_guardian_consent(self, gc: GuardianConsent) -> GuardianConsent:
        return await self._upsert(GUARDIANS, str(gc.id), gc)

    @platform_only(PERM)
    async def get_guardian_consent(self, consent_id: uuid.UUID) -> GuardianConsent | None:
        return await self._get_obj(GuardianConsent, GUARDIANS, str(consent_id))

    @platform_only(PERM)
    async def latest_guardian_consent(self, user_id: uuid.UUID) -> GuardianConsent | None:
        """Newest guardian consent of a child (``ORDER BY created_at DESC LIMIT 1``)."""
        rows = await self._objs(GuardianConsent, GUARDIANS, user_id=user_id)
        return max(rows, key=lambda g: (g.created_at, str(g.id)), default=None)

    # ------------------------------------------------------------------ verification tokens / OTP

    @platform_only(PERM)
    async def add_token(self, tok: VerificationToken) -> VerificationToken:
        d = await self.store.create(VTOKENS, self._token_doc(tok), doc_id=str(tok.id))
        return doc_obj(VerificationToken, d.data)

    @platform_only(PERM)
    async def get_token(self, token_id: uuid.UUID) -> VerificationToken | None:
        return await self._get_obj(VerificationToken, VTOKENS, str(token_id))

    @platform_only(PERM)
    async def save_token(self, tok: VerificationToken) -> VerificationToken:
        return await self._upsert(VTOKENS, str(tok.id), tok)

    @platform_only(PERM)
    async def token_times_since(self, destination_hmac: bytes, since: datetime) -> list[datetime]:
        """``created_at`` of every token sent to a destination after ``since`` (OTP send caps)."""
        docs = await self._all(
            VTOKENS,
            filters=(("destination_hmac", "==", destination_hmac.hex()), ("created_at", ">", since)),
            order_by=(("created_at", "asc"),),
        )
        return [d["created_at"] for d in docs]

    @platform_only(PERM)
    async def create_otp(self, tok: VerificationToken) -> VerificationToken:
        """Expire the binding's open OTPs (same purpose, user and auth session) and insert ``tok``."""
        now = clock.now()

        async def fn(tx: ScopedTransaction) -> Doc:
            open_ = await tx.query(
                VTOKENS, filters=(("purpose", "==", tok.purpose), ("consumed_at", "==", None))
            )
            for d in open_:
                if (
                    d.get("user_id") == _uid(tok.user_id)
                    and d.get("auth_session_id") == _uid(tok.auth_session_id)
                    and d["expires_at"] > now
                ):
                    await tx.update_read(VTOKENS, d, {"expires_at": now, "expire_at": token_expire_at(now)})
            return await tx.create(VTOKENS, self._token_doc(tok), doc_id=str(tok.id))

        return doc_obj(VerificationToken, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def check_otp(
        self,
        *,
        purpose: str,
        code: str,
        digest: Callable[[uuid.UUID, str], bytes],
        user_id: uuid.UUID | None = None,
        auth_session_id: uuid.UUID | None = None,
    ) -> tuple[bool, ProblemError | None, VerificationToken | None]:
        """``service.check_otp`` in one transaction (latest open OTP of the binding)."""
        now = clock.now()
        filters: list[Any] = [("purpose", "==", purpose), ("consumed_at", "==", None)]
        if user_id is not None:
            filters.append(("user_id", "==", str(user_id)))
        if auth_session_id is not None:
            filters.append(("auth_session_id", "==", str(auth_session_id)))

        async def fn(tx: ScopedTransaction) -> tuple[bool, ProblemError | None, VerificationToken | None]:
            docs = await tx.query(VTOKENS, filters=tuple(filters))
            if not docs:
                return False, ProblemError("otp_expired", attempts_remaining=0), None
            cur = max(docs, key=lambda d: (d["created_at"], d.id))
            tok = doc_obj(VerificationToken, cur.data)
            if tok.expires_at <= now:
                return False, ProblemError("otp_expired", attempts_remaining=0), tok
            if tok.attempts >= tok.max_attempts:
                return False, ProblemError("otp_attempts_exceeded"), tok
            if digest(tok.id, (code or "").strip()) != tok.token_hash:
                tok.attempts += 1
                await tx.update_read(VTOKENS, cur, {"attempts": tok.attempts})
                remaining = tok.max_attempts - tok.attempts
                if remaining <= 0:
                    return False, ProblemError("otp_attempts_exceeded"), tok
                return False, ProblemError("otp_invalid", attempts_remaining=remaining), tok
            tok.consumed_at = now
            await tx.update_read(VTOKENS, cur, {"consumed_at": now})
            return True, None, tok

        return await self.store.run_transaction(fn)

    @platform_only(PERM)
    async def claim_link_token(self, token_hash: bytes, purpose: str) -> VerificationToken | None:
        """Single-use link token: valid -> marked consumed in the same transaction and returned
        (as it was before the claim, so callers see the Postgres ``consume_link_token`` result)."""
        now = clock.now()

        async def fn(tx: ScopedTransaction) -> VerificationToken | None:
            docs = await tx.query(
                VTOKENS, filters=(("token_hash", "==", token_hash.hex()), ("purpose", "==", purpose))
            )
            if not docs:
                return None
            cur = docs[0]
            tok = doc_obj(VerificationToken, cur.data)
            if tok.consumed_at is not None or tok.expires_at <= now:
                return None
            await tx.update_read(VTOKENS, cur, {"consumed_at": now})
            return tok

        return await self.store.run_transaction(fn)

    @platform_only(PERM)
    async def link_token(self, token_hash: bytes, purpose: str) -> VerificationToken | None:
        """A valid (unconsumed, unexpired) link token by hash, without consuming it."""
        docs = await self._all(
            VTOKENS, filters=(("token_hash", "==", token_hash.hex()), ("purpose", "==", purpose))
        )
        if not docs:
            return None
        tok = doc_obj(VerificationToken, docs[0].data)
        if tok.consumed_at is not None or tok.expires_at <= clock.now():
            return None
        return tok

    @platform_only(PERM)
    async def delete_credential(self, user_id: uuid.UUID) -> bool:
        if await self.store.get(CREDENTIALS, str(user_id)) is None:
            return False
        await self.store.delete(CREDENTIALS, str(user_id))
        return True

    # ------------------------------------------------------------------ password reset tokens

    @platform_only(PERM)
    async def add_reset_token(self, tok: PasswordResetToken) -> PasswordResetToken:
        d = await self.store.create(RESETS, self._token_doc(tok), doc_id=str(tok.id))
        return doc_obj(PasswordResetToken, d.data)

    @platform_only(PERM)
    async def reset_tokens_since(self, user_id: uuid.UUID, since: datetime) -> int:
        docs = await self._all(RESETS, filters=(("user_id", "==", str(user_id)),))
        return sum(1 for d in docs if d["created_at"] > since)

    @platform_only(PERM)
    async def reset_token_by_hash(self, token_hash: bytes) -> PasswordResetToken | None:
        docs = await self._all(RESETS, filters=(("token_hash", "==", token_hash.hex()),))
        return doc_obj(PasswordResetToken, docs[0].data) if docs else None

    @platform_only(PERM)
    async def claim_reset_token(self, token_id: uuid.UUID) -> bool:
        """Mark a reset token consumed unless it already is (single use under concurrency)."""
        now = clock.now()

        async def fn(tx: ScopedTransaction) -> bool:
            cur = await tx.get(RESETS, str(token_id))
            if cur is None or cur.get("consumed_at") is not None or cur["expires_at"] <= now:
                return False
            await tx.update_read(RESETS, cur, {"consumed_at": now})
            return True

        return await self.store.run_transaction(fn)

    @platform_only(PERM)
    async def get_reset_token(self, token_id: uuid.UUID) -> PasswordResetToken | None:
        return await self._get_obj(PasswordResetToken, RESETS, str(token_id))

    @platform_only(PERM)
    async def save_reset_token(self, tok: PasswordResetToken) -> PasswordResetToken:
        return await self._upsert(RESETS, str(tok.id), tok)

    # ------------------------------------------------------------------ MFA factors

    @platform_only(PERM)
    async def active_factors(self, user_id: uuid.UUID) -> list[MfaFactor]:
        rows = await self._objs(
            MfaFactor, MFA, filters=(("user_id", "==", str(user_id)), ("revoked_at", "==", None))
        )
        return sorted(rows, key=lambda f: (f.created_at, str(f.id)))

    @platform_only(PERM)
    async def all_factors(self, user_id: uuid.UUID) -> list[MfaFactor]:
        rows = await self._objs(MfaFactor, MFA, filters=(("user_id", "==", str(user_id)),))
        return sorted(rows, key=lambda f: (f.created_at, str(f.id)))

    @platform_only(PERM)
    async def get_factor(self, factor_id: uuid.UUID) -> MfaFactor | None:
        return await self._get_obj(MfaFactor, MFA, str(factor_id))

    @platform_only(PERM)
    async def save_factor(self, f: MfaFactor) -> MfaFactor:
        return await self._upsert(MFA, str(f.id), f)

    @platform_only(PERM)
    async def find_factor_by_webauthn(self, credential_id: bytes) -> MfaFactor | None:
        docs = await self._all(MFA, filters=(("webauthn_credential_id", "==", credential_id.hex()),))
        return doc_obj(MfaFactor, docs[0].data) if docs else None

    @platform_only(PERM)
    async def use_totp_step(self, factor_id: uuid.UUID, step: int) -> bool:
        """Record a TOTP step as used; False if the step (or a later one) was used meanwhile."""
        fid = str(factor_id)

        async def fn(tx: ScopedTransaction) -> bool:
            cur = await tx.get(MFA, fid)
            if cur is None or cur.get("revoked_at") is not None:
                return False
            last = cur.get("totp_last_used_step")
            if last is not None and int(last) >= step:
                return False
            await tx.update_read(MFA, cur, {"totp_last_used_step": step, "last_used_at": clock.now()})
            return True

        return await self.store.run_transaction(fn)

    @platform_only(PERM)
    async def use_recovery_code(self, user_id: uuid.UUID, digest: bytes) -> bool:
        """Remove ``digest`` from the user's active recovery-code factor (single use)."""
        hexd = digest.hex()
        ids = [str(f.id) for f in await self.active_factors(user_id) if f.factor_type == "recovery_codes"]

        async def fn(tx: ScopedTransaction) -> bool:
            docs = await tx.get_many(MFA, ids)
            for fid in ids:
                cur = docs.get(fid)
                if cur is None or cur.get("revoked_at") is not None:
                    continue
                hashes = list(cur.get("recovery_code_hashes") or [])
                if hexd in hashes:
                    await tx.update_read(
                        MFA,
                        cur,
                        {
                            "recovery_code_hashes": [h for h in hashes if h != hexd],
                            "last_used_at": clock.now(),
                        },
                    )
                    return True
            return False

        return await self.store.run_transaction(fn)

    # ------------------------------------------------------------------ helpers for callers

    @staticmethod
    def doc_of(obj: Any) -> dict[str, Any]:
        return obj_doc(obj)

    @staticmethod
    def enc(model: type, attr: str, v: Any) -> Any:
        return enc_value(model, attr, v)


def system_repo(job: str = JOB) -> IdentityRepo:
    from app.modules.identity.fs_journal import JournalingStore

    return IdentityRepo(JournalingStore.system(job))


def window_start(hours: int = 0, days: int = 0) -> datetime:
    return clock.now() - timedelta(hours=hours, days=days)
