"""Guided learning path ORM models (migration ``paths_0001``)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_UUID = UUID(as_uuid=True)


class LearningPath(Base):
    __tablename__ = "learning_paths"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("organizations.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description_md: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    level: Mapped[str] = mapped_column(Text, nullable=False, server_default="beginner")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default="manual")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    has_unpublished_changes: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_by: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class _StepCols:
    step_key: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    parent_key: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    step_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description_md: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    est_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, server_default="0")
    credits: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    url: Mapped[str | None] = mapped_column(Text)
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    test_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    article_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)


class LearningPathStep(_StepCols, Base):
    __tablename__ = "learning_path_steps"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    path_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("learning_paths.id"), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class LearningPathVersion(Base):
    __tablename__ = "learning_path_versions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    path_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("learning_paths.id"), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description_md: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    level: Mapped[str] = mapped_column(Text, nullable=False)
    total_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    total_credits: Mapped[int] = mapped_column(Integer, nullable=False)
    published_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    published_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class LearningPathVersionStep(_StepCols, Base):
    __tablename__ = "learning_path_version_steps"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    path_version_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("learning_path_versions.id"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)


class PathArticle(Base):
    __tablename__ = "path_articles"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("organizations.id"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    level: Mapped[str] = mapped_column(Text, nullable=False, server_default="beginner")
    est_minutes: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    body_md: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    toc: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, server_default="[]")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    audience: Mapped[str | None] = mapped_column(Text)
    batch_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(_UUID), nullable=False, server_default="{}")
    user_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(_UUID), nullable=False, server_default="{}")
    published_at: Mapped[datetime | None] = mapped_column(_TS)
    deleted_at: Mapped[datetime | None] = mapped_column(_TS)
    created_by: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class PathAllocation(Base):
    __tablename__ = "path_allocations"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    organization_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    path_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("learning_paths.id"), nullable=False)
    path_version_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("learning_path_versions.id"), nullable=False
    )
    target_type: Mapped[str] = mapped_column(Text, nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    user_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(_UUID), nullable=False, server_default="{}")
    flow: Mapped[str] = mapped_column(Text, nullable=False)
    sequential: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    pace: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    weekly_hours: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    total_hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    finish_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    created_by: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class PathStepProgress(Base):
    __tablename__ = "path_step_progress"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    allocation_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("path_allocations.id"), nullable=False)
    organization_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    step_key: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    opened_at: Mapped[datetime | None] = mapped_column(_TS)
    completed_at: Mapped[datetime | None] = mapped_column(_TS)
    credits_awarded: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    source: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
