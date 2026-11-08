"""Engage ORM models (migrations ``engage_0001``, ``engage_0002``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ARRAY, Boolean, DateTime, ForeignKey, Integer, SmallInteger, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_UUID = UUID(as_uuid=True)


class EngageActivity(Base):
    __tablename__ = "engage_activities"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("batches.id"))
    owner_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    activity_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    run_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="instant")
    audience: Mapped[str] = mapped_column(Text, nullable=False, server_default="members")
    identity_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="named")
    results_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="live")
    pacing: Mapped[str] = mapped_column(Text, nullable=False, server_default="all_at_once")
    winner_rule: Mapped[str | None] = mapped_column(Text)
    participant_limit: Mapped[int | None] = mapped_column(Integer)
    opens_at: Mapped[datetime | None] = mapped_column(_TS)
    closes_at: Mapped[datetime | None] = mapped_column(_TS)
    deleted_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class EngageQuestion(Base):
    __tablename__ = "engage_questions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    activity_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("engage_activities.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    max_words: Mapped[int | None] = mapped_column(SmallInteger)
    source_question_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class EngageRun(Base):
    __tablename__ = "engage_runs"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    activity_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("engage_activities.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    run_no: Mapped[int] = mapped_column(Integer, nullable=False)
    join_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="scheduled")
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    questions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    current_position: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    revealed_positions: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), nullable=False, server_default="{}"
    )
    # SEC-06: positions ever revealed; they stay closed for answering after a "hide" (engage_0002).
    closed_positions: Mapped[list[int]] = mapped_column(
        ARRAY(SmallInteger), nullable=False, server_default="{}"
    )
    results_published: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    opens_at: Mapped[datetime | None] = mapped_column(_TS)
    closes_at: Mapped[datetime | None] = mapped_column(_TS)
    opened_at: Mapped[datetime | None] = mapped_column(_TS)
    closed_at: Mapped[datetime | None] = mapped_column(_TS)
    finalised_at: Mapped[datetime | None] = mapped_column(_TS)
    created_by: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class EngageParticipant(Base):
    __tablename__ = "engage_participants"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("engage_runs.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class EngageResponse(Base):
    __tablename__ = "engage_responses"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("engage_runs.id", ondelete="CASCADE"), nullable=False
    )
    participant_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("engage_participants.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    question_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    answer: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    terms: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    filtered: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    answered_at: Mapped[datetime] = mapped_column(
        _TS, nullable=False, server_default=text("clock_timestamp()")
    )
