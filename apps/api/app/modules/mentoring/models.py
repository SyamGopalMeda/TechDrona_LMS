"""Mentoring and résumé ORM models (database-schema §8; migration ``mentoring_0001``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_UUID = UUID(as_uuid=True)


class MentorSlot(Base):
    __tablename__ = "mentor_slots"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    mentor_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    starts_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    session_kind: Mapped[str] = mapped_column(Text, nullable=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("companies.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class MentorBooking(Base):
    __tablename__ = "mentor_bookings"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    mentor_slot_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("mentor_slots.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    entitlement_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("entitlements.id"))
    meeting_url: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="booked")
    quota_consumed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    cancelled_at: Mapped[datetime | None] = mapped_column(_TS)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class InterviewFeedback(Base):
    __tablename__ = "interview_feedback"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    mentor_booking_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("mentor_bookings.id"), nullable=False, unique=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    mentor_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    comments: Mapped[str | None] = mapped_column(Text)
    released_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class MentorNote(Base):
    __tablename__ = "mentor_notes"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    student_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    author_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    mentor_booking_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("mentor_bookings.id"))
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class Resume(Base):
    __tablename__ = "resumes"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    template_key: Mapped[str] = mapped_column(Text, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    checklist_score: Mapped[int | None] = mapped_column(SmallInteger)
    pdf_s3_key: Mapped[str | None] = mapped_column(Text)
    pdf_pending_key: Mapped[str | None] = mapped_column(Text)
    pdf_uploaded_at: Mapped[datetime | None] = mapped_column(_TS)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class ResumeReview(Base):
    __tablename__ = "resume_reviews"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    resume_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("resumes.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    entitlement_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("entitlements.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="requested")
    note: Mapped[str | None] = mapped_column(Text)
    comments: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    summary: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(_TS)
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
