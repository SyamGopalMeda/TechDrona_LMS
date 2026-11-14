"""Identity erasure provider (DB-01; privacy-and-data-retention §2 D1/D3/D4, §7 ``account_erasure``).

Registered with ``app.modules.admin.privacy.register_erasure_provider("identity", ...)`` from
``app.wiring``. Idempotent: a re-run finds nothing left to erase and reports zero counts.

* ``users``: contact details removed (``ck_users_contact`` allows no contact once ``status =
  'deleted'``), status ``deleted``, ``deleted_at`` set. The row stays as a tombstone so
  legal-hold records (invoices, audit, consents) keep a valid foreign key.
* ``user_profiles``: name replaced by a neutral placeholder; DOB and every other optional
  personal field cleared (DOB reduced to the ``users.is_minor`` age-band flag, D1). The avatar
  object is deleted from the uploads bucket through ``app.modules.media.storage`` first.
* ``user_credentials``, ``mfa_factors``, ``verification_tokens``, ``password_reset_tokens``:
  deleted (no retention basis once the account is gone).
* Legal holds kept in minimal form: ``consents`` (append-only proof ledger, account + 3 years,
  D4) and ``guardian_consents`` (child account + 3 years, D3) are not touched here; they age out
  through the retention jobs.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.identity import clock
from app.modules.identity.models import (
    MfaFactor,
    PasswordResetToken,
    User,
    UserCredential,
    UserProfile,
    VerificationToken,
)


def _count(res: object) -> int:
    return int(getattr(res, "rowcount", 0) or 0)


ERASED_NAME = "Deleted user"


_PROFILE_CLEAR: dict[str, Any] = {
    "display_name": None,
    "date_of_birth": None,
    "college_name_text": None,
    "degree": None,
    "branch": None,
    "graduation_year": None,
    "city": None,
    "state_code": None,
    "target_role": None,
    "target_company_ids": [],
    "target_date": None,
    "avatar_s3_key": None,
}


async def _erase_firestore(user_id: uuid.UUID, avatars: int) -> dict[str, Any]:
    """``TD_STORE_IDENTITY=firestore``: same effect and counts as the SQL below. The user
    tombstone frees its email/phone/username reservations (``save_user``)."""
    from app.modules.identity.repo_firestore import system_repo
    from app.modules.identity.store_specs import MFA, RESETS, VTOKENS

    repo = system_repo("identity.erasure")
    now = clock.now()
    users = 0
    user = await repo.get_user(user_id)
    if user is not None and (
        user.email is not None or user.phone_e164 is not None or user.status != "deleted"
    ):
        user.email = None
        user.email_verified_at = None
        user.phone_e164 = None
        user.phone_verified_at = None
        user.status = "deleted"
        user.deleted_at = now
        user.last_login_at = None
        await repo.save_user(user)
        users = 1
    profiles = 0
    prof = await repo.get_profile(user_id)
    if prof is not None and (
        prof.full_name != ERASED_NAME
        or prof.date_of_birth is not None
        or prof.display_name is not None
        or prof.avatar_s3_key is not None
        or prof.city is not None
        or prof.college_name_text is not None
    ):
        prof.full_name = ERASED_NAME
        for k, v in _PROFILE_CLEAR.items():
            setattr(prof, k, v)
        await repo.save_profile(prof)
        profiles = 1
    deleted: dict[str, int] = {}
    deleted["user_credentials"] = int(await repo.delete_credential(user_id))
    for name, coll in (
        ("mfa_factors", MFA),
        ("verification_tokens", VTOKENS),
        ("password_reset_tokens", RESETS),
    ):
        docs = await repo._all(coll, filters=(("user_id", "==", str(user_id)),))
        for d in docs:
            await repo.store.delete(coll, d.id)
        deleted[name] = len(docs)

    return {
        "users_tombstoned": users,
        "profiles_scrubbed": profiles,
        "deleted": deleted,
        "avatar_objects_deleted": avatars,
        "kept_legal_hold": ["consents", "guardian_consents"],
    }


async def erase_user(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    now = clock.now()
    # The avatar object goes first (core request 7): if storage fails the erasure rolls back
    # with the key still recorded and can be re-run. A missing object is not an error.
    from app.core.firestore.backend import uses_firestore
    from app.modules.media import storage

    if uses_firestore("identity"):
        from app.modules.identity.repo_firestore import system_repo

        prof = await system_repo("identity.erasure").get_profile(user_id)
        avatar = prof.avatar_s3_key if prof is not None else None
        avatars = await storage.delete_objects(storage.storage_settings().S3_BUCKET_UPLOADS, [avatar or ""])
        return await _erase_firestore(user_id, avatars)
    avatar = (
        await session.execute(select(UserProfile.avatar_s3_key).where(UserProfile.user_id == user_id))
    ).scalar_one_or_none()
    avatars = await storage.delete_objects(storage.storage_settings().S3_BUCKET_UPLOADS, [avatar or ""])
    users = _count(
        await session.execute(
            update(User)
            .where(User.id == user_id)
            .where((User.email.is_not(None)) | (User.phone_e164.is_not(None)) | (User.status != "deleted"))
            .values(
                email=None,
                email_verified_at=None,
                phone_e164=None,
                phone_verified_at=None,
                status="deleted",
                deleted_at=now,
                last_login_at=None,
            )
        )
    )
    profiles = _count(
        await session.execute(
            update(UserProfile)
            .where(UserProfile.user_id == user_id)
            .where(
                (UserProfile.full_name != ERASED_NAME)
                | UserProfile.date_of_birth.is_not(None)
                | UserProfile.display_name.is_not(None)
                | UserProfile.avatar_s3_key.is_not(None)
                | UserProfile.city.is_not(None)
                | UserProfile.college_name_text.is_not(None)
            )
            .values(
                full_name=ERASED_NAME,
                display_name=None,
                date_of_birth=None,
                college_name_text=None,
                degree=None,
                branch=None,
                graduation_year=None,
                city=None,
                state_code=None,
                target_role=None,
                target_company_ids=[],
                target_date=None,
                avatar_s3_key=None,
            )
        )
    )
    deleted: dict[str, int] = {}
    for name, model, col in (
        ("user_credentials", UserCredential, UserCredential.user_id),
        ("mfa_factors", MfaFactor, MfaFactor.user_id),
        ("verification_tokens", VerificationToken, VerificationToken.user_id),
        ("password_reset_tokens", PasswordResetToken, PasswordResetToken.user_id),
    ):
        deleted[name] = _count(await session.execute(delete(model).where(col == user_id)))
    await session.flush()
    return {
        "users_tombstoned": users or 0,
        "profiles_scrubbed": profiles or 0,
        "deleted": deleted,
        "avatar_objects_deleted": avatars,
        "kept_legal_hold": ["consents", "guardian_consents"],
    }
