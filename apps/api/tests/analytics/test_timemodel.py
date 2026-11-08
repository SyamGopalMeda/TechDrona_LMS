"""Measurement model tm-1.0 as pure functions: the worked examples of
analytics-event-schema §3.13 as golden values, plus the §8 data-quality invariants."""

from __future__ import annotations

import itertools
import random
import uuid
from datetime import date

import pytest

from app.modules.analytics.timemodel import (
    AttemptRec,
    IntervalRec,
    Lifecycle,
    Sample,
    Span,
    attribute,
    build_intervals,
    clamp_played_ranges,
    compute_day,
    coverage_fraction,
    ist_day_bounds,
    union_measure,
)

DAY = date(2026, 11, 2)
D0, _ = ist_day_bounds(DAY)


def T(hh: int, mm: int = 0, ss: float = 0) -> float:
    """Epoch seconds for an IST wall-clock time on DAY."""
    return D0 + hh * 3600 + mm * 60 + ss


def run(start: float, end: float, *, seq0: int = 1, step: float = 15, entity=None, **state) -> list[Sample]:
    out, t, seq = [], start + step, seq0
    defaults = {"visible": True, "focused": True, "input_recent": True, "media_playing": False}
    defaults.update(state)
    ent = entity or (None,) * 6
    while t <= end + 1e-9:
        out.append(Sample(seq, t, "engaged", int(step * 1000), entity=ent, **defaults))
        t += step
        seq += 1
    return out


def life(start: float, end: float) -> list[Lifecycle]:
    """page.view at start, page.hide at end (a clean close, no crash grace)."""
    return [Lifecycle(0, start, "page.view", {}), Lifecycle(10**6, end, "page.hide", {"reason": "pagehide"})]


def rec(iv, pid: str, surface: str, **kw) -> IntervalRec:
    return IntervalRec(
        page_instance_id=pid,
        surface=surface,
        mode=iv.mode,
        hidden_playback=iv.hidden_playback,
        start=iv.started_at,
        end=iv.ended_at,
        last_sample=iv.last_sample_at,
        **kw,
    )


L1, A1_ASSET, COURSE, TOPIC = (uuid.uuid4() for _ in range(4))
Q1, Q2, Q3 = (uuid.uuid4() for _ in range(3))


def example1():
    # Window A: video focused 10:00-10:20 (mixed), visible-unfocused playing 10:20-10:30 (media).
    a_ent = (COURSE, L1, A1_ASSET, None, None, None)
    a = run(T(10), T(10, 20), entity=a_ent, media_playing=True)
    a += run(
        T(10, 20),
        T(10, 30),
        seq0=len(a) + 2,
        entity=a_ent,
        focused=False,
        input_recent=False,
        media_playing=True,
    )
    a_ev = [
        Lifecycle(0, T(10), "page.view", {"visible": True, "focused": True}),
        Lifecycle(81, T(10, 20), "page.blur", {}),  # video still playing -> not terminal
        Lifecycle(10_000, T(10, 30), "page.idle_change", {"idle": True}),
    ]
    # Window B: practice, interactive 10:20-10:40, questions switch at 10:24 and 10:31.
    b = []
    for s in run(T(10, 20), T(10, 40)):
        q = Q1 if s.t <= T(10, 24) else Q2 if s.t <= T(10, 31) else Q3
        b.append(
            Sample(
                s.seq,
                s.t,
                "engaged",
                15000,
                True,
                True,
                True,
                False,
                entity=(None, None, None, q, None, None),
            )
        )
    b_ev = [
        Lifecycle(0, T(10, 20), "page.view", {}),
        Lifecycle(10_000, T(10, 40), "page.hide", {"reason": "pagehide"}),
    ]
    now = T(12)
    ia = build_intervals(a, a_ev, now=now)
    ib = build_intervals(b, b_ev, now=now)
    recs = [
        rec(iv, "A1", "lesson_video", course_id=COURSE, lesson_id=L1, lesson_asset_id=A1_ASSET) for iv in ia
    ]
    recs += [rec(iv, "B1", "practice", topic_id=TOPIC, question_id=iv.entity[3]) for iv in ib]
    server = {"practice": [T(10, 24), T(10, 31), T(10, 37)]}
    return ia, ib, recs, server, now


def test_example1_overlapping_windows_union_not_sum() -> None:
    ia, ib, recs, server, now = example1()
    assert [(iv.mode, iv.started_at, iv.ended_at) for iv in ia] == [
        ("mixed", T(10), T(10, 20)),
        ("media", T(10, 20), T(10, 30)),
    ]
    assert ia[-1].close_reason == "idle"
    assert (
        ib[0].started_at == T(10, 20) and ib[-1].ended_at == T(10, 40) and ib[-1].close_reason == "pagehide"
    )
    naive = sum(iv.active_s for iv in ia + ib)
    assert naive == pytest.approx(50 * 60)
    res = compute_day(
        day=DAY, intervals=recs, client_evidence={}, server_evidence=server, presence=[], now=now
    )
    assert res.m2 == pytest.approx(40 * 60)  # union, not the 50-min per-tab sum
    assert res.entities[("lesson", L1)].m2 == pytest.approx(20 * 60)  # interactive beats media
    assert res.entities[("topic", TOPIC)].m2 == pytest.approx(20 * 60)
    attributed = sum(m.m2 for k, m in res.entities.items() if k[0] in ("lesson", "topic"))
    assert attributed == pytest.approx(res.m2)
    assert res.m3 == pytest.approx(30 * 60)  # playback is not exclusive
    assert res.m5 == pytest.approx(40 * 60)
    assert res.m1 == pytest.approx(40 * 60)
    assert res.m4 == 0
    assert res.m5 <= res.m2 <= res.m1


def test_example1_variant_hidden_tab_gets_playback_not_active() -> None:
    a_ent = (COURSE, L1, A1_ASSET, None, None, None)
    a = run(T(10), T(10, 20), entity=a_ent, media_playing=True)
    # Same window, video tab hidden 10:20-10:30: client reports active_ms 0, media playing.
    a += [
        Sample(s.seq, s.t, "engaged", 0, False, False, False, True, sample_interval_ms=15000, entity=a_ent)
        for s in run(T(10, 20), T(10, 30), seq0=200)
    ]
    ia = build_intervals(a, [Lifecycle(0, T(10), "page.view", {})], now=T(12))
    assert any(iv.hidden_playback for iv in ia)
    b = run(T(10, 20), T(10, 40))
    b_ev = [
        Lifecycle(0, T(10, 20), "page.view", {}),
        Lifecycle(999, T(10, 40), "page.hide", {"reason": "pagehide"}),
    ]
    ib = build_intervals(b, b_ev, now=T(12))
    recs = [rec(iv, "A1", "lesson_video", lesson_id=L1, lesson_asset_id=A1_ASSET) for iv in ia]
    recs += [rec(iv, "B1", "practice", topic_id=TOPIC) for iv in ib]
    res = compute_day(
        day=DAY,
        intervals=recs,
        client_evidence={},
        server_evidence={"practice": [T(10, 30)]},
        presence=[],
        now=T(12),
    )
    assert res.m2 == pytest.approx(40 * 60)
    assert res.entities[("lesson", L1)].m2 == pytest.approx(20 * 60)
    assert res.m3 == pytest.approx(30 * 60)


def test_example2_tab_left_open_for_hours_no_credit_beyond_idle() -> None:
    lesson = uuid.uuid4()
    # Inputs until 14:12; client keeps crediting T_idle(lesson_text)=180 s -> idle at 14:15.
    s = run(T(14), T(14, 15), entity=(None, lesson, None, None, None, None))
    s = [
        Sample(x.seq, x.t, x.kind, x.active_ms, True, True, x.t <= T(14, 15), False, entity=x.entity)
        for x in s
    ]
    keep = [
        Sample(1000 + i, T(14, 20) + i * 300, "keepalive", 0, True, True, False, False, entity=s[0].entity)
        for i in range(12)  # 14:20 ... 15:15, then the session expires (401)
    ]
    ev = [Lifecycle(0, T(14), "page.view", {}), Lifecycle(999, T(14, 15), "page.idle_change", {"idle": True})]
    ivs = build_intervals(s + keep, ev, now=T(18))
    assert len(ivs) == 1 and ivs[0].close_reason == "idle"
    assert ivs[0].ended_at == T(14, 15)
    recs = [rec(iv, "P", "lesson_text", lesson_id=lesson) for iv in ivs]
    evidence = {"P": [x.t for x in s if x.t <= T(14, 12)]}  # scroll depth rising
    res = compute_day(
        day=DAY,
        intervals=recs,
        client_evidence=evidence,
        server_evidence={},
        presence=[x.t for x in s + keep] + [T(14)],
        now=T(18),
    )
    assert res.m2 == pytest.approx(15 * 60)
    assert res.m5 == pytest.approx(15 * 60)
    assert res.m1 == pytest.approx(75 * 60)  # "signed in", not study time
    assert res.m3 == 0 and res.m4 == 0


def test_example3_crash_closes_at_last_sample_plus_grace() -> None:
    s = run(T(11), T(11, 7, 45))
    ev = [Lifecycle(0, T(11), "page.view", {})]
    still_open = build_intervals(s, ev, now=T(11, 8, 40))  # < D_close after the last sample
    assert still_open[-1].is_open
    closed = build_intervals(s, ev, now=T(11, 8, 51))
    assert closed[-1].close_reason == "grace_timeout"
    assert closed[-1].ended_at == pytest.approx(T(11, 7, 52.5))
    # If the 11:07:45 flush had also been lost, the interval ends at 11:07:30 + 7.5 s.
    lost = build_intervals(s[:-1], ev, now=T(11, 9))
    assert lost[-1].ended_at == pytest.approx(T(11, 7, 37.5))


def test_example4_assessment_time_is_server_authoritative() -> None:
    attempt = uuid.uuid4()
    ent = (None, None, None, None, attempt, None)
    first = run(T(10), T(10, 20), entity=ent)
    second = run(T(10, 35), T(10, 50), entity=ent)
    i1 = build_intervals(first, life(T(10), T(10, 20)), now=T(12))  # browser closed (pagehide)
    i2 = build_intervals(second, life(T(10, 35), T(10, 50)), now=T(12))
    recs = [rec(iv, "T1", "test", test_attempt_id=attempt) for iv in i1]
    recs += [rec(iv, "T2", "test", test_attempt_id=attempt) for iv in i2]
    a = AttemptRec(attempt, T(10), T(11), T(10, 50))
    res = compute_day(
        day=DAY, intervals=recs, client_evidence={}, server_evidence={}, presence=[], attempts=[a], now=T(12)
    )
    assert res.m4 == pytest.approx(50 * 60)
    assert res.assessment_active_s[attempt] == pytest.approx(35 * 60)
    unsubmitted = AttemptRec(attempt, T(10), T(11), None)
    res2 = compute_day(
        day=DAY,
        intervals=[],
        client_evidence={},
        server_evidence={},
        presence=[],
        attempts=[unsubmitted],
        now=T(13),
    )
    assert res2.m4 == pytest.approx(60 * 60)


def test_example5_video_seek_and_rate() -> None:
    # 0-5 min at 1x (300 s wall), 15-20 min at 2x (150 s wall), re-watch 3-5 min at 1x (120 s wall)
    wall = 300 + 150 + 120
    assert wall / 60 == pytest.approx(9.5)
    ranges = [(0, 300), (900, 1200), (180, 300)]
    assert sum(b - a for a, b in ranges) / 60 == pytest.approx(12)
    assert coverage_fraction(ranges, 1200) == pytest.approx(0.5)


def test_video_plausibility_clamp() -> None:
    ok, clamped = clamp_played_ranges([(0, 15)], 15, 1.0)
    assert not clamped and ok == [(0, 15)]
    forged, clamped = clamp_played_ranges([(0, 600)], 15, 2.0)
    assert clamped and forged[0][1] == pytest.approx(15 * 2 * 1.1 + 1)


def test_example6_two_devices_union_and_overlap() -> None:
    laptop, phone = uuid.uuid4(), uuid.uuid4()
    i1 = build_intervals(run(T(20), T(21)), life(T(20), T(21)), now=T(23))
    i2 = build_intervals(run(T(20, 30), T(21, 30)), life(T(20, 30), T(21, 30)), now=T(23))
    recs = [rec(iv, "L", "lesson_text", device_id=laptop) for iv in i1]
    recs += [rec(iv, "P", "practice", device_id=phone) for iv in i2]
    res = compute_day(day=DAY, intervals=recs, client_evidence={}, server_evidence={}, presence=[], now=T(23))
    assert res.m2 == pytest.approx(90 * 60)  # not 120
    assert res.multi_device_overlap_s == pytest.approx(30 * 60)
    assert res.active_devices == 2


def test_server_cap_per_sample_and_since_previous_sample() -> None:
    # A forged burst of samples 1 s apart claiming 20 s each earns at most 1 s each.
    burst = [Sample(i + 1, T(9) + i, "engaged", 20000, True, True, True, False) for i in range(1, 30)]
    ivs = build_intervals(burst, life(T(9), T(9) + 29), now=T(12))
    assert sum(iv.active_s for iv in ivs) <= 29 + 1e-6
    # A single sample after a long gap is capped at C_max = 20 s.
    lone = build_intervals([Sample(1, T(9, 30), "engaged", 20000, True, True, True, False)], [], now=T(12))
    assert lone[0].ended_at - lone[0].started_at <= 20 + 7.5 + 1e-6


def test_hidden_tab_and_keepalive_earn_no_active_credit() -> None:
    hidden = [Sample(i, T(9) + 15 * i, "engaged", 15000, False, False, False, False) for i in range(1, 20)]
    keep = [Sample(100 + i, T(9) + 300 * i, "keepalive", 0, True, True, False, False) for i in range(1, 10)]
    assert build_intervals(hidden + keep, [], now=T(12)) == []


def test_refresh_lost_hide_grace_overlap_is_removed_by_union() -> None:
    old = build_intervals(run(T(9), T(9, 10)), [], now=T(12))  # page.hide lost -> grace close
    new = build_intervals(run(T(9, 10, 2), T(9, 20)), [Lifecycle(0, T(9, 10, 2), "page.view", {})], now=T(12))
    recs = [rec(iv, "old", "lesson_text") for iv in old] + [rec(iv, "new", "lesson_text") for iv in new]
    res = compute_day(day=DAY, intervals=recs, client_evidence={}, server_evidence={}, presence=[], now=T(12))
    assert res.m2 == pytest.approx(union_measure((r.start, r.end) for r in recs))
    assert res.m2 < sum(r.end - r.start for r in recs)


@pytest.mark.parametrize("seed", range(25))
def test_union_invariant_random_multi_tab(seed: int) -> None:
    """§8.1: Σ attributed = |U| <= wall clock, for random multi-tab fixtures."""
    rnd = random.Random(seed)
    spans = []
    for i in range(rnd.randint(1, 12)):
        s = rnd.uniform(0, 3600)
        spans.append(Span(s, s + rnd.uniform(1, 1800), i, rnd.randint(0, 3), rnd.uniform(0, 5000), f"p{i}"))
    pieces = attribute(spans)
    total = sum(e - s for s, e, _ in pieces)
    assert total == pytest.approx(union_measure((sp.start, sp.end) for sp in spans))
    lo, hi = min(sp.start for sp in spans), max(sp.end for sp in spans)
    assert total <= hi - lo + 1e-6
    # pieces never overlap: one wall-clock second earns at most one active second
    ordered = sorted(pieces)
    assert all(a[1] <= b[0] + 1e-9 for a, b in itertools.pairwise(ordered))


def test_m5_requires_learning_evidence_and_respects_caps() -> None:
    q = uuid.uuid4()
    long_view = build_intervals(
        run(T(9), T(9, 30), entity=(None, None, None, q, None, None)), life(T(9), T(9, 30)), now=T(12)
    )
    recs = [rec(iv, "P", "practice", question_id=q) for iv in long_view]
    no_evidence = compute_day(
        day=DAY, intervals=recs, client_evidence={}, server_evidence={}, presence=[], now=T(12)
    )
    assert no_evidence.m2 == pytest.approx(30 * 60) and no_evidence.m5 == 0
    answered = compute_day(
        day=DAY,
        intervals=recs,
        client_evidence={},
        server_evidence={"practice": [T(9, 10), T(9, 20)]},
        presence=[],
        now=T(12),
    )
    assert answered.m5 == pytest.approx(10 * 60)  # practice question cap: 10 min per view
    dash = compute_day(
        day=DAY,
        intervals=[rec(iv, "D", "dashboard") for iv in long_view],
        client_evidence={"D": [T(9, 5)]},
        server_evidence={},
        presence=[],
        now=T(12),
    )
    assert dash.m2 > 0 and dash.m5 == 0  # dashboard is not a learning surface


def test_intervals_crossing_midnight_are_split_by_ist_day() -> None:
    ivs = build_intervals(run(T(23, 50), T(24, 10)), life(T(23, 50), T(24, 10)), now=T(30))
    recs = [rec(iv, "P", "lesson_text") for iv in ivs]
    d1 = compute_day(day=DAY, intervals=recs, client_evidence={}, server_evidence={}, presence=[], now=T(30))
    d2 = compute_day(
        day=date(2026, 11, 3), intervals=recs, client_evidence={}, server_evidence={}, presence=[], now=T(30)
    )
    assert d1.m2 == pytest.approx(10 * 60) and d2.m2 == pytest.approx(10 * 60)
