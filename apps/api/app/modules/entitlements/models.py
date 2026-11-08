"""Entitlements (database-schema §11): the single source of access truth, its append-only
history. (The B2B institution tables and columns were dropped in ``entitlements_0003``.)"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_U = UUID(as_uuid=True)


class Entitlement(Base):
    __tablename__ = "entitlements"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_U, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    product_id: Mapped[uuid.UUID | None] = mapped_column(_U, ForeignKey("products.id"))
    course_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    feature_key: Mapped[str | None] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    order_item_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    coupon_redemption_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(_U)
    grant_reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    starts_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    ends_at: Mapped[datetime | None] = mapped_column(_TS)
    grace_ends_at: Mapped[datetime | None] = mapped_column(_TS)
    mentor_sessions_remaining: Mapped[int | None] = mapped_column(SmallInteger)
    mocks_remaining: Mapped[int | None] = mapped_column(SmallInteger)
    resume_reviews_remaining: Mapped[int | None] = mapped_column(SmallInteger)
    revoked_at: Mapped[datetime | None] = mapped_column(_TS)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(_U)
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class EntitlementEvent(Base):
    __tablename__ = "entitlement_events"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    entitlement_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("entitlements.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(_U, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    from_status: Mapped[str | None] = mapped_column(Text)
    to_status: Mapped[str | None] = mapped_column(Text)
    delta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    reason: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    source_ref: Mapped[uuid.UUID | None] = mapped_column(_U)
    occurred_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
