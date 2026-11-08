"""Catalog: courses, versions, modules, lessons, lesson topics, lesson assets, resources
(database-schema §7; migration ``catalog_0001``)."""

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
    Numeric,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_UUID = UUID(as_uuid=True)


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    slug: Mapped[str] = mapped_column(CITEXT, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    course_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="self_paced")
    visibility: Mapped[str] = mapped_column(Text, nullable=False, server_default="private")
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    is_free: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        _UUID, ForeignKey("course_versions.id", use_alter=True, name="fk_courses_current_version")
    )
    primary_topic_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    completeness_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, server_default="0")
    created_by: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(_TS)


class CourseVersion(Base):
    __tablename__ = "course_versions"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    course_id: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("courses.id"), nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    description_md: Mapped[str | None] = mapped_column(Text)
    outcomes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    level: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, nullable=False, server_default="en")
    category: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    certificate_rule: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    completeness_plan: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    change_type: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(_TS)
    published_at: Mapped[datetime | None] = mapped_column(_TS)
    published_by: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("users.id"))
    changelog: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class CourseModule(Base):
    __tablename__ = "course_modules"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    course_version_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("course_versions.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    module_key: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class Lesson(Base):
    __tablename__ = "lessons"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    course_module_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("course_modules.id", ondelete="CASCADE"), nullable=False
    )
    course_version_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("course_versions.id"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    lesson_key: Mapped[uuid.UUID] = mapped_column(_UUID, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    lesson_type: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    is_free_preview: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    article_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    test_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    coding_problem_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    live_url: Mapped[str | None] = mapped_column(Text)
    est_reading_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class LessonTopic(Base):
    __tablename__ = "lesson_topics"

    lesson_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("lessons.id", ondelete="CASCADE"), primary_key=True
    )
    topic_id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class LessonAsset(Base):
    __tablename__ = "lesson_assets"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    lesson_id: Mapped[uuid.UUID] = mapped_column(
        _UUID, ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    asset_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_asset_id: Mapped[str | None] = mapped_column(Text)
    s3_key: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="processing")
    scan_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = mapped_column(_UUID, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("organizations.id"))
    course_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("courses.id"))
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(_UUID, ForeignKey("lessons.id", ondelete="SET NULL"))
    company_id: Mapped[uuid.UUID | None] = mapped_column(_UUID)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    resource_type: Mapped[str] = mapped_column(Text, nullable=False)
    access_level: Mapped[str] = mapped_column(Text, nullable=False, server_default="entitled")
    s3_key: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_by: Mapped[uuid.UUID] = mapped_column(_UUID, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
