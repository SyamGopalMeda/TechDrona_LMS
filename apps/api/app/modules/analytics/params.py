"""Measurement model ``tm-1.0`` parameters, k-floors, retention and the event catalogue
(analytics-event-schema §2, §3.1, §4.4, §4.5, §5.2).

Changing any ``tm`` parameter bumps the measurement version (§3.12). ``policy_settings``
overrides (``analytics.tm.*``) are Planned; v1 uses these defaults.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Literal

MEASUREMENT_VERSION = "tm-1.0"
MASTERY_MODEL_VERSION = "mastery-1.0"
FEED_VERSION = "feed-1.0"

Purpose = Literal["learning", "product"]
Store = Literal["events", "heartbeats"]


@dataclass(frozen=True)
class TimeModel:
    heartbeat_s: float = 15.0  # H
    flush_s: float = 30.0  # F
    keepalive_s: float = 300.0  # K
    idle_s: float = 90.0  # generic T_idle
    idle_by_surface_s: dict[str, float] = field(
        default_factory=lambda: {
            "lesson_text": 180.0,
            "practice": 240.0,
            "coding": 180.0,
            "test": 300.0,
            "lesson_video": 90.0,
        }
    )
    c_max_s: float = 20.0  # per-sample credit cap
    grace_s: float = 7.5  # G = H/2
    d_close_s: float = 65.0  # 2F + 5
    merge_eps_s: float = 5.0  # eps_merge
    session_gap_s: float = 30 * 60.0  # S_gap
    late_window: timedelta = timedelta(hours=72)  # L_late
    uuid_time_tolerance: timedelta = timedelta(minutes=5)
    large_skew_ms: int = 10 * 60 * 1000
    clock_jump_ms: int = 2000
    evidence_window_s: float = 300.0  # ±5 min (M5 evidence rule)
    implausible_day_s: int = 16 * 3600
    late_flag_after: timedelta = timedelta(minutes=5)
    freeze_after_days: int = 4  # a day is frozen at D+4
    # Per-item MLAT caps (§3.1)
    cap_practice_question_s: float = 600.0
    cap_lesson_text_min_s: float = 600.0
    cap_lesson_text_factor: float = 3.0
    default_est_reading_min: float = 10.0  # used when the catalog has no estimate (documented)
    cap_video_factor: float = 1.25
    cap_coding_problem_s: float = 7200.0

    def idle_for(self, surface: str | None) -> float:
        return self.idle_by_surface_s.get(surface or "", self.idle_s)


TM = TimeModel()

LEARNING_SURFACES = frozenset({"lesson_text", "lesson_video", "practice", "test", "coding"})
SURFACES = frozenset(
    {"lesson_text", "lesson_video", "practice", "test", "coding", "dashboard", "catalog", "account", "other"}
)

# k-floors (§4.5; reconciliation §3.12)
K_MIN_COHORT = 10
K_MIN_ITEM = 10
K_MIN_CROSS_ORG_DISPLAY = 50
K_MIN_PERCENTILE_REFERENCE = 20

# Ingest limits (§5.2 — the single authoritative source)
MAX_BODY_BYTES = 64 * 1024
MAX_EVENTS_PER_BATCH = 100
MAX_EVENT_BYTES = 4096
MAX_PAYLOAD_PROPS = 24
MAX_PAYLOAD_DEPTH = 3
MAX_PAYLOAD_STRING = 256
RATE_SESSION_PER_MIN = 30
RATE_SESSION_BURST_10S = 10
RATE_USER_PER_MIN = 60
RATE_IP_PER_MIN = 600
MIN_ENGAGED_GAP_S = 10.0

# Retention (§4.4; database-schema §1.4)
RETENTION = {
    "activity_heartbeats": timedelta(days=35),
    "analytics_events": timedelta(days=90),
    "engagement_intervals": timedelta(days=396),  # 13 months
    "aggregates": timedelta(days=730),  # 24 months identifiable
    "security_activity_feed_daily": timedelta(days=180),
    "analytics_ingest_rejections": timedelta(days=90),
}


@dataclass(frozen=True)
class EventSpec:
    purpose: Purpose
    store: Store
    server_only: bool = False


_L: Purpose = "learning"
_P: Purpose = "product"

EVENT_CATALOGUE: dict[str, EventSpec] = {
    # 2.1 page lifecycle (client)
    "page.view": EventSpec(_L, "events"),
    "page.visibility_change": EventSpec(_L, "events"),
    "page.focus": EventSpec(_L, "events"),
    "page.blur": EventSpec(_L, "events"),
    "page.idle_change": EventSpec(_L, "events"),
    "page.heartbeat": EventSpec(_L, "heartbeats"),
    "page.hide": EventSpec(_L, "events"),
    # 2.2 video (client)
    "video.play": EventSpec(_L, "events"),
    "video.pause": EventSpec(_L, "events"),
    "video.seek": EventSpec(_L, "events"),
    "video.rate_change": EventSpec(_L, "events"),
    "video.ended": EventSpec(_L, "events"),
    "video.buffering": EventSpec(_P, "events"),
    "video.error": EventSpec(_P, "events"),
    # 2.3 practice
    "practice.question_viewed": EventSpec(_L, "events"),
    "practice.hint_viewed": EventSpec(_L, "events", server_only=True),
    "practice.solution_viewed": EventSpec(_L, "events", server_only=True),
    "practice.answer_submitted": EventSpec(_L, "events", server_only=True),
    # 2.4 assessment
    "assessment.attempt_started": EventSpec(_L, "events", server_only=True),
    "assessment.attempt_resumed": EventSpec(_L, "events", server_only=True),
    "assessment.section_entered": EventSpec(_L, "events", server_only=True),
    "assessment.question_viewed": EventSpec(_L, "events"),
    "assessment.answer_saved": EventSpec(_L, "events", server_only=True),
    "assessment.attempt_submitted": EventSpec(_L, "events", server_only=True),
    "assessment.auto_submitted": EventSpec(_L, "events", server_only=True),
    # 2.5 coding
    "coding.editor_focus": EventSpec(_L, "events"),
    "coding.editor_blur": EventSpec(_L, "events"),
    "coding.run": EventSpec(_L, "events", server_only=True),
    "coding.submit": EventSpec(_L, "events", server_only=True),
    "coding.submission_judged": EventSpec(_L, "events", server_only=True),
    # 2.6 learning
    "learning.lesson_started": EventSpec(_L, "events", server_only=True),
    "learning.lesson_completed": EventSpec(_L, "events", server_only=True),
    "learning.course_completed": EventSpec(_L, "events", server_only=True),
    "learning.certificate_issued": EventSpec(_L, "events", server_only=True),
    "learning.resource_downloaded": EventSpec(_L, "events", server_only=True),
    "learning.assignment_submitted": EventSpec(_L, "events", server_only=True),
}

SUPPORTED_SCHEMA_VERSIONS = frozenset({1})

# Events that start ACTIVE crediting (§3.3 t_{k-1}) and terminal events (§3.3).
START_EVENTS = frozenset({"page.view", "page.focus"})
REJECTION_CODES = (
    "unknown_event_type",
    "unsupported_schema_version",
    "server_only_event",
    "purpose_not_permitted",
    "event_too_old",
    "event_in_future",
    "invalid_payload",
    "payload_too_large",
    "entity_not_entitled",
    "rate_capped",
    "uuid_time_mismatch",
)


def config_payload(product_permitted: bool, privacy_tier: str) -> dict[str, object]:
    """ANL-03 body; shape matches ``apps/web/src/lib/analytics/config.ts``."""
    return {
        "measurement_version": MEASUREMENT_VERSION,
        "params": {
            "heartbeat_interval_s": TM.heartbeat_s,
            "flush_interval_s": TM.flush_s,
            "keepalive_interval_s": TM.keepalive_s,
            "idle_threshold_s": TM.idle_s,
            "idle_threshold_by_surface_s": dict(TM.idle_by_surface_s),
            "per_sample_credit_cap_s": TM.c_max_s,
            "crash_grace_s": TM.grace_s,
            "interval_close_timeout_s": TM.d_close_s,
            "merge_gap_s": TM.merge_eps_s,
            "learning_session_gap_s": TM.session_gap_s,
            "late_window_h": TM.late_window.total_seconds() / 3600,
        },
        "purposes": {"learning": True, "product": product_permitted},
        "privacy_tier": privacy_tier,
        "limits": {"max_events_per_batch": MAX_EVENTS_PER_BATCH, "max_body_bytes": MAX_BODY_BYTES},
        "sampling": {"product_events": product_permitted},
    }
