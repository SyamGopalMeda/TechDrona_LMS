"""Placement request/response schemas.

Delivery DTOs (``QuestionDelivery``, ``OptionDelivery``) intentionally have NO key fields
(``is_correct``, ``answer_key``, ``explanation``, ``correct_option_ids``); a contract test
asserts it. Feedback/key fields live only in separate review/feedback models.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

QuestionType = Literal[
    "mcq_single", "mcq_multi", "numeric", "fill_blank", "coding", "essay", "poll", "survey", "word_cloud"
]
Slug = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- delivery (no keys)


class OptionDelivery(BaseModel):
    option_id: uuid.UUID
    label: str
    html: str
    image_url: str | None = None  # clean-scanned option image (placement_0005)


class ImageRef(BaseModel):
    media_id: uuid.UUID
    url: str


class QuestionDelivery(BaseModel):
    question_version_id: uuid.UUID
    type: str
    topic_id: uuid.UUID
    difficulty: int
    stem_html: str
    options: list[OptionDelivery] = []
    marks: Decimal | None = None
    negative_marks: Decimal | None = None
    expected_seconds: int | None = None
    coding_problem_id: uuid.UUID | None = None  # ``coding`` questions: solve via COD-07 with attempt_id
    settings: dict[str, Any] | None = None  # poll/survey/word_cloud/essay presentation settings
    stem_images: list[ImageRef] | None = None


# --------------------------------------------------------------------------- taxonomy


class TopicCreate(_In):
    parent_id: uuid.UUID | None = None
    slug: str = Slug
    name: str = Field(min_length=1, max_length=200)
    position: int = 0


class TopicPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,62}$")
    parent_id: uuid.UUID | None = None
    position: int | None = None
    is_active: bool | None = None


class TopicOut(BaseModel):
    id: uuid.UUID
    parent_id: uuid.UUID | None
    kind: str
    slug: str
    name: str
    path: str
    depth: int
    position: int
    is_active: bool


# --------------------------------------------------------------------------- questions


class OptionIn(_In):
    html: str = Field(min_length=1, max_length=5000)
    is_correct: bool = False
    feedback_html: str | None = Field(default=None, max_length=5000)
    image_id: uuid.UUID | None = None  # ``question_media`` id (QBK media upload)


class TagIn(_In):
    tag_type: Literal["topic", "company", "skill", "exam_pattern", "source", "custom"]
    topic_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    value: str | None = Field(default=None, max_length=120)


class QuestionContent(_In):
    stem_html: str = Field(min_length=1, max_length=20000)
    options: list[OptionIn] = []
    answer_key: dict[str, Any] | None = None
    explanation_html: str | None = Field(default=None, max_length=20000)
    difficulty: int = Field(ge=1, le=5)
    default_marks: Decimal = Field(default=Decimal("1"), gt=0, le=100)
    default_negative: Decimal = Field(default=Decimal("0"), ge=0, le=100)
    expected_seconds: int | None = Field(default=None, gt=0, le=3600)
    coding_problem_id: uuid.UUID | None = None  # required for (and only for) ``coding`` questions
    settings: dict[str, Any] | None = None  # per-type, see ``grading.validate_settings``
    stem_image_ids: list[uuid.UUID] = Field(default=[], max_length=4)


class QuestionCreate(QuestionContent):
    organization_id: uuid.UUID | None = None
    question_type: QuestionType
    # Optional since placement_0005: defaults to the bank's topic, else "Uncategorised".
    primary_topic_id: uuid.UUID | None = None
    bank_id: uuid.UUID | None = None
    tags: list[TagIn] = Field(default=[], max_length=30)
    external_ref: str | None = Field(default=None, max_length=200)


class ReviewIn(_In):
    decision: Literal["approve", "request_changes"]
    comment: str | None = Field(default=None, max_length=2000)


class RetireIn(_In):
    reason: str | None = Field(default=None, max_length=500)


# --------------------------------------------------------------------------- companies


class CompanyCreate(_In):
    slug: str = Slug
    name: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=100)
    description_md: str | None = Field(default=None, max_length=20000)
    hub_status: Literal["draft", "published", "archived"] = "draft"


class PatternSection(_In):
    section: str = Field(min_length=1, max_length=120)
    topic_id: uuid.UUID
    weight: Decimal = Field(gt=0, le=100)
    minutes: int | None = Field(default=None, gt=0, le=600)
    question_count: int | None = Field(default=None, gt=0, le=500)
    negative_marking: Decimal | None = Field(default=None, ge=0, le=10)


class PathStepIn(_In):
    step_type: Literal["lesson", "practice_set", "test", "coding_set"]
    title: str = Field(min_length=1, max_length=200)
    topic_id: uuid.UUID | None = None
    test_id: uuid.UUID | None = None
    lesson_key: uuid.UUID | None = None
    is_required: bool = True

    @model_validator(mode="after")
    def _one_ref(self) -> PathStepIn:
        if sum(x is not None for x in (self.topic_id, self.test_id, self.lesson_key)) != 1:
            raise ValueError("exactly one of topic_id, test_id, lesson_key is required")
        return self


class CompanyPathPut(_In):
    company_id: uuid.UUID
    organization_id: uuid.UUID | None = None
    role_name: str = Field(min_length=1, max_length=120)
    status: Literal["draft", "published", "retired"] = "draft"
    pattern: list[PatternSection] = Field(min_length=1, max_length=20)
    steps: list[PathStepIn] = Field(default=[], max_length=200)


# --------------------------------------------------------------------------- practice


class PracticeStart(_In):
    mode: Literal["topic_set", "company_step", "revision"] = "topic_set"
    topic_id: uuid.UUID | None = None
    company_path_step_id: uuid.UUID | None = None
    difficulty_min: int = Field(default=1, ge=1, le=5)
    difficulty_max: int = Field(default=5, ge=1, le=5)
    count: int = Field(default=10, ge=1, le=20)


class PracticeAnswer(_In):
    question_version_id: uuid.UUID
    response: dict[str, Any]
    time_spent_ms: int = Field(ge=0, le=3_600_000)
    client_attempt_no: int | None = Field(default=None, ge=1)


class RevealIn(_In):
    kind: Literal["hint", "solution"] = "solution"


class ServedItem(BaseModel):
    question: QuestionDelivery
    served_at: datetime
    answered: bool
    feedback: dict[str, Any] | None = None


# --------------------------------------------------------------------------- question banks


class BankCreate(_In):
    name: str = Field(min_length=1, max_length=120)
    subject: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    organization_id: uuid.UUID | None = None
    default_topic_id: uuid.UUID | None = None


class BankPatch(_In):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    subject: str | None = Field(default=None, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    default_topic_id: uuid.UUID | None = None


class BankAddQuestions(_In):
    question_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class ResolveIn(_In):
    question_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)
    prefer: Literal["published", "latest"] = "published"


ImportKind = Literal["mcq", "code", "essay", "poll", "survey", "word_cloud"]


class ImportPromptIn(_In):
    question_type: ImportKind
    count: int = Field(default=5, ge=1, le=50)
    subject: str | None = Field(default=None, max_length=120)
    topic: str | None = Field(default=None, max_length=200)
    instructions: str | None = Field(default=None, max_length=2000)


class ImportValidateIn(_In):
    question_type: ImportKind
    raw: str | None = Field(default=None, max_length=500_000)
    items: list[Any] | None = Field(default=None, max_length=50)


class ImportIn(ImportValidateIn):
    bank_id: uuid.UUID | None = None
    new_bank_name: str | None = Field(default=None, max_length=120)
    subject: str | None = Field(default=None, max_length=120)
    topic: str | None = Field(default=None, max_length=200)
    organization_id: uuid.UUID | None = None
    primary_topic_id: uuid.UUID | None = None
    source: Literal["bulk", "ai"] = "bulk"


class GenerateIn(_In):
    source_mode: Literal["topic", "company", "subject", "test"] = "topic"
    question_type: ImportKind
    count: int = Field(default=5, ge=1, le=50)
    subject: str | None = Field(default=None, max_length=120)
    topic: str | None = Field(default=None, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    difficulty: Literal["easy", "medium", "hard", "mixed"] = "mixed"
    instructions: str | None = Field(default=None, max_length=2000)
    organization_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _source(self) -> GenerateIn:
        need = {"topic": self.topic, "company": self.company, "subject": self.subject, "test": self.topic}
        if not (need[self.source_mode] or "").strip():
            field = {"test": "topic"}.get(self.source_mode, self.source_mode)
            raise ValueError(f"{field} is required for source_mode={self.source_mode}")
        return self


class MediaUploadIn(_In):
    filename: str = Field(min_length=1, max_length=200)
    content_type: Literal["image/png", "image/jpeg", "image/webp", "image/gif"]
    size_bytes: int = Field(gt=0, le=5 * 1024 * 1024)
    organization_id: uuid.UUID | None = None
