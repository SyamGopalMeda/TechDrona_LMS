"""Request/response models. Hidden-case output models carry ONLY ordinal/verdict/time/memory
(``extra="forbid"``) so nothing else can be serialised for a hidden case (api-spec COD-08)."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_SOURCE_BYTES = 64 * 1024
MAX_CASE_BYTES = 96 * 1024  # each of input/expected for inline authoring (body limit 256 KiB)

LanguageKey = str
SLUG_RE = r"^[a-z0-9][a-z0-9-]{1,79}$"


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class ProblemCreateIn(_In):
    slug: str = Field(pattern=SLUG_RE)
    title: str = Field(min_length=3, max_length=200)
    statement_md: str = Field(min_length=1, max_length=50_000)
    input_format_md: str | None = Field(default=None, max_length=10_000)
    output_format_md: str | None = Field(default=None, max_length=10_000)
    constraints_md: str | None = Field(default=None, max_length=10_000)
    difficulty: int = Field(ge=1, le=5)
    organization_id: uuid.UUID | None = None
    time_limit_ms: int = Field(default=2000, ge=100, le=5000)
    wall_limit_ms: int | None = Field(default=None, ge=200, le=10000)
    memory_limit_kb: int = Field(default=262144, ge=16384, le=524288)
    allowed_languages: list[str] = Field(
        default_factory=lambda: ["c", "cpp17", "java17", "python3"], min_length=1, max_length=16
    )
    checker_type: Literal["exact", "token", "float_tolerance"] = "exact"
    checker_config: dict[str, Any] | None = None
    scoring_mode: Literal["weighted_cases", "all_or_nothing"] = "weighted_cases"
    is_free: bool = False

    @model_validator(mode="after")
    def _wall(self) -> ProblemCreateIn:
        if self.wall_limit_ms is None:
            self.wall_limit_ms = min(2 * self.time_limit_ms + 1000, 10000)
        if self.wall_limit_ms < self.time_limit_ms:
            raise ValueError("wall_limit_ms must be >= time_limit_ms")
        return self


class ProblemPatchIn(_In):
    title: str | None = Field(default=None, min_length=3, max_length=200)
    statement_md: str | None = Field(default=None, min_length=1, max_length=50_000)
    input_format_md: str | None = Field(default=None, max_length=10_000)
    output_format_md: str | None = Field(default=None, max_length=10_000)
    constraints_md: str | None = Field(default=None, max_length=10_000)
    difficulty: int | None = Field(default=None, ge=1, le=5)
    time_limit_ms: int | None = Field(default=None, ge=100, le=5000)
    wall_limit_ms: int | None = Field(default=None, ge=200, le=10000)
    memory_limit_kb: int | None = Field(default=None, ge=16384, le=524288)
    allowed_languages: list[str] | None = Field(default=None, min_length=1, max_length=16)
    checker_type: Literal["exact", "token", "float_tolerance"] | None = None
    checker_config: dict[str, Any] | None = None
    scoring_mode: Literal["weighted_cases", "all_or_nothing"] | None = None
    is_free: bool | None = None


class TestCaseIn(_In):
    __test__ = False
    kind: Literal["sample", "hidden"]
    input: str = Field(max_length=MAX_CASE_BYTES)
    expected_output: str = Field(max_length=MAX_CASE_BYTES)
    weight: Decimal = Field(default=Decimal(1), ge=0, le=1000)


class RunIn(_In):
    language_key: str = Field(min_length=1, max_length=32)
    source_code: str = Field(min_length=1)
    custom_input: str | None = None
    attempt_id: uuid.UUID | None = None  # in-test run: access via the attempt, not an entitlement


class SubmitIn(_In):
    language_key: str = Field(min_length=1, max_length=32)
    source_code: str = Field(min_length=1)
    attempt_id: uuid.UUID | None = None
    practice_session_id: uuid.UUID | None = None


# --------------------------------------------------------------------------- outputs


class SampleCaseResultOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ordinal: int
    is_sample: Literal[True] = True
    is_custom: bool = False
    verdict: str
    time_ms: int | None
    memory_kb: int | None
    stdout_excerpt: str | None
    expected_output: str | None
    input: str | None


class HiddenCaseResultOut(BaseModel):
    """Exactly the fields allowed for a hidden case — nothing else exists to leak."""

    model_config = ConfigDict(extra="forbid")
    ordinal: int
    is_sample: Literal[False] = False
    verdict: str
    time_ms: int | None
    memory_kb: int | None


class SubmissionOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    submission_id: uuid.UUID
    problem_id: uuid.UUID
    problem_version: int
    language_key: str
    mode: str
    status: str
    notice: str | None
    verdict: str | None
    score: float | None
    max_score: float | None
    passed_cases: int | None
    total_cases: int | None
    max_time_ms: int | None
    max_memory_kb: int | None
    compile_output: str | None
    cases: list[SampleCaseResultOut | HiddenCaseResultOut]
    queued_at: str
    completed_at: str | None
    source_code: str | None = None  # only for submission.code.read staff / own history detail


class HiddenCaseMetaOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test_case_id: uuid.UUID
    ordinal: int
    is_sample: Literal[False] = False
    weight: float
    size_bytes: int | None
    input_sha256: str | None
    expected_sha256: str | None


class SampleCaseMetaOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test_case_id: uuid.UUID
    ordinal: int
    is_sample: Literal[True] = True
    weight: float
    input: str
    expected_output: str


# --------------------------------------------------------------------------- authoring gaps


class DraftIn(_In):
    source_code: str = Field(max_length=MAX_SOURCE_BYTES * 4)  # byte limit enforced as 413


class ReferenceSolutionIn(_In):
    source_code: str = Field(min_length=1, max_length=MAX_SOURCE_BYTES * 4)


class ReferenceSolutionItem(_In):
    language_key: str = Field(min_length=1, max_length=32)
    source_code: str = Field(min_length=1, max_length=MAX_SOURCE_BYTES * 4)


class ValidateIn(_In):
    reference_solutions: list[ReferenceSolutionItem] | None = Field(default=None, max_length=8)
