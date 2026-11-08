"""Wave-2 fixes (agent w2a): BE-02 attribution through the orgs service end to end (learner
activity -> trainer batch report), and the batch report fields the staff portals render
(progress distribution, lesson funnel). Single company: organization reports are gone."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text

from app.core.db import system_context
from app.core.ids import uuid7
from app.core.principal import RoleGrant
from app.core.time import ist_date
from app.modules.analytics import hooks, reports
from app.modules.analytics.consumer import consume_outbox
from app.modules.analytics.jobs import run_daily_aggregation, run_interval_builder
from tests.analytics.conftest import (
    Page,
    add_batch_member,
    add_member,
    ingest,
    make_batch,
    make_org,
    make_user,
    principal_for,
)
from tests.catalog.factory import make_published_course


async def _enrol(db, user, pc, org, batch, *, pct: float, status: str = "active") -> uuid.UUID:
    await system_context(db, "test.analytics")
    eid = uuid7()
    await db.execute(
        text(
            "INSERT INTO enrolments (id, user_id, course_id, course_version_id, organization_id, batch_id, "
            "source, status, progress_pct, completed_at) VALUES (:id, :u, :c, :v, :o, :b, 'batch_sync', :s, "
            ":p, CASE WHEN :s = 'completed' THEN now() END)"
        ),
        {
            "id": eid,
            "u": user,
            "c": pc.course_id,
            "v": pc.version_id,
            "o": org,
            "b": batch,
            "s": status,
            "p": pct,
        },
    )
    return eid


async def _progress(db, eid, user, org, lesson_key, status: str) -> None:
    await system_context(db, "test.analytics")
    await db.execute(
        text(
            "INSERT INTO lesson_progress (enrolment_id, lesson_key, user_id, organization_id, status, "
            "first_opened_at, completed_at) VALUES (:e, :k, :u, :o, :s, now(), "
            "CASE WHEN :s = 'completed' THEN now() END)"
        ),
        {"e": eid, "k": lesson_key, "u": user, "o": org, "s": status},
    )


async def _lesson_keys(db, version_id) -> list[uuid.UUID]:
    await system_context(db, "test.read")
    return list(
        (
            await db.execute(
                text(
                    "SELECT l.lesson_key FROM lessons l JOIN course_modules m ON m.id = l.course_module_id "
                    "WHERE l.course_version_id = :v ORDER BY m.position, l.position"
                ),
                {"v": version_id},
            )
        ).scalars()
    )


def test_default_resolver_is_the_orgs_service_one() -> None:
    """No resolver registered in wiring -> ``resolve_org`` uses ``_default_org`` (orgs service
    helpers, no raw SQL on memberships)."""
    import inspect

    src = inspect.getsource(hooks._default_org)
    assert "batch_org_for_member" in src and "active_student_org_ids" in src
    assert "text(" not in src and "FROM " not in src  # no raw SQL


async def test_be02_learner_activity_reaches_trainer_batch_report(db, client, scoped_auth, now) -> None:
    t0 = now - timedelta(minutes=4)
    if ist_date(t0) != ist_date(now):
        pytest.skip("straddles IST midnight")
    org = await make_org(db)
    trainer_id = await make_user(db)
    await add_member(db, org, trainer_id, "staff")
    batch = await make_batch(db, org, trainer_id)
    scoped_auth.batch_orgs[batch] = org
    pc = await make_published_course(db, trainer_id)
    keys = await _lesson_keys(db, pc.version_id)
    # ten students in the batch (k-floor 10), each enrolled through the batch
    students: list[uuid.UUID] = []
    for i in range(10):
        u = await make_user(db)
        await add_member(db, org, u)
        await add_batch_member(db, batch, org, u)
        if i < 9:
            eid = await _enrol(
                db,
                u,
                pc,
                org,
                batch,
                pct=[0, 10, 30, 30, 60, 80, 100, 50, 0][i],
                status="completed" if i == 6 else "active",
            )
            if i in (1, 2, 3, 4, 5, 6, 7):
                await _progress(db, eid, u, org, keys[0], "completed" if i >= 4 else "in_progress")
            if i == 6:
                await _progress(db, eid, u, org, keys[1], "completed")
        students.append(u)
    # learner A: enrolled -> attribution through the enrolment; learner B (no enrolment) sends
    # only a batch hint -> attribution through orgs.service.batch_org_for_member
    a, b = students[0], students[9]
    for who, entity in (
        (a, {"course_id": str(pc.course_id), "lesson_id": str(pc.lessons["article"])}),
        (b, {"batch_id": str(batch)}),
    ):
        page = Page("lesson_text", entity)
        ev = [page.view(t0)]
        for i in range(1, 6):
            ev.append(page.hb(t0 + timedelta(seconds=15 * i), reading={"max_scroll_depth_pct": 20 * i}))
        ev.append(page.hide(t0 + timedelta(seconds=80)))
        res = await ingest(db, principal_for(who, org_ids=(org,)), ev, now=now)
        assert all(r["status"] == "accepted" for r in res), res
    await consume_outbox(db)
    await run_interval_builder(db, now=now)
    await run_daily_aggregation(db, now=now)

    trainer = principal_for(trainer_id, org_ids=(org,), grants=(RoleGrant("trainer", "batch", batch),))
    scoped_auth.grant(trainer, "analytics.read", "batch", batch)
    h = scoped_auth.login(trainer)
    r = await client.get(f"/api/v1/analytics/reports/batches/{batch}", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    rows = {x["user_id"]: x for x in body["learners"]}
    assert body["learners_total"] == 10 and len(rows) == 10
    assert rows[str(a)]["weekly_learning_s"] > 0, body
    assert rows[str(b)]["weekly_learning_s"] > 0, body
    # progress distribution over the 9 enrolments: below the k-floor -> suppressed
    dist = body["progress_distribution"]
    assert dist["suppressed"] is True and dist["enrolments"] == "<10"
    assert [x["bucket"] for x in dist["buckets"]] == [
        "not_started",
        "1-25",
        "26-50",
        "51-75",
        "76-99",
        "completed",
    ]
    funnel = body["lesson_funnel"]
    assert len(funnel) == 1 and funnel[0]["course_id"] == str(pc.course_id)
    assert [s["lesson_key"] for s in funnel[0]["steps"]] == [str(k) for k in keys]

    # a 10th enrolment lifts the floor: real counts
    await _enrol(db, b, pc, org, batch, pct=0)
    body = (await client.get(f"/api/v1/analytics/reports/batches/{batch}", headers=h)).json()
    dist = body["progress_distribution"]
    assert dist["suppressed"] is False and dist["enrolments"] == 10
    got = {x["bucket"]: x["enrolments"] for x in dist["buckets"]}
    assert got == {"not_started": 3, "1-25": 1, "26-50": 3, "51-75": 1, "76-99": 1, "completed": 1}
    steps = body["lesson_funnel"][0]["steps"]
    assert steps[0]["started"] == 7 and steps[0]["completed"] == 4
    assert steps[1]["started"] == 1 and steps[1]["completed"] == 1

    # single company: the organization report is gone
    assert (await client.get(f"/api/v1/analytics/reports/orgs/{org}", headers=h)).status_code == 404


def test_progress_buckets() -> None:
    assert reports._bucket_of(0, False) == "not_started"
    assert reports._bucket_of(25, False) == "1-25"
    assert reports._bucket_of(25.5, False) == "26-50"
    assert reports._bucket_of(99.99, False) == "76-99"
    assert reports._bucket_of(40, True) == "completed"
