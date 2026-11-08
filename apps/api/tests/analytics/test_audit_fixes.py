"""Regression tests for audit findings fixed in the analytics module (docs/audit/fixes/assess.md):
BE-01 video coverage clamp, BE-02 server-side org attribution, BE-12 attempt ids, BE-13 entity
checks, BE-24 retention vs client clocks, ADM-04 learning-activity feed."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.access import AccessDecision, register_access_checker
from app.core.db import system_context
from app.core.ids import uuid7
from app.core.time import ist_date
from app.modules.analytics import feeds
from app.modules.analytics.consumer import consume_outbox
from app.modules.analytics.jobs import (
    run_daily_aggregation,
    run_interval_builder,
    run_retention_purge,
    run_video_coverage,
)
from tests.analytics.conftest import (
    Page,
    add_batch_member,
    add_member,
    ingest,
    make_attempt,
    make_batch,
    make_org,
    make_user,
    principal_for,
)
from tests.catalog.factory import make_published_course


class _OnlyAllow:
    """Allows only the listed resource types."""

    def __init__(self, *types: str) -> None:
        self.types = set(types)

    async def check(self, session, principal, resource_type, resource_id, *, is_free=False):
        return AccessDecision(resource_type in self.types, "test")


async def _covered(db, uid: uuid.UUID, asset: uuid.UUID) -> float | None:
    await system_context(db, "test.read")
    row = (
        await db.execute(
            text("SELECT covered_s FROM video_watch_coverage WHERE user_id = :u AND lesson_asset_id = :a"),
            {"u": uid, "a": asset},
        )
    ).first()
    return float(row[0]) if row else None


def _video_hb(page: Page, at, start: float, length: float, *, asset, interval_ms: int = 330000, rate=2.0):
    return page.hb(
        at,
        active_ms=10000,
        media=True,
        interval_ms=interval_ms,
        media_info={
            "lesson_asset_id": str(asset),
            "position_s": start + length,
            "rate": rate,
            "played_ranges": [[start, start + length]],
        },
    )


# --------------------------------------------------------------------------- BE-01


async def test_be01_coverage_budget_uses_server_cadence_not_claimed_interval(db, now) -> None:
    uid = await make_user(db)
    p = principal_for(uid)
    pc = await make_published_course(db, uid)
    lesson, asset = pc.lessons["video"], pc.assets["video"]
    page = Page(
        "lesson_video",
        {"course_id": str(pc.course_id), "lesson_id": str(lesson), "lesson_asset_id": str(asset)},
    )
    t0 = now - timedelta(minutes=2)
    ev = [page.view(t0)]
    for i in range(3):  # 30 s of wall clock, each sample claims 330 s at 2x and 180 s of media
        ev.append(_video_hb(page, t0 + timedelta(seconds=10 * (i + 1)), 180.0 * i, 180.0, asset=asset))
    res = await ingest(db, p, ev, now=now)
    assert all(r["status"] == "accepted" for r in res), res
    await run_video_coverage(db, now=now)
    covered = await _covered(db, uid, asset)
    # budget per sample = 10 s x 2.0 x 1.1 + 1 = 23 s -> at most 69 s for 30 s of wall clock
    assert covered is not None and covered <= 3 * (10 * 2.0 * 1.1 + 1) + 0.5


async def test_be01_unknown_or_foreign_asset_is_rejected(db, now) -> None:
    uid = await make_user(db)
    p = principal_for(uid)
    pc = await make_published_course(db, uid)
    other = await make_published_course(db, uid)
    lesson = pc.lessons["video"]
    t = now - timedelta(seconds=40)
    for asset in (uuid7(), other.assets["video"]):
        page = Page("lesson_video", {"course_id": str(pc.course_id), "lesson_id": str(lesson)})
        res = await ingest(db, p, [_video_hb(page, t, 0.0, 10.0, asset=asset, rate=1.0)], now=now)
        assert res[0] == {"event_id": res[0]["event_id"], "status": "rejected", "code": "entity_not_entitled"}
        page2 = Page(
            "lesson_video",
            {"course_id": str(pc.course_id), "lesson_id": str(lesson), "lesson_asset_id": str(asset)},
        )
        res2 = await ingest(db, p, [page2.view(t)], now=now)
        assert res2[0]["status"] == "rejected" and res2[0]["code"] == "entity_not_entitled"


async def test_be01_coverage_clipped_to_asset_duration(db, now) -> None:
    uid = await make_user(db)
    p = principal_for(uid)
    pc = await make_published_course(db, uid)  # 600 s asset
    lesson, asset = pc.lessons["video"], pc.assets["video"]
    page = Page(
        "lesson_video",
        {"course_id": str(pc.course_id), "lesson_id": str(lesson), "lesson_asset_id": str(asset)},
    )
    t0 = now - timedelta(minutes=1)
    ev = [page.view(t0), _video_hb(page, t0 + timedelta(seconds=15), 595.0, 15.0, asset=asset, rate=1.0)]
    res = await ingest(db, p, ev, now=now)
    assert all(r["status"] == "accepted" for r in res), res
    await run_video_coverage(db, now=now)
    assert await _covered(db, uid, asset) == 5.0


# --------------------------------------------------------------------------- BE-02


async def _org_of(db, uid: uuid.UUID, page: Page):
    await system_context(db, "test.read")
    return (
        await db.execute(
            text(
                "SELECT organization_id FROM activity_heartbeats WHERE user_id = :u AND page_instance_id = :p"
            ),
            {"u": uid, "p": uuid.UUID(page.page_instance_id)},
        )
    ).scalar()


async def test_be02_web_shaped_heartbeat_is_attributed_to_the_company_batch(db, now) -> None:
    uid = await make_user(db)
    org = await make_org(db)
    await add_member(db, org, uid)
    b = await make_batch(db, org, uid)
    await add_batch_member(db, b, org, uid)
    p = principal_for(uid, org_ids=(org,))
    pc = await make_published_course(db, uid)
    page = Page("lesson_text", {"course_id": str(pc.course_id), "lesson_id": str(pc.lessons["article"])})
    await ingest(db, p, [page.hb(now - timedelta(seconds=30))], now=now)
    assert await _org_of(db, uid, page) == org


async def test_be02_enrolment_org_wins_and_foreign_batch_hint_is_ignored(db, now) -> None:
    """Single company: a public learner (no membership) is attributed through the enrolment's
    organization; a hint naming a batch they are not a member of is ignored (no attribution)."""
    uid = await make_user(db)
    org_a = await make_org(db)
    foreign_batch = await make_batch(db, org_a, uid)  # not a member of this batch
    pc = await make_published_course(db, uid)
    await system_context(db, "test.analytics")
    await db.execute(
        text(
            "INSERT INTO enrolments (id, user_id, course_id, course_version_id, organization_id, source) "
            "VALUES (:id, :u, :c, :v, :o, 'batch_sync')"
        ),
        {"id": uuid7(), "u": uid, "c": str(pc.course_id), "v": pc.version_id, "o": org_a},
    )
    p = principal_for(uid)
    t = now - timedelta(seconds=30)
    via_lesson = Page("lesson_text", {"lesson_id": str(pc.lessons["article"])})
    spoofed = Page("lesson_text", {"batch_id": str(foreign_batch)})
    await ingest(db, p, [via_lesson.hb(t), spoofed.hb(t)], now=now)
    assert await _org_of(db, uid, via_lesson) == org_a
    assert await _org_of(db, uid, spoofed) is None


# --------------------------------------------------------------------------- BE-12


async def test_be12_test_attempt_id_must_be_own_attempt_within_its_lifetime(db, now) -> None:
    uid, other = await make_user(db), await make_user(db)
    p = principal_for(uid)
    t = now - timedelta(minutes=5)
    own = await make_attempt(
        db, uid, started_at=now - timedelta(minutes=10), deadline_at=now + timedelta(hours=1)
    )
    theirs = await make_attempt(db, other, started_at=now - timedelta(minutes=10))
    ended = await make_attempt(
        db, uid, started_at=now - timedelta(hours=3), submitted_at=now - timedelta(hours=2)
    )
    codes = {}
    for label, attempt in (("random", uuid7()), ("theirs", theirs), ("ended", ended), ("own", own)):
        page = Page("test", {"test_attempt_id": str(attempt)}, route="/app/tests/[attemptId]")
        res = await ingest(db, p, [page.hb(t)], now=now)
        codes[label] = res[0].get("code", res[0]["status"])
    assert codes == {
        "random": "entity_not_entitled",
        "theirs": "entity_not_entitled",
        "ended": "entity_not_entitled",
        "own": "accepted",
    }


# --------------------------------------------------------------------------- BE-13


async def test_be13_every_entity_reference_is_checked(db, now) -> None:
    uid = await make_user(db)
    p = principal_for(uid)
    pc = await make_published_course(db, uid)
    other = await make_published_course(db, uid)
    t = now - timedelta(seconds=30)

    async def status(entity: dict) -> str:
        res = await ingest(db, p, [Page("lesson_text", entity).view(t)], now=now)
        return res[0].get("code", res[0]["status"])

    register_access_checker(_OnlyAllow("course"))
    assert (
        await status({"course_id": str(pc.course_id), "lesson_id": str(pc.lessons["article"])})
        == "entity_not_entitled"
    )
    register_access_checker(_OnlyAllow("course", "lesson"))
    assert (
        await status({"course_id": str(pc.course_id), "lesson_id": str(pc.lessons["article"])}) == "accepted"
    )
    # lesson of another course
    assert (
        await status({"course_id": str(pc.course_id), "lesson_id": str(other.lessons["article"])})
        == "entity_not_entitled"
    )
    for field in ("test_id", "company_path_id", "coding_problem_id"):
        assert await status({field: str(uuid7())}) == "entity_not_entitled", field


# --------------------------------------------------------------------------- BE-24


async def test_be24_old_uuid_time_rejected_and_purge_needs_server_age(db, now) -> None:
    uid = await make_user(db)
    p = principal_for(uid)
    page = Page("lesson_text")
    client_now = now - timedelta(days=40)
    res = await ingest(db, p, [page.hb(client_now)], now=now, sent_at=client_now)
    assert res[0]["status"] == "rejected" and res[0]["code"] == "event_too_old"
    # a row whose event_ts is old but which the server received recently is kept
    await system_context(db, "test.analytics")
    await db.execute(
        text(
            "INSERT INTO activity_heartbeats (event_id, event_ts, user_id, tab_id, page_instance_id, seq, "
            "effective_at, kind, active_ms, state_bits, surface, received_at) "
            "VALUES (:e, :ts, :u, :t, :p, 0, :now, 'engaged', 1000, 7, 'other', :now)"
        ),
        {"e": uuid7(), "ts": client_now, "u": uid, "t": uuid.uuid4(), "p": uuid.uuid4(), "now": now},
    )
    await run_retention_purge(db, now=now)
    await system_context(db, "test.read")
    n = (
        await db.execute(text("SELECT count(*) FROM activity_heartbeats WHERE user_id = :u"), {"u": uid})
    ).scalar()
    assert n == 1


# --------------------------------------------------------------------------- ADM-04


async def test_adm04_learning_activity_feed_buckets(db, now) -> None:
    """Single company: the feed is platform-wide only (no organization views, no
    ``organization_id`` argument) and never suppressed."""
    import inspect

    day = ist_date(now) - timedelta(days=400)  # a day no other test writes
    users = [await make_user(db) for _ in range(3)]
    await system_context(db, "test.analytics")
    for u in users:
        await db.execute(
            text(
                "INSERT INTO daily_learning_aggregates (user_id, activity_date, entity_kind, entity_id, "
                "m1_session_elapsed_s, m2_active_s, m5_learning_s, privacy_tier, measurement_version) "
                "VALUES (:u, :d, '_total', :u, 600, 600, 300, 'adult', 'tm-1.0')"
            ),
            {"u": u, "d": day},
        )
    rows = await feeds.get_learning_activity(db, day, day, granularity="month", k_min=10)
    assert len(rows) == 1 and not rows[0].suppressed
    assert (rows[0].active_learners, rows[0].engaged_minutes, rows[0].learning_minutes) == (3, 30, 15)
    assert "organization_id" not in inspect.signature(feeds.get_learning_activity).parameters


# --------------------------------------------------------------------------- E2E-05


@pytest.mark.parametrize("with_scroll", [True, False])
async def test_e2e05_todays_lesson_and_test_time_reach_the_learner_summary(
    db, client, auth, now, with_scroll
) -> None:
    """Heartbeats -> interval builder -> daily aggregator -> GET /me/analytics/summary, on the
    same IST day (the aggregator's default). A text lesson read with rising scroll depth and
    an in-progress attempt are learning evidence (M5 > 0); the same lesson time without any
    learning signal is active time only (M5 = 0, by design: §3.11 E(s))."""
    t0 = now - timedelta(minutes=4)
    if ist_date(t0) != ist_date(now):
        pytest.skip("straddles IST midnight")
    uid = await make_user(db)
    p = principal_for(uid)
    pc = await make_published_course(db, uid)
    lesson = Page("lesson_text", {"course_id": str(pc.course_id), "lesson_id": str(pc.lessons["article"])})
    ev = [lesson.view(t0)]
    for i in range(1, 6):  # ~75 s of reading
        extra = {"reading": {"max_scroll_depth_pct": 20 * i}} if with_scroll else {}
        ev.append(lesson.hb(t0 + timedelta(seconds=15 * i), **extra))
    ev.append(lesson.hide(t0 + timedelta(seconds=80)))
    attempt = await make_attempt(
        db, uid, started_at=t0 + timedelta(seconds=85), deadline_at=now + timedelta(hours=1)
    )
    test = Page("test", {"test_attempt_id": str(attempt)}, route="/app/tests/[attemptId]")
    t1 = t0 + timedelta(seconds=90)
    ev += [test.view(t1), test.hb(t1 + timedelta(seconds=15)), test.hide(t1 + timedelta(seconds=20))]
    res = await ingest(db, p, ev, now=now)
    assert all(r["status"] == "accepted" for r in res), [r for r in res if r["status"] != "accepted"]
    await consume_outbox(db)
    await run_interval_builder(db, now=now)
    await run_daily_aggregation(db, now=now)  # default day = today (IST)
    r = await client.get("/api/v1/me/analytics/summary", headers=auth.login(p))
    assert r.status_code == 200, r.text
    today_s = r.json()["learning_time"]["today_s"]
    if with_scroll:
        assert today_s >= 75
    else:
        assert 0 < today_s < 75  # only the in-attempt test time is learning without reading signals
