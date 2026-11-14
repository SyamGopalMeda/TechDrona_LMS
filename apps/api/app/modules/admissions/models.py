"""Admissions tables (migration ``admissions_0001``). Money is integer paise (ADR-0012).

All four tables are platform-only under RLS (the public routes write under a named system
context; staff with a platform grant read and decide). ``admission_events`` is append-only.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_U = UUID(as_uuid=True)


class CourseStatus(Base):
    """Registration status of one website course (admissions_0003): open / coming_soon / closed."""

    __tablename__ = "course_status"

    course_slug: Mapped[str] = mapped_column(Text, primary_key=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="coming_soon")
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_U, ForeignKey("users.id"))


class AdmissionPaySettings(Base):
    """Site-wide "pay to" details students see (single row, id = 1)."""

    __tablename__ = "admission_pay_settings"

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    phone: Mapped[str | None] = mapped_column(Text)
    preferred_app: Mapped[str] = mapped_column(Text, nullable=False, server_default="PhonePe")
    upi_id: Mapped[str | None] = mapped_column(Text)
    payee_name: Mapped[str | None] = mapped_column(Text)
    instructions: Mapped[str | None] = mapped_column(Text)
    # admissions_0004: open the admission-letter step after enrolling (NULL = not chosen = on)
    letter_step_auto: Mapped[bool | None] = mapped_column(Boolean)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_U)
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AdmissionFeePlan(Base):
    __tablename__ = "admission_fee_plans"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    course_slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    course_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(_U, ForeignKey("batches.id"))
    fee_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    allow_instalments: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    schedule: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    policy: Mapped[str] = mapped_column(Text, nullable=False, server_default="full")
    min_first_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    access_min_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    upi_id: Mapped[str | None] = mapped_column(Text)
    payee_name: Mapped[str | None] = mapped_column(Text)
    bank_details: Mapped[str | None] = mapped_column(Text)
    instructions: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    updated_by: Mapped[uuid.UUID | None] = mapped_column(_U)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AdmissionRegistration(Base):
    __tablename__ = "admission_registrations"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    reg_no: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    fee_plan_id: Mapped[uuid.UUID] = mapped_column(_U, ForeignKey("admission_fee_plans.id"), nullable=False)
    course_slug: Mapped[str] = mapped_column(Text, nullable=False)
    course_title: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)  # normalised lower case
    phone: Mapped[str] = mapped_column(Text, nullable=False)
    college: Mapped[str] = mapped_column(Text, nullable=False)
    branch: Mapped[str] = mapped_column(Text, nullable=False)
    year: Mapped[str] = mapped_column(Text, nullable=False)
    current_status: Mapped[str | None] = mapped_column(Text)
    preferred_mode: Mapped[str | None] = mapped_column(Text)
    message: Mapped[str | None] = mapped_column(Text)
    # money terms, snapshotted from the plan at registration (staff may adjust the fee later)
    fee_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    access_min_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    policy: Mapped[str] = mapped_column(Text, nullable=False)
    allow_instalments: Mapped[bool] = mapped_column(Boolean, nullable=False)
    min_first_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    schedule: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    verified_total_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    balance_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="registered")
    status_note: Mapped[str | None] = mapped_column(Text)
    open_claims: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    resume_key: Mapped[str | None] = mapped_column(Text)
    resume_name: Mapped[str | None] = mapped_column(Text)
    resume_type: Mapped[str | None] = mapped_column(Text)
    resume_size: Mapped[int | None] = mapped_column(Integer)
    consent_text: Mapped[str] = mapped_column(Text, nullable=False)
    consent_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    show_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    marketing_consent_at: Mapped[datetime | None] = mapped_column(_TS)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="website")
    # LMS links (set at enrolment)
    user_id: Mapped[uuid.UUID | None] = mapped_column(_U, ForeignKey("users.id"))
    entitlement_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    enrolment_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    batch_member_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    enrolled_course_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    enrolled_batch_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    enrolled_at: Mapped[datetime | None] = mapped_column(_TS)
    # admissions_0003: when the LMS login email (username + temporary password) last went out
    login_email_sent_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AdmissionPaymentClaim(Base):
    __tablename__ = "admission_payment_claims"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    registration_id: Mapped[uuid.UUID] = mapped_column(
        _U, ForeignKey("admission_registrations.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    method: Mapped[str] = mapped_column(Text, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False)
    utr: Mapped[str | None] = mapped_column(Text)
    paid_on: Mapped[date] = mapped_column(Date, nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
    proof_key: Mapped[str | None] = mapped_column(Text)
    proof_name: Mapped[str | None] = mapped_column(Text)
    proof_type: Mapped[str | None] = mapped_column(Text)
    proof_size: Mapped[int | None] = mapped_column(Integer)
    proof_sha256: Mapped[str | None] = mapped_column(Text)
    proof_original_sha256: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    verified_amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    locks_released: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(_U)
    reviewed_at: Mapped[datetime | None] = mapped_column(_TS)
    review_note: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AdmissionEvent(Base):
    """Append-only trail of every registration, payment and enrolment change."""

    __tablename__ = "admission_events"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    registration_id: Mapped[uuid.UUID | None] = mapped_column(_U, ForeignKey("admission_registrations.id"))
    claim_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    amount_paise: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    actor_label: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
