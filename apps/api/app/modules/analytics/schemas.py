"""Wire schemas (analytics-event-schema §1.4, §2). ``extra="forbid"`` everywhere: the client
can never send identity fields (``user_id``, ``organization_id``, ``auth_session_id``,
``device_id``, ``privacy_tier``)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator

UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
UUID7_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
ROUTE_RE = r"^/[A-Za-z0-9_\-/\[\]]*$"

Uuid = str  # pattern-checked per field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClientInfo(_Strict):
    app_version: str = Field(max_length=32)
    platform: Literal["web", "android_webview", "ios_webview"]
    tz_offset_min: int | None = Field(default=None, ge=-840, le=840)
    measurement_version: Literal["tm-1.0"] | None = None


class BatchIn(_Strict):
    """Top-level batch; events are validated one by one (per-event results, §5.3)."""

    sent_at: AwareDatetime
    csrf: str | None = Field(default=None, max_length=256)  # beacon only; validated by the BFF
    client: ClientInfo
    events: list[dict[str, Any]] = Field(min_length=1, max_length=100)


def _uuid_field() -> Any:
    return Field(default=None, pattern=UUID_RE)


class EntityIn(_Strict):
    course_id: str | None = _uuid_field()
    course_version_id: str | None = _uuid_field()
    lesson_id: str | None = _uuid_field()
    lesson_asset_id: str | None = _uuid_field()
    topic_id: str | None = _uuid_field()
    company_path_id: str | None = _uuid_field()
    question_id: str | None = _uuid_field()
    question_version_id: str | None = _uuid_field()
    test_id: str | None = _uuid_field()
    test_attempt_id: str | None = _uuid_field()
    test_section_id: str | None = _uuid_field()
    coding_problem_id: str | None = _uuid_field()
    assignment_id: str | None = _uuid_field()
    batch_id: str | None = _uuid_field()

    def uuid(self, name: str) -> uuid.UUID | None:
        v = getattr(self, name)
        return uuid.UUID(v) if v else None


class EventIn(_Strict):
    event_id: str = Field(pattern=UUID7_RE)
    event_type: str = Field(pattern=r"^[a-z]+\.[a-z_]+$", max_length=48)
    schema_version: int = Field(ge=1, le=99)
    occurred_at: AwareDatetime
    mono_ms: int = Field(ge=0)
    tab_id: str = Field(pattern=UUID_RE)
    page_instance_id: str = Field(pattern=UUID_RE)
    seq: int = Field(ge=0)
    route: str = Field(max_length=200, pattern=ROUTE_RE)
    surface: (
        Literal[
            "lesson_text",
            "lesson_video",
            "practice",
            "test",
            "coding",
            "dashboard",
            "catalog",
            "account",
            "other",
        ]
        | None
    ) = None
    entity: EntityIn | None = None
    payload: dict[str, Any] = Field(max_length=24)


# --------------------------------------------------------------------------- payloads (v1)


class HeartbeatState(_Strict):
    visible: bool
    focused: bool
    input_recent: bool
    media_playing: bool


class HeartbeatMedia(_Strict):
    lesson_asset_id: str | None = Field(default=None, pattern=UUID_RE)
    position_s: float | None = Field(default=None, ge=0)
    rate: float | None = Field(default=None, ge=0.25, le=2.0)
    played_ranges: list[list[float]] | None = Field(default=None, max_length=8)

    @field_validator("played_ranges")
    @classmethod
    def _pairs(cls, v: list[list[float]] | None) -> list[list[float]] | None:
        if v is None:
            return v
        for r in v:
            if len(r) != 2 or r[0] < 0 or r[1] < r[0]:
                raise ValueError("played_ranges items must be [from, to] with 0 <= from <= to")
        return v


class HeartbeatEditor(_Strict):
    focused: bool | None = None
    edit_ops: int | None = Field(default=None, ge=0, le=5000)


class HeartbeatReading(_Strict):
    max_scroll_depth_pct: int | None = Field(default=None, ge=0, le=100)


class HeartbeatPayload(_Strict):
    kind: Literal["engaged", "keepalive"]
    sample_interval_ms: int = Field(ge=1000, le=330000)
    active_ms: int = Field(ge=0, le=20000)
    state: HeartbeatState
    input_events: int | None = Field(default=None, ge=0, le=1000)
    media: HeartbeatMedia | None = None
    editor: HeartbeatEditor | None = None
    reading: HeartbeatReading | None = None


class PageViewPayload(_Strict):
    nav_type: Literal["navigate", "reload", "back_forward", "spa"]
    referrer_route: str | None = Field(default=None, max_length=200, pattern=ROUTE_RE)
    visible: bool
    focused: bool


class VisibilityPayload(_Strict):
    visible: bool


class EmptyPayload(_Strict):
    pass


class IdleChangePayload(_Strict):
    idle: bool
    idle_threshold_s: int = Field(ge=1, le=3600)


class PageHidePayload(_Strict):
    reason: Literal["pagehide", "freeze", "route_change"]
    persisted: bool | None = None


class VideoPosPayload(_Strict):
    position_s: float = Field(ge=0)


class VideoPlayPayload(_Strict):
    position_s: float = Field(ge=0)
    rate: float = Field(ge=0.25, le=2.0)


class VideoSeekPayload(_Strict):
    from_s: float = Field(ge=0)
    to_s: float = Field(ge=0)


class VideoRatePayload(_Strict):
    from_rate: float = Field(ge=0.25, le=2.0)
    to_rate: float = Field(ge=0.25, le=2.0)
    position_s: float = Field(ge=0)


class VideoEndedPayload(_Strict):
    position_s: float = Field(ge=0)
    duration_s: float = Field(gt=0)


class VideoBufferingPayload(_Strict):
    position_s: float = Field(ge=0)
    buffer_ms: int = Field(ge=0)
    bitrate_kbps: int | None = Field(default=None, ge=0)


class VideoErrorPayload(_Strict):
    code: str = Field(max_length=32, pattern=r"^[A-Za-z0-9_.\-]+$")
    position_s: float = Field(ge=0)


class QuestionViewedPayload(_Strict):
    position_in_set: int = Field(ge=0)
    set_id: str | None = Field(default=None, pattern=UUID_RE)


class AssessmentQuestionViewedPayload(_Strict):
    question_index: int = Field(ge=0)


class EditorFocusPayload(_Strict):
    language: str | None = Field(default=None, max_length=32, pattern=r"^[a-z0-9_+#.\-]+$")


PAYLOAD_MODELS: dict[tuple[str, int], type[BaseModel]] = {
    ("page.heartbeat", 1): HeartbeatPayload,
    ("page.view", 1): PageViewPayload,
    ("page.visibility_change", 1): VisibilityPayload,
    ("page.focus", 1): EmptyPayload,
    ("page.blur", 1): EmptyPayload,
    ("page.idle_change", 1): IdleChangePayload,
    ("page.hide", 1): PageHidePayload,
    ("video.play", 1): VideoPlayPayload,
    ("video.pause", 1): VideoPosPayload,
    ("video.seek", 1): VideoSeekPayload,
    ("video.rate_change", 1): VideoRatePayload,
    ("video.ended", 1): VideoEndedPayload,
    ("video.buffering", 1): VideoBufferingPayload,
    ("video.error", 1): VideoErrorPayload,
    ("practice.question_viewed", 1): QuestionViewedPayload,
    ("assessment.question_viewed", 1): AssessmentQuestionViewedPayload,
    ("coding.editor_focus", 1): EditorFocusPayload,
    ("coding.editor_blur", 1): EditorFocusPayload,
}


def parse_payload(event_type: str, version: int, payload: dict[str, Any]) -> BaseModel | None:
    """Validated payload model, or ``None`` when invalid."""
    model = PAYLOAD_MODELS.get((event_type, version))
    if model is None:
        return None
    try:
        return model.model_validate(payload)
    except ValidationError:
        return None


# --------------------------------------------------------------------------- responses


class EventResult(BaseModel):
    event_id: str
    status: Literal["accepted", "duplicate", "rejected"]
    code: str | None = None


class IngestOut(BaseModel):
    accepted: int
    duplicate: int
    rejected: int
    results: list[EventResult]
    server_time: str
    config_version: str


class LearningTimePoint(BaseModel):
    period_start: date
    learning_s: int
    active_s: int
    video_s: int
    assessment_s: int
    active_days: int | None = None


class LearningTimeOut(BaseModel):
    grain: Literal["day", "week"]
    measurement_version: str
    points: list[LearningTimePoint]


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)
