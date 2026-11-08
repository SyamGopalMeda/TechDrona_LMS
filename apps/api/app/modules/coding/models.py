"""Coding module tables (database-schema §10; DDL in ``migrations/versions/coding_0001``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, LargeBinary, Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _ts(nullable: bool = False) -> Any:
    if nullable:
        return mapped_column(DateTime(timezone=True), nullable=True)
    return mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class JudgeLanguage(Base):
    __tablename__ = "judge_languages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    language_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    version_label: Mapped[str | None] = mapped_column(Text)
    provider_language_id: Mapped[int] = mapped_column(Integer, nullable=False)
    time_multiplier: Mapped[Decimal] = mapped_column(Numeric(4, 2), nullable=False)
    memory_extra_kb: Mapped[int] = mapped_column(Integer, nullable=False)
    max_processes: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    starter_template: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = _ts()


class CodingProblem(Base):
    __tablename__ = "coding_problems"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    slug: Mapped[str] = mapped_column(Text, nullable=False)  # citext in DDL
    title: Mapped[str] = mapped_column(Text, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    statement_md: Mapped[str] = mapped_column(Text, nullable=False)
    input_format_md: Mapped[str | None] = mapped_column(Text)
    output_format_md: Mapped[str | None] = mapped_column(Text)
    constraints_md: Mapped[str | None] = mapped_column(Text)
    difficulty: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    primary_topic_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    time_limit_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=2000)
    wall_limit_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=5000)
    memory_limit_kb: Mapped[int] = mapped_column(Integer, nullable=False, default=262144)
    allowed_languages: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    checker_type: Mapped[str] = mapped_column(Text, nullable=False, default="exact")
    checker_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    scoring_mode: Mapped[str] = mapped_column(Text, nullable=False, default="weighted_cases")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    is_free: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    published_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    published_at: Mapped[datetime | None] = _ts(nullable=True)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class CodingTestCaseBlob(Base):
    """AES-256-GCM ciphertext of hidden case input/expected output (stand-in for S3)."""

    __tablename__ = "coding_test_case_blobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    coding_problem_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = _ts()


class CodingTestCase(Base):
    __tablename__ = "coding_test_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    coding_problem_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    problem_version: Mapped[int] = mapped_column(Integer, nullable=False)
    ordinal: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    sample_input: Mapped[str | None] = mapped_column(Text)
    sample_output: Mapped[str | None] = mapped_column(Text)
    input_s3_key: Mapped[str | None] = mapped_column(Text)
    expected_s3_key: Mapped[str | None] = mapped_column(Text)
    wrapped_data_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    input_sha256: Mapped[bytes | None] = mapped_column(LargeBinary)
    expected_sha256: Mapped[bytes | None] = mapped_column(LargeBinary)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = _ts()


class CodeSubmission(Base):
    __tablename__ = "code_submissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    coding_problem_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    problem_version: Mapped[int] = mapped_column(Integer, nullable=False)
    language_key: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    attempt_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    practice_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    custom_input: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    verdict: Mapped[str | None] = mapped_column(Text)
    score: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    max_score: Mapped[Decimal | None] = mapped_column(Numeric(7, 2))
    passed_cases: Mapped[int | None] = mapped_column(SmallInteger)
    total_cases: Mapped[int | None] = mapped_column(SmallInteger)
    max_time_ms: Mapped[int | None] = mapped_column(Integer)
    max_memory_kb: Mapped[int | None] = mapped_column(Integer)
    compile_output: Mapped[str | None] = mapped_column(Text)
    judge_provider: Mapped[str] = mapped_column(Text, nullable=False)
    queue_name: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_sha256: Mapped[bytes | None] = mapped_column(LargeBinary)
    similarity_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retry_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    notice: Mapped[str | None] = mapped_column(Text)
    queued_at: Mapped[datetime] = _ts()
    started_at: Mapped[datetime | None] = _ts(nullable=True)
    completed_at: Mapped[datetime | None] = _ts(nullable=True)


class SubmissionResult(Base):
    __tablename__ = "submission_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    code_submission_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    test_case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    ordinal: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False)
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    time_ms: Mapped[int | None] = mapped_column(Integer)
    memory_kb: Mapped[int | None] = mapped_column(Integer)
    exit_code: Mapped[int | None] = mapped_column(SmallInteger)
    stdout_excerpt: Mapped[str | None] = mapped_column(Text)
    judge_token: Mapped[str | None] = mapped_column(Text)
    weight_awarded: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=Decimal(0))


# --------------------------------------------------------------------------- coding_0002 (authoring gaps)


class CodingDraft(Base):
    """COD-04/05 autosaved editor code (RLS O)."""

    __tablename__ = "coding_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    coding_problem_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    language_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    window_started_at: Mapped[datetime] = _ts()
    window_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class CodingReferenceSolution(Base):
    __tablename__ = "coding_reference_solutions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    coding_problem_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    language_key: Mapped[str] = mapped_column(Text, nullable=False)
    source_code: Mapped[str] = mapped_column(Text, nullable=False)
    updated_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = _ts()


class CodingProblemValidation(Base):
    """COD-18 result. ``results`` holds per-case verdict/time/memory only — never content."""

    __tablename__ = "coding_problem_validations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    coding_problem_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    problem_version: Mapped[int] = mapped_column(Integer, nullable=False)
    fingerprint: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    detail: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = _ts()


class CodingTestCaseContentToken(Base):
    """COD-17 single-use download token (sha256 stored; RLS O)."""

    __tablename__ = "coding_testcase_content_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    request_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    test_case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    coding_problem_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    part: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = _ts(nullable=True)
    created_at: Mapped[datetime] = _ts()
