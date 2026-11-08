"""Analytics tables (database-schema §12). DDL lives in migrations/versions/analytics_*.

Mapped for Alembic autogenerate awareness and simple ORM reads; the hot paths (ingest,
builder, aggregator) use Core SQL in ``service.py`` / ``jobs.py``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Float, Integer, Numeric, SmallInteger, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, BYTEA, INT4RANGE, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

_TS = DateTime(timezone=True)
_U = UUID(as_uuid=True)


class _EntityCols:
    course_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    lesson_asset_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    question_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    test_attempt_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    coding_problem_id: Mapped[uuid.UUID | None] = mapped_column(_U)


class AnalyticsEvent(_EntityCols, Base):
    __tablename__ = "analytics_events"

    event_id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    event_ts: Mapped[datetime] = mapped_column(_TS, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text)
    schema_version: Mapped[int] = mapped_column(SmallInteger)
    source: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text)
    user_id: Mapped[uuid.UUID] = mapped_column(_U)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    auth_session_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    device_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    tab_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    page_instance_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    seq: Mapped[int | None] = mapped_column(Integer)
    route: Mapped[str | None] = mapped_column(Text)
    surface: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(_TS)
    received_at: Mapped[datetime] = mapped_column(_TS)
    effective_at: Mapped[datetime] = mapped_column(_TS)
    skew_ms: Mapped[int] = mapped_column(Integer)
    privacy_tier: Mapped[str] = mapped_column(Text)
    ingest_flags: Mapped[list[str]] = mapped_column(ARRAY(Text))
    measurement_version: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)


class ActivityHeartbeat(_EntityCols, Base):
    __tablename__ = "activity_heartbeats"

    event_id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    event_ts: Mapped[datetime] = mapped_column(_TS, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(_U)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    auth_session_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    device_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    tab_id: Mapped[uuid.UUID] = mapped_column(_U)
    page_instance_id: Mapped[uuid.UUID] = mapped_column(_U)
    seq: Mapped[int] = mapped_column(Integer)
    effective_at: Mapped[datetime] = mapped_column(_TS)
    received_at: Mapped[datetime] = mapped_column(_TS)
    kind: Mapped[str] = mapped_column(Text)
    active_ms: Mapped[int] = mapped_column(Integer)
    sample_interval_ms: Mapped[int | None] = mapped_column(Integer)
    state_bits: Mapped[int] = mapped_column(SmallInteger)
    surface: Mapped[str] = mapped_column(Text)
    route: Mapped[str | None] = mapped_column(Text)
    privacy_tier: Mapped[str] = mapped_column(Text)
    media_position_s: Mapped[Decimal | None] = mapped_column(Numeric(9, 2))
    media_rate: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    played_ranges: Mapped[list[Any] | None] = mapped_column(ARRAY(INT4RANGE))
    edit_ops: Mapped[int | None] = mapped_column(Integer)
    editor_focused: Mapped[bool | None] = mapped_column(Boolean)
    scroll_depth_pct: Mapped[int | None] = mapped_column(SmallInteger)
    input_events: Mapped[int | None] = mapped_column(Integer)
    ingest_flags: Mapped[list[str]] = mapped_column(ARRAY(Text))


class EngagementInterval(_EntityCols, Base):
    __tablename__ = "engagement_intervals"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(_TS, primary_key=True)
    ended_at: Mapped[datetime | None] = mapped_column(_TS)
    last_sample_at: Mapped[datetime] = mapped_column(_TS)
    provisional_end: Mapped[datetime] = mapped_column(_TS)
    user_id: Mapped[uuid.UUID] = mapped_column(_U)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    auth_session_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    device_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    tab_id: Mapped[uuid.UUID] = mapped_column(_U)
    page_instance_id: Mapped[uuid.UUID] = mapped_column(_U)
    surface: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(Text)
    active_s: Mapped[Decimal] = mapped_column(Numeric(10, 3))
    heartbeat_count: Mapped[int] = mapped_column(Integer)
    close_reason: Mapped[str | None] = mapped_column(Text)
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text))
    is_open: Mapped[bool] = mapped_column(Boolean)
    privacy_tier: Mapped[str] = mapped_column(Text)
    measurement_version: Mapped[str] = mapped_column(Text)
    built_at: Mapped[datetime] = mapped_column(_TS)


class DailyLearningAggregate(Base):
    __tablename__ = "daily_learning_aggregates"

    user_id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    activity_date: Mapped[date] = mapped_column(Date, primary_key=True)
    entity_kind: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    course_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    topic_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    category_topic_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    m1_session_elapsed_s: Mapped[int | None] = mapped_column(Integer)
    m2_active_s: Mapped[int] = mapped_column(Integer)
    m3_video_playback_s: Mapped[int] = mapped_column(Integer)
    m4_assessment_s: Mapped[int] = mapped_column(Integer)
    m5_learning_s: Mapped[int] = mapped_column(Integer)
    assessment_active_s: Mapped[int] = mapped_column(Integer)
    questions_attempted: Mapped[int] = mapped_column(Integer)
    questions_correct: Mapped[int] = mapped_column(Integer)
    first_attempt_correct: Mapped[int] = mapped_column(Integer)
    code_runs: Mapped[int] = mapped_column(Integer)
    code_submissions: Mapped[int] = mapped_column(Integer)
    code_accepted: Mapped[int] = mapped_column(Integer)
    lessons_completed: Mapped[int] = mapped_column(Integer)
    video_coverage_gain_s: Mapped[int] = mapped_column(Integer)
    implausible_day: Mapped[bool] = mapped_column(Boolean)
    privacy_tier: Mapped[str] = mapped_column(Text)
    measurement_version: Mapped[str] = mapped_column(Text)
    is_frozen: Mapped[bool] = mapped_column(Boolean)
    computed_at: Mapped[datetime] = mapped_column(_TS)


class WeeklyLearningAggregate(Base):
    __tablename__ = "weekly_learning_aggregates"

    user_id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    iso_week_start: Mapped[date] = mapped_column(Date, primary_key=True)
    entity_kind: Mapped[str] = mapped_column(Text, primary_key=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    m2_active_s: Mapped[int] = mapped_column(Integer)
    m3_video_playback_s: Mapped[int] = mapped_column(Integer)
    m4_assessment_s: Mapped[int] = mapped_column(Integer)
    m5_learning_s: Mapped[int] = mapped_column(Integer)
    active_days: Mapped[int] = mapped_column(SmallInteger)
    privacy_tier: Mapped[str] = mapped_column(Text)
    measurement_version: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(_TS)


class CohortLearningAggregate(Base):
    __tablename__ = "cohort_learning_aggregates"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    period_kind: Mapped[str] = mapped_column(Text)
    period_start: Mapped[date] = mapped_column(Date)
    entity_kind: Mapped[str] = mapped_column(Text)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    learners_enrolled: Mapped[int | None] = mapped_column(Integer)
    learners_active: Mapped[int | None] = mapped_column(Integer)
    m5_sum_s: Mapped[int | None] = mapped_column(BigInteger)
    m5_p50_s: Mapped[int | None] = mapped_column(Integer)
    m5_p90_s: Mapped[int | None] = mapped_column(Integer)
    completions: Mapped[int | None] = mapped_column(Integer)
    accuracy: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    score_deciles: Mapped[list[Decimal] | None] = mapped_column(ARRAY(Numeric(7, 2)))
    suppressed: Mapped[bool] = mapped_column(Boolean)
    measurement_version: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(_TS)


class RouteDailyAggregate(Base):
    __tablename__ = "route_daily_aggregates"

    route: Mapped[str] = mapped_column(Text, primary_key=True)
    activity_date: Mapped[date] = mapped_column(Date, primary_key=True)
    views: Mapped[int] = mapped_column(Integer)
    unique_users_hll: Mapped[bytes | None] = mapped_column(BYTEA)
    unique_users_est: Mapped[int | None] = mapped_column(Integer)
    m2_p50_s: Mapped[int | None] = mapped_column(Integer)
    bounce_count: Mapped[int] = mapped_column(Integer)
    buffering_events: Mapped[int] = mapped_column(Integer)
    computed_at: Mapped[datetime] = mapped_column(_TS)


class VideoWatchCoverage(Base):
    __tablename__ = "video_watch_coverage"

    user_id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    lesson_asset_id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    lesson_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    covered_ranges: Mapped[list[Any]] = mapped_column(ARRAY(INT4RANGE))
    covered_s: Mapped[Decimal] = mapped_column(Numeric(10, 1))
    coverage_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))
    duration_s: Mapped[int | None] = mapped_column(Integer)
    last_position_s: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(_TS)


class TopicMastery(Base):
    __tablename__ = "topic_mastery"

    user_id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    topic_id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    theta: Mapped[Decimal] = mapped_column(Numeric(6, 3))
    n_eff: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    attempts: Mapped[int] = mapped_column(Integer)
    correct: Mapped[int] = mapped_column(Integer)
    weighted_accuracy: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    wa_num: Mapped[float] = mapped_column(Float)
    wa_den: Mapped[float] = mapped_column(Float)
    band: Mapped[str] = mapped_column(Text)
    avg_time_ms: Mapped[int | None] = mapped_column(Integer)
    last_practiced_at: Mapped[datetime | None] = mapped_column(_TS)
    model_version: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(_TS)


class QuestionItemStats(Base):
    __tablename__ = "question_item_stats"

    question_version_id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    n_first: Mapped[int] = mapped_column(Integer)
    p_value: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    median_time_s: Mapped[int | None] = mapped_column(Integer)
    skip_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    option_dist: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    point_biserial: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    difficulty_b: Mapped[Decimal | None] = mapped_column(Numeric(6, 3))
    n_updates: Mapped[int] = mapped_column(Integer)
    review_flag: Mapped[bool] = mapped_column(Boolean)
    computed_at: Mapped[datetime] = mapped_column(_TS)


class SecurityActivityFeedDaily(Base):
    __tablename__ = "security_activity_feed_daily"

    user_id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    activity_date: Mapped[date] = mapped_column(Date, primary_key=True)
    privacy_tier: Mapped[str] = mapped_column(Text)
    active_devices: Mapped[int] = mapped_column(SmallInteger)
    multi_device_overlap_s: Mapped[int] = mapped_column(Integer)
    max_concurrent_active_page_instances: Mapped[int] = mapped_column(SmallInteger)
    active_hours_bitmap: Mapped[int] = mapped_column(Integer)
    implausible_day: Mapped[bool] = mapped_column(Boolean)
    plausibility_violations: Mapped[dict[str, Any]] = mapped_column(JSONB)
    clock_jump_count: Mapped[int] = mapped_column(Integer)
    large_skew_count: Mapped[int] = mapped_column(Integer)
    feed_version: Mapped[str] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(_TS)


class AnalyticsDirtyDay(Base):
    __tablename__ = "analytics_dirty_days"

    user_id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    activity_date: Mapped[date] = mapped_column(Date, primary_key=True)
    reason: Mapped[str] = mapped_column(Text)
    marked_at: Mapped[datetime] = mapped_column(_TS)


class AnalyticsIngestRejection(Base):
    __tablename__ = "analytics_ingest_rejections"

    hour_start: Mapped[datetime] = mapped_column(_TS, primary_key=True)
    code: Mapped[str] = mapped_column(Text, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text, primary_key=True)
    count: Mapped[int] = mapped_column(BigInteger)


class AnalyticsJobState(Base):
    __tablename__ = "analytics_job_state"

    job: Mapped[str] = mapped_column(Text, primary_key=True)
    watermark: Mapped[datetime | None] = mapped_column(_TS)
    last_run_at: Mapped[datetime | None] = mapped_column(_TS)
    last_duration_ms: Mapped[int | None] = mapped_column(Integer)
    last_result: Mapped[dict[str, Any]] = mapped_column(JSONB)


class AnalyticsConsumedEvent(Base):
    __tablename__ = "analytics_consumed_events"

    outbox_event_id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    event_type: Mapped[str] = mapped_column(Text)
    consumed_at: Mapped[datetime] = mapped_column(_TS)


class ExportJob(Base):
    """ANL-13..15 audited, expiring report exports (migration ``analytics_0002``)."""

    __tablename__ = "export_jobs"

    id: Mapped[uuid.UUID] = mapped_column(_U, primary_key=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(_U, nullable=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    report_key: Mapped[str] = mapped_column(Text, nullable=False)
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    filters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    format: Mapped[str] = mapped_column(Text, nullable=False, server_default="csv")
    contains_pii: Mapped[bool] = mapped_column(Boolean, nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="requested")
    approval_request_id: Mapped[uuid.UUID | None] = mapped_column(_U)
    reason_code: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    file_s3_key: Mapped[str | None] = mapped_column(Text)
    file_sha256: Mapped[bytes | None] = mapped_column(BYTEA)
    watermark: Mapped[str | None] = mapped_column(Text)
    failure_code: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(_TS)
    downloaded_at: Mapped[datetime | None] = mapped_column(_TS)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    completed_at: Mapped[datetime | None] = mapped_column(_TS)
    created_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(_TS, nullable=False, server_default=func.now())
