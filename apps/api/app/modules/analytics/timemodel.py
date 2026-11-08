"""Pure implementation of measurement model ``tm-1.0`` (analytics-event-schema §3).

No database access: the builder/aggregator jobs load rows, call these functions and persist
the results, so every rule here is unit-testable with the worked examples (§3.13).

Times are float epoch seconds (UTC) inside this module.

* ``build_intervals``  — heartbeats + lifecycle events of ONE page instance -> engagement
  intervals (§3.3, §3.4): ``credit_k = min(active_ms_k/1000, t_k - t_{k-1}, C_max)``, merge
  segments with gap <= eps, terminal events add ``[t_n, min(t_x, t_n + H)]``, crash closes at
  ``t_n + G`` after ``D_close`` without samples.
* ``attribute``        — union per user + priority attribution of overlapping time (§3.5):
  sum attributed = |U A_u| exactly.
* ``compute_day``      — the five metrics M1..M5 for one user x IST day (§3.11).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, time, timedelta
from typing import Any

from app.core.time import IST
from app.modules.analytics.params import LEARNING_SURFACES, TM, TimeModel

ENTITY_FIELDS = (
    "course_id",
    "lesson_id",
    "lesson_asset_id",
    "question_id",
    "test_attempt_id",
    "coding_problem_id",
)


# --------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class Sample:
    """One ``page.heartbeat`` (an ``activity_heartbeats`` row)."""

    seq: int
    t: float  # effective_at
    kind: str  # engaged | keepalive
    active_ms: int
    visible: bool
    focused: bool
    input_recent: bool
    media_playing: bool
    sample_interval_ms: int | None = None
    entity: tuple[uuid.UUID | None, ...] = (None,) * len(ENTITY_FIELDS)
    flags: tuple[str, ...] = ()
    scroll_depth_pct: int | None = None
    edit_ops: int | None = None
    editor_focused: bool | None = None

    def ent(self, name: str) -> uuid.UUID | None:
        return self.entity[ENTITY_FIELDS.index(name)]


@dataclass(frozen=True)
class Lifecycle:
    """A page lifecycle event (``page.view``, ``page.hide``, ...) or a synthetic
    ``session.ended``."""

    seq: int
    t: float
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class BuiltInterval:
    started_at: float
    ended_at: float  # provisional end (= last credited instant) while open
    last_sample_at: float
    mode: str  # interactive | mixed | media
    hidden_playback: bool
    entity: tuple[uuid.UUID | None, ...]
    active_s: float = 0.0
    heartbeat_count: int = 0
    is_open: bool = True
    close_reason: str | None = None
    flags: set[str] = field(default_factory=set)

    def ent(self, name: str) -> uuid.UUID | None:
        return self.entity[ENTITY_FIELDS.index(name)]


# --------------------------------------------------------------------------- builder


def _mode(s: Sample, previous: str | None) -> str:
    interactive = s.focused and s.input_recent
    if interactive and s.media_playing:
        return "mixed"
    if s.media_playing:
        return "media"
    if interactive:
        return "interactive"
    # The transition sample (taken when input just went stale) keeps the previous mode.
    return previous or "interactive"


_TERMINAL_REASONS = {
    "page.hide": "pagehide",
    "page.blur": "blur",
    "session.ended": "session_ended",
}


def _terminal_reason(ev: Lifecycle, last: Sample | None) -> str | None:
    et, p = ev.event_type, ev.payload
    if et == "page.hide":
        return "navigate" if p.get("reason") == "route_change" else "pagehide"
    if et == "page.visibility_change":
        return None if p.get("visible") else "hidden"
    if et == "page.idle_change":
        return "idle" if p.get("idle") else None
    if et == "page.blur":
        # A video playing in a visible, unfocused window stays active (§3.2).
        return None if (last is not None and last.media_playing) else "blur"
    return _TERMINAL_REASONS.get(et)


def _is_start(ev: Lifecycle) -> bool:
    et, p = ev.event_type, ev.payload
    if et == "page.view":
        return bool(p.get("visible", True))
    if et == "page.focus":
        return True
    if et == "page.visibility_change":
        return bool(p.get("visible"))
    if et == "page.idle_change":
        return not p.get("idle", True)
    return False


def build_intervals(
    samples: Iterable[Sample],
    events: Iterable[Lifecycle] = (),
    *,
    now: float,
    session_end: float | None = None,
    tm: TimeModel = TM,
) -> list[BuiltInterval]:
    """Rebuild every interval of one page instance from raw rows (deterministic, idempotent;
    late samples simply trigger a rebuild, §3.7). Items are ordered by ``seq`` (§3.7)."""
    items: list[tuple[int, float, int, Sample | Lifecycle]] = []
    seqs: list[int] = []
    for s in samples:
        items.append((s.seq, s.t, 0, s))
        seqs.append(s.seq)
    for e in events:
        items.append((e.seq, e.t, 1, e))
        seqs.append(e.seq)
    if session_end is not None:
        items.append((2**62, session_end, 2, Lifecycle(2**62, session_end, "session.ended")))
    items.sort(key=lambda x: (x[0], x[1], x[2]))
    seq_gap = bool(seqs) and (max(seqs) - min(seqs) + 1) > len(set(seqs))

    out: list[BuiltInterval] = []
    cur: BuiltInterval | None = None
    floor = float("-inf")  # intervals of one page instance never overlap each other
    prev_t: float | None = None
    last: Sample | None = None
    last_active = False
    last_mode: str | None = None

    def close(reason: str, extra_to: float | None = None) -> None:
        nonlocal cur, floor
        if cur is None:
            return
        if extra_to is not None and extra_to > cur.ended_at:
            cur.active_s += extra_to - cur.ended_at
            cur.ended_at = extra_to
        cur.is_open = False
        cur.close_reason = reason
        floor = max(floor, cur.ended_at)
        out.append(cur)
        cur = None

    def add(start: float, end: float, s: Sample, mode: str, hidden: bool) -> None:
        nonlocal cur
        key = (mode, hidden, s.entity)
        if cur is not None:
            gap = start - cur.ended_at
            same = (cur.mode, cur.hidden_playback, cur.entity) == key
            if s.t - cur.last_sample_at > tm.d_close_s:
                # No sample for D_close: the earlier interval was abandoned (crash/disconnect).
                close("grace_timeout", cur.last_sample_at + tm.grace_s if last_active else None)
            elif not same or gap > tm.merge_eps_s:
                close("mode_change" if not same else "gap")
        start = max(start, floor)
        if end <= start:
            return
        if cur is None:
            cur = BuiltInterval(start, start, s.t, mode, hidden, s.entity)
        added = end - max(start, cur.ended_at)
        if added > 0:
            cur.active_s += added
        cur.ended_at = max(cur.ended_at, end)
        cur.last_sample_at = max(cur.last_sample_at, s.t)
        cur.heartbeat_count += 1
        cur.flags.update(f for f in s.flags if f in ("clock_jump", "late"))
        if hidden:
            cur.flags.add("hidden_playback")

    for _seq, t, _kind, item in items:
        if isinstance(item, Sample):
            s = item
            cap = tm.c_max_s if prev_t is None else max(0.0, min(tm.c_max_s, t - prev_t))
            active_now = False
            if s.kind == "engaged" and s.visible:
                credit = max(0.0, min(s.active_ms / 1000.0, cap))
                if credit > 0:
                    mode = _mode(s, last_mode)
                    add(t - credit, t, s, mode, False)
                    last_mode = mode
                    active_now = True
            elif s.kind == "engaged" and s.media_playing:
                # Hidden-tab playback: video playback time only, never active credit (§3.2).
                interval_s = (s.sample_interval_ms or tm.heartbeat_s * 1000) / 1000.0
                credit = max(0.0, min(interval_s, cap))
                if credit > 0:
                    add(t - credit, t, s, "media", True)
            if cur is not None and s.kind == "engaged":
                cur.last_sample_at = max(cur.last_sample_at, t)
            prev_t = t
            last = s
            last_active = active_now
            continue
        ev = item  # Lifecycle
        assert isinstance(ev, Lifecycle)
        reason = _terminal_reason(ev, last)
        if reason is not None:
            if cur is not None:
                extra = min(t, last.t + tm.heartbeat_s) if (last_active and last is not None) else None
                close(reason, extra)
            last_active = False
        elif _is_start(ev):
            prev_t = t if prev_t is None else max(prev_t, t)

    if cur is not None:
        if now - cur.last_sample_at > tm.d_close_s:
            close("grace_timeout", cur.last_sample_at + tm.grace_s if last_active else None)
        else:
            out.append(cur)  # still open
    if seq_gap:
        for iv in out:
            iv.flags.add("seq_gap")
    out.sort(key=lambda iv: iv.started_at)
    return out


# --------------------------------------------------------------------------- union + attribution


@dataclass(frozen=True)
class Span:
    start: float
    end: float
    ref: int  # index into the caller's interval list
    priority: int  # 0 assessment, 1 interactive, 2 mixed, 3 media
    last_sample: float
    tiebreak: str  # page_instance_id


def union_measure(pairs: Iterable[tuple[float, float]]) -> float:
    total = 0.0
    cur_s: float | None = None
    cur_e = 0.0
    for s, e in sorted(p for p in pairs if p[1] > p[0]):
        if cur_s is None or s > cur_e:
            if cur_s is not None:
                total += cur_e - cur_s
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_s is not None:
        total += cur_e - cur_s
    return total


def merge_ranges(pairs: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for s, e in sorted(p for p in pairs if p[1] > p[0]):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def attribute(spans: Sequence[Span]) -> list[tuple[float, float, int]]:
    """Cut the union at every boundary; give each elementary piece to exactly one span by
    priority, then latest sample, then lowest page_instance_id (§3.5). Returns
    ``(start, end, ref)`` pieces whose total length equals the union measure."""
    bounds: list[tuple[float, int, int]] = []
    for i, sp in enumerate(spans):
        if sp.end > sp.start:
            bounds.append((sp.start, 1, i))
            bounds.append((sp.end, -1, i))
    bounds.sort(key=lambda b: (b[0], b[1]))
    active: set[int] = set()
    pieces: list[tuple[float, float, int]] = []
    prev: float | None = None
    for t, kind, i in bounds:
        if prev is not None and t > prev and active:
            win = min(active, key=lambda j: (spans[j].priority, -spans[j].last_sample, spans[j].tiebreak))
            ref = spans[win].ref
            if pieces and pieces[-1][2] == ref and pieces[-1][1] == prev:
                pieces[-1] = (pieces[-1][0], t, ref)
            else:
                pieces.append((prev, t, ref))
        if kind == 1:
            active.add(i)
        else:
            active.discard(i)
        prev = t
    return pieces


def overlap_measure(a: tuple[float, float], windows: Sequence[tuple[float, float]]) -> float:
    """|a & U windows| for merged, sorted windows."""
    total = 0.0
    for s, e in windows:
        if e <= a[0]:
            continue
        if s >= a[1]:
            break
        total += min(e, a[1]) - max(s, a[0])
    return total


def multi_device_overlap(spans_by_device: dict[Any, list[tuple[float, float]]]) -> float:
    """Seconds where active intervals exist on >= 2 distinct devices (§6.5)."""
    bounds: list[tuple[float, int]] = []
    for ranges in spans_by_device.values():
        for s, e in merge_ranges(ranges):
            bounds.append((s, 1))
            bounds.append((e, -1))
    bounds.sort(key=lambda b: (b[0], b[1]))
    count, total, prev = 0, 0.0, 0.0
    for t, d in bounds:
        if count >= 2:
            total += t - prev
        count += d
        prev = t
    return total


def max_concurrency(ranges: Iterable[tuple[float, float]]) -> int:
    bounds: list[tuple[float, int]] = []
    for s, e in ranges:
        if e > s:
            bounds.append((s, 1))
            bounds.append((e, -1))
    bounds.sort(key=lambda b: (b[0], b[1]))
    best = cur = 0
    for _t, d in bounds:
        cur += d
        best = max(best, cur)
    return best


# --------------------------------------------------------------------------- daily metrics


def ist_day_bounds(d: date) -> tuple[float, float]:
    start = datetime.combine(d, time(0, 0), tzinfo=IST)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


@dataclass(frozen=True)
class IntervalRec:
    """An ``engagement_intervals`` row as the aggregator sees it."""

    page_instance_id: str
    surface: str
    mode: str
    hidden_playback: bool
    start: float
    end: float  # ended_at or provisional end for open intervals
    last_sample: float
    course_id: uuid.UUID | None = None
    lesson_id: uuid.UUID | None = None
    lesson_asset_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None
    question_id: uuid.UUID | None = None
    test_attempt_id: uuid.UUID | None = None
    coding_problem_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    device_id: uuid.UUID | None = None


@dataclass(frozen=True)
class AttemptRec:
    attempt_id: uuid.UUID
    started_at: float
    deadline_at: float | None
    submitted_at: float | None
    organization_id: uuid.UUID | None = None


EntityKey = tuple[str, uuid.UUID | None]


@dataclass
class EntityMetrics:
    m2: float = 0.0
    m3: float = 0.0
    m4: float = 0.0
    m5: float = 0.0
    organization_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    topic_id: uuid.UUID | None = None


@dataclass
class DayResult:
    m1: float
    m2: float
    m3: float
    m4: float
    m5: float
    entities: dict[EntityKey, EntityMetrics]
    assessment_active_s: dict[uuid.UUID, float]
    pieces: list[tuple[float, float, int]]
    implausible: bool
    active_devices: int
    multi_device_overlap_s: float
    max_concurrent_page_instances: int
    active_hours_bitmap: int


# Server-side learning signals, keyed by the surface they count as evidence for (§3.11 E(s)).
SERVER_EVIDENCE_SURFACE = {
    "practice.answer_submitted": "practice",
    "practice.hint_viewed": "practice",
    "assessment.answer_saved": "test",
    "coding.run": "coding",
    "coding.submit": "coding",
    "coding.submission_judged": "coding",
}

CapFn = Callable[[IntervalRec], tuple[Any, float | None]]


def default_cap(iv: IntervalRec, tm: TimeModel = TM) -> tuple[Any, float | None]:
    """Item key and MLAT cap (§3.1) when no catalog metadata is available."""
    if iv.surface == "practice":
        return ("q", iv.page_instance_id, iv.question_id), tm.cap_practice_question_s
    if iv.surface == "lesson_text":
        cap = max(tm.cap_lesson_text_factor * tm.default_est_reading_min * 60, tm.cap_lesson_text_min_s)
        return ("lt", iv.lesson_id or iv.page_instance_id), cap
    if iv.surface == "lesson_video":
        return ("lv", iv.lesson_asset_id or iv.page_instance_id), None
    if iv.surface == "coding":
        return ("cp", iv.coding_problem_id or iv.page_instance_id), tm.cap_coding_problem_s
    return ("other", iv.surface, iv.test_attempt_id or iv.page_instance_id), None


def sessions_elapsed(timestamps: Iterable[float], day: tuple[float, float], gap_s: float) -> float:
    """M1: learning sessions split at gaps > S_gap; sum(last - first) clipped to the day."""
    ts = sorted(timestamps)
    if not ts:
        return 0.0
    total = 0.0
    first = last = ts[0]
    for t in ts[1:]:
        if t - last > gap_s:
            total += max(0.0, min(last, day[1]) - max(first, day[0]))
            first = t
        last = t
    total += max(0.0, min(last, day[1]) - max(first, day[0]))
    return total


def compute_day(
    *,
    day: date,
    intervals: Sequence[IntervalRec],
    client_evidence: dict[str, list[float]],
    server_evidence: dict[str, list[float]],
    presence: Iterable[float],
    attempts: Sequence[AttemptRec] = (),
    now: float,
    cap_fn: CapFn | None = None,
    tm: TimeModel = TM,
) -> DayResult:
    d0, d1 = ist_day_bounds(day)
    cap_fn = cap_fn or (lambda iv: default_cap(iv, tm))
    clipped: list[IntervalRec] = []
    for iv in intervals:
        s, e = max(iv.start, d0), min(iv.end, d1)
        if e > s:
            clipped.append(replace(iv, start=s, end=e))

    # ---- M2 union + attribution (active = non-hidden intervals)
    spans: list[Span] = []
    for i, iv in enumerate(clipped):
        if iv.hidden_playback:
            continue
        prio = 0 if iv.test_attempt_id else {"interactive": 1, "mixed": 2, "media": 3}.get(iv.mode, 3)
        spans.append(Span(iv.start, iv.end, i, prio, iv.last_sample, iv.page_instance_id))
    pieces = attribute(spans)

    entities: dict[EntityKey, EntityMetrics] = defaultdict(EntityMetrics)

    def keys_for(iv: IntervalRec) -> list[EntityKey]:
        ks: list[EntityKey] = [("_total", None)]
        for kind, val in (
            ("course", iv.course_id),
            ("lesson", iv.lesson_id),
            ("topic", iv.topic_id),
            ("test_attempt", iv.test_attempt_id),
            ("coding_problem", iv.coding_problem_id),
        ):
            if val is not None:
                ks.append((kind, val))
        return ks

    def bump(iv: IntervalRec, metric: str, secs: float) -> None:
        if secs <= 0:
            return
        for k in keys_for(iv):
            em = entities[k]
            setattr(em, metric, getattr(em, metric) + secs)
            if k[0] != "_total":
                em.organization_id = em.organization_id or iv.organization_id
                em.course_id = em.course_id or iv.course_id
                em.topic_id = em.topic_id or iv.topic_id

    m2 = 0.0
    assessment_active: dict[uuid.UUID, float] = defaultdict(float)
    for s, e, ref in pieces:
        iv = clipped[ref]
        bump(iv, "m2", e - s)
        m2 += e - s
        if iv.test_attempt_id:
            assessment_active[iv.test_attempt_id] += e - s

    # ---- M5: attributed learning-surface seconds with evidence, capped per item
    ev_windows: dict[str, list[tuple[float, float]]] = {}
    w = tm.evidence_window_s
    for pid, times in client_evidence.items():
        ev_windows[pid] = merge_ranges((t - w, t + w) for t in times)
    srv_windows = {
        surf: merge_ranges((t - w, t + w) for t in times) for surf, times in server_evidence.items()
    }
    raw_by_item: dict[Any, list[tuple[IntervalRec, float]]] = defaultdict(list)
    caps: dict[Any, float | None] = {}
    for s, e, ref in pieces:
        iv = clipped[ref]
        if iv.surface not in LEARNING_SURFACES:
            continue
        if iv.test_attempt_id or iv.mode in ("media", "mixed"):
            secs = e - s  # in-progress attempt / media playing = evidence for the whole piece
        else:
            windows = merge_ranges(
                [*ev_windows.get(iv.page_instance_id, []), *srv_windows.get(iv.surface, [])]
            )
            secs = overlap_measure((s, e), windows)
        if secs <= 0:
            continue
        item, cap = cap_fn(iv)
        caps[item] = cap
        raw_by_item[item].append((iv, secs))
    m5 = 0.0
    for item, parts in raw_by_item.items():
        raw = sum(p[1] for p in parts)
        cap = caps[item]
        factor = 1.0 if cap is None or raw <= cap else cap / raw
        for iv, secs in parts:
            bump(iv, "m5", secs * factor)
            m5 += secs * factor

    # ---- M3: wall-clock playback per asset (not exclusive; includes hidden playback)
    by_asset: dict[Any, list[IntervalRec]] = defaultdict(list)
    for iv in clipped:
        if iv.mode in ("media", "mixed") or iv.hidden_playback:
            by_asset[iv.lesson_asset_id or iv.page_instance_id].append(iv)
    m3 = 0.0
    for ivs in by_asset.values():
        secs = union_measure((iv.start, iv.end) for iv in ivs)
        m3 += secs
        bump(ivs[0], "m3", secs)

    # ---- M4: server-authoritative attempt time
    m4 = 0.0
    for a in attempts:
        end = a.submitted_at if a.submitted_at is not None else now
        if a.deadline_at is not None:
            end = min(end, a.deadline_at)
        secs = max(0.0, min(end, d1) - max(a.started_at, d0))
        if secs <= 0:
            continue
        m4 += secs
        for k in (("_total", None), ("test_attempt", a.attempt_id)):
            em = entities[k]
            em.m4 += secs
            if k[0] != "_total":
                em.organization_id = em.organization_id or a.organization_id

    # ---- M1: session elapsed (presence includes credited interval bounds so M2 <= M1)
    pres = [t for t in presence if d0 - tm.session_gap_s * 24 <= t <= d1 + tm.session_gap_s * 24]
    for iv in clipped:
        pres.extend((iv.start, iv.end))
    m1 = sessions_elapsed(pres, (d0, d1), tm.session_gap_s)

    # ---- security-feed shapes (only persisted for eligible adults)
    by_device: dict[Any, list[tuple[float, float]]] = defaultdict(list)
    hours = 0
    for iv in clipped:
        if iv.hidden_playback:
            continue
        by_device[iv.device_id].append((iv.start, iv.end))
    for s, e, _ref in pieces:
        h = int((s - d0) // 3600)
        while h < 24 and d0 + h * 3600 < e:
            hours |= 1 << h
            h += 1
    return DayResult(
        m1=m1,
        m2=m2,
        m3=m3,
        m4=m4,
        m5=m5,
        entities=dict(entities),
        assessment_active_s=dict(assessment_active),
        pieces=pieces,
        implausible=m2 > tm.implausible_day_s,
        active_devices=len([d for d, r in by_device.items() if d is not None and r]),
        multi_device_overlap_s=multi_device_overlap({d: r for d, r in by_device.items() if d is not None}),
        max_concurrent_page_instances=max_concurrency(
            (iv.start, iv.end) for iv in clipped if not iv.hidden_playback
        ),
        active_hours_bitmap=hours,
    )


# --------------------------------------------------------------------------- video coverage


def clamp_played_ranges(
    ranges: Sequence[tuple[float, float]], wall_s: float, rate: float | None
) -> tuple[list[tuple[float, float]], bool]:
    """§3.9: sum(to - from) <= wall x rate x 1.1 + 1; the excess is dropped (flagged)."""
    budget = wall_s * (rate or 1.0) * 1.1 + 1.0
    out: list[tuple[float, float]] = []
    used = 0.0
    clamped = False
    for a, b in ranges:
        if b <= a:
            continue
        take = min(b - a, max(0.0, budget - used))
        if take < b - a:
            clamped = True
        if take > 0:
            out.append((a, a + take))
            used += take
    return out, clamped


def coverage_fraction(ranges: Iterable[tuple[float, float]], duration_s: float) -> float:
    if duration_s <= 0:
        return 0.0
    clipped = [(max(0.0, a), min(duration_s, b)) for a, b in ranges]
    return min(1.0, union_measure(clipped) / duration_s)
