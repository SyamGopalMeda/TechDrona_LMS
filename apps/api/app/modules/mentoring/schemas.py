"""Request bodies for the résumé endpoints (responses are plain dicts built in ``service`` — the
field list is documented in the module router). The mentoring sessions/slots bodies were removed
with the mentoring feature (docs/cleanup/feature-removal-plan.md §3.1)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

TemplateKey = Literal["ats_classic", "ats_modern"]
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
