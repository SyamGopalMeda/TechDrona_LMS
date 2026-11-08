"""Assessments ORM models (database-schema §9)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, INET, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_UUID = UUID(as_uuid=True)


class Test(Base):
    __test__ = False  # not a pytest class
    __tablename__ = "tests"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    test_kind: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str | None] = mapped_column(Text)
    company_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    company_path_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    grace_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="30")
    navigation_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="free")
    attempts_allowed: Mapped[int | None] = mapped_column(SmallInteger)
    grading_method: Mapped[str] = mapped_column(Text, nullable=False, server_default="highest")
    shuffle_questions: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    shuffle_options: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    review_policy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    integrity_settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    pass_percentage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    is_free: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    available_from: Mapped[datetime | None] = mapped_column(_TS)
    available_until: Mapped[datetime | None] = mapped_column(_TS)
    settings_locked_at: Mapped[datetime | None] = mapped_column(_TS)
    published_at: Mapped[datetime | None] = mapped_column(_TS)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)  # owning batch (ADM-49)
    created_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class TestSection(Base):
    __test__ = False  # not a pytest class
    __tablename__ = "test_sections"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    test_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("tests.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    instructions_md: Mapped[str | None] = mapped_column(Text)
    min_attempt_required: Mapped[int | None] = mapped_column(SmallInteger)


class TestSectionRule(Base):
    __test__ = False  # not a pytest class
    __tablename__ = "test_section_rules"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    test_section_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("test_sections.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rule_type: Mapped[str] = mapped_column(Text, nullable=False)
    question_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    question_version_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    company_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    question_types: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    difficulty_min: Mapped[int | None] = mapped_column(SmallInteger)
    difficulty_max: Mapped[int | None] = mapped_column(SmallInteger)
    tag_filter: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    draw_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    marks_each: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    negative_marks_each: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))


class TestAssignment(Base):
    __test__ = False  # not a pytest class
    __tablename__ = "test_assignments"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    test_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tests.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    course_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    available_from: Mapped[datetime] = mapped_column(_TS, nullable=False)
    available_until: Mapped[datetime] = mapped_column(_TS, nullable=False)
    attempts_allowed: Mapped[int | None] = mapped_column(SmallInteger)
    release_mode: Mapped[str] = mapped_column(Text, nullable=False, server_default="immediate")
    results_release_at: Mapped[datetime | None] = mapped_column(_TS)
    assigned_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AttemptOverride(Base):
    __tablename__ = "attempt_overrides"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    test_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tests.id"), nullable=False)
    test_assignment_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    user_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    extra_time_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    extra_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    window_extension_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    granted_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class TestAttempt(Base):
    __test__ = False  # not a pytest class
    __tablename__ = "test_attempts"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    test_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("tests.id"), nullable=False)
    test_version: Mapped[int] = mapped_column(Integer, nullable=False)
    test_assignment_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    attempt_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="in_progress")
    selection_seed: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    layout: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    started_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    deadline_at: Mapped[datetime | None] = mapped_column(_TS)
    extra_time_seconds: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    submitted_at: Mapped[datetime | None] = mapped_column(_TS)
    submit_reason: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    current_section_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    bound_session_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    bound_device_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    rebind_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    start_ip: Mapped[str | None] = mapped_column(INET)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    integrity_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="none")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AttemptSection(Base):
    __tablename__ = "attempt_sections"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("test_attempts.id", ondelete="CASCADE"), primary_key=True
    )
    test_section_id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="not_started")
    started_at: Mapped[datetime | None] = mapped_column(_TS)
    deadline_at: Mapped[datetime | None] = mapped_column(_TS)
    submitted_at: Mapped[datetime | None] = mapped_column(_TS)


class AttemptResponse(Base):
    __tablename__ = "attempt_responses"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("test_attempts.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    test_section_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    question_version_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    client_seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    time_spent_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    first_answered_at: Mapped[datetime | None] = mapped_column(_TS)
    saved_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    marks_awarded: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    manual_grade_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)


class AttemptEvent(Base):
    __tablename__ = "attempt_events"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(_TS, primary_key=True)
    attempt_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    question_version_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    client_seq: Mapped[int | None] = mapped_column(BigInteger)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    auth_session_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    ip: Mapped[str | None] = mapped_column(INET)


class AttemptResult(Base):
    __tablename__ = "attempt_results"

    attempt_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("test_attempts.id"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    test_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    scoring_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    score: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    max_score: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    percentage: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    correct_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    incorrect_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    unanswered_count: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    time_taken_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    section_scores: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    topic_scores: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    percentile: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    rank: Mapped[int | None] = mapped_column(Integer)
    rank_provisional: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    passed: Mapped[bool | None] = mapped_column(Boolean)
    graded_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    released_at: Mapped[datetime | None] = mapped_column(_TS)
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AttemptIntegrityDecision(Base):
    __tablename__ = "attempt_integrity_decisions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    attempt_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("test_attempts.id"), nullable=False)
    test_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False)
    signals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    security_case_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    security_case_ref: Mapped[str | None] = mapped_column(Text)
    decided_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class AttemptItemGrade(Base):
    """Human grading of free-text items (descriptive/essay/short answer). The AI columns hold a
    *suggestion* only (``ai_status = 'pending'``); ``final_*`` is set by a person and is the only
    value scoring uses."""

    __tablename__ = "attempt_item_grades"

    attempt_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("test_attempts.id", ondelete="CASCADE"), primary_key=True
    )
    question_version_id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    test_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    max_marks: Mapped[Decimal] = mapped_column(Numeric(7, 2), nullable=False)
    ai_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="none")
    ai_marks: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    ai_feedback: Mapped[str | None] = mapped_column(Text)
    ai_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    ai_criteria: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    ai_error: Mapped[str | None] = mapped_column(Text)
    ai_graded_at: Mapped[datetime | None] = mapped_column(_TS)
    final_marks: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    final_feedback: Mapped[str | None] = mapped_column(Text)
    finalized_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    finalized_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
