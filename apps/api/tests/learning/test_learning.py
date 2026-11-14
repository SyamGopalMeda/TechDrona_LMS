"""Enrolment (free self-enrol, paid fail-closed, entitlement checker), lesson delivery,
evidence-based completion, certificates + public verification + revocation, assignments and
grading, batch enrolment, progress, restricted principals, cross-tenant denial."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, text, update

from app.core import access
from app.core.access import AccessDecision
from app.core.db import system_context
from app.core.time import utcnow
from app.modules.learning.models import Certificate, Enrolment, LessonProgress
from tests.catalog.factory import idem, make_published_course, staff, student
from tests.identity.factory import add_member, company_org, make_batch, make_user, step_up


class AllowChecker:
    """Stand-in for the entitlements module's checker."""

    def __init__(self) -> None:
        self.ent = uuid.uuid4()

    async def check(self, session, principal, resource_type, resource_id, *, is_free=False):
        return AccessDecision(True, "entitlement", (self.ent,))


@pytest.fixture
def no_checker():
    prev = access.get_access_checker()
    access.register_access_checker(None)
    yield
    access.register_access_checker(prev)


async def _stale_step_up(db, user_id):
    from app.modules.sessions.models import AuthSession

    await system_context(db, "t")
    await db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id)
        .values(last_step_up_at=utcnow() - timedelta(hours=2))
    )
    await db.flush()


async def _backdate_open(db, enrolment_id, minutes=5):
    await system_context(db, "t")
    await db.execute(
        update(LessonProgress)
        .where(LessonProgress.enrolment_id == enrolment_id)
        .values(first_opened_at=utcnow() - timedelta(minutes=minutes))
    )
    await db.flush()


@pytest.mark.usefixtures("catalog_backend")
async def test_free_enrol_paid_fail_closed_and_entitlement(browser, db, no_checker) -> None:
    author = await make_user(db)
    free = await make_published_course(db, author.id, is_free=True)
    paid = await make_published_course(db, author.id, is_free=False, video_preview=True)
    await student(db, browser)
    r = await browser.post("/me/enrolments", {"course_id": str(free.course_id)})
    assert r.status_code == 201 and r.json()["source"] == "free", r.text
    assert (await browser.post("/me/enrolments", {"course_id": str(free.course_id)})).status_code == 200
    # paid course, no entitlements checker registered -> fail closed
    r = await browser.post("/me/enrolments", {"course_id": str(paid.course_id)})
    assert r.status_code == 403 and r.json()["code"] == "entitlement_required"
    r = await browser.get(f"/me/courses/{paid.course_id}/lessons/{paid.lessons['article']}")
    assert r.status_code == 403 and r.json()["code"] == "entitlement_required"
    # free-preview lesson of a paid course: any signed-in user, no enrolment/progress
    r = await browser.get(f"/me/courses/{paid.course_id}/lessons/{paid.lessons['video']}")
    assert (
        r.status_code == 200
        and r.json()["progress"] is None
        and r.json()["access"]["reason"] == "free_preview"
    )
    # an entitlement checker allows it (source entitlement)
    chk = AllowChecker()
    access.register_access_checker(chk)
    r = await browser.post("/me/enrolments", {"course_id": str(paid.course_id)})
    assert r.status_code == 201 and r.json()["source"] == "entitlement"
    mine = (await browser.get("/me/enrolments")).json()["data"]
    assert {e["course_id"] for e in mine} == {str(free.course_id), str(paid.course_id)}
    # unknown / draft course -> 404
    assert (await browser.post("/me/enrolments", {"course_id": str(uuid.uuid4())})).status_code == 404


@pytest.mark.usefixtures("catalog_backend")
async def test_article_evidence_completion_certificate_verify_and_revoke(
    browser, db, no_checker, audited
) -> None:
    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=True)
    u = await student(db, browser, full_name="Ananya Reddy")
    enr = (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).json()
    # completion requires opening the lesson first (server-observed), then scroll evidence + time
    r = await browser.post(
        f"/me/lessons/{pc.keys['article']}/completion", {"evidence": {"scrolled_to_end": True}}
    )
    assert r.status_code == 409
    r = await browser.get(f"/me/courses/{pc.course_id}/lessons/{pc.lessons['article']}")
    assert r.status_code == 200 and r.json()["article_body"] == {"doc": "Arrays"}
    assert r.json()["progress"]["status"] == "in_progress"
    r = await browser.post(
        f"/me/lessons/{pc.keys['article']}/completion", {"evidence": {"scrolled_to_end": True}}
    )
    assert (
        r.status_code == 409 and "retry_after_seconds" in r.json()
    )  # time alone is not enough, nor too little
    await _backdate_open(db, uuid.UUID(enr["id"]))
    r = await browser.post(f"/me/lessons/{pc.keys['article']}/completion", {"evidence": {}})
    assert r.status_code == 422  # time without the scroll evidence is not enough
    r = await browser.post(
        f"/me/lessons/{pc.keys['article']}/completion", {"evidence": {"scrolled_to_end": True}}
    )
    assert r.status_code == 200 and r.json()["status"] == "completed"
    assert r.json()["enrolment"]["progress_pct"] == 50.0
    # video lessons cannot be completed by assertion
    r = await browser.post(
        f"/me/lessons/{pc.keys['video']}/completion", {"evidence": {"scrolled_to_end": True}}
    )
    assert r.status_code == 409
    # the video completes from watched coverage (other modules / heartbeats use record_completion)
    from app.modules.learning import service as ls

    await system_context(db, "t")
    assert await ls.record_completion(
        db, u.id, pc.keys["video"], {"kind": "video_coverage", "watched_seconds": 560}
    )
    await db.flush()
    ov = (await browser.get(f"/me/courses/{pc.course_id}")).json()
    assert ov["enrolment"]["status"] == "completed" and ov["enrolment"]["progress_pct"] == 100.0
    assert ov["certificate"]["status"] == "issued"
    code = ov["certificate"]["public_code"]
    assert len(code) == 12 and code.isupper()
    # public verification: minimal fields, no session needed
    anon = browser.fork()
    v = await anon.get(f"/certificates/verify/{code}")
    assert v.status_code == 200, v.text
    assert v.json() == {
        "public_code": code,
        "status": "valid",
        "name_on_certificate": "Ananya Reddy",
        "course_title": "Data Structures for Placements",
        "issued_at": v.json()["issued_at"],
        "identity_verified": False,
        "issuer": "Tech Drona",
    }
    assert (await anon.get("/certificates/verify/ZZZZZZZZZZZZ")).status_code == 404
    assert (await anon.get("/certificates/verify/not-a-code")).status_code == 404
    certs = (await browser.get("/me/certificates")).json()["data"]
    assert certs[0]["public_code"] == code
    r = await browser.get(f"/me/certificates/{certs[0]['id']}/pdf")
    assert r.status_code == 404  # PDF rendering is Planned
    # revoke: platform certificate.revoke + step-up S10; verify shows the date only
    cm = browser.fork()
    cmu = await staff(db, cm, "content_manager")
    await _stale_step_up(db, cmu.id)
    r = await cm.post(f"/certificates/{certs[0]['id']}/revoke", {"reason": "Integrity violation confirmed"})
    assert r.status_code == 401 and r.json()["code"] == "step_up_required"
    await step_up(cm, cmu)
    r = await cm.post(f"/certificates/{certs[0]['id']}/revoke", {"reason": "Integrity violation confirmed"})
    assert r.status_code == 200 and r.json()["status"] == "revoked"
    v = (await anon.get(f"/certificates/verify/{code}")).json()
    assert v["status"] == "revoked" and "revoked_on" in v and "reason" not in str(v).lower()
    assert "certificate.revoke" in audited
    # the student cannot revoke or issue
    assert (
        await browser.post(f"/certificates/{certs[0]['id']}/revoke", {"reason": "whatever"})
    ).status_code == 403
    await system_context(db, "t")
    events = set((await db.execute(text("SELECT event_type FROM outbox_events"))).scalars())
    assert {
        "learning.enrolled",
        "learning.lesson_completed",
        "learning.course_completed",
        "learning.certificate_issued",
        "learning.certificate_revoked",
    } <= events


@pytest.mark.usefixtures("catalog_backend")
async def test_manual_certificate_requires_platform_permission(browser, db, no_checker, audited) -> None:
    author = await make_user(db)
    pc = await make_published_course(db, author.id)
    s = await student(db, browser)
    enr = (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).json()
    r = await browser.post(
        "/certificates", {"enrolment_id": enr["id"], "reason": "special case"}, headers=idem()
    )
    assert r.status_code == 403
    cm = browser.fork()
    await staff(db, cm, "content_manager")
    r = await cm.post("/certificates", {"enrolment_id": enr["id"], "reason": "Offline exam passed"})
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"
    r = await cm.post(
        "/certificates", {"enrolment_id": enr["id"], "reason": "Offline exam passed"}, headers=idem()
    )
    assert r.status_code == 201, r.text
    assert "certificate.issue_manual" in audited
    await system_context(db, "t")
    c = (await db.execute(select(Certificate).where(Certificate.user_id == s.id))).scalar_one()
    assert c.issue_source == "manual" and len(c.content_hash) == 32


@pytest.mark.usefixtures("catalog_backend")
async def test_assignments_submission_grading_release_override(
    browser, db, no_checker, mail, audited
) -> None:
    org = company_org()
    tr = browser.fork()
    trainer = await make_user(db, with_totp=True)
    await add_member(db, org, trainer.id, "staff")
    batch = await make_batch(db, org, trainer.id)
    from tests.identity.factory import grant, staff_login

    await grant(db, trainer.id, "trainer", "batch", batch)
    await staff_login(tr, trainer)
    s = await student(db, browser)
    await add_member(db, org, s.id, "student", batch_id=batch)
    due = (utcnow() + timedelta(days=3)).isoformat()
    r = await tr.post(
        "/assignments",
        {
            "batch_id": str(batch),
            "title": "Linked lists",
            "instructions_md": "Reverse a list",
            "submission_type": "file",
            "max_score": 10,
            "due_at": due,
            "allowed_file_types": ["pdf"],
        },
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    # student sees it; outsider (a student of ANOTHER company batch) gets 404
    assert [a["id"] for a in (await browser.get("/me/assignments")).json()["data"]] == [aid]
    other_batch = await make_batch(db, org, trainer.id)
    outsider = browser.fork()
    o = await student(db, outsider)
    await add_member(db, org, o.id, "student", batch_id=other_batch)
    assert (await outsider.get(f"/me/assignments/{aid}")).status_code == 404
    # trainer of the other batch cannot grade / edit (403 cross-batch: same company org)
    tb = browser.fork()
    tbu = await make_user(db, with_totp=True)
    await add_member(db, org, tbu.id, "staff")
    await grant(db, tbu.id, "trainer", "batch", other_batch)
    await staff_login(tb, tbu)
    assert (await tb.get(f"/assignments/{aid}/submissions")).status_code == 403
    assert (await tb.patch(f"/assignments/{aid}", {"title": "x"})).status_code == 403
    # student cannot create assignments
    r = await browser.post(
        "/assignments",
        {
            "batch_id": str(batch),
            "title": "x",
            "instructions_md": "x",
            "submission_type": "text",
            "max_score": 5,
        },
    )
    assert r.status_code == 403
    # upload credentials for the file (own prefix) then submit (Idempotency-Key required)
    up = await browser.post(
        "/media/uploads/file",
        {
            "purpose": "assignment_submission",
            "filename": "answer.pdf",
            "content_type": "application/pdf",
            "size_bytes": 2048,
        },
    )
    assert up.status_code == 201, up.text
    key = up.json()["s3_key"]
    assert key.startswith(f"uploads/assignment_submission/{s.id}/")
    body = {"file_s3_keys": [key]}
    r = await browser.post(f"/me/assignments/{aid}/submissions", body)
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"
    r = await browser.post(
        f"/me/assignments/{aid}/submissions",
        {"file_s3_keys": [f"uploads/assignment_submission/{o.id}/x/a.pdf"]},
        headers=idem(),
    )
    assert r.status_code == 422
    k = idem()
    r = await browser.post(f"/me/assignments/{aid}/submissions", body, headers=k)
    assert r.status_code == 201 and r.json()["status"] == "submitted", r.text
    sub_id = r.json()["id"]
    again = await browser.post(f"/me/assignments/{aid}/submissions", body, headers=k)
    assert again.status_code == 201 and again.headers.get("Idempotency-Replayed") == "true"
    r = await browser.post(f"/me/assignments/{aid}/submissions", body, headers=idem())
    assert r.status_code == 409 and r.json()["code"] == "attempt_limit_reached"
    # grading; students see the score only after release
    queue = (await tr.get(f"/assignments/{aid}/submissions")).json()["data"]
    assert [q["id"] for q in queue] == [sub_id]
    r = await tr.post(f"/assignment-submissions/{sub_id}/grade", {"score": 11})
    assert r.status_code == 422
    r = await tr.post(f"/assignment-submissions/{sub_id}/grade", {"score": 8, "feedback_md": "Good"})
    assert r.status_code == 200 and r.json()["status"] == "graded"
    mine = (await browser.get(f"/me/assignments/{aid}")).json()
    assert "score" not in mine["submissions"][0]
    assert (await tr.post(f"/assignments/{aid}/release-grades")).status_code == 200
    mine = (await browser.get(f"/me/assignments/{aid}")).json()
    assert mine["submissions"][0]["score"] == 8.0
    # after release: grade -> 409; override needs permission + step-up + reason, audited
    r = await tr.post(f"/assignment-submissions/{sub_id}/grade", {"score": 9})
    assert r.status_code == 409
    await _stale_step_up(db, trainer.id)
    r = await tr.post(
        f"/assignment-submissions/{sub_id}/grade-override", {"score": 9, "reason": "Re-checked rubric"}
    )
    assert r.status_code == 401 and r.json()["code"] == "step_up_required"
    await step_up(tr, trainer)
    r = await tr.post(f"/assignment-submissions/{sub_id}/grade-override", {"score": 9})
    assert r.status_code == 400  # reason required
    r = await tr.post(
        f"/assignment-submissions/{sub_id}/grade-override", {"score": 9, "reason": "Re-checked rubric"}
    )
    assert r.status_code == 200 and r.json()["score"] == 9.0
    assert "grade.override_released" in audited


@pytest.mark.usefixtures("catalog_backend")
async def test_batch_enrolment_progress_and_cross_batch(browser, db, no_checker, audited) -> None:
    """Single company: Admin enrols a batch and reads company-wide progress (no
    ``organization_id`` parameter any more); a trainer reads only their own batch."""
    org = company_org()
    author = await make_user(db)
    pc = await make_published_course(db, author.id)
    ad = browser.fork()
    admin = await staff(db, ad, "super_admin", "platform")
    batch = await make_batch(db, org, admin.id)
    other_batch = await make_batch(db, org, admin.id)
    studs = []
    for _ in range(2):
        u = await make_user(db)
        await add_member(db, org, u.id, "student", batch_id=batch)
        studs.append(u)
    gone = await make_user(db)
    await add_member(db, org, gone.id, "student", batch_id=batch)
    async with system_context(db, "test.factory"):
        await db.execute(
            text("UPDATE batch_members SET status='removed', removed_at=now() WHERE user_id=:u"),
            {"u": gone.id},
        )
    r = await ad.post("/enrolments", {"batch_id": str(batch), "course_id": str(pc.course_id)})
    assert r.status_code == 200 and r.json()["created"] == 2, r.text  # removed member skipped
    r = await ad.post("/enrolments", {"batch_id": str(batch), "course_id": str(pc.course_id)})
    assert r.json()["created"] == 0 and r.json()["already_enrolled"] == 2
    prog = await ad.get("/progress")
    assert prog.status_code == 200 and len(prog.json()["data"]) == 2, prog.text
    assert {"enrolment.batch_assign", "progress.read"} <= set(audited)
    # trainer of this batch reads it; trainer of another batch is refused
    tb = browser.fork()
    tr = await staff(db, tb, "trainer", "batch", batch)
    await add_member(db, org, tr.id, "staff", batch_id=batch)
    listed = (await tb.get("/enrolments", params={"batch_id": str(batch)})).json()["data"]
    assert {e["user_id"] for e in listed} == {str(u.id) for u in studs}
    assert all(e["source"] == "batch_sync" for e in listed)
    assert (await tb.get("/progress")).status_code == 403  # company-wide needs platform
    ob = browser.fork()
    other = await staff(db, ob, "trainer", "batch", other_batch)
    await add_member(db, org, other.id, "staff", batch_id=other_batch)
    assert (await ob.get("/enrolments", params={"batch_id": str(batch)})).status_code == 403
    assert (await ob.get("/progress", params={"batch_id": str(batch)})).status_code == 403
    r = await ob.post("/enrolments", {"batch_id": str(batch), "course_id": str(pc.course_id)})
    assert r.status_code == 403
    # a student cannot list enrolments
    s = await student(db, browser)
    await add_member(db, org, s.id)
    assert (await browser.get("/enrolments")).status_code == 403
    # RLS: the student sees only own enrolments even with a raw query
    from app.core.db import tenant_context
    from app.core.ids import uuid7
    from app.core.principal import Principal

    await tenant_context(db, Principal(user_id=s.id, session_id=uuid7()))
    assert (await db.execute(select(Enrolment))).scalars().all() == []


@pytest.mark.usefixtures("catalog_backend")
async def test_restricted_l3_keeps_read_only_learning(browser, db, no_checker) -> None:
    from app.modules.sessions import hooks
    from app.modules.sessions.hooks import RestrictionState

    author = await make_user(db)
    pc = await make_published_course(db, author.id)
    await student(db, browser)
    assert (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).status_code == 201

    async def lookup(session, user_id):
        return RestrictionState(level=3, case_ref="SEC-2611-AAAAAA")

    hooks.register_restriction_lookup(lookup)
    try:
        assert (await browser.get("/me/enrolments")).status_code == 200  # l3_readonly
        assert (await browser.get(f"/me/courses/{pc.course_id}")).status_code == 200
        assert (await browser.get("/me/certificates")).status_code == 200
        r = await browser.get(f"/me/courses/{pc.course_id}/lessons/{pc.lessons['article']}")
        assert r.status_code == 403 and r.json()["code"] == "account_restricted"
        r = await browser.post(
            f"/me/lessons/{pc.keys['article']}/completion", {"evidence": {"scrolled_to_end": True}}
        )
        assert r.status_code == 403
    finally:
        hooks.register_restriction_lookup(None)


@pytest.mark.usefixtures("catalog_backend")
async def test_minor_version_publish_migrates_enrolments(browser, db, no_checker) -> None:
    cm1 = browser.fork()
    await staff(db, cm1, "content_manager")
    cm2 = browser.fork()
    await staff(db, cm2, "content_manager")
    r = await cm1.post(
        "/studio/courses",
        {"title": "Aptitude Basics", "slug": "apt-basics", "visibility": "public", "is_free": True},
    )
    cid = r.json()["id"]
    a = await cm1.post(f"/studio/courses/{cid}/draft/lessons", {"title": "Ratios", "lesson_type": "article"})
    await cm1.post(f"/studio/courses/{cid}/submit-review")
    assert (
        await cm2.post(f"/studio/courses/{cid}/publish", {"change_type": "major"}, headers=idem())
    ).status_code == 200
    await student(db, browser)
    enr = (await browser.post("/me/enrolments", {"course_id": cid})).json()
    v1 = enr["course_version_id"]
    # minor fix: typo in the title -> auto-migrates enrolments, lesson_key kept
    await cm1.patch(f"/studio/courses/{cid}/draft", {"summary": "typo fixed"})
    await cm1.post(f"/studio/courses/{cid}/submit-review")
    r = await cm2.post(f"/studio/courses/{cid}/publish", {"change_type": "minor"}, headers=idem())
    assert r.status_code == 200
    mine = (await browser.get("/me/enrolments")).json()["data"][0]
    assert mine["course_version_id"] != v1 and mine["course_version_id"] == r.json()["version"]["id"]
    ov = (await browser.get(f"/me/courses/{cid}")).json()
    assert ov["modules"][0]["lessons"][0]["lesson_key"] == a.json()["lesson_key"]
    assert ov["version_migration"] is None
