"""ai tables (migrations ``ai_0001``, ``ai_0002``): platform AI settings (singleton), platform app
toggles, the usage ledger (with reservations) and server-side tutor history.

No prompt text is stored in the ledger; provider API keys live only in server settings / the
secret store (never in these tables). ``ai_tutor_turns`` holds the learner's own tutor chat
(own rows or platform under RLS) and is deleted on erasure.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Integer, Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)


class AISettings(Base):
    """Singleton row ``id = 1``. Every cap is non-NULL (SEC-05)."""

    __tablename__ = "ai_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    model: Mapped[str | None] = mapped_column(Text)  # NULL = platform default model
    monthly_token_cap: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="50000000")
    monthly_call_cap: Mapped[int] = mapped_column(Integer, nullable=False, server_default="50000")
    per_activity_default_cap: Mapped[int] = mapped_column(Integer, nullable=False, server_default="20")
    tutor_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, server_default="10")
    tutor_per_day: Mapped[int] = mapped_column(Integer, nullable=False, server_default="200")
    generate_per_hour: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    generate_per_day: Mapped[int] = mapped_column(Integer, nullable=False, server_default="100")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AppSetting(Base):
    __tablename__ = "app_settings"

    app_key: Mapped[str] = mapped_column(Text, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AIUsage(Base):
    __tablename__ = "ai_usage"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # legacy; NULL now
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    feature: Mapped[str] = mapped_column(Text, nullable=False)
    context_type: Mapped[str | None] = mapped_column(Text)
    context_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    cost_estimate: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, server_default="0")
    outcome: Mapped[str] = mapped_column(Text, nullable=False, server_default="ok")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class TutorTurn(Base):
    __tablename__ = "ai_tutor_turns"

    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    context_type: Mapped[str] = mapped_column(Text, nullable=False)
    context_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    item_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
