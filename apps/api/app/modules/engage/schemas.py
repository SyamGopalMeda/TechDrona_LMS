"""Request bodies for the engage endpoints (responses are plain dicts built in ``service``)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ActivityType = Literal["quiz", "poll", "word_cloud", "survey"]
QuestionKind = Literal["single_choice", "multi_choice", "word", "text", "rating"]
RunMode = Literal["instant", "scheduled"]
Audience = Literal["members", "public"]
IdentityMode = Literal["named", "anonymous"]
ResultsMode = Literal["live", "on_publish"]
Pacing = Literal["all_at_once", "one_by_one"]
WinnerRule = Literal["fastest_first", "all_correct"]

# Which question kinds each activity type may contain.
KINDS_BY_TYPE: dict[str, frozenset[str]] = {
    "quiz": frozenset({"single_choice", "multi_choice"}),
    "poll": frozenset({"single_choice", "multi_choice"}),
    "word_cloud": frozenset({"word"}),
    "survey": frozenset({"single_choice", "multi_choice", "text", "rating"}),
}
CHOICE_KINDS = frozenset({"single_choice", "multi_choice"})
MAX_QUESTIONS = 50


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OptionIn(_In):
    id: uuid.UUID | None = None
    text: Annotated[str, Field(min_length=1, max_length=500)]
    is_correct: bool = False


class QuestionIn(_In):
    kind: QuestionKind
    prompt: Annotated[str, Field(min_length=1, max_length=2000)]
    options: Annotated[list[OptionIn], Field(max_length=10)] = []
    max_words: Annotated[int | None, Field(ge=1, le=5)] = None
    source_question_id: uuid.UUID | None = None
    source_version_id: uuid.UUID | None = None


class ActivityIn(_In):
    activity_type: ActivityType
    title: Annotated[str, Field(min_length=1, max_length=200)]
    description: Annotated[str | None, Field(max_length=500)] = None
    # Single company: an activity targets one batch, or (batch_id null) the platform. There is
    # no organization-wide target and no organization picker (extra=forbid rejects the field).
    batch_id: uuid.UUID | None = None
    run_mode: RunMode = "instant"
    audience: Audience = "members"
    identity_mode: IdentityMode = "named"
    results_mode: ResultsMode = "live"
    pacing: Pacing = "all_at_once"
    winner_rule: WinnerRule | None = None
    participant_limit: Annotated[int | None, Field(ge=1, le=10000)] = None
    opens_at: datetime | None = None
    closes_at: datetime | None = None
    questions: Annotated[list[QuestionIn], Field(max_length=MAX_QUESTIONS)] = []


class LaunchIn(_In):
    opens_at: datetime | None = None
    closes_at: datetime | None = None


ControlAction = Literal["start", "close", "goto", "reveal", "hide", "publish", "unpublish", "finalise"]


class ControlIn(_In):
    action: ControlAction
    position: Annotated[int | None, Field(ge=0, le=MAX_QUESTIONS)] = None


class AnswerIn(_In):
    question_id: uuid.UUID
    option_ids: Annotated[list[uuid.UUID] | None, Field(max_length=10)] = None
    text: Annotated[str | None, Field(max_length=500)] = None
    rating: Annotated[int | None, Field(ge=1, le=5)] = None


class BankImportIn(_In):
    question_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=MAX_QUESTIONS)]
