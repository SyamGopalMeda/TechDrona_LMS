"""Firestore collections of the identity module (``TD_STORE_IDENTITY=firestore``).

Data model (docs/firebase/agents/data-access.md §identity). Document ids keep the Postgres
primary keys; every column is stored under its attribute name through ``fs_codec`` (bytes as
hex, UUIDs as strings), so the repository and the backfill share one mapper per table.

* ``users/{id}``                 users row (incl. the computed ``privacy_tier``)
* ``user_profiles/{user_id}``    user_profiles row
* ``user_credentials/{user_id}`` password hash etc. (system family: never read by a principal store)
* ``mfa_factors/{id}``           TOTP ciphertext + wrapped key exactly as in Postgres (hex)
* ``consents/{id}``              append-only (Postgres ``revoke_app_writes``)
* ``guardian_consents/{id}``     owned by ``child_user_id``
* ``verification_tokens/{id}``   looked up by ``token_hash`` / ``destination_hmac`` (hex fields)
* ``password_reset_tokens/{id}`` looked up by ``token_hash``
* ``users_by_email/{sha256}``, ``users_by_phone/{sha256}``, ``users_by_username/{sha256}``
  ``{user_id}``: the partial unique indexes ``ux_users_email`` / ``ux_users_phone`` /
  ``ux_users_username`` (live rows only: ``deleted_at IS NULL``). Created/deleted in the same
  transaction as the user document, so two signups with one email cannot both commit.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import hashed_id
from app.modules.identity.fs_codec import row_doc
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

USERS = "users"
PROFILES = "user_profiles"
CREDENTIALS = "user_credentials"
MFA = "mfa_factors"
CONSENTS = "consents"
GUARDIANS = "guardian_consents"
VTOKENS = "verification_tokens"
RESETS = "password_reset_tokens"
BY_EMAIL = "users_by_email"
BY_PHONE = "users_by_phone"
BY_USERNAME = "users_by_username"

# contact kind -> (users column, lookup collection)
LOOKUPS: dict[str, tuple[str, str]] = {
    "email": ("email", BY_EMAIL),
    "phone": ("phone_e164", BY_PHONE),
    "username": ("username", BY_USERNAME),
}

register_collection(
    CollectionSpec(
        USERS, "owned", owner_field="id", read_permission="user.read", write_permission="user.deactivate"
    )
)
register_collection(
    CollectionSpec(PROFILES, "owned", read_permission="user.read", write_permission="user.legal_name.change")
)
register_collection(CollectionSpec(CREDENTIALS, "system"))
register_collection(CollectionSpec(MFA, "system"))
register_collection(CollectionSpec(CONSENTS, "owned", read_permission="user.read", append_only=True))
register_collection(
    CollectionSpec(GUARDIANS, "owned", owner_field="child_user_id", read_permission="user.read")
)
register_collection(CollectionSpec(VTOKENS, "system"))
register_collection(CollectionSpec(RESETS, "system"))
for _c in (BY_EMAIL, BY_PHONE, BY_USERNAME):
    register_collection(CollectionSpec(_c, "system"))


# R-TOKEN (database-schema §1.4): tokens are deleted 7 days after expiry. ``expire_at`` is the
# Firestore TTL field (policy declared in firestore.indexes.fragment.json).
TOKEN_RETENTION = timedelta(days=7)


def token_expire_at(expires_at: datetime | None) -> datetime | None:
    return expires_at + TOKEN_RETENTION if expires_at is not None else None


def token_doc(model: type, r: Row) -> dict[str, Any]:
    d = row_doc(model, r)
    d["expire_at"] = token_expire_at(r.get("expires_at"))
    return d


def lookup_id(kind: str, value: str) -> str:
    return hashed_id(kind, value)


def user_doc(r: Row) -> dict[str, Any]:
    d = row_doc(User, r)
    d["privacy_tier"] = "minor" if d.get("is_minor") else "adult"
    return d


def _by(kind: str) -> TableMapping:
    col, coll = LOOKUPS[kind]
    return TableMapping(
        "identity",
        "users",
        coll,
        lambda r: lookup_id(kind, r[col]),
        lambda r: {"user_id": str(r["id"])},
        where=f"{col} IS NOT NULL AND deleted_at IS NULL",
    )


register_mapping(TableMapping("identity", "users", USERS, lambda r: str(r["id"]), user_doc))
for _kind in LOOKUPS:
    register_mapping(_by(_kind))
register_mapping(
    TableMapping(
        "identity",
        "user_profiles",
        PROFILES,
        lambda r: str(r["user_id"]),
        lambda r: row_doc(UserProfile, r),
        order_by="user_id",
    )
)
register_mapping(
    TableMapping(
        "identity",
        "user_credentials",
        CREDENTIALS,
        lambda r: str(r["user_id"]),
        lambda r: row_doc(UserCredential, r),
        order_by="user_id",
    )
)
for _model, _coll in (
    (MfaFactor, MFA),
    (Consent, CONSENTS),
    (GuardianConsent, GUARDIANS),
):
    register_mapping(
        TableMapping(
            "identity",
            _model.__tablename__,
            _coll,
            lambda r: str(r["id"]),
            (lambda m: lambda r: row_doc(m, r))(_model),
        )
    )
for _tmodel, _tcoll in ((VerificationToken, VTOKENS), (PasswordResetToken, RESETS)):
    register_mapping(
        TableMapping(
            "identity",
            _tmodel.__tablename__,
            _tcoll,
            lambda r: str(r["id"]),
            (lambda m: lambda r: token_doc(m, r))(_tmodel),
        )
    )
