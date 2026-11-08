"""End-to-end on Postgres: ingest -> outbox consumer -> interval builder -> daily aggregator
-> rollups / security feed / reports; worked examples as golden values (§3.13, §8)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text

from app.core.db import system_context, tenant_context
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import RoleGrant
from app.core.time import ist_date
from app.modules.analytics import evidence, feeds
from app.modules.analytics.consumer import consume_outbox, handle_domain_event
from app.modules.analytics.jobs import (
    compute_user_day,
    erase_user,
    rollup_cohorts,
    run_daily_aggregation,
    run_interval_builder,
    run_retention_purge,
    run_security_feed,
    run_video_coverage,
)
from app.modules.analytics.mastery import MasteryState, band_for, elo_update, get_topic_mastery
from tests.analytics.conftest import (
    Page,
    add_batch_member,
    add_member,
    grant_consent,
    ingest,
    ist,
    make_attempt,
    make_batch,
    make_org,
    make_user,
    principal_for,
)
from tests.catalog.factory import make_published_course


def steps(start: datetime, end: datetime, step: int = 15) -> list[datetime]:
    out, t = [], start + timedelta(seconds=step)
    while t <= end:
        out.append(t)
        t += timedelta(seconds=step)
    return out


async def daily(db, user, day: date) -> dict[tuple[str, uuid.UUID], dict]:
    await system_context(db, "test.read")
    rows = (
        (
            await db.execute(
                text("SELECT * FROM daily_learning_aggregates WHERE user_id = :u AND activity_date = :d"),
                {"u": user, "d": day},
            )
        )
        .mappings()
        .all()
    )
    return {(r["entity_kind"], r["entity_id"]): dict(r) for r in rows}


async def build_and_aggregate(db, now: datetime, days: list[date]) -> None:
    await consume_outbox(db)
    await run_interval_builder(db, now=now)
    await run_daily_aggregation(db, days=days, now=now)


# --------------------------------------------------------------------------- example 1


async def test_example1_end_to_end_union_attribution_coverage(db, client, auth, now) -> None:
    day = ist_date(now) - timedelta(days=1)
    uid = await make_user(db)
    p = principal_for(uid)
    pc = await make_published_course(db, uid)
    course, lesson, asset, topic = pc.course_id, pc.lessons["video"], pc.assets["video"], uuid7()
    await db.execute(text("UPDATE lesson_assets SET duration_seconds = 1800 WHERE id = :a"), {"a": asset})
    q1, q2, q3 = (uuid7() for _ in range(3))
    a = Page("lesson_video", {"course_id": course, "lesson_id": lesson, "lesson_asset_id": asset})
    t0 = ist(day, 10)
    ev = [a.view(t0)]
    for i, t in enumerate(steps(t0, ist(day, 10, 30))):
        focused = t <= ist(day, 10, 20)
        media = {
            "lesson_asset_id": str(asset),
            "position_s": 15.0 * (i + 1),
            "rate": 1.0,
            "played_ranges": [[15.0 * i, 15.0 * (i + 1)]],
        }
        ev.append(a.hb(t, focused=focused, input_recent=focused, media=True, media_info=media))
        if t == ist(day, 10, 20):
            ev.append(a.blur(t))
    ev.append(a.ev("video.ended", ist(day, 10, 30), {"position_s": 1800.0, "duration_s": 1800.0}))
    ev.append(a.idle(ist(day, 10, 30)))
    b = Page("practice", {"topic_id": topic}, route="/app/practice/[setId]")
    t1 = ist(day, 10, 20)
    ev.append(b.view(t1))
    for t in steps(t1, ist(day, 10, 40)):
        q = q1 if t <= ist(day, 10, 24) else q2 if t <= ist(day, 10, 31) else q3
        ev.append(b.hb(t, entity={"topic_id": topic, "question_id": q}))
    ev.append(b.hide(ist(day, 10, 40)))
    results = await ingest(db, p, ev, now=now)
    assert all(r["status"] == "accepted" for r in results), [r for r in results if r["status"] != "accepted"][
        :3
    ]
    await system_context(db, "test.outbox")
    for q, at in ((q1, ist(day, 10, 24)), (q2, ist(day, 10, 31)), (q3, ist(day, 10, 37))):
        await emit_event(
            db,
            "practice.answered",
            {
                "user_id": str(uid),
                "question_id": str(q),
                "topic_ids": [str(topic)],
                "is_correct": True,
                "attempt_no": 1,
                "difficulty": "medium",
                "answered_at": at.isoformat(),
            },
            aggregate_type="practice_response",
            aggregate_id=uuid7(),
        )
    await build_and_aggregate(db, now, [day])
    rows = await daily(db, uid, day)
    total = rows[("_total", uid)]
    assert total["m2_active_s"] == 2400  # union: not the 50-min per-tab sum
    assert total["m3_video_playback_s"] == 1800
    assert total["m5_learning_s"] == 2400
    assert total["m1_session_elapsed_s"] == 2400
    assert total["m4_assessment_s"] == 0
    assert total["m5_learning_s"] <= total["m2_active_s"] <= total["m1_session_elapsed_s"] <= 86400
    assert rows[("lesson", lesson)]["m2_active_s"] == 1200
    assert rows[("topic", topic)]["m2_active_s"] == 1200
    assert rows[("course", course)]["m2_active_s"] == 1200
    assert total["questions_attempted"] == 3 and total["first_attempt_correct"] == 3
    # video coverage + learning-module interface
    await run_video_coverage(db, now=now)
    await tenant_context(db, p)
    cov = await evidence.video_coverage(db, uid, asset)
    assert cov is not None and cov.coverage == pytest.approx(1.0)
    ev_l = await evidence.lesson_time_evidence(db, uid, lesson)
    assert ev_l.learning_s == 1200 and ev_l.video_playback_s == 1800 and ev_l.coverage[0].coverage == 1.0
    mastery = await get_topic_mastery(db, uid)
    assert mastery[0].topic_id == topic and mastery[0].band == "insufficient_data"
    # self endpoints
    headers = auth.login(p)
    series = await client.get(
        "/api/v1/me/analytics/learning-time",
        params={"from": day.isoformat(), "to": day.isoformat()},
        headers=headers,
    )
    assert series.status_code == 200
    assert series.json()["points"][0]["learning_s"] == 2400
    summary = await client.get("/api/v1/me/analytics/summary", headers=headers)
    assert summary.status_code == 200
    body = summary.json()
    assert body["how_we_measure"]["measurement_version"] == "tm-1.0"
    assert body["accuracy_by_topic"][0]["accuracy"] == 1.0
    # re-running every job is idempotent
    await build_and_aggregate(db, now, [day])
    assert (await daily(db, uid, day))[("_total", uid)]["m2_active_s"] == 2400


# --------------------------------------------------------------------------- example 4


async def test_example4_assessment_time_and_mastery_from_outbox(db, now) -> None:
    day = ist_date(now) - timedelta(days=1)
    uid = await make_user(db)
    p = principal_for(uid)
    topic = uuid7()
    attempt = await make_attempt(
        db, uid, started_at=ist(day, 10), submitted_at=ist(day, 10, 50), deadline_at=ist(day, 11)
    )
    ev = []
    for start, end in ((ist(day, 10), ist(day, 10, 20)), (ist(day, 10, 35), ist(day, 10, 50))):
        page = Page("test", {"test_attempt_id": attempt}, route="/app/tests/[attemptId]")
        ev.append(page.view(start))
        ev += [page.hb(t) for t in steps(start, end)]
        ev.append(page.hide(end))
    await ingest(db, p, ev, now=now)
    await system_context(db, "test.outbox")
    common = {"user_id": str(uid), "attempt_id": str(attempt), "test_id": str(uuid7()), "attempt_no": 1}
    # Producer shapes as emitted by app.modules.assessments (attempt.started/submitted/scored).
    for etype, extra in (
        (
            "attempt.started",
            {"started_at": ist(day, 10).isoformat(), "deadline_at": ist(day, 11).isoformat()},
        ),
        (
            "attempt.submitted",
            {"submitted_at": ist(day, 10, 50).isoformat(), "submit_reason": "user", "auto": False},
        ),
        (
            "attempt.scored",
            {
                "score": "7",
                "max_score": "10",
                "percentage": "70",
                "topic_scores": [{"topic_id": str(topic), "correct": 4, "total": 6, "avg_time_ms": 1}],
            },
        ),
    ):
        await emit_event(db, etype, {**common, **extra}, aggregate_type="test_attempt", aggregate_id=attempt)
    await build_and_aggregate(db, now, [day])
    rows = await daily(db, uid, day)
    assert rows[("_total", uid)]["m4_assessment_s"] == 3000  # server timestamps, includes time away
    assert rows[("test_attempt", attempt)]["assessment_active_s"] == 2100  # advisory heartbeat time
    await system_context(db, "t")
    m = (
        await db.execute(
            text("SELECT attempts, correct, n_eff, band FROM topic_mastery WHERE user_id = :u"), {"u": uid}
        )
    ).one()
    assert m.attempts == 6 and m.correct == 4 and float(m.n_eff) == 6.0 and m.band != "not_started"
    # consuming the same outbox rows again changes nothing (idempotent per event id)
    await system_context(db, "t")
    await db.execute(text("DELETE FROM analytics_consumed_events"))
    await db.execute(text("DELETE FROM analytics_job_state WHERE job = 'outbox_consumer'"))
    await consume_outbox(db)
    m2 = (
        await db.execute(text("SELECT attempts FROM topic_mastery WHERE user_id = :u"), {"u": uid})
    ).scalar()
    assert m2 == 6


# --------------------------------------------------------------------------- late events / crash


async def test_late_event_within_window_reaggregates_dirty_day(db, now) -> None:
    d2 = ist_date(now) - timedelta(days=2)
    uid = await make_user(db)
    p = principal_for(uid)
    first = Page("lesson_text")
    ev = [first.view(ist(d2, 10))] + [first.hb(t) for t in steps(ist(d2, 10), ist(d2, 10, 10))]
    ev.append(first.hide(ist(d2, 10, 10)))
    await ingest(db, p, ev, now=now)
    await build_and_aggregate(db, now, [d2])
    assert (await daily(db, uid, d2))[("_total", uid)]["m2_active_s"] == 600
    late = Page("lesson_text")
    ev2 = [late.view(ist(d2, 11))] + [late.hb(t) for t in steps(ist(d2, 11), ist(d2, 11, 5))]
    ev2.append(late.hide(ist(d2, 11, 5)))
    res = await ingest(db, p, ev2, now=now)
    assert all(r["status"] == "accepted" for r in res)
    await system_context(db, "t")
    dirty = (
        await db.execute(
            text("SELECT reason FROM analytics_dirty_days WHERE user_id = :u AND activity_date = :d"),
            {"u": uid, "d": d2},
        )
    ).scalar()
    assert dirty == "late_event"
    await run_interval_builder(db, now=now)
    await run_daily_aggregation(db, days=[ist_date(now)], now=now)  # D-2 only via the dirty mark
    assert (await daily(db, uid, d2))[("_total", uid)]["m2_active_s"] == 900


async def test_crash_closes_interval_with_grace_in_db(db, now) -> None:
    uid = await make_user(db)
    p = principal_for(uid)
    page = Page("lesson_text")
    start = now - timedelta(minutes=10)
    end = start + timedelta(minutes=2)
    await ingest(db, p, [page.view(start)] + [page.hb(t) for t in steps(start, end)], now=now)
    await run_interval_builder(db, now=end + timedelta(seconds=30))
    await system_context(db, "t")
    row = (
        await db.execute(
            text("SELECT is_open FROM engagement_intervals WHERE page_instance_id = :p"),
            {"p": page.page_instance_id},
        )
    ).one()
    assert row.is_open
    await run_interval_builder(db, now=end + timedelta(seconds=70))
    row = (
        await db.execute(
            text(
                "SELECT is_open, ended_at, close_reason FROM engagement_intervals WHERE page_instance_id = :p"
            ),
            {"p": page.page_instance_id},
        )
    ).one()
    assert not row.is_open and row.close_reason == "grace_timeout"
    assert abs((row.ended_at - end).total_seconds() - 7.5) < 0.01


async def test_session_ended_event_closes_open_interval(db, now) -> None:
    uid = await make_user(db)
    p = principal_for(uid)
    page = Page("lesson_text")
    start = now - timedelta(minutes=3)
    await ingest(
        db, p, [page.view(start)] + [page.hb(t) for t in steps(start, start + timedelta(minutes=1))], now=now
    )
    await run_interval_builder(db, now=start + timedelta(minutes=1, seconds=5))
    await system_context(db, "t")
    await handle_domain_event(
        db,
        event_id=uuid7(),
        event_type="session.ended",
        payload={
            "user_id": str(uid),
            "session_id": str(p.session_id),
            "ended_at": (start + timedelta(minutes=1, seconds=3)).isoformat(),
        },
        occurred_at=now,
    )
    await run_interval_builder(db, now=start + timedelta(minutes=1, seconds=10))
    row = (
        await db.execute(
            text("SELECT close_reason, is_open FROM engagement_intervals WHERE page_instance_id = :p"),
            {"p": page.page_instance_id},
        )
    ).one()
    assert row.close_reason == "session_ended" and not row.is_open


# --------------------------------------------------------------------------- example 6 + feed eligibility


async def _two_devices(db, uid, adult: bool, day: date, now: datetime) -> None:
    laptop = principal_for(uid, adult=adult)
    phone = principal_for(uid, adult=adult)
    lp, pp = Page("lesson_text"), Page("practice")
    ev_l = (
        [lp.view(ist(day, 20))]
        + [lp.hb(t) for t in steps(ist(day, 20), ist(day, 21))]
        + [lp.hide(ist(day, 21))]
    )
    ev_p = [pp.view(ist(day, 20, 30))] + [pp.hb(t) for t in steps(ist(day, 20, 30), ist(day, 21, 30))]
    ev_p.append(pp.hide(ist(day, 21, 30)))
    await ingest(db, laptop, ev_l, now=now)
    await ingest(db, phone, ev_p, now=now)


async def test_example6_two_devices_feed_only_for_consenting_adults(db, now) -> None:
    day = ist_date(now) - timedelta(days=1)
    adult = await make_user(db)
    await grant_consent(db, adult, "security_monitoring")
    no_consent = await make_user(db)
    minor = await make_user(db, minor=True)
    await grant_consent(db, minor, "security_monitoring")  # still never eligible
    for u, is_adult in ((adult, True), (no_consent, True), (minor, False)):
        await _two_devices(db, u, is_adult, day, now)
    await build_and_aggregate(db, now, [day])
    assert (await daily(db, adult, day))[("_total", adult)]["m2_active_s"] == 5400  # 90 min, not 120
    assert (await daily(db, minor, day))[("_total", minor)]["m2_active_s"] == 5400  # learning metrics allowed
    await run_security_feed(db, day=day, now=now)
    rows = (
        await db.execute(
            text("SELECT user_id, multi_device_overlap_s, active_devices FROM security_activity_feed_daily")
        )
    ).all()
    assert [(r[0], r[1], r[2]) for r in rows] == [(adult, 1800, 2)]
    summary = await feeds.get_activity_summary(db, adult, day, day)
    assert summary[0].multi_device_overlap_s == 1800 and summary[0].active_hours_bitmap == (1 << 20) | (
        1 << 21
    )
    buckets = await feeds.get_engaged_buckets(db, adult, ist(day, 20), ist(day, 22))
    assert {b.activity_kind for b in buckets} == {"interactive"} and len({b.device_id for b in buckets}) == 2
    assert await feeds.get_activity_summary(db, minor, day, day) == []
    assert await feeds.get_engaged_buckets(db, minor, ist(day, 20), ist(day, 22)) == []
    assert await feeds.get_engaged_buckets(db, no_consent, ist(day, 20), ist(day, 22)) == []
    # withdrawal: rows deleted immediately by the consent.changed handler
    await grant_consent(db, adult, "security_monitoring", "withdrawn")
    await handle_domain_event(
        db,
        event_id=uuid7(),
        event_type="consent.changed",
        payload={"user_id": str(adult), "purpose": "security_monitoring", "action": "withdrawn"},
        occurred_at=now,
    )
    assert (await db.execute(text("SELECT count(*) FROM security_activity_feed_daily"))).scalar() == 0


# --------------------------------------------------------------------------- synthetic + k-floor + permissions


async def _seed_daily(db, user, org, day: date, m5: int) -> None:
    """A ``_total`` day row (single company: no ``organization`` entity rows); ``org`` is the
    attributed organization stored on the row (None for a public learner)."""
    await system_context(db, "test.seed")
    await db.execute(
        text(
            "INSERT INTO daily_learning_aggregates (user_id, activity_date, entity_kind, entity_id, organization_id, "
            "m1_session_elapsed_s, m2_active_s, m5_learning_s, privacy_tier, measurement_version) "
            "VALUES (:u, :d, '_total', :u, :o, :m, :m, :m, 'adult', 'tm-1.0')"
        ),
        {"u": user, "d": day, "o": org, "m": m5},
    )


async def test_synthetic_users_excluded_from_aggregates_and_k_counts(db, now) -> None:
    day = ist_date(now) - timedelta(days=1)
    syn = await make_user(db, synthetic=True)
    page = Page("lesson_text")
    ev = (
        [page.view(ist(day, 9))]
        + [page.hb(t) for t in steps(ist(day, 9), ist(day, 9, 5))]
        + [page.hide(ist(day, 9, 5))]
    )
    await ingest(db, principal_for(syn), ev, now=now)
    await build_and_aggregate(db, now, [day])
    assert await daily(db, syn, day) == {}
    assert await compute_user_day(db, syn, day, now=now) is None
    org = await make_org(db)
    batch = await make_batch(db, org, syn)
    for _ in range(9):
        u = await make_user(db)
        await add_member(db, org, u)
        await add_batch_member(db, batch, org, u)
        await _seed_daily(db, u, org, day, 1200)
    for _ in range(3):  # synthetic members never count toward k
        u = await make_user(db, synthetic=True)
        await add_member(db, org, u)
        await add_batch_member(db, batch, org, u)
        await _seed_daily(db, u, org, day, 1200)
    await rollup_cohorts(db, "day", day)
    cell = (
        await db.execute(
            text(
                "SELECT learners_enrolled, suppressed, m5_p50_s FROM cohort_learning_aggregates "
                "WHERE batch_id = :b AND period_kind = 'day' AND period_start = :d"
            ),
            {"b": batch, "d": day},
        )
    ).one()
    assert cell.learners_enrolled == 9 and cell.suppressed and cell.m5_p50_s is None
    # single company: no organization-level cohort cells
    org_cells = (
        await db.execute(
            text(
                "SELECT count(*) FROM cohort_learning_aggregates WHERE organization_id IS NOT NULL "
                "AND batch_id IS NULL"
            )
        )
    ).scalar()
    assert org_cells == 0


async def test_k_floor_suppression_and_scoped_batch_reports(db, client, scoped_auth, now) -> None:
    """Batch reports for trainer (``analytics.read`` @B), evaluator (``progress.read`` @B or @P)
    and Admin (@P); the k-floor; cross-batch, student and org-route denials."""
    today = ist_date(now)
    org = await make_org(db)
    owner = await make_user(db)
    batch_a = await make_batch(db, org, owner)
    batch_b = await make_batch(db, org, owner)
    scoped_auth.batch_orgs.update({batch_a: org, batch_b: org})
    students = []
    for i in range(3):
        u = await make_user(db)
        await add_member(db, org, u)
        await add_batch_member(db, batch_a, org, u)
        await _seed_daily(db, u, org, today, 600 * (i + 1))
        students.append(u)

    trainer = principal_for(
        await make_user(db), org_ids=(org,), grants=(RoleGrant("trainer", "batch", batch_a),)
    )
    scoped_auth.grant(trainer, "analytics.read", "batch", batch_a)
    evaluator = principal_for(
        await make_user(db), org_ids=(org,), grants=(RoleGrant("evaluator", "batch", batch_a),)
    )
    scoped_auth.grant(evaluator, "progress.read", "batch", batch_a)
    evaluator_p = principal_for(
        await make_user(db), is_platform=True, grants=(RoleGrant("evaluator", "platform"),)
    )
    scoped_auth.grant(evaluator_p, "progress.read")
    admin = principal_for(
        await make_user(db), is_platform=True, grants=(RoleGrant("super_admin", "platform"),)
    )
    scoped_auth.grant(admin, "analytics.read")

    for who in (trainer, evaluator, evaluator_p, admin):
        rb = await client.get(f"/api/v1/analytics/reports/batches/{batch_a}", headers=scoped_auth.login(who))
        assert rb.status_code == 200, rb.text
        body = rb.json()
        assert body["weekly_learning_time"]["suppressed"] is True and "organization_id" not in body
        assert len(body["learners"]) == 3  # identifiable per-student rows within scope
        assert {x["weekly_learning_s"] for x in body["learners"]} == {600, 1200, 1800}
    # >= 10 active learners -> not suppressed
    for _ in range(8):
        u = await make_user(db)
        await add_member(db, org, u)
        await add_batch_member(db, batch_a, org, u)
        await _seed_daily(db, u, org, today, 900)
    h = scoped_auth.login(trainer)
    dist = (await client.get(f"/api/v1/analytics/reports/batches/{batch_a}", headers=h)).json()[
        "weekly_learning_time"
    ]
    assert dist["suppressed"] is False and dist["n"] == 11 and dist["median_s"] == 900
    await rollup_cohorts(db, "day", today)
    await system_context(db, "t")
    cell = (
        await db.execute(
            text(
                "SELECT suppressed, learners_active FROM cohort_learning_aggregates "
                "WHERE batch_id = :b AND period_kind = 'day' AND period_start = :d"
            ),
            {"b": batch_a, "d": today},
        )
    ).one()
    assert not cell.suppressed and cell.learners_active == 11
    # cross-batch and permission denials; organization reports are gone
    for who in (trainer, evaluator):
        hh = scoped_auth.login(who)
        assert (
            await client.get(f"/api/v1/analytics/reports/batches/{batch_b}", headers=hh)
        ).status_code == 403
        assert (await client.get("/api/v1/analytics/reports/platform", headers=hh)).status_code == 403
    assert (await client.get("/api/v1/analytics/ingest-health", headers=h)).status_code == 403
    student_h = scoped_auth.login(principal_for(students[0], org_ids=(org,)))
    assert (
        await client.get(f"/api/v1/analytics/reports/batches/{batch_a}", headers=student_h)
    ).status_code == 403
    admin_h = scoped_auth.login(admin)
    assert (await client.get(f"/api/v1/analytics/reports/orgs/{org}", headers=admin_h)).status_code == 404
    assert (
        await client.get(f"/api/v1/analytics/reports/orgs/{org}/students/{students[0]}", headers=admin_h)
    ).status_code == 404


async def test_platform_reports_require_platform_permission(db, client, scoped_auth, now) -> None:
    admin = principal_for(
        await make_user(db), is_platform=True, grants=(RoleGrant("super_admin", "platform"),)
    )
    scoped_auth.grant(admin, "analytics.read.platform")
    h = scoped_auth.login(admin)
    r = await client.get("/api/v1/analytics/reports/platform", headers=h)
    assert r.status_code == 200 and {"dau", "wau", "mau"} <= set(r.json())
    health = await client.get("/api/v1/analytics/ingest-health", headers=h)
    assert health.status_code == 200 and "rejections_by_code" in health.json()


async def test_minor_summary_shows_neutral_count_not_streak(db, client, auth, now) -> None:
    minor = principal_for(await make_user(db, minor=True), adult=False)
    r = await client.get("/api/v1/me/analytics/summary", headers=auth.login(minor))
    assert r.status_code == 200
    assert "active_days_streak" not in r.json() and "active_days_last_30" in r.json()


# --------------------------------------------------------------------------- mastery, retention, erasure


def test_elo_mastery_rules() -> None:
    at = datetime(2026, 11, 1, tzinfo=UTC)
    s = MasteryState()
    for _ in range(6):
        s = elo_update(s, correct=True, b=0.0, w=1.0, at=at)
    assert s.theta > 0 and s.n_eff == 6 and s.band in ("developing", "strong")
    zero = elo_update(MasteryState(), correct=True, b=0.0, w=0.0, at=at)  # after solution viewed
    assert zero.theta == 0 and zero.n_eff == 0 and zero.attempts == 1
    assert band_for(5.0, 4.0) == "insufficient_data" and band_for(-2.0, 10) == "weak"
    later = elo_update(s, correct=False, b=0.0, w=1.0, at=at + timedelta(days=30))
    assert later.weighted_accuracy == pytest.approx((s.wa_num * 0.5) / (s.wa_den * 0.5 + 1.0))


async def test_retention_purge_and_erasure(db, now) -> None:
    uid = await make_user(db)
    p = principal_for(uid)
    page = Page("lesson_text")
    await ingest(db, p, [page.view(now - timedelta(minutes=1))], now=now)
    await system_context(db, "t")
    old_hb = uuid7()
    await db.execute(
        text(
            "INSERT INTO activity_heartbeats (event_id, event_ts, user_id, tab_id, page_instance_id, seq, effective_at, "
            "kind, active_ms, state_bits, surface, received_at) "
            "VALUES (:e, :ts, :u, :t, :p, 0, :ts, 'engaged', 1000, 7, 'other', :ts)"
        ),
        {"e": old_hb, "ts": now - timedelta(days=40), "u": uid, "t": uuid.uuid4(), "p": uuid.uuid4()},
    )
    await db.execute(
        text(
            "INSERT INTO analytics_events (event_id, event_ts, event_type, schema_version, source, purpose, user_id, "
            "occurred_at, effective_at, skew_ms, privacy_tier, received_at) VALUES (:e, :ts, 'page.view', 1, 'client', "
            "'learning', :u, :ts, :ts, 0, 'adult', :ts)"
        ),
        {"e": uuid7(), "ts": now - timedelta(days=91), "u": uid},
    )
    out = await run_retention_purge(db, now=now)
    assert out["activity_heartbeats"] == 1 and out["analytics_events"] == 1
    assert (
        await db.execute(text("SELECT count(*) FROM analytics_events WHERE user_id = :u"), {"u": uid})
    ).scalar() == 1
    erased = await erase_user(db, uid)
    assert erased["analytics_events"] == 1
    assert (
        await db.execute(text("SELECT count(*) FROM analytics_events WHERE user_id = :u"), {"u": uid})
    ).scalar() == 0


async def test_rls_learner_cannot_read_another_learners_rows(db, now) -> None:
    day = ist_date(now)
    org = await make_org(db)
    a, b = await make_user(db), await make_user(db)
    await _seed_daily(db, a, None, day, 100)
    await tenant_context(db, principal_for(b))
    n = (
        await db.execute(text("SELECT count(*) FROM daily_learning_aggregates WHERE user_id = :u"), {"u": a})
    ).scalar()
    assert n == 0
    _ = org


async def test_rls_batch_students_cannot_read_each_other_but_staff_can(db, now) -> None:
    """analytics_0003: org-attributed analytics rows (company org) are readable by the learner,
    by staff of the org and by platform principals — never by another batch student."""
    day = ist_date(now) - timedelta(days=3)
    org = await make_org(db)
    owner = await make_user(db)
    batch = await make_batch(db, org, owner)
    a, b = await make_user(db), await make_user(db)
    for u in (a, b):
        await add_member(db, org, u)
        await add_batch_member(db, batch, org, u)
    await _seed_daily(db, a, org, day, 100)
    staff = await make_user(db)
    await add_member(db, org, staff, "staff")

    async def count_as(p) -> int:
        await tenant_context(db, p)
        n = (
            await db.execute(
                text(
                    "SELECT count(*) FROM daily_learning_aggregates WHERE user_id = :u AND activity_date = :d"
                ),
                {"u": a, "d": day},
            )
        ).scalar()
        await system_context(db, "t")
        return int(n or 0)

    assert await count_as(principal_for(b, org_ids=(org,))) == 0
    assert await count_as(principal_for(a, org_ids=(org,))) == 1
    assert await count_as(principal_for(staff, org_ids=(org,))) == 1
