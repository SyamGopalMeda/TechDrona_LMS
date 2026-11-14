"""Identity tables (database-schema §3). DDL lives in migrations/versions/identity_*.

Emails are stored lower-cased (``citext`` column; the app normalises before every write and
lookup so ``=`` comparisons never depend on the bind type).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    email: Mapped[str | None] = mapped_column(Text)
    email_verified_at: Mapped[datetime | None] = mapped_column(_TS)
    phone_e164: Mapped[str | None] = mapped_column(Text)
    phone_verified_at: Mapped[datetime | None] = mapped_column(_TS)
    # identity_0006: optional sign-in name (lower case [a-z0-9._-]{3,32}), e.g. admissions "td123456"
    username: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending_verification")
    is_minor: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    age_verified_at: Mapped[datetime | None] = mapped_column(_TS)
    age_verification_method: Mapped[str | None] = mapped_column(Text)
    privacy_tier: Mapped[str] = mapped_column(
        Text, Computed("CASE WHEN is_minor THEN 'minor' ELSE 'adult' END", persisted=True)
    )
    restriction_level: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    sessions_valid_after: Mapped[datetime | None] = mapped_column(_TS)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    account_origin: Mapped[str] = mapped_column(Text, nullable=False, server_default="self_signup")
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default="en-IN")
    last_login_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(_TS)

    __mapper_args__ = {"eager_defaults": True}


class UserProfile(Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    full_name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    college_name_text: Mapped[str | None] = mapped_column(Text)
    degree: Mapped[str | None] = mapped_column(Text)
    branch: Mapped[str | None] = mapped_column(Text)
    graduation_year: Mapped[int | None] = mapped_column(SmallInteger)
    city: Mapped[str | None] = mapped_column(Text)
    state_code: Mapped[str | None] = mapped_column(Text)
    target_role: Mapped[str | None] = mapped_column(Text)
    target_company_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default="{}"
    )
    target_date: Mapped[date | None] = mapped_column(Date)
    avatar_s3_key: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, server_default="Asia/Kolkata")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class UserCredential(Base):
    __tablename__ = "user_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    hash_params_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    password_set_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    breach_checked_at: Mapped[datetime | None] = mapped_column(_TS)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    hard_locked_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class MfaFactor(Base):
    __tablename__ = "mfa_factors"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    factor_type: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    totp_secret_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_wrapped_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    totp_last_used_step: Mapped[int | None] = mapped_column(BigInteger)
    totp_confirmed_at: Mapped[datetime | None] = mapped_column(_TS)
    webauthn_credential_id: Mapped[bytes | None] = mapped_column(LargeBinary)
    webauthn_public_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    webauthn_sign_count: Mapped[int | None] = mapped_column(Integer)
    sms_phone_e164: Mapped[str | None] = mapped_column(Text)
    recovery_code_hashes: Mapped[list[bytes] | None] = mapped_column(ARRAY(LargeBinary))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    last_used_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(_TS)


class VerificationToken(Base):
    __tablename__ = "verification_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    destination_hmac: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    auth_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    device_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="5")
    expires_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(_TS)
    created_ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(_TS)
    requested_ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    context_ref: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    notice_version: Mapped[str] = mapped_column(Text, nullable=False)
    notice_locale: Mapped[str] = mapped_column(Text, nullable=False, server_default="en-IN")
    channel: Mapped[str] = mapped_column(Text, nullable=False)
    guardian_consent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ip: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class GuardianConsent(Base):
    __tablename__ = "guardian_consents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    child_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    guardian_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    guardian_name: Mapped[str] = mapped_column(Text, nullable=False)
    guardian_email: Mapped[str | None] = mapped_column(Text)
    guardian_phone_e164: Mapped[str | None] = mapped_column(Text)
    relationship: Mapped[str] = mapped_column(Text, nullable=False)
    verification_method: Mapped[str] = mapped_column(Text, nullable=False)
    verification_ref: Mapped[str | None] = mapped_column(Text)
    evidence_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    verified_at: Mapped[datetime | None] = mapped_column(_TS)
    revoked_at: Mapped[datetime | None] = mapped_column(_TS)
    expires_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
