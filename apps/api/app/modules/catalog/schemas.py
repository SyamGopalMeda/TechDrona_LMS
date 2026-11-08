"""Request bodies for catalog routes (extra fields forbidden, api-spec §1.1)."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

SLUG = r"^[a-z0-9][a-z0-9-]{1,118}$"
# FR-CAT-001 / CAT-13: pdf (PDF lesson file, MED-02 lesson_file) and practice_set (an embedded
# practice-set test, referenced by test_id like a quiz) were missing (webstaff request 8).
LessonType = Literal["video", "article", "pdf", "practice_set", "quiz", "coding", "assignment", "live_link"]
Level = Literal["beginner", "intermediate", "advanced"]
Category = Literal["aptitude", "programming", "dsa", "cs_fundamentals", "company", "interview", "other"]
Visibility = Literal["public", "unlisted", "private"]
CourseKind = Literal["self_paced", "cohort", "crash_course", "company_prep", "bootcamp"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CertificateRule(Strict):
    required_lessons_pct: int = Field(default=100, ge=1, le=100)
    final_test_id: uuid.UUID | None = None
    final_test_min_pct: int | None = Field(default=None, ge=1, le=100)


class CompletenessPlan(Strict):
    planned_lessons: int | None = Field(default=None, ge=1, le=10000)
    roadmap: list[dict[str, str]] = Field(default_factory=list, max_length=100)


class CourseIn(Strict):
    title: str = Field(min_length=3, max_length=200)
    slug: str = Field(pattern=SLUG)
    course_kind: CourseKind = "self_paced"
    visibility: Visibility = "private"
    is_free: bool = False
    summary: str | None = Field(default=None, max_length=2000)


class DraftPatch(Strict):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    slug: str | None = Field(default=None, pattern=SLUG)
    summary: str | None = Field(default=None, max_length=2000)
    description_md: str | None = Field(default=None, max_length=100_000)
    outcomes: list[str] | None = Field(default=None, max_length=30)
    level: Level | None = None
    language: str | None = Field(default=None, min_length=2, max_length=10)
    category: Category | None = None
    tags: list[str] | None = Field(default=None, max_length=30)
    certificate_rule: CertificateRule | None = None
    completeness_plan: CompletenessPlan | None = None
    visibility: Visibility | None = None
    is_free: bool | None = None
    course_kind: CourseKind | None = None


class OutlineModule(Strict):
    module_key: uuid.UUID | None = None
    title: str = Field(min_length=1, max_length=200)
    lesson_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class OutlineIn(Strict):
    modules: list[OutlineModule] = Field(max_length=200)


class LessonFields(Strict):
    is_required: bool | None = None
    is_free_preview: bool | None = None
    duration_seconds: int | None = Field(default=None, ge=0, le=86_400)
    est_reading_minutes: int | None = Field(default=None, ge=0, le=600)
    article_body: dict[str, Any] | None = None
    test_id: uuid.UUID | None = None
    coding_problem_id: uuid.UUID | None = None
    assignment_id: uuid.UUID | None = None
    live_url: str | None = Field(default=None, pattern=r"^https://", max_length=2000)


class LessonIn(LessonFields):
    title: str = Field(min_length=1, max_length=200)
    lesson_type: LessonType
    module_key: uuid.UUID | None = None
    module_title: str | None = Field(default=None, min_length=1, max_length=200)


class LessonPatch(LessonFields):
    title: str | None = Field(default=None, min_length=1, max_length=200)


class TopicIn(Strict):
    topic_id: uuid.UUID
    is_primary: bool = False


class TopicsIn(Strict):
    topics: list[TopicIn] = Field(max_length=20)


class PublishIn(Strict):
    change_type: Literal["minor", "major"] = "major"
    changelog: str | None = Field(default=None, max_length=5000)


class ResourceIn(Strict):
    title: str = Field(min_length=1, max_length=200)
    resource_type: Literal["file", "link", "cheatsheet", "interview_experience"]
    access_level: Literal["public", "signed_in", "entitled"] = "entitled"
    course_id: uuid.UUID | None = None
    lesson_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    s3_key: str | None = Field(default=None, max_length=1024)
    url: str | None = Field(default=None, pattern=r"^https://", max_length=2000)


class ResourcePatch(Strict):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    access_level: Literal["public", "signed_in", "entitled"] | None = None
    s3_key: str | None = Field(default=None, max_length=1024)
    url: str | None = Field(default=None, pattern=r"^https://", max_length=2000)
