"""Request bodies for the mentoring and résumé endpoints (responses are plain dicts built in
``service`` — the field list is documented in the module router)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, field_validator

SessionKind = Literal["mock_interview", "resume_review", "career_guidance"]
TemplateKey = Literal["ats_classic", "ats_modern"]
SCORE_KEYS = ("communication", "problem_solving", "technical_depth", "confidence", "overall")
RESUME_SECTIONS = (
    "headline",
    "summary",
    "education",
    "skills",
    "projects",
    "internships",
    "achievements",
    "certifications",
)

Short = Annotated[str, Field(min_length=1, max_length=200)]
OptShort = Annotated[str | None, Field(max_length=200)]
OptLong = Annotated[str | None, Field(max_length=2000)]
YearOrText = str | int | None


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- mentor slots


class SlotIn(_In):
    starts_at: datetime
    duration_minutes: Literal[30, 45, 60]
    session_kind: SessionKind = "mock_interview"
    company_id: uuid.UUID | None = None

    @field_validator("starts_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            raise ValueError("timestamp must include a timezone offset")
        return v


class SlotsIn(_In):
    slots: list[SlotIn] = Field(min_length=1, max_length=50)


# --------------------------------------------------------------------------- bookings


class BookIn(_In):
    slot_id: uuid.UUID


class RescheduleIn(_In):
    slot_id: uuid.UUID


class CancelIn(_In):
    reason: str | None = Field(default=None, max_length=500)


class MeetingLinkIn(_In):
    meeting_url: AnyUrl | None

    @field_validator("meeting_url")
    @classmethod
    def _https(cls, v: AnyUrl | None) -> AnyUrl | None:
        if v is None:
            return v
        if v.scheme != "https" or not v.host:
            raise ValueError("meeting link must be an https:// URL")
        if len(str(v)) > 2048:
            raise ValueError("meeting link too long")
        return v


Score = Annotated[int, Field(ge=1, le=5)]


class Scores(_In):
    communication: Score
    problem_solving: Score
    technical_depth: Score
    confidence: Score
    overall: Score


class FeedbackIn(_In):
    scores: Scores
    comments: str | None = Field(default=None, max_length=5000)


class NoShowIn(_In):
    party: Literal["student", "mentor"]


class NoteIn(_In):
    body: str = Field(min_length=1, max_length=5000)
    booking_id: uuid.UUID | None = None

    @field_validator("body")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("note cannot be blank")
        return v


# --------------------------------------------------------------------------- résumés


class Education(_In):
    institution: Short
    degree: OptShort = None
    field: OptShort = None
    start_year: YearOrText = None
    end_year: YearOrText = None
    score: OptShort = None


class Project(_In):
    title: Short
    description: OptLong = None
    tech: list[Annotated[str, Field(max_length=60)]] = Field(default_factory=list, max_length=30)
    link: Annotated[str | None, Field(max_length=500)] = None


class Internship(_In):
    company: Short
    role: OptShort = None
    start: OptShort = None
    end: OptShort = None
    description: OptLong = None


class Certification(_In):
    title: Short
    issuer: OptShort = None
    issued_on: OptShort = None
    credential_id: OptShort = None


class ResumeContent(_In):
    headline: Annotated[str | None, Field(max_length=200)] = None
    summary: Annotated[str | None, Field(max_length=2000)] = None
    education: list[Education] = Field(default_factory=list, max_length=20)
    skills: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(
        default_factory=list, max_length=60
    )
    projects: list[Project] = Field(default_factory=list, max_length=20)
    internships: list[Internship] = Field(default_factory=list, max_length=20)
    achievements: list[Annotated[str, Field(min_length=1, max_length=300)]] = Field(
        default_factory=list, max_length=30
    )
    certifications: list[Certification] = Field(default_factory=list, max_length=30)


class ResumeIn(_In):
    template_key: TemplateKey = "ats_classic"
    content: ResumeContent


class PdfUploadIn(_In):
    filename: str = Field(min_length=1, max_length=200)
    size_bytes: int = Field(ge=1, le=5 * 1024 * 1024)
    content_type: Literal["application/pdf"] = "application/pdf"


class PdfCompleteIn(_In):
    key: str = Field(min_length=1, max_length=500)


class ReviewRequestIn(_In):
    note: str | None = Field(default=None, max_length=1000)


class ReviewComment(_In):
    section: Literal[
        "general",
        "headline",
        "summary",
        "education",
        "skills",
        "projects",
        "internships",
        "achievements",
        "certifications",
    ]
    comment: str = Field(min_length=1, max_length=2000)


class ReviewFeedbackIn(_In):
    comments: list[ReviewComment] = Field(default_factory=list, max_length=100)
    summary: str = Field(min_length=1, max_length=5000)
