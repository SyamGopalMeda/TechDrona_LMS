"""Admin tables (database-schema §13, §13.1; migrations admin_0001..admin_0004).

Single company (admin_0004): no per-org policy layer (``org_overridable`` dropped) and no
feature-flag org allowlist."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, Interval, LargeBinary, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_UUID = UUID(as_uuid=True)


class PolicySetting(Base):
    __tablename__ = "policy_settings"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    setting_key: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    value_schema: Mapped[str] = mapped_column(Text, nullable=False)
    min_value: Mapped[Any] = mapped_column(JSONB)
    max_value: Mapped[Any] = mapped_column(JSONB)
    plan_overridable: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    locked: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    effective_from: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(_TS)
    case_decision_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    change_reason: Mapped[str] = mapped_column(Text, nullable=False)
    changed_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    flag_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    rollout_percent: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    user_allowlist: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(_UUID), nullable=False, server_default="{}")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class PrivacyRequest(Base):
    __tablename__ = "privacy_requests"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    request_ref: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    requester_relationship: Mapped[str] = mapped_column(Text, nullable=False, server_default="self")
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    request_type: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="received")
    details: Mapped[str | None] = mapped_column(Text)
    identity_verification_method: Mapped[str | None] = mapped_column(Text)
    identity_verified_at: Mapped[datetime | None] = mapped_column(_TS)
    received_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    due_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    cooling_off_until: Mapped[datetime | None] = mapped_column(_TS)
    completed_at: Mapped[datetime | None] = mapped_column(_TS)
    response_summary: Mapped[str | None] = mapped_column(Text)
    export_job_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    export_payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    legal_hold: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    idempotency_key: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    data_category: Mapped[str] = mapped_column(Text, nullable=False)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    retention_class: Mapped[str] = mapped_column(Text, nullable=False)
    retention_interval: Mapped[timedelta | None] = mapped_column(Interval)
    basis: Mapped[str] = mapped_column(Text, nullable=False)
    deletion_method: Mapped[str] = mapped_column(Text, nullable=False)
    legal_hold_aware: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    job_name: Mapped[str] = mapped_column(Text, nullable=False)
    owner_module: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class BreakGlassSession(Base):
    __tablename__ = "break_glass_sessions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    elevated_role: Mapped[str] = mapped_column(Text, nullable=False, server_default="super_admin")
    role_grant_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    started_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(_TS)
    end_reason: Mapped[str | None] = mapped_column(Text)
    ended_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    review_due_at: Mapped[datetime | None] = mapped_column(_TS)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    reviewed_at: Mapped[datetime | None] = mapped_column(_TS)
    review_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class ErasureLedger(Base):
    """Append-only record of executed erasures (CCP-P1; admin_0003). Stores ``subject_hash``,
    never the user id, so restores can re-apply deletions."""

    __tablename__ = "erasure_ledger"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    privacy_request_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    subject_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    erased_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    pending_modules: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
