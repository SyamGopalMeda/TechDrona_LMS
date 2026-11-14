"""ADM-016 courses overview: per-course enrolment / certificate counts, the course's batches
(through ``enrolments.batch_id``) and the dashboard certificate block; same permission as the
ADM-01 dashboard."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import update

from app.core.db import system_context
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.catalog.models import Course
from app.modules.learning.models import Certificate, Enrolment
from app.modules.orgs.models import Batch
from tests.catalog.factory import make_published_course
from tests.identity.factory import Browser, company_org, make_batch, make_user
from tests.security.helpers import adult, staff, staff_browser


def _cert(user_id, course_id, version_id, enrolment_id, *, revoked: bool = False) -> Certificate:
    cid = uuid7()
    return Certificate(
        id=cid,
        public_code=f"T{cid.hex[-12:].upper()}",
        user_id=user_id,
        course_id=course_id,
        course_version_id=version_id,
        enrolment_id=enrolment_id,
        name_on_certificate="Test User",
        template_version="v1",
        content_hash=b"\x01" * 32,
        revoked_at=utcnow() if revoked else None,
        revoke_reason="test" if revoked else None,
    )


async def test_courses_overview_counts_batches_and_certificates(client, db) -> None:
    sa = await staff(db, "super_admin")
    bsa = await staff_browser(client, sa, ip="198.18.6.1")
    pc = await make_published_course(db, sa.id, title="Overview Course")
    batch = await make_batch(db, company_org(), sa.id)
    start, end = date.today() + timedelta(days=7), date.today() + timedelta(days=60)

    before = (await bsa.get("/admin/courses/overview")).json()["certificates"]

    users = [await make_user(db) for _ in range(5)]
    await system_context(db, "test.factory")
    await db.execute(update(Batch).where(Batch.id == batch).values(starts_on=start, ends_on=end))
    # u0, u1 active (u0 in the batch); u2 completed + valid certificate; u3 completed, no
    # certificate (ready); u4 completed + revoked certificate (handled, not ready).
    enr = {}
    for i, u in enumerate(users):
        eid = uuid7()
        enr[i] = eid
        db.add(
            Enrolment(
                id=eid,
                user_id=u.id,
                course_id=pc.course_id,
                course_version_id=pc.version_id,
                batch_id=batch if i == 0 else None,
                source="manual",
                status="active" if i < 2 else "completed",
                completed_at=None if i < 2 else utcnow(),
            )
        )
    await db.flush()
    db.add(_cert(users[2].id, pc.course_id, pc.version_id, enr[2]))
    db.add(_cert(users[4].id, pc.course_id, pc.version_id, enr[4], revoked=True))
    await db.flush()

    res = await bsa.get("/admin/courses/overview")
    assert res.status_code == 200, res.text
    body = res.json()
    assert {"generated_at", "totals", "certificates", "courses"} <= body.keys()
    card = next(c for c in body["courses"] if c["course_id"] == str(pc.course_id))
    assert card["title"] == "Overview Course" and card["slug"] == pc.slug
    assert card["status"] == "published" and card["published_at"]
    assert card["enrolled"] == 2 and card["completed"] == 3
    assert card["certificates_issued"] == 1 and card["certificates_ready"] == 1
    assert card["batch_count"] == 1
    b = card["batches"][0]
    assert b["batch_id"] == str(batch) and b["enrolled"] == 1
    assert b["starts_on"] == start.isoformat() and b["ends_on"] == end.isoformat()

    certs = body["certificates"]
    assert certs["issued_valid"] == before["issued_valid"] + 1
    assert certs["revoked"] == before["revoked"] + 1
    assert certs["issued_30d"] == before["issued_30d"] + 2
    assert certs["ready"] == before["ready"] + 1
    assert body["totals"]["learners"] >= 5 and body["totals"]["courses"] >= 1


async def test_courses_overview_lists_drafts_skips_deleted_and_needs_admin(client, db) -> None:
    sa = await staff(db, "super_admin")
    bsa = await staff_browser(client, sa, ip="198.18.6.2")
    cm = await staff(db, "content_manager")
    bcm = await staff_browser(client, cm, ip="198.18.6.3")
    student = await adult(db)

    pc = await make_published_course(db, sa.id, title="Soon Gone")
    await system_context(db, "test.factory")
    draft_id = uuid7()
    db.add(Course(id=draft_id, slug=f"draft-{draft_id.hex[-10:]}", title="Draft Only", created_by=sa.id))
    await db.flush()
    await db.execute(update(Course).where(Course.id == pc.course_id).values(deleted_at=utcnow()))
    await db.flush()

    res = await bsa.get("/admin/courses/overview")
    assert res.status_code == 200, res.text
    ids = {c["course_id"]: c for c in res.json()["courses"]}
    assert str(pc.course_id) not in ids  # soft-deleted
    draft = ids[str(draft_id)]
    assert draft["status"] == "draft" and draft["published_at"] is None
    assert draft["enrolled"] == 0 and draft["batches"] == [] and draft["batch_count"] == 0

    assert (await bcm.get("/admin/courses/overview")).status_code == 403
    sb = Browser(client)
    await sb.login(student.email)
    assert (await sb.get("/admin/courses/overview")).status_code == 403
