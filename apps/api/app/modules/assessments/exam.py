"""Exam protocol (invigilated tests): settings resolution and live integrity counting.

Client-reported events (tab hidden, window blur, copy/cut/paste, resize, full-screen exit, right
click) are *evidence*, never a verdict: the server stores them (``attempt_events``), counts them,
and at the configured threshold marks the attempt ``review_recommended`` for staff. No score is
ever changed here; the human decision flow (``integrity.decide``) stays the only penalty path.
The one automatic consequence is the opt-in ``auto_submit_after`` (off by default), which only
ends the attempt early — it is graded normally and still goes to staff review.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.assessments import datastore as adb
from app.modules.assessments.models import AttemptEvent, Test, TestAttempt
from app.modules.assessments.schemas import RECORDABLE_EVENTS

# Default conduct text (Tech Drona wording). Authors may replace it per test.
DEFAULT_CONDUCT_INSTRUCTIONS = (
    "This is a timed, invigilated exam. Keep this page open and in focus until you submit. "
    "Switching tabs or windows, copying, cutting or pasting, right-clicking, resizing the window "
    "and leaving full screen are recorded and shared with your evaluators. The timer starts as "
    "soon as you agree to these instructions, cannot be paused, and your answers are submitted "
    "automatically when time runs out."
)
DEFAULT_EXAM_EVENTS: tuple[str, ...] = (
    "focus_lost",
    "window_blur",
    "copy",
    "cut",
    "paste",
    "resize",
    "fullscreen_exit",
)
# Legacy (non-exam) tests accept the advisory events they always accepted.
LEGACY_EVENTS: tuple[str, ...] = ("focus_lost", "fullscreen_exit", "paste")
DEFAULT_TYPE_THRESHOLD = 3
DEFAULT_FLAG_THRESHOLD = 5
# Abuse guard: recordable events stored per attempt (beyond this they are ignored, not an error).
MAX_EVENTS_PER_ATTEMPT = 500
# SEC-13: connectivity events (focus_gained / disconnect / reconnect) are not recordable
# integrity signals but are stored for the timeline; they get their own per-attempt cap.
MAX_CONNECTIVITY_EVENTS_PER_ATTEMPT = 300

EVENT_LABELS: dict[str, str] = {
    "focus_lost": "Tab switches",
    "window_blur": "Window inactive",
    "copy": "Copy",
    "cut": "Cut",
    "paste": "Paste",
    "resize": "Window resized",
    "fullscreen_exit": "Left full screen",
    "right_click": "Right click",
}


@dataclass(frozen=True)
class Protocol:
    exam_mode: bool
    require_agreement: bool
    conduct_instructions: str | None
    record_events: tuple[str, ...]
    require_fullscreen: bool
    type_thresholds: dict[str, int] = field(default_factory=dict)
    flag_threshold: int | None = None
    auto_submit_after: int | None = None

    def public(self) -> dict[str, Any]:
        return {
            "exam_mode": self.exam_mode,
            "require_agreement": self.require_agreement,
            "conduct_instructions": self.conduct_instructions,
            "record_events": list(self.record_events),
            "require_fullscreen": self.require_fullscreen,
            "type_thresholds": dict(self.type_thresholds),
            "flag_threshold": self.flag_threshold,
            "auto_submit_after": self.auto_submit_after,
            "ai_hints": False,
            "labels": {k: EVENT_LABELS[k] for k in self.record_events},
        }


def protocol_of(test: Test) -> Protocol:
    s = test.integrity_settings or {}
    exam = bool(s.get("exam_mode"))
    if not exam:
        events = tuple(
            e
            for e in LEGACY_EVENTS
            if not (e == "focus_lost" and s.get("log_focus") is False)
            and not (e == "paste" and s.get("log_paste") is False)
        )
        return Protocol(
            exam_mode=False,
            require_agreement=bool(s.get("require_agreement")),
            conduct_instructions=s.get("conduct_instructions") or None,
            record_events=events,
            require_fullscreen=bool(s.get("require_fullscreen")),
        )
    raw = s.get("record_events")
    events = tuple(e for e in RECORDABLE_EVENTS if e in (raw if raw is not None else DEFAULT_EXAM_EVENTS))
    overrides = s.get("warn_thresholds") or {}
    return Protocol(
        exam_mode=True,
        require_agreement=True,
        conduct_instructions=s.get("conduct_instructions") or DEFAULT_CONDUCT_INSTRUCTIONS,
        record_events=events,
        require_fullscreen=bool(s.get("require_fullscreen")),
        type_thresholds={e: int(overrides.get(e) or DEFAULT_TYPE_THRESHOLD) for e in events},
        flag_threshold=int(s.get("flag_threshold") or DEFAULT_FLAG_THRESHOLD),
        auto_submit_after=int(s["auto_submit_after"]) if s.get("auto_submit_after") else None,
    )


async def event_counts(
    session: AsyncSession, attempt_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, int]]:
    """Recordable event counts per attempt (one grouped query)."""
    if not attempt_ids:
        return {}
    rows = await adb.execute(
        session,
        select(AttemptEvent.attempt_id, AttemptEvent.event_type, func.count())
        .where(AttemptEvent.attempt_id.in_(attempt_ids), AttemptEvent.event_type.in_(RECORDABLE_EVENTS))
        .group_by(AttemptEvent.attempt_id, AttemptEvent.event_type),
    )
    out: dict[uuid.UUID, dict[str, int]] = {a: {} for a in attempt_ids}
    for aid, et, n in rows.all():
        out[aid][str(et)] = int(n)
    return out


async def connectivity_event_count(
    session: AsyncSession, attempt_id: uuid.UUID, types: frozenset[str]
) -> int:
    """Stored connectivity events of one attempt (SEC-13 cap)."""
    n = await adb.execute(
        session,
        select(func.count())
        .select_from(AttemptEvent)
        .where(AttemptEvent.attempt_id == attempt_id, AttemptEvent.event_type.in_(types)),
    )
    return int(n.scalar_one())


def summarize(p: Protocol, counts: dict[str, int], integrity_status: str) -> dict[str, Any]:
    """The integrity block shown to the candidate (banner) and to evaluators (badges)."""
    shown = {e: counts.get(e, 0) for e in p.record_events}
    total = sum(shown.values())
    over = [
        {"type": e, "label": EVENT_LABELS[e], "count": n, "threshold": p.type_thresholds[e]}
        for e, n in shown.items()
        if e in p.type_thresholds and n >= p.type_thresholds[e]
    ]
    by_rule = p.exam_mode and (bool(over) or (p.flag_threshold is not None and total >= p.flag_threshold))
    return {
        "exam_mode": p.exam_mode,
        "counts": shown,
        "total": total,
        "over_threshold": over,
        "flag_threshold": p.flag_threshold,
        "flagged": integrity_status == "review_recommended" or by_rule,
        "integrity_status": integrity_status,
    }


def should_flag(p: Protocol, summary: dict[str, Any]) -> bool:
    return p.exam_mode and bool(
        summary["over_threshold"] or (p.flag_threshold is not None and summary["total"] >= p.flag_threshold)
    )


def should_auto_submit(p: Protocol, summary: dict[str, Any]) -> bool:
    return p.exam_mode and p.auto_submit_after is not None and summary["total"] >= p.auto_submit_after


async def attempt_summary(session: AsyncSession, attempt: TestAttempt, test: Test) -> dict[str, Any]:
    counts = (await event_counts(session, [attempt.id])).get(attempt.id, {})
    return summarize(protocol_of(test), counts, attempt.integrity_status)
