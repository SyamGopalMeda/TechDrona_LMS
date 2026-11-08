"""Assessments request schemas (responses are built as dicts by the services; question payloads
inside them are ``placement.schemas.QuestionDelivery`` — key-free by construction)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

TestKind = Literal["practice_set", "mock", "company_mock", "diagnostic", "course_quiz", "drive"]
# Exam-protocol events a client may report (advisory evidence; the server decides what is kept).
# ``focus_lost`` = the tab was hidden (tab switch / minimise); ``window_blur`` = the window lost focus.
RecordableEvent = Literal[
    "focus_lost", "window_blur", "copy", "cut", "paste", "resize", "fullscreen_exit", "right_click"
]
RECORDABLE_EVENTS: tuple[str, ...] = (
    "focus_lost",
    "window_blur",
    "copy",
    "cut",
    "paste",
    "resize",
    "fullscreen_exit",
    "right_click",
)
INTEGRITY_EVENTS = (*RECORDABLE_EVENTS, "focus_gained", "disconnect", "reconnect")
PHASE_KEYS = ("score", "correctness", "answer_key", "explanation", "section_analytics", "rank")


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PhaseVisibility(_In):
    score: bool = False
    correctness: bool = False
    answer_key: bool = False
    explanation: bool = False
    section_analytics: bool = False
    rank: bool = False


class ReviewPolicy(_In):
    during: PhaseVisibility = PhaseVisibility()
    after_submit: PhaseVisibility = PhaseVisibility(score=True, section_analytics=True)
    after_close: PhaseVisibility = PhaseVisibility(
        score=True, correctness=True, answer_key=True, explanation=True, section_analytics=True, rank=True
    )
    release_at: datetime | None = None

    @model_validator(mode="after")
    def _never_during(self) -> ReviewPolicy:
        # Keys/correctness never leave the server while an attempt is in progress.
        if self.during.correctness or self.during.answer_key or self.during.explanation:
            raise ValueError("review_policy.during cannot reveal correctness, keys or explanations")
        return self


class IntegritySettings(_In):
    """``tests.integrity_settings``. Legacy keys (``fullscreen``/``log_*``/``consent_mandatory``/
    ``single_device_binding``) keep their meaning; ``exam_mode`` turns on the exam protocol
    (agreement screen, recorded events, live warnings, auto-flag for staff review)."""

    fullscreen: bool = False
    log_focus: bool = True
    log_paste: bool = True
    consent_mandatory: bool = False
    single_device_binding: bool = False
    exam_mode: bool = False
    require_agreement: bool = False
    conduct_instructions: str | None = Field(default=None, max_length=5000)
    record_events: list[RecordableEvent] | None = None
    require_fullscreen: bool = False
    # Per event type: count at which that type is marked "over threshold" (and flags the attempt).
    warn_thresholds: dict[RecordableEvent, int] = Field(default_factory=dict)
    # Total recorded events (all types) at which the attempt is flagged for staff review.
    flag_threshold: int | None = Field(default=None, ge=1, le=1000)
    # Opt-in: submit the attempt automatically after this many recorded events (default off).
    auto_submit_after: int | None = Field(default=None, ge=1, le=1000)
    ai_hints: bool = False

    @model_validator(mode="after")
    def _shape(self) -> IntegritySettings:
        if self.ai_hints:
            raise ValueError("AI hints are always off in assessments")
        if any(not 1 <= v <= 1000 for v in self.warn_thresholds.values()):
            raise ValueError("warn_thresholds values must be between 1 and 1000")
        if self.exam_mode:
            self.require_agreement = True
        if self.record_events is not None:
            self.record_events = sorted(set(self.record_events), key=RECORDABLE_EVENTS.index)
        return self


class TestSettings(_In):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    slug: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,80}$")
    company_id: uuid.UUID | None = None
    company_path_id: uuid.UUID | None = None
    duration_seconds: int | None = Field(default=None, gt=0, le=6 * 3600)
    grace_seconds: int | None = Field(default=None, ge=0, le=300)
    navigation_mode: Literal["free", "sequential", "section_locked"] | None = None
    attempts_allowed: int | None = Field(default=None, gt=0, le=100)
    grading_method: Literal["highest", "latest", "first", "average"] | None = None
    shuffle_questions: bool | None = None
    shuffle_options: bool | None = None
    review_policy: ReviewPolicy | None = None
    integrity_settings: IntegritySettings | None = None
    pass_percentage: Decimal | None = Field(default=None, ge=0, le=100)
    is_free: bool | None = None
    available_from: datetime | None = None
    available_until: datetime | None = None


class TestCreate(TestSettings):
    __test__ = False
    title: str = Field(min_length=1, max_length=300)
    test_kind: TestKind
    # Owner: ``null`` = platform test; the company org (or ``batch_id``) = a company test. Any
    # other organization id is unknown (404).
    organization_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None  # scope hint for batch-scoped trainers (owner = the batch's org)


class RuleIn(_In):
    rule_type: Literal["fixed", "random"]
    question_id: uuid.UUID | None = None
    question_version_id: uuid.UUID | None = None
    # Fixed coding item by problem: resolved to the published bank ``coding`` question that
    # wraps this coding problem (stored as ``question_id``).
    coding_problem_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    # ``coding`` draws published coding questions of the topic subtree (coding sections);
    # omitted = objective types only.
    question_types: list[Literal["mcq_single", "mcq_multi", "numeric", "fill_blank", "coding"]] | None = None
    difficulty_min: int | None = Field(default=None, ge=1, le=5)
    difficulty_max: int | None = Field(default=None, ge=1, le=5)
    draw_count: int = Field(default=1, ge=1, le=200)
    marks_each: Decimal | None = Field(default=None, gt=0, le=100)
    negative_marks_each: Decimal | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _shape(self) -> RuleIn:
        if self.rule_type == "fixed" and (
            (self.question_id is None) == (self.coding_problem_id is None) or self.draw_count != 1
        ):
            raise ValueError(
                "fixed rules need exactly one of question_id or coding_problem_id, and draw_count 1"
            )
        if self.coding_problem_id is not None and self.question_version_id is not None:
            raise ValueError("question_version_id cannot be combined with coding_problem_id")
        if self.rule_type == "random" and (
            self.question_id is not None or self.coding_problem_id is not None or self.topic_id is None
        ):
            raise ValueError("random rules need topic_id and no question_id or coding_problem_id")
        if self.difficulty_min and self.difficulty_max and self.difficulty_min > self.difficulty_max:
            raise ValueError("difficulty_min must be <= difficulty_max")
        return self


class SectionIn(_In):
    title: str = Field(min_length=1, max_length=200)
    duration_seconds: int | None = Field(default=None, gt=0, le=6 * 3600)
    instructions_md: str | None = Field(default=None, max_length=10000)
    rules: list[RuleIn] = Field(min_length=1, max_length=50)


class SectionsPut(_In):
    sections: list[SectionIn] = Field(min_length=1, max_length=20)


class AssignmentCreate(_In):
    # Single company: a test is assigned to a batch (the whole-organization target is gone).
    batch_id: uuid.UUID
    available_from: datetime
    available_until: datetime
    attempts_allowed: int | None = Field(default=None, gt=0, le=100)
    release_mode: Literal["immediate", "after_window", "scheduled", "manual"] = "immediate"
    results_release_at: datetime | None = None

    @model_validator(mode="after")
    def _shape(self) -> AssignmentCreate:
        if self.available_until <= self.available_from:
            raise ValueError("available_until must be after available_from")
        if self.release_mode == "scheduled" and self.results_release_at is None:
            raise ValueError("results_release_at is required for scheduled release")
        return self


class AssignmentPatch(_In):
    available_from: datetime | None = None
    available_until: datetime | None = None
    attempts_allowed: int | None = Field(default=None, gt=0, le=100)
    release_mode: Literal["immediate", "after_window", "scheduled", "manual"] | None = None
    results_release_at: datetime | None = None


class OverrideCreate(_In):
    user_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    test_assignment_id: uuid.UUID | None = None
    extra_time_seconds: int = Field(default=0, ge=0, le=6 * 3600)
    extra_attempts: int = Field(default=0, ge=0, le=10)
    window_extension_seconds: int = Field(default=0, ge=0, le=30 * 86400)
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def _shape(self) -> OverrideCreate:
        if (self.user_id is None) == (self.batch_id is None):
            raise ValueError("exactly one of user_id or batch_id is required")
        if not (self.extra_time_seconds or self.extra_attempts or self.window_extension_seconds):
            raise ValueError("the override grants nothing")
        return self


class ReleaseIn(_In):
    test_assignment_id: uuid.UUID


class RebindOverrideIn(_In):
    reason: str = Field(min_length=3, max_length=500)


# --------------------------------------------------------------------------- attempts


class AttemptStart(_In):
    test_id: uuid.UUID
    test_assignment_id: uuid.UUID | None = None
    integrity_consent: bool = False
    # Exam protocol: the candidate agreed to the conduct instructions (starts the timer).
    instructions_agreed: bool = False
    client_info: dict[str, Any] | None = None


class AutosaveItem(_In):
    question_version_id: uuid.UUID
    response: dict[str, Any] | None = None
    client_seq: int = Field(ge=0, le=2**62)
    time_spent_ms: int = Field(default=0, ge=0, le=24 * 3600 * 1000)
    flagged: bool = False


class IntegrityEvent(_In):
    type: Literal[
        "focus_lost",
        "window_blur",
        "copy",
        "cut",
        "paste",
        "resize",
        "fullscreen_exit",
        "right_click",
        "focus_gained",
        "disconnect",
        "reconnect",
    ]
    client_at: datetime | None = None
    client_seq: int = Field(ge=0, le=2**62)


class AutosaveIn(_In):
    items: list[AutosaveItem] = Field(default=[], max_length=50)
    events: list[IntegrityEvent] = Field(default=[], max_length=50)
    current_section_id: uuid.UUID | None = None


class SubmitIn(_In):
    final_items: list[AutosaveItem] = Field(default=[], max_length=200)
    confirm_unanswered: int | None = Field(default=None, ge=0)


class RebindIn(_In):
    confirm: bool
    otp_code: str | None = Field(default=None, min_length=4, max_length=10)


# --------------------------------------------------------------------------- integrity review


class IntegrityDecisionIn(_In):
    outcome: Literal["no_action", "refer_security", "invalidate"]
    note: str = Field(min_length=3, max_length=2000)


class InvalidateIn(_In):
    reason: str = Field(min_length=3, max_length=2000)


# --------------------------------------------------------------------------- evaluation


class AiGradeIn(_In):
    attempt_id: uuid.UUID | None = None  # one learner (Review modal) or all submitted attempts
    redo: bool = False  # replace existing (not finalized) AI suggestions


class ItemGradeIn(_In):
    marks: Decimal = Field(ge=0, le=1000)
    feedback: str | None = Field(default=None, max_length=10000)
