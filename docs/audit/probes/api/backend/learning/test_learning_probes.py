"""Audit probes: learning / media / catalog (Phase A - evidence only)."""
from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core import access
from app.core.access import AccessDecision
from app.core.db import system_context
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.catalog.models import Course, CourseModule, CourseVersion, Lesson
from tests.catalog.factory import make_published_course, student
from tests.identity.factory import add_member, grant, make_batch, make_org, make_user, staff_login


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


async def test_probe_org_private_free_course_cross_org(browser, db) -> None:
    author = await make_user(db)
    org_a, org_b = await make_org(db, "College A"), await make_org(db, "College B")
    pc = await make_published_course(db, author.id, is_free=True, org_id=org_a, visibility="private")
    outsider = await student(db, browser)
    await add_member(db, org_b, outsider.id)
    r = await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})
    print("ENROL outsider", r.status_code, r.text[:160])
    r = await browser.get(f"/me/courses/{pc.course_id}/lessons/{pc.lessons['article']}")
    print("LESSON outsider", r.status_code, r.text[:220])
    r2 = await browser.post("/media/playback-tokens", {"lesson_asset_id": str(pc.assets["video"])})
    print("PLAYBACK outsider", r2.status_code, r2.text[:160])
    assert r.status_code == 404, "org-private course lesson readable by another college's student"


async def test_probe_private_visibility_platform_free_course(browser, db) -> None:
    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=True, visibility="private")
    await student(db, browser)
    r = await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})
    print("ENROL private", r.status_code, r.text[:120])
    r = await browser.get(f"/me/courses/{pc.course_id}/lessons/{pc.lessons['article']}")
    print("LESSON private", r.status_code, r.text[:200])
    assert r.status_code == 404


async def test_probe_free_preview_of_org_private_paid_course(browser, db) -> None:
    author = await make_user(db)
    org_a, org_b = await make_org(db, "College A"), await make_org(db, "College B")
    pc = await make_published_course(
        db, author.id, is_free=False, org_id=org_a, visibility="private", video_preview=True
    )
    outsider = await student(db, browser)
    await add_member(db, org_b, outsider.id)
    r = await browser.get(f"/me/courses/{pc.course_id}/lessons/{pc.lessons['video']}")
    print("PREVIEW LESSON outsider", r.status_code, r.text[:160])
    r2 = await browser.post("/media/playback-tokens", {"lesson_asset_id": str(pc.assets["video"])})
    print("PREVIEW PLAYBACK outsider", r2.status_code, r2.text[:160])
    assert r.status_code == 404 and r2.status_code == 404


async def test_probe_minor_version_publish_does_not_recompute(browser, db) -> None:
    from app.modules.learning import service as ls

    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=True, certificate_rule={"required_lessons_pct": 100})
    u = await student(db, browser)
    assert (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).status_code == 201
    await system_context(db, "t")
    for k in ("article", "video"):
        assert await ls.record_completion(db, u.id, pc.keys[k], {"kind": "test"})
    await db.flush()
    v2 = uuid7()
    db.add(CourseVersion(id=v2, course_id=pc.course_id, version_no=2, title="DS v2", status="published",
                         published_at=utcnow(), published_by=author.id, created_by=author.id,
                         change_type="minor", certificate_rule={"required_lessons_pct": 100}))
    await db.flush()
    mid = uuid7()
    db.add(CourseModule(id=mid, course_version_id=v2, module_key=uuid7(), title="B", position=0))
    await db.flush()
    old = (await db.execute(select(Lesson).where(Lesson.course_version_id == pc.version_id))).scalars().all()
    for i, le in enumerate(old):
        db.add(Lesson(id=uuid7(), course_module_id=mid, course_version_id=v2, lesson_key=le.lesson_key,
                      title=le.title, position=i, lesson_type=le.lesson_type,
                      duration_seconds=le.duration_seconds, est_reading_minutes=le.est_reading_minutes))
    db.add(Lesson(id=uuid7(), course_module_id=mid, course_version_id=v2, lesson_key=uuid7(), title="New",
                  position=9, lesson_type="article", est_reading_minutes=1, article_body={"d": 1}))
    await db.flush()
    await db.execute(update(Course).where(Course.id == pc.course_id).values(current_version_id=v2))
    course = await db.get(Course, pc.course_id)
    version = await db.get(CourseVersion, v2)
    await ls.on_course_published(db, course, version)
    await db.flush()
    db.expire_all()
    ov = (await browser.get(f"/me/courses/{pc.course_id}")).json()
    print("AFTER MINOR on_v2:", ov["enrolment"]["course_version_id"] == str(v2), ov["enrolment"]["status"],
          ov["enrolment"]["progress_pct"], [le["status"] for m in ov["modules"] for le in m["lessons"]])
    assert ov["enrolment"]["status"] == "active" or ov["enrolment"]["progress_pct"] < 100


async def _trainer_batch_student(db, browser):
    org = await make_org(db, "College A")
    tr = browser.fork()
    trainer = await make_user(db, with_totp=True)
    await add_member(db, org, trainer.id, "staff")
    batch = await make_batch(db, org, trainer.id)
    await grant(db, trainer.id, "trainer", "batch", batch)
    await staff_login(tr, trainer)
    s = await student(db, browser)
    await add_member(db, org, s.id, "student", batch_id=batch)
    return tr, batch, s


async def test_probe_code_assignment_accepts_foreign_code_submission(browser, db) -> None:
    tr, batch, _s = await _trainer_batch_student(db, browser)
    r = await tr.post("/assignments", {"batch_id": str(batch), "title": "Code", "instructions_md": "x",
                                       "submission_type": "code", "max_score": 10,
                                       "due_at": (utcnow() + timedelta(days=2)).isoformat()})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    r = await browser.post(f"/me/assignments/{aid}/submissions", {"code_submission_id": str(uuid.uuid4())},
                           headers={"Idempotency-Key": str(uuid.uuid4())})
    print("CODE SUBMIT random code_submission_id", r.status_code, r.text[:200])
    assert r.status_code in (404, 422), "unverified code_submission_id accepted"


async def test_probe_late_penalty_not_applied(browser, db) -> None:
    from app.modules.learning.models import Assignment

    tr, batch, _s = await _trainer_batch_student(db, browser)
    r = await tr.post("/assignments", {"batch_id": str(batch), "title": "T", "instructions_md": "x",
                                       "submission_type": "text", "max_score": 10, "late_penalty_pct": 50,
                                       "due_at": (utcnow() + timedelta(days=2)).isoformat(),
                                       "late_until": (utcnow() + timedelta(days=4)).isoformat()})
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    await system_context(db, "t")
    await db.execute(update(Assignment).where(Assignment.id == uuid.UUID(aid))
                     .values(due_at=utcnow() - timedelta(hours=1)))
    await db.flush()
    r = await browser.post(f"/me/assignments/{aid}/submissions", {"body_text": "answer"},
                           headers={"Idempotency-Key": str(uuid.uuid4())})
    print("LATE SUBMIT", r.status_code, r.json().get("status"))
    sid = r.json()["id"]
    g = await tr.post(f"/assignment-submissions/{sid}/grade", {"score": 10})
    rel = await tr.post(f"/assignments/{aid}/release-grades", {})
    mine = await browser.get(f"/assignment-submissions/{sid}")
    print("GRADE late w/ 50% penalty:", g.status_code, g.json().get("score"), "release", rel.status_code,
          "learner view", mine.status_code, mine.json().get("score"))
    assert mine.json().get("score") == 5.0


async def test_probe_errors_and_pagination(browser, db) -> None:
    await student(db, browser)
    r = await browser.get(f"/me/courses/{uuid.uuid4()}/lessons/{uuid.uuid4()}")
    print("LESSON unknown", r.status_code, r.headers.get("content-type"), r.json().get("code"))
    r = await browser.get("/me/courses/not-a-uuid/lessons/x")
    print("LESSON bad uuid", r.status_code, r.headers.get("content-type"), r.json().get("code"))
    r = await browser.get("/courses", params={"limit": 1000})
    print("CATALOG limit=1000", r.status_code, r.json().get("page"))
    r = await browser.get("/courses", params={"cursor": "garbage"})
    print("CATALOG bad cursor", r.status_code, r.json().get("code"))
    r = await browser.get("/me/enrolments", params={"limit": 5})
    print("MY ENROLMENTS page", r.json().get("page"))
    r = await browser.get("/courses/no-such-slug")
    print("CATALOG detail unknown", r.status_code, r.json().get("code"))


async def test_probe_video_heartbeat_after_entitlement_revoked(browser, db) -> None:
    from app.modules.media.models import PlaybackSession

    class Allow:
        allowed = True

        async def check(self, session, principal, rt, rid, *, is_free=False):
            return AccessDecision(self.allowed, "entitlement" if self.allowed else "no_entitlement", (uuid.uuid4(),))

    chk = Allow()
    access.register_access_checker(chk)
    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=False)
    await student(db, browser)
    assert (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).status_code == 201
    r = await browser.post("/media/playback-tokens", {"lesson_asset_id": str(pc.assets["video"])})
    assert r.status_code == 201, r.text
    ps = r.json()["playback_session_id"]
    chk.allowed = False
    await system_context(db, "t")
    await db.execute(update(PlaybackSession).where(PlaybackSession.id == uuid.UUID(ps))
                     .values(last_heartbeat_at=utcnow() - timedelta(seconds=30)))
    await db.flush()
    r = await browser.post(f"/media/playback-sessions/{ps}/heartbeat", {"position_seconds": 60, "playing": True})
    print("HEARTBEAT after revoke", r.status_code, r.text[:120])
    lesson = await browser.get(f"/me/courses/{pc.course_id}/lessons/{pc.lessons['video']}")
    print("LESSON after revoke", lesson.status_code, lesson.json().get("code"))
    ov = (await browser.get(f"/me/courses/{pc.course_id}")).json()
    print("OVERVIEW after revoke", [le.get("progress_pct") for m in ov["modules"] for le in m["lessons"]])


async def test_probe_catalog_public(browser, db) -> None:
    author = await make_user(db)
    priv = await make_published_course(db, author.id, is_free=True, visibility="private")
    anon = browser.fork()
    r = await anon.get("/catalog/courses", params={"limit": 1000})
    print("CATALOG limit=1000", r.status_code, r.json().get("page"))
    r = await anon.get("/catalog/courses", params={"cursor": "garbage"})
    print("CATALOG bad cursor", r.status_code, r.json().get("code"))
    r = await anon.get(f"/catalog/courses/{priv.slug}")
    print("CATALOG private detail", r.status_code)
    r = await anon.get("/catalog/search", params={"q": "Data"})
    print("CATALOG search has private", any(c.get("slug") == priv.slug for c in r.json().get("data", [])))
