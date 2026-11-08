"""Placement ORM models (database-schema §8)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_UUID = UUID(as_uuid=True)


class Topic(Base):
    __tablename__ = "topics"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("topics.id"))
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    depth: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    logo_s3_key: Mapped[str | None] = mapped_column(Text)
    industry: Mapped[str | None] = mapped_column(Text)
    hub_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    description_md: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class CompanyPath(Base):
    __tablename__ = "company_paths"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    company_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("companies.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    role_name: Mapped[str] = mapped_column(Text, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    pattern: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    published_at: Mapped[datetime | None] = mapped_column(_TS)
    created_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class CompanyPathStep(Base):
    __tablename__ = "company_path_steps"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    company_path_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("company_paths.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(Text, nullable=False)
    lesson_key: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    test_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("topics.id"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class Question(Base):
    __tablename__ = "questions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    question_type: Mapped[str] = mapped_column(Text, nullable=False)
    primary_topic_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("topics.id"), nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    external_ref: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    retired_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(_TS)


class QuestionVersion(Base):
    __tablename__ = "question_versions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("questions.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    stem: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    answer_key: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    explanation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    difficulty: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    item_rating: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1000")
    default_marks: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, server_default="1")
    default_negative: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, server_default="0")
    expected_seconds: Mapped[int | None] = mapped_column(Integer)
    coding_problem_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    authored_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    edited_by: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(_UUID), nullable=False, server_default="{}")
    review_comment: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class QuestionOption(Base):
    __tablename__ = "question_options"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    question_version_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("question_versions.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    feedback: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class QuestionTag(Base):
    __tablename__ = "question_tags"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    tag_type: Mapped[str] = mapped_column(Text, nullable=False)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    company_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    tag_value: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class PracticeSession(Base):
    __tablename__ = "practice_sessions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    company_path_step_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    target_count: Mapped[int | None] = mapped_column(SmallInteger)
    answered_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    correct_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="0")
    served: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    started_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(_TS)
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class PracticeResponse(Base):
    __tablename__ = "practice_responses"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    practice_session_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("practice_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    question_version_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    topic_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_correct: Mapped[bool | None] = mapped_column(Boolean)
    attempt_no: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    served_at: Mapped[datetime] = mapped_column(_TS, nullable=False)
    time_spent_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    hint_used: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    solution_viewed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    rating_before: Mapped[int | None] = mapped_column(SmallInteger)
    rating_after: Mapped[int | None] = mapped_column(SmallInteger)
    answered_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    rule_key: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    priority: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="50")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    generated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(_TS, nullable=False)


class QuestionReport(Base):
    """PLC-33..35 learner-reported question error (RLS U; ``organization_id`` = question's)."""

    __tablename__ = "question_reports"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    question_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("questions.id"), nullable=False)
    question_version_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="open")
    resolution: Mapped[str | None] = mapped_column(Text)
    resolution_note: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    resolved_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class QuestionBank(Base):
    """Named collection of questions (placement_0005; RLS TN)."""

    __tablename__ = "question_banks"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    default_topic_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("topics.id"))
    created_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    last_added_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(_TS)


class QuestionBankItem(Base):
    __tablename__ = "question_bank_items"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    bank_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("question_banks.id", ondelete="CASCADE"), nullable=False
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    added_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    added_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class QuestionMedia(Base):
    """Image on a question stem/option (presigned upload + malware scan; RLS TN)."""

    __tablename__ = "question_media"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    s3_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="uploading")
    scan_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    created_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
