"""Batch plan, classes and attendance API + website plan import (orgs_0005, Postgres).

Scope: a trainer granted on batch A manages A's classes and attendance and never sees or marks
batch B; the plan is edited by Admin only; learners see their own classes and attendance.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from app.core.company import COMPANY_ORG_ID
from app.core.db import system_context
from app.core.time import ist_date, utcnow
from app.modules.orgs.import_website_plans import import_plans, map_document
from app.modules.orgs.models import Batch, BatchPlan, ClassAttendance
from app.modules.orgs.service import attendance_certificate_block
from tests.identity.factory import add_member, company_org, grant, make_batch, make_user, staff_login

PLAN = {
    "total_hours": 20,
    "daily_hours": 2,
    "working_days": [1, 2, 3, 4, 5],
    "holidays": [],
    "class_time": "18:30",
    "meet_url": "https://meet.example.com/abc",
    "weeks": [
        {"title": "Basics", "topics": ["HTML"], "activities": []},
        {
            "title": "Project",
            "topics": [],
            "activities": [{"id": "p1-submit", "kind": "project", "title": "Submit"}],
        },
    ],
}


async def _admin(db, browser):
    a = await make_user(db, with_totp=True)
    await grant(db, a.id, "super_admin")
    await staff_login(browser, a)
    return a


def _yesterday() -> str:
    return (ist_date(utcnow()) - timedelta(days=1)).isoformat()


async def test_admin_edits_plan_and_schedule_follows(browser, db) -> None:
    admin = await _admin(db, browser)
    b = await make_batch(db, company_org(), admin.id)
    empty = (await browser.get(f"/batches/{b}/plan")).json()
    assert empty["has_plan"] is False and empty["schedule"]["sessions"] == 0
    r = await browser.request(
        "PUT",
        f"/batches/{b}/plan",
        json={
            "plan": PLAN,
            "starts_on": "2026-11-02",
            "website_course_slug": "full-stack",
            "min_attendance_percent": 75,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_plan"] and body["batch"]["ends_on"] == "2026-11-13"
    assert body["batch"]["website_course_slug"] == "full-stack"
    assert body["schedule"]["weeks_count"] == 2 and body["min_attendance_percent"] == 75
    got = (await browser.get(f"/batches/{b}")).json()
    assert (got["starts_on"], got["ends_on"], got["website_course_slug"]) == (
        "2026-11-02",
        "2026-11-13",
        "full-stack",
    )
    bad = await browser.request("PUT", f"/batches/{b}/plan", json={"plan": {**PLAN, "working_days": [9]}})
    assert bad.status_code == 400  # body schema errors use the global validation handler (400)
    unknown = await browser.request(
        "PUT", f"/batches/{b}/plan", json={"plan": PLAN, "course_id": "00000000-0000-7000-8000-000000000001"}
    )
    assert unknown.status_code == 422
    prev = await browser.post(
        f"/batches/{b}/plan/preview", {"plan": {**PLAN, "total_hours": 40}, "starts_on": "2026-11-02"}
    )
    assert prev.status_code == 200 and prev.json()["end_date"] == "2026-11-27"
    gen = await browser.post(f"/batches/{b}/sessions/generate", {})
    assert gen.status_code == 200 and gen.json()["created"] == 10
    again = await browser.post(f"/batches/{b}/sessions/generate", {})
    assert again.json()["created"] == 0
    rows = (await browser.get(f"/batches/{b}/sessions")).json()["data"]
    assert rows[0]["topic"] == "Week 1: Basics" and rows[0]["starts_at"] == "18:30"
    assert rows[0]["meet_url"] == "https://meet.example.com/abc"


async def test_trainer_scope_classes_and_attendance(browser, db) -> None:
    owner = await make_user(db)
    a = await make_batch(db, company_org(), owner.id)
    other = await make_batch(db, company_org(), owner.id)
    s1, s2, outsider = await make_user(db), await make_user(db), await make_user(db)
    await add_member(db, company_org(), s1.id, "student", a)
    await add_member(db, company_org(), s2.id, "student", a)
    trainer = await make_user(db, with_totp=True)
    await grant(db, trainer.id, "trainer", "batch", a)
    await staff_login(browser, trainer)

    r = await browser.post(f"/batches/{a}/sessions", {"session_date": _yesterday(), "topic": "Intro"})
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    dup = await browser.post(f"/batches/{a}/sessions", {"session_date": _yesterday()})
    assert dup.status_code == 409
    # plan edits are Admin only; reading is fine
    assert (await browser.get(f"/batches/{a}/plan")).status_code == 200
    assert (await browser.request("PUT", f"/batches/{a}/plan", json={"plan": PLAN})).status_code == 403

    marks = {"marks": [{"user_id": str(s1.id), "status": "P"}, {"user_id": str(s2.id), "status": "L"}]}
    r = await browser.request("PUT", f"/batches/{a}/sessions/{sid}/attendance", json=marks)
    assert r.status_code == 200, r.text
    assert r.json()["session"]["attendance"] == {"P": 1, "L": 1, "A": 0, "marked": 2}
    # re-marking upserts (unique per class + learner), null clears
    r = await browser.request(
        "PUT",
        f"/batches/{a}/sessions/{sid}/attendance",
        json={"marks": [{"user_id": str(s2.id), "status": "A"}, {"user_id": str(s1.id), "status": None}]},
    )
    assert r.json()["session"]["attendance"] == {"P": 0, "L": 0, "A": 1, "marked": 1}
    # only students of the batch
    r = await browser.request(
        "PUT",
        f"/batches/{a}/sessions/{sid}/attendance",
        json={"marks": [{"user_id": str(outsider.id), "status": "P"}]},
    )
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not_in_batch"
    summary = (await browser.get(f"/batches/{a}/attendance")).json()
    by = {row["user_id"]: row for row in summary["data"]}
    assert by[str(s2.id)]["percent"] == 0 and by[str(s1.id)]["marked"] == 0

    # batch B: everything is refused, and a class of A is not reachable through B
    assert (await browser.get(f"/batches/{other}/sessions")).status_code == 403
    assert (
        await browser.post(f"/batches/{other}/sessions", {"session_date": _yesterday()})
    ).status_code == 403
    r = await browser.request("PUT", f"/batches/{other}/sessions/{sid}/attendance", json=marks)
    assert r.status_code == 403
    assert (await browser.get(f"/batches/{other}/attendance")).status_code == 403

    # future classes cannot be marked; marked classes cannot be deleted
    fut = (ist_date(utcnow()) + timedelta(days=3)).isoformat()
    fid = (await browser.post(f"/batches/{a}/sessions", {"session_date": fut})).json()["id"]
    r = await browser.request("PUT", f"/batches/{a}/sessions/{fid}/attendance", json=marks)
    assert r.status_code == 422
    assert (await browser.delete(f"/batches/{a}/sessions/{sid}")).status_code == 409
    assert (await browser.delete(f"/batches/{a}/sessions/{fid}")).status_code == 200

    # the learner sees their own classes and attendance, and cannot mark
    sb = browser.fork(ua="Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0")
    await sb.login(s2.email)
    mine = (await sb.get("/me/classes")).json()
    [entry] = [x for x in mine["batches"] if x["batch"]["id"] == str(a)]
    assert entry["attendance"]["absent"] == 1 and entry["recent"][0]["my_status"] == "A"
    assert "notes" not in entry["recent"][0]
    att = (await sb.get("/me/attendance")).json()
    assert any(x["summary"]["marked"] == 1 for x in att["batches"])
    assert (await sb.get(f"/batches/{a}/sessions")).status_code == 403
    r = await sb.request("PUT", f"/batches/{a}/sessions/{sid}/attendance", json=marks)
    assert r.status_code == 403


async def test_attendance_certificate_gate(db) -> None:
    owner = await make_user(db)
    b = await make_batch(db, company_org(), owner.id)
    s = await make_user(db)
    await add_member(db, company_org(), s.id, "student", b)
    await system_context(db, "t")
    assert await attendance_certificate_block(db, b, s.id) is None  # no plan: off
    from app.core.ids import uuid7
    from app.modules.orgs.models import ClassSession

    db.add(BatchPlan(batch_id=b, organization_id=COMPANY_ORG_ID, plan=PLAN, min_attendance_percent=75))
    cs = ClassSession(
        id=uuid7(),
        batch_id=b,
        organization_id=COMPANY_ORG_ID,
        session_date=ist_date(utcnow()),
        created_by=owner.id,
    )
    db.add(cs)
    await db.flush()
    assert await attendance_certificate_block(db, b, s.id) is None  # never marked: not blocked
    db.add(
        ClassAttendance(
            id=uuid7(),
            session_id=cs.id,
            batch_id=b,
            organization_id=COMPANY_ORG_ID,
            user_id=s.id,
            status="A",
            marked_by=owner.id,
        )
    )
    await db.flush()
    assert await attendance_certificate_block(db, b, s.id) == "Attendance is 0% (at least 75% is needed)"


def _fields(**over):
    base = {
        "title": "Agentic AI",
        "status": "coming_soon",
        "site_slug": "agentic-ai-t",
        "start_date": "",
        "total_hours": 50,
        "daily_hours": 2,
        "working_days": [1, 2, 3, 4, 5],
        "holidays": [],
        "registrations_open": False,
        "weeks": [{"title": "Week one", "topics": ["LLMs"], "activities": []}],
    }
    return base | over


async def test_import_is_dry_run_by_default_and_idempotent(db) -> None:
    admin = await make_user(db)
    doc = "TestDocImport01"
    mapped = [map_document(doc, _fields(created_by=admin.email))]
    rep = await import_plans(db, mapped, apply=False)
    assert [r["action"] for r in rep] == ["create"]

    async def _count():
        await system_context(db, "t")
        return (
            await db.execute(
                select(func.count())
                .select_from(BatchPlan)
                .where(BatchPlan.source_ref == f"web_courses/{doc}")
            )
        ).scalar_one()

    assert await _count() == 0  # dry run wrote nothing
    rep = await import_plans(db, mapped, apply=True)
    assert rep[0]["action"] == "create" and rep[0]["course_id"] is None
    assert await _count() == 1
    plan = (
        await db.execute(select(BatchPlan).where(BatchPlan.source_ref == f"web_courses/{doc}"))
    ).scalar_one()
    b = await db.get(Batch, plan.batch_id)
    assert (b.name, b.status, b.starts_on, b.ends_on, b.website_course_slug) == (
        "Agentic AI",
        "planned",
        None,
        None,
        "agentic-ai-t",
    )
    assert b.code == "web-agentic-ai-t" and b.created_by == admin.id
    # same input again: nothing changes
    rep = await import_plans(db, mapped, apply=True)
    assert rep[0]["action"] == "unchanged" and await _count() == 1
    # the website plan changed: the batch is updated in place (same id)
    changed = [map_document(doc, _fields(created_by=admin.email, status="running", start_date="2026-11-02"))]
    rep = await import_plans(db, changed, apply=True)
    assert rep[0]["action"] == "update" and {"status", "starts_on", "ends_on"} <= set(rep[0]["changes"])
    await db.refresh(b)
    assert b.status == "active" and str(b.starts_on) == "2026-11-02" and b.ends_on is not None
    rep = await import_plans(db, changed, apply=True, skip_existing=True)
    assert rep[0]["action"] == "skip"
    # an unknown creator without --created-by is an error row (the CLI then writes nothing)
    orphan = [
        map_document("TestDocImport02", _fields(site_slug="agentic-ai-u", created_by="nobody@example.com"))
    ]
    rep = await import_plans(db, orphan, apply=False)
    assert rep[0]["action"] == "error"
    rep = await import_plans(db, orphan, apply=False, created_by_email=admin.email)
    assert rep[0]["action"] == "create"
