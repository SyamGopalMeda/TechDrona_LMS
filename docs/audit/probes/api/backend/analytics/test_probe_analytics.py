"""Audit probes (Phase A, backend/analytics). Not part of the product suite."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.core.access import AccessDecision, get_access_checker, register_access_checker
from app.core.db import system_context
from app.core.ids import uuid7
from app.core.principal import RoleGrant
from app.core.time import ist_date
from app.modules.analytics import hooks
from app.modules.analytics.consumer import consume_outbox
from app.modules.analytics.jobs import (
    run_daily_aggregation,
    run_interval_builder,
    run_retention_purge,
    run_video_coverage,
)
from tests.analytics.conftest import (
    Page,
    ScopedAuth,
    add_batch_member,
    add_member,
    batch,
    ingest,
    ist,
    make_batch,
    make_org,
    make_user,
    principal_for,
)

URL = "/api/v1/analytics/events"


class _AllowAll:
    async def check(self, session, principal, resource_type, resource_id, *, is_free=False):
        return AccessDecision(True, "test")


class _CourseOnly:
    """Allows ONLY resource_type == course; records every check."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, uuid.UUID]] = []

    async def check(self, session, principal, resource_type, resource_id, *, is_free=False):
        self.calls.append((resource_type, resource_id))
        return AccessDecision(resource_type == "course", "test")


class _DenyAll:
    def __init__(self) -> None:
        self.calls: list[tuple[str, uuid.UUID]] = []

    async def check(self, session, principal, resource_type, resource_id, *, is_free=False):
        self.calls.append((resource_type, resource_id))
        return AccessDecision(False, "no_entitlement")


@pytest.fixture(autouse=True)
def _wiring():
    from app.main import discover_routers

    discover_routers("all")
    prev = get_access_checker()
    register_access_checker(_AllowAll())

    async def _noop(_sid):
        return None

    hooks.register_engagement_toucher(_noop)
    yield
    register_access_checker(prev)
    hooks.register_engagement_toucher(None)


@pytest.fixture
def now():
    from app.core.time import utcnow

    return utcnow()


def steps(start, end, step=15):
    out, t = [], start + timedelta(seconds=step)
    while t <= end:
        out.append(t)
        t += timedelta(seconds=step)
    return out


async def pipeline(db, now, days):
    await consume_outbox(db)
    await run_interval_builder(db, now=now)
    await run_daily_aggregation(db, days=days, now=now)


async def total_row(db, user, day: date):
    await system_context(db, "audit.read")
    r = (
        await db.execute(
            text(
                "SELECT m1_session_elapsed_s, m2_active_s, m3_video_playback_s, m4_assessment_s, "
                "m5_learning_s FROM daily_learning_aggregates WHERE user_id = :u AND activity_date = :d "
                "AND entity_kind = '_total'"
            ),
            {"u": user, "d": day},
        )
    ).first()
    return tuple(r) if r else None


# --------------------------------------------------------------------------- P1 video coverage forgery


async def test_p1_video_coverage_forged_by_claimed_sample_interval(db, now) -> None:
    """3 heartbeats 10 s apart (30 s wall clock) claiming sample_interval_ms=330000 and rate 2.0."""
    uid = await make_user(db)
    p = principal_for(uid)
    course, lesson, asset = uuid7(), uuid7(), uuid7()
    page = Page("lesson_video", {"course_id": course, "lesson_id": lesson, "lesson_asset_id": asset})
    t0 = now - timedelta(minutes=2)
    ev = [page.view(t0)]
    start = 0.0
    for i in range(3):
        t = t0 + timedelta(seconds=10 * (i + 1))
        ev.append(
            page.hb(
                t,
                active_ms=10000,
                media=True,
                interval_ms=330000,
                media_info={
                    "lesson_asset_id": str(asset),
                    "position_s": start + 727,
                    "rate": 2.0,
                    "played_ranges": [[start, start + 727]],
                },
            )
        )
        start += 727
    res = await ingest(db, p, ev, now=now)
    print("P1 ingest statuses:", [r["status"] for r in res])
    await run_video_coverage(db, now=now)
    await system_context(db, "audit.read")
    row = (
        await db.execute(
            text("SELECT covered_s FROM video_watch_coverage WHERE user_id = :u AND lesson_asset_id = :a"),
            {"u": uid, "a": asset},
        )
    ).first()
    print("P1 covered_s after 30 s of wall clock:", row[0] if row else None)
    assert row is not None and float(row[0]) > 2000  # documents the issue (budget per spec ~= 70 s)


# --------------------------------------------------------------------------- P2 test_attempt_id spoof


async def test_p2_spoofed_test_attempt_id_turns_evidence_free_time_into_m5(db, now) -> None:
    day = ist_date(now) - timedelta(days=1)
    out = {}
    for label, ent in (("control", {}), ("spoof", {"test_attempt_id": str(uuid7())})):
        uid = await make_user(db)
        p = principal_for(uid)
        page = Page("lesson_text", ent)
        t0 = ist(day, 9)
        ev = [page.view(t0)] + [page.hb(t) for t in steps(t0, ist(day, 9, 10))] + [page.hide(ist(day, 9, 10))]
        res = await ingest(db, p, ev, now=now)
        assert all(r["status"] == "accepted" for r in res), res[:2]
        await pipeline(db, now, [day])
        out[label] = await total_row(db, uid, day)
    print("P2 (m1,m2,m3,m4,m5) control:", out["control"], "spoof:", out["spoof"])
    assert out["control"][4] == 0 and out["spoof"][4] == 600


# --------------------------------------------------------------------------- P3 org attribution


async def test_p3_org_attribution_requires_client_batch_id(db, now) -> None:
    uid = await make_user(db)
    org = await make_org(db)
    await add_member(db, org, uid)
    b = await make_batch(db, org, uid)
    await add_batch_member(db, b, org, uid)
    p = principal_for(uid, org_ids=(org,))
    course, lesson = uuid7(), uuid7()
    web_like = Page("lesson_text", {"course_id": course, "lesson_id": lesson})  # what LessonView.tsx sends
    with_batch = Page("lesson_text", {"course_id": course, "lesson_id": lesson, "batch_id": b})
    t = now - timedelta(minutes=1)
    await ingest(db, p, [web_like.hb(t), with_batch.hb(t)], now=now)
    await system_context(db, "audit.read")
    rows = (
        await db.execute(
            text("SELECT page_instance_id, organization_id FROM activity_heartbeats WHERE user_id = :u"),
            {"u": uid},
        )
    ).all()
    m = {str(r[0]): r[1] for r in rows}
    print("P3 org web_like:", m[web_like.page_instance_id], "with batch_id:", m[with_batch.page_instance_id])
    assert m[web_like.page_instance_id] is None and m[with_batch.page_instance_id] == org


# --------------------------------------------------------------------------- P4 entitlement coverage


async def test_p4_entity_entitlement_gaps(db, now) -> None:
    uid = await make_user(db)
    p = principal_for(uid)
    chk = _CourseOnly()
    register_access_checker(chk)
    gated_lesson = uuid7()
    pg = Page("lesson_text", {"course_id": str(uuid7()), "lesson_id": str(gated_lesson)})
    res = await ingest(db, p, [pg.view(now - timedelta(seconds=30))], now=now)
    print("P4a course(allowed)+lesson(denied):", res[0], "checks:", [c[0] for c in chk.calls])
    assert res[0]["status"] == "accepted" and not any(c[0] == "lesson" for c in chk.calls)
    deny = _DenyAll()
    register_access_checker(deny)
    pg2 = Page(
        "lesson_video",
        {"lesson_asset_id": str(uuid7()), "test_attempt_id": str(uuid7()), "question_id": str(uuid7()),
         "test_id": str(uuid7()), "company_path_id": str(uuid7())},
    )
    res2 = await ingest(db, p, [pg2.view(now - timedelta(seconds=20))], now=now)
    print("P4b deny-all checker, asset/attempt/test/company_path entity:", res2[0], "checks:", deny.calls)
    assert res2[0]["status"] == "accepted" and deny.calls == []


# --------------------------------------------------------------------------- P5 crafted metrics


async def test_p5_two_tabs_out_of_order_duplicates_and_forged_active_ms(db, now) -> None:
    """Hand-computed: A lesson_text 10:00 view, hb every 15 s to 10:10:00, hide 10:10:05.
    B lesson_text (other lesson) 10:05 view, hb every 15 s to 10:15:00, hide 10:15:00.
    Scroll rises each sample (evidence). Expected: M2 = |[10:00,10:10:05] U [10:05,10:15]| = 900,
    M5 = 900, M1 = 900, M3 = M4 = 0. Batches are sent in reverse order, one batch is re-sent, and
    one forged extra sample (active_ms=20000, 10 s after the previous) is added to tab A."""
    day = ist_date(now) - timedelta(days=1)
    uid = await make_user(db)
    p = principal_for(uid)
    a = Page("lesson_text", {"lesson_id": str(uuid7())})
    b = Page("lesson_text", {"lesson_id": str(uuid7())})
    ev_a = [a.view(ist(day, 10))]
    for i, t in enumerate(steps(ist(day, 10), ist(day, 10, 10))):
        ev_a.append(a.hb(t, reading={"max_scroll_depth_pct": min(100, i + 1)}))
    ev_a.append(a.hide(ist(day, 10, 10, 5)))
    ev_b = [b.view(ist(day, 10, 5))]
    for i, t in enumerate(steps(ist(day, 10, 5), ist(day, 10, 15))):
        ev_b.append(b.hb(t, reading={"max_scroll_depth_pct": min(100, i + 1)}))
    ev_b.append(b.hide(ist(day, 10, 15)))
    chunks = [ev_a[i : i + 7] for i in range(0, len(ev_a), 7)] + [ev_b[i : i + 7] for i in range(0, len(ev_b), 7)]
    for c in reversed(chunks):
        await ingest(db, p, c, now=now)
    dup = await ingest(db, p, chunks[0], now=now)
    assert all(r["status"] == "duplicate" for r in dup)
    await pipeline(db, now, [day])
    got = await total_row(db, uid, day)
    print("P5 (m1,m2,m3,m4,m5):", got, "expected (900,900,0,0,900)")
    assert got == (900, 900, 0, 0, 900)


# --------------------------------------------------------------------------- P6 clock skew + retention


async def test_p6_device_clock_40_days_behind_is_accepted_then_purged_by_event_ts(db, now) -> None:
    uid = await make_user(db)
    p = principal_for(uid)
    page = Page("lesson_text")
    client_now = now - timedelta(days=40)
    res = await ingest(db, p, [page.hb(client_now)], now=now, sent_at=client_now)
    print("P6 ingest:", res)
    assert res[0]["status"] == "accepted"
    await system_context(db, "audit.read")
    eff, ets = (
        await db.execute(
            text("SELECT effective_at, event_ts FROM activity_heartbeats WHERE user_id = :u"), {"u": uid}
        )
    ).one()
    print("P6 effective_at:", eff, "event_ts:", ets)
    out = await run_retention_purge(db, now=now)
    await system_context(db, "audit.read")
    n = (await db.execute(text("SELECT count(*) FROM activity_heartbeats WHERE user_id = :u"), {"u": uid})).scalar()
    print("P6 purge:", out.get("activity_heartbeats"), "remaining rows for user:", n)
    assert n == 0


async def test_p6b_future_skew_and_future_event(db, client, auth, now) -> None:
    uid = await make_user(db)
    h = auth.login(principal_for(uid))
    page = Page("lesson_text")
    fut = now + timedelta(hours=1)
    # whole device clock 1 h fast (sent_at also fast) -> accepted, effective corrected
    r1 = await client.post(URL, json=batch([page.view(fut)], sent_at=fut), headers=h)
    # only the event is in the future -> event_in_future
    r2 = await client.post(URL, json=batch([page.hb(now + timedelta(hours=1))], sent_at=now), headers=h)
    print("P6b", r1.json()["results"], r2.json()["results"])
    assert r1.json()["results"][0]["status"] == "accepted"
    assert r2.json()["results"][0]["code"] == "event_in_future"


# --------------------------------------------------------------------------- P7 API validation shapes


async def test_p7_api_validation_and_problem_shape(db, client, auth, now) -> None:
    uid = await make_user(db)
    h = auth.login(principal_for(uid))
    page = Page("lesson_text")
    big = batch([page.hb(now - timedelta(seconds=200 - i)) for i in range(101)])
    r = await client.post(URL, json=big, headers=h)
    print("P7 101 events:", r.status_code, r.headers.get("content-type"), r.json().get("code"))
    assert r.status_code == 422 and r.headers["content-type"].startswith("application/problem+json")
    ev = page.view(now)
    ev["user_id"] = str(uuid7())
    r = await client.post(URL, json=batch([ev]), headers=h)
    print("P7 identity field in event:", r.status_code, r.json()["results"])
    assert r.json()["results"][0]["status"] == "rejected"
    r = await client.post(URL, json={**batch([page.view(now)]), "user_id": str(uuid7())}, headers=h)
    print("P7 identity at batch level:", r.status_code)
    assert r.status_code == 422
    ev = page.ev("assessment.answer_saved", now, {})
    r = await client.post(URL, json=batch([ev]), headers=h)
    print("P7 server-only:", r.json()["results"])
    r = await client.post(URL, data=b"x" * (65 * 1024), headers={**h, "content-type": "application/json"})
    print("P7 >64KiB:", r.status_code, r.json().get("code"))
    assert r.status_code == 413
    r = await client.get("/api/v1/me/analytics/learning-time", params={"from": "2026-02-01", "to": "2026-01-01"}, headers=h)
    print("P7 from>to:", r.status_code, r.json().get("code"))
    r = await client.get("/api/v1/me/analytics/summary")
    print("P7 unauth:", r.status_code, r.headers.get("content-type"))
    assert r.status_code == 401
    r = await client.get("/api/v1/exports", params={"limit": 101}, headers=h)
    print("P7 exports limit 101:", r.status_code)
    r = await client.get(f"/api/v1/exports/{uuid7()}", headers=h)
    print("P7 exports unknown:", r.status_code, r.json().get("code"))


# --------------------------------------------------------------------------- P8 drill-down scope


async def test_p8_drilldown_mastery_and_tests_not_org_scoped(db, client, auth, now) -> None:
    from app.core import auth as core_auth

    sa = ScopedAuth(auth)
    core_auth.register_permission_checker(sa)
    try:
        org_a, org_b = await make_org(db), await make_org(db)
        coordinator = await make_user(db)
        await add_member(db, org_a, coordinator, "staff")
        student = await make_user(db)
        await add_member(db, org_a, student)
        await add_member(db, org_b, student)
        await system_context(db, "audit.seed")
        t_b, t_d2c = uuid7(), uuid7()
        for topic, org in ((t_b, org_b), (t_d2c, None)):
            await db.execute(
                text(
                    "INSERT INTO topic_mastery (user_id, topic_id, organization_id, theta, band, model_version, attempts) "
                    "VALUES (:u, :t, :o, 1.0, 'strong', 'mastery-1.0', 30)"
                ),
                {"u": student, "t": topic, "o": org},
            )
        coord = principal_for(
            coordinator, org_ids=(org_a,), grants=(RoleGrant("college_coordinator", "organization", org_a),)
        )
        sa.grant(coord, "analytics.read", "organization", org_a)
        r = await client.get(f"/api/v1/analytics/reports/orgs/{org_a}/students/{student}", headers=sa.login(coord))
        print("P8 status:", r.status_code, "mastery topics:", [m["topic_id"] for m in r.json().get("mastery", [])])
        print("P8 org_b topic:", t_b, "d2c topic:", t_d2c)
    finally:
        core_auth.register_permission_checker(auth)


# --------------------------------------------------------------------------- P9 notifications


async def test_p9_notifications_ownership_and_validation(db, client, auth) -> None:
    from app.modules.notifications.service import notify

    a, b = await make_user(db), await make_user(db)
    await system_context(db, "audit.seed")
    na = await notify(db, a, "t.audit", category="learning", data={"x": 1})
    nb = await notify(db, b, "t.audit", category="learning", data={"x": 2})
    ha = auth.login(principal_for(a))
    r = await client.get("/api/v1/me/notifications", headers=ha)
    ids = [n["notification_id"] for n in r.json()["data"]]
    print("P9 list A:", r.status_code, str(na) in ids, str(nb) in ids, r.json()["unread_count"])
    r = await client.post(f"/api/v1/me/notifications/{nb}/read", headers=ha)
    print("P9 A marks B's:", r.status_code, r.json().get("code"))
    r = await client.post("/api/v1/me/notifications/read-all", headers=ha)
    print("P9 read-all A:", r.json())
    await system_context(db, "audit.read")
    rb = (await db.execute(text("SELECT read_at FROM notifications WHERE id = :i"), {"i": nb})).scalar()
    print("P9 B's read_at after A read-all:", rb)
    r = await client.get("/api/v1/me/notifications", params={"limit": 101}, headers=ha)
    print("P9 limit 101:", r.status_code, r.headers.get("content-type"), r.json().get("code"))
    r = await client.get("/api/v1/me/notifications", params={"cursor": "abc.def"}, headers=ha)
    print("P9 bad cursor:", r.status_code, r.json().get("code"))
    r = await client.post("/api/v1/me/notifications/not-a-uuid/read", headers=ha)
    print("P9 bad id:", r.status_code, r.json().get("code"))
    r = await client.get("/api/v1/me/notification-preferences", headers=ha)
    print("P9 preferences:", r.status_code)
    assert rb is None


async def test_p8b_drilldown_mastery_visibility_own_org(db, client, auth, now) -> None:
    from app.core import auth as core_auth

    sa = ScopedAuth(auth)
    core_auth.register_permission_checker(sa)
    try:
        org_a = await make_org(db)
        coordinator = await make_user(db)
        await add_member(db, org_a, coordinator, "staff")
        student = await make_user(db)
        await add_member(db, org_a, student)
        await system_context(db, "audit.seed")
        t_a = uuid7()
        await db.execute(
            text(
                "INSERT INTO topic_mastery (user_id, topic_id, organization_id, theta, band, model_version, attempts) "
                "VALUES (:u, :t, :o, 1.0, 'strong', 'mastery-1.0', 30)"
            ),
            {"u": student, "t": t_a, "o": org_a},
        )
        coord = principal_for(
            coordinator, org_ids=(org_a,), grants=(RoleGrant("college_coordinator", "organization", org_a),)
        )
        sa.grant(coord, "analytics.read", "organization", org_a)
        r = await client.get(f"/api/v1/analytics/reports/orgs/{org_a}/students/{student}", headers=sa.login(coord))
        print("P8b own-org mastery visible to coordinator:", r.status_code, r.json().get("mastery"))
        print("P8b accuracy_by_topic:", r.json().get("accuracy_by_topic"))
    finally:
        core_auth.register_permission_checker(auth)


# --------------------------------------------------------------------------- P1b end-to-end lesson completion


async def test_p1b_forged_analytics_coverage_completes_video_lesson(db, app, now) -> None:
    from sqlalchemy import select

    from app.core.db import tenant_context
    from app.modules.catalog.models import Course, Lesson
    from app.modules.learning import service as learning
    from app.modules.learning.models import LessonProgress
    from tests.catalog.factory import make_published_course

    uid = await make_user(db)
    p = principal_for(uid)
    pc = await make_published_course(db, uid, is_free=True)
    await tenant_context(db, p)
    course = await db.get(Course, pc.course_id)
    enr, _ = await learning.self_enrol(db, p, course)
    vid_lesson = pc.lessons["video"]
    # 3 forged analytics heartbeats, 10 s apart, random asset id, lesson_id = the enrolled video lesson
    page = Page("lesson_video", {"course_id": pc.course_id, "lesson_id": vid_lesson})
    t0 = now - timedelta(minutes=1)
    ev = []
    asset = uuid7()
    for i in range(3):
        ev.append(
            page.hb(
                t0 + timedelta(seconds=10 * i),
                active_ms=10000,
                media=True,
                interval_ms=330000,
                media_info={"lesson_asset_id": str(asset), "rate": 2.0, "played_ranges": [[727 * i, 727 * (i + 1)]]},
            )
        )
    res = await ingest(db, p, ev, now=now)
    assert all(r["status"] == "accepted" for r in res), res
    await run_video_coverage(db, now=now)
    await tenant_context(db, p)
    lesson = await db.get(Lesson, vid_lesson)
    # ONE learning video heartbeat with a 5 s position advance (what any player would send)
    await learning.record_video_heartbeat(
        db, p, lesson, course, prev_pos=0, new_pos=5, elapsed_s=5, playing=True, duration_s=600
    )
    lp = (
        await db.execute(
            select(LessonProgress).where(LessonProgress.enrolment_id == enr.id, LessonProgress.lesson_key == pc.keys["video"])
        )
    ).scalar_one()
    from app.modules.learning import service as _ls
    print("P1b lookup registered:", _ls._coverage_lookup is not None)
    print("P1b lesson progress:", lp.status, lp.watched_seconds, lp.progress_pct)
    assert lp.status == "completed"
