"""Learning: enrolments, lesson progress, assignments, submissions, certificates
(database-schema §7; migration ``learning_0001``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, REAL, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_UUID = UUID(as_uuid=True)


class Enrolment(Base):
    __tablename__ = "enrolments"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    # No ForeignKey into the catalog: the catalog may live in Firestore (learning_0004).
    course_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    course_version_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    batch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("batches.id"))
    source: Mapped[str] = mapped_column(Text, nullable=False)
    entitlement_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    enrolled_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(_TS)
    expires_at: Mapped[datetime | None] = mapped_column(_TS)
    progress_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    last_activity_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class LessonProgress(Base):
    __tablename__ = "lesson_progress"

    enrolment_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("enrolments.id", ondelete="CASCADE"), primary_key=True
    )
    lesson_key: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="not_started")
    progress_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    video_position_s: Mapped[int | None] = mapped_column(Integer)
    watched_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    watched_intervals: Mapped[list[list[int]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    first_opened_at: Mapped[datetime | None] = mapped_column(_TS)
    completed_at: Mapped[datetime | None] = mapped_column(_TS)
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    course_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)  # catalog: no FK (learning_0004)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("batches.id"))
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    instructions_md: Mapped[str] = mapped_column(Text, nullable=False)
    submission_type: Mapped[str] = mapped_column(Text, nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    rubric: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ai_help_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    ai_help_limit: Mapped[int | None] = mapped_column(Integer)
    allowed_file_types: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    available_from: Mapped[datetime | None] = mapped_column(_TS)
    due_at: Mapped[datetime | None] = mapped_column(_TS)
    late_until: Mapped[datetime | None] = mapped_column(_TS)
    late_penalty_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    grades_released_at: Mapped[datetime | None] = mapped_column(_TS)
    created_by: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AssignmentSubmission(Base):
    __tablename__ = "assignment_submissions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("assignments.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    attempt_no: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    body_text: Mapped[str | None] = mapped_column(Text)
    link_url: Mapped[str | None] = mapped_column(Text)
    file_s3_keys: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    code_submission_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    allocation_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("assignment_allocations.id"))
    ai_help_used: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="submitted")
    submitted_at: Mapped[datetime | None] = mapped_column(_TS)
    score: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    raw_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    late_penalty_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    rubric_scores: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    feedback_md: Mapped[str | None] = mapped_column(Text)
    returned_reason: Mapped[str | None] = mapped_column(Text)
    graded_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    graded_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    public_code: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    # No ForeignKey into the catalog: the catalog may live in Firestore (learning_0004).
    course_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    course_version_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    enrolment_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("enrolments.id"), nullable=False)
    name_on_certificate: Mapped[str] = mapped_column(Text, nullable=False)
    identity_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    final_attempt_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    issue_source: Mapped[str] = mapped_column(Text, nullable=False, server_default="rule")
    template_version: Mapped[str] = mapped_column(Text, nullable=False)
    pdf_s3_key: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(_TS)
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


# --------------------------------------------------------------------------- structured assignments
# (migration ``learning_0003``; WISEMAN-FEATURES build "assign")


class AssignmentSection(Base):
    __tablename__ = "assignment_sections"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    max_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AssignmentItem(Base):
    __tablename__ = "assignment_items"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    section_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("assignment_sections.id", ondelete="CASCADE"), nullable=False
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    question_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    question_version_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    coding_problem_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    prompt_md: Mapped[str | None] = mapped_column(Text)
    marks: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False, server_default="0")
    rubric: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reference_answer_md: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AssignmentAllocation(Base):
    __tablename__ = "assignment_allocations"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("organizations.id"), nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("batches.id"))
    user_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(_UUID), nullable=False, server_default="{}")
    visible_from: Mapped[datetime | None] = mapped_column(_TS)
    visible_until: Mapped[datetime | None] = mapped_column(_TS)
    start_at: Mapped[datetime | None] = mapped_column(_TS)
    due_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    section_engines: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    evaluator_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(_UUID), nullable=False, server_default="{}")
    extensions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_by: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AssignmentItemResponse(Base):
    __tablename__ = "assignment_item_responses"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("assignment_submissions.id", ondelete="CASCADE"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("assignment_items.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    saved_at: Mapped[datetime | None] = mapped_column(_TS)
    auto_marks: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    ai_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="none")
    ai_marks: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    ai_feedback_md: Mapped[str | None] = mapped_column(Text)
    ai_confidence: Mapped[float | None] = mapped_column(REAL)
    ai_criteria: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    ai_error: Mapped[str | None] = mapped_column(Text)
    final_marks: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    final_feedback_md: Mapped[str | None] = mapped_column(Text)
    grade_source: Mapped[str | None] = mapped_column(Text)
    graded_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    graded_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AssignmentRegradeRequest(Base):
    __tablename__ = "assignment_regrade_requests"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    submission_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("assignment_submissions.id", ondelete="CASCADE"), nullable=False
    )
    assignment_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("assignments.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    item_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID, ForeignKey("assignment_items.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


# Certificate email outbox (learning_0005) lives in cert_models.py; imported so Base.metadata has it.
from app.modules.learning.cert_models import CertificateOutbox  # noqa: E402, F401

# Issued documents, templates, settings (learning_0006) live in doc_models.py.
from app.modules.learning.doc_models import DocumentSettings, DocumentTemplate, IssuedDocument  # noqa: E402, F401
