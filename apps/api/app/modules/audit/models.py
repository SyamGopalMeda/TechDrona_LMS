"""Audit tables (database-schema.md §13). DDL lives in migrations ``audit_0001``."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, LargeBinary, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class AuditOutbox(Base):
    __tablename__ = "audit_outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.clock_timestamp()
    )
    record: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    __table_args__ = (Index("ix_audit_outbox_time", "occurred_at", "id"),)


class AuditLog(Base):
    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    actor_roles: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    reason_code: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    before_state: Mapped[Any | None] = mapped_column(JSONB)
    after_state: Mapped[Any | None] = mapped_column(JSONB)
    request_id: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(INET)
    prev_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    row_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('user','system','gateway','support_impersonation')", name="actor_type"
        ),
        CheckConstraint("octet_length(prev_hash) = 32", name="prev_hash_len"),
        CheckConstraint("octet_length(row_hash) = 32", name="row_hash_len"),
        Index("ix_audit_target", "target_type", "target_id", "occurred_at"),
        Index("ix_audit_actor", "actor_user_id", "occurred_at"),
        Index("ix_audit_subject", "subject_user_id", "occurred_at"),
        {"postgresql_partition_by": "RANGE (occurred_at)"},
    )
