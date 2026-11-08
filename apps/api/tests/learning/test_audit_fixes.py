"""Regression tests for audit Phase B fixes in catalog/learning (fix agent ``learn``):
BE-05, BE-06, BE-07, BE-08, BE-34, DB-03, COM-12, ADM-41, ADM-47, ADM-57."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core import access
from app.core.access import AccessDecision
from app.core.audit import AuditActor
from app.core.db import system_context
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.catalog.models import Course, CourseModule, CourseVersion, Lesson
from app.modules.learning import service as ls
from app.modules.learning.models import Assignment, AssignmentSubmission, Certificate, Enrolment
from tests.catalog.factory import idem, make_published_course, student
from tests.identity.factory import add_member, company_org, grant, make_batch, make_user, staff_login


@pytest.fixture(autouse=True)
def fake_video():
    from app.modules.media import providers

    fake = providers.FakeVideoProvider()
    providers.set_video_provider(fake)
    prev = access.get_access_checker()
    access.register_access_checker(None)
    yield fake
    access.register_access_checker(prev)
    providers.set_video_provider(None)


# --------------------------------------------------------------------------- BE-05


async def test_be05_private_free_platform_course_lessons_are_404(browser, db) -> None:
    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=True, visibility="private")
    await student(db, browser)
    assert (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).status_code == 404
    r = await browser.get(f"/me/courses/{pc.course_id}/lessons/{pc.lessons['article']}")
    assert r.status_code == 404, r.text
    assert "article_body" not in r.text
    r = await browser.post("/media/playback-tokens", {"lesson_asset_id": str(pc.assets["video"])})
    assert r.status_code == 404


async def test_be05_existing_enrolment_keeps_access_when_course_becomes_private(browser, db) -> None:
    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=True)
    await student(db, browser)
    assert (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).status_code == 201
    await system_context(db, "t")
    await db.execute(update(Course).where(Course.id == pc.course_id).values(visibility="private"))
    await db.flush()
    r = await browser.get(f"/me/courses/{pc.course_id}/lessons/{pc.lessons['article']}")
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- BE-06


async def test_be06_minor_publish_recomputes_and_reopens(browser, db) -> None:
    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=True)
    u = await student(db, browser)
    assert (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).status_code == 201
    await system_context(db, "t")
    for k in ("article", "video"):
        assert await ls.record_completion(db, u.id, pc.keys[k], {"kind": "test"})
    await db.flush()
    v2 = uuid7()
    db.add(
        CourseVersion(
            id=v2,
            course_id=pc.course_id,
            version_no=2,
            title="v2",
            status="published",
            published_at=utcnow(),
            published_by=author.id,
            created_by=author.id,
            change_type="minor",
            certificate_rule={"required_lessons_pct": 100},
        )
    )
    await db.flush()
    mid = uuid7()
    db.add(CourseModule(id=mid, course_version_id=v2, module_key=uuid7(), title="B", position=0))
    await db.flush()
    old = (await db.execute(select(Lesson).where(Lesson.course_version_id == pc.version_id))).scalars().all()
    for i, le in enumerate(old):
        db.add(
            Lesson(
                id=uuid7(),
                course_module_id=mid,
                course_version_id=v2,
                lesson_key=le.lesson_key,
                title=le.title,
                position=i,
                lesson_type=le.lesson_type,
                duration_seconds=le.duration_seconds,
                est_reading_minutes=le.est_reading_minutes,
            )
        )
    db.add(
        Lesson(
            id=uuid7(),
            course_module_id=mid,
            course_version_id=v2,
            lesson_key=uuid7(),
            title="New",
            position=9,
            lesson_type="article",
            est_reading_minutes=1,
            article_body={"d": 1},
        )
    )
    await db.flush()
    await db.execute(update(Course).where(Course.id == pc.course_id).values(current_version_id=v2))
    course = await db.get(Course, pc.course_id)
    version = await db.get(CourseVersion, v2)
    assert course is not None and version is not None
    await db.refresh(course)
    await ls.on_course_published(db, course, version)
    await db.flush()
    db.expire_all()
    ov = (await browser.get(f"/me/courses/{pc.course_id}")).json()
    assert ov["enrolment"]["course_version_id"] == str(v2)
    assert ov["enrolment"]["status"] == "active"
    assert ov["enrolment"]["progress_pct"] == pytest.approx(66.67)


# --------------------------------------------------------------------------- DB-03


async def test_db03_duplicate_enrolment_insert_is_409_not_500(browser, db) -> None:
    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=True)
    u = await student(db, browser)
    assert (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).status_code == 201
    await system_context(db, "t")
    course = await db.get(Course, pc.course_id)
    assert course is not None
    # Simulates the loser of a race that passed the existence check before the winner committed.
    with pytest.raises(ProblemError) as ei:
        await ls.create_enrolment(db, user_id=u.id, course=course, source="free")
    assert ei.value.status == 409
    n = (await db.execute(select(Enrolment).where(Enrolment.user_id == u.id))).scalars().all()
    assert len(n) == 1
    # A repeated self-enrol (second tab) is a 200 replay of the same enrolment.
    r = await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})
    assert r.status_code == 200, r.text


# --------------------------------------------------------------------------- BE-34


async def test_be34_limits_validated_and_learner_lists_paginate(browser, db) -> None:
    author = await make_user(db)
    a = await make_published_course(db, author.id, is_free=True, title="A")
    b = await make_published_course(db, author.id, is_free=True, title="B")
    await student(db, browser)
    anon = browser.fork()
    r = await anon.get("/catalog/courses", params={"limit": 1000})
    assert r.status_code == 400 and r.json()["code"] == "validation_failed"
    for pc in (a, b):
        assert (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).status_code == 201
    r1 = (await browser.get("/me/enrolments", params={"limit": 1})).json()
    assert len(r1["data"]) == 1 and r1["page"]["has_more"] is True and r1["page"]["limit"] == 1
    r2 = (
        await browser.get("/me/enrolments", params={"limit": 1, "cursor": r1["page"]["next_cursor"]})
    ).json()
    assert len(r2["data"]) == 1 and r2["page"]["has_more"] is False
    assert {r1["data"][0]["course_id"], r2["data"][0]["course_id"]} == {str(a.course_id), str(b.course_id)}
    assert (await browser.get("/me/enrolments", params={"limit": 0})).status_code == 400
    assert (await browser.get("/me/certificates", params={"limit": 500})).status_code == 400


# --------------------------------------------------------------------------- COM-12


async def test_com12_revoke_certificates_for_entitlement(browser, db) -> None:
    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=True)
    u = await student(db, browser)
    assert (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).status_code == 201
    await system_context(db, "t")
    ent_id = uuid.uuid4()
    await db.execute(update(Enrolment).where(Enrolment.user_id == u.id).values(entitlement_id=ent_id))
    for k in ("article", "video"):
        assert await ls.record_completion(db, u.id, pc.keys[k], {"kind": "test"})
    await db.flush()
    cert = (await db.execute(select(Certificate).where(Certificate.user_id == u.id))).scalar_one()
    assert cert.revoked_at is None
    out = await ls.revoke_certificates_for_entitlement(db, AuditActor.system("test"), ent_id, reason="refund")
    assert out == [cert.id]
    await db.refresh(cert)
    assert cert.revoked_at is not None and cert.revoke_reason == "refund"
    # idempotent
    assert await ls.revoke_certificates_for_entitlement(db, AuditActor.system("test"), ent_id) == []


# --------------------------------------------------------------------------- assignments


async def _trainer_batch_student(db, browser):
    org = company_org()
    tr = browser.fork()
    trainer = await make_user(db, with_totp=True)
    await add_member(db, org, trainer.id, "staff")
    batch = await make_batch(db, org, trainer.id)
    await grant(db, trainer.id, "trainer", "batch", batch)
    await staff_login(tr, trainer)
    s = await student(db, browser)
    await add_member(db, org, s.id, "student", batch_id=batch)
    return tr, batch, s


async def test_be07_code_assignment_rejects_unknown_code_submission(browser, db) -> None:
    tr, batch, _s = await _trainer_batch_student(db, browser)
    r = await tr.post(
        "/assignments",
        {
            "batch_id": str(batch),
            "title": "Code",
            "instructions_md": "x",
            "submission_type": "code",
            "max_score": 10,
            "due_at": (utcnow() + timedelta(days=2)).isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    r = await browser.post(
        f"/me/assignments/{r.json()['id']}/submissions",
        {"code_submission_id": str(uuid.uuid4())},
        headers=idem(),
    )
    assert r.status_code == 422, r.text
    assert r.json()["errors"][0]["field"] == "code_submission_id"


async def test_be08_late_penalty_applied_and_adm57_grading_audited(browser, db, audited) -> None:
    tr, batch, _s = await _trainer_batch_student(db, browser)
    r = await tr.post(
        "/assignments",
        {
            "batch_id": str(batch),
            "title": "T",
            "instructions_md": "x",
            "submission_type": "text",
            "max_score": 10,
            "late_penalty_pct": 50,
            "due_at": (utcnow() + timedelta(days=2)).isoformat(),
            "late_until": (utcnow() + timedelta(days=4)).isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    await system_context(db, "t")
    await db.execute(
        update(Assignment).where(Assignment.id == uuid.UUID(aid)).values(due_at=utcnow() - timedelta(hours=1))
    )
    await db.flush()
    r = await browser.post(f"/me/assignments/{aid}/submissions", {"body_text": "answer"}, headers=idem())
    assert r.status_code == 201 and r.json()["status"] == "late", r.text
    sid = r.json()["id"]
    g = await tr.post(f"/assignment-submissions/{sid}/grade", {"score": 10})
    assert g.status_code == 200, g.text
    assert g.json()["score"] == 5.0 and g.json()["raw_score"] == 10.0 and g.json()["late_penalty_pct"] == 50.0
    assert (await tr.post(f"/assignments/{aid}/release-grades", {})).status_code == 200
    mine = await browser.get(f"/assignment-submissions/{sid}")
    assert mine.json()["score"] == 5.0
    assert "assignment.grade" in audited and "assignment.grades_release" in audited


async def test_on_time_submission_has_no_penalty(browser, db) -> None:
    tr, batch, _s = await _trainer_batch_student(db, browser)
    r = await tr.post(
        "/assignments",
        {
            "batch_id": str(batch),
            "title": "T",
            "instructions_md": "x",
            "submission_type": "text",
            "max_score": 10,
            "late_penalty_pct": 50,
            "due_at": (utcnow() + timedelta(days=2)).isoformat(),
        },
    )
    aid = r.json()["id"]
    r = await browser.post(f"/me/assignments/{aid}/submissions", {"body_text": "answer"}, headers=idem())
    g = await tr.post(f"/assignment-submissions/{r.json()['id']}/grade", {"score": 8})
    assert g.status_code == 200 and g.json()["score"] == 8.0 and g.json()["late_penalty_pct"] is None


async def test_adm47_submission_file_download_staff_and_owner_only(browser, db) -> None:
    tr, batch, s = await _trainer_batch_student(db, browser)
    r = await tr.post(
        "/assignments",
        {
            "batch_id": str(batch),
            "title": "F",
            "instructions_md": "x",
            "submission_type": "file",
            "max_score": 10,
            "allowed_file_types": ["pdf"],
            "due_at": (utcnow() + timedelta(days=2)).isoformat(),
        },
    )
    assert r.status_code == 201, r.text
    key = f"uploads/assignment_submission/{s.id}/{uuid7()}/answer.pdf"
    r = await browser.post(
        f"/me/assignments/{r.json()['id']}/submissions", {"file_s3_keys": [key]}, headers=idem()
    )
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    d = await tr.get(f"/assignment-submissions/{sid}/files/0")
    assert d.status_code == 200, d.text
    assert "X-Amz-Signature" in d.json()["url"] and d.json()["filename"] == "answer.pdf"
    assert (await browser.get(f"/assignment-submissions/{sid}/files/0")).status_code == 200
    assert (await tr.get(f"/assignment-submissions/{sid}/files/1")).status_code == 404
    other = browser.fork()
    await student(db, other)
    assert (await other.get(f"/assignment-submissions/{sid}/files/0")).status_code == 404
    sub = await db.get(AssignmentSubmission, uuid.UUID(sid))
    assert sub is not None


# --------------------------------------------------------------------------- ADM-41


async def test_adm41_batch_trainer_studio_course_list_is_not_403(browser, db) -> None:
    tr, _batch, _s = await _trainer_batch_student(db, browser)
    r = await tr.get("/studio/courses", params={"limit": 100})
    assert r.status_code == 200, r.text
    assert r.json()["data"] == []


async def test_be19_style_access_decision_unchanged_for_free_preview(browser, db) -> None:
    """Guard for BE-05: a free-preview lesson of a public paid course stays open to any
    signed-in user (the visibility check does not over-block)."""

    class Deny:
        async def check(self, session, principal, rt, rid, *, is_free=False):
            return AccessDecision(False, "no_entitlement")

    access.register_access_checker(Deny())
    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=False, video_preview=True)
    await student(db, browser)
    r = await browser.get(f"/me/courses/{pc.course_id}/lessons/{pc.lessons['video']}")
    assert r.status_code == 200, r.text
    r = await browser.get(f"/me/courses/{pc.course_id}/lessons/{pc.lessons['article']}")
    assert r.status_code == 403


async def test_com12_revoke_certificates_for_courses(browser, db) -> None:
    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=True)
    u = await student(db, browser)
    assert (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).status_code == 201
    await system_context(db, "t")
    for k in ("article", "video"):
        assert await ls.record_completion(db, u.id, pc.keys[k], {"kind": "test"})
    await db.flush()
    actor = AuditActor.system("test")
    assert await ls.revoke_certificates_for_courses(db, actor, u.id, {uuid.uuid4()}) == []
    out = await ls.revoke_certificates_for_courses(db, actor, u.id, {pc.course_id})
    assert len(out) == 1
    assert await ls.revoke_certificates_for_courses(db, actor, u.id, {pc.course_id}) == []
