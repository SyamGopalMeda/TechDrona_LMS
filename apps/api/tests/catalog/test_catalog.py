"""Catalog authoring (draft -> review -> published versions, SoD-04), outline with stable
lesson keys, public catalogue/search, permission denials, cross-tenant 404 and RLS."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.db import system_context, tenant_context
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.modules.catalog import service as cat
from app.modules.catalog.models import CourseVersion
from tests.catalog.factory import idem, make_published_course, staff, student
from tests.identity.factory import add_member, company_org, make_batch, make_user

# Every test runs on Postgres and on Firestore (TD_STORE_CATALOG); see tests/catalog/conftest.py.
pytestmark = pytest.mark.usefixtures("catalog_backend")


async def _create(b, slug="dsa-placements", **kw):
    body = {"title": "DSA for Placements", "slug": slug, "visibility": "public", "is_free": True, **kw}
    r = await b.post("/studio/courses", body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_authoring_publish_flow_sod_and_public_catalog(browser, db, audited) -> None:
    author = await staff(db, browser, "content_manager")
    course = await _create(browser)
    cid = course["id"]
    assert course["status"] == "draft" and course["draft"]["version_no"] == 1
    r = await browser.patch(
        f"/studio/courses/{cid}/draft",
        {
            "summary": "Arrays to graphs",
            "tags": ["dsa", "arrays"],
            "level": "beginner",
            "category": "dsa",
            "outcomes": ["Solve array problems"],
        },
    )
    assert r.status_code == 200 and r.json()["tags"] == ["dsa", "arrays"]
    art = await browser.post(
        f"/studio/courses/{cid}/draft/lessons",
        {"title": "Arrays", "lesson_type": "article", "article_body": {"doc": "x"}, "est_reading_minutes": 3},
    )
    assert art.status_code == 201, art.text
    vid = await browser.post(
        f"/studio/courses/{cid}/draft/lessons", {"title": "Intro video", "lesson_type": "video"}
    )
    assert vid.status_code == 201
    quiz = await browser.post(
        f"/studio/courses/{cid}/draft/lessons", {"title": "Quiz", "lesson_type": "quiz"}
    )
    assert quiz.status_code == 400 or quiz.status_code == 422
    # outline: two modules, video first
    r = await browser.request(
        "PUT",
        f"/studio/courses/{cid}/draft/outline",
        json={
            "modules": [
                {"title": "Start here", "lesson_ids": [vid.json()["id"]]},
                {"title": "Arrays", "lesson_ids": [art.json()["id"]]},
            ]
        },
    )
    assert r.status_code == 200, r.text
    mods = r.json()["modules"]
    assert [m["title"] for m in mods] == ["Start here", "Arrays"]
    assert mods[0]["lessons"][0]["lesson_key"] == vid.json()["lesson_key"]
    # media still processing blocks publishing; video upload via the fake provider
    up = await browser.post("/media/uploads/video", {"lesson_id": vid.json()["id"], "title": "Intro"})
    assert up.status_code == 201, up.text
    asset_id = up.json()["lesson_asset_id"]
    assert (await browser.post(f"/studio/courses/{cid}/submit-review")).status_code == 200
    r = await browser.post(f"/studio/courses/{cid}/publish", {"change_type": "major"}, headers=idem())
    assert r.status_code == 403 and r.json()["code"] == "sod_violation"
    publisher = browser.fork()
    await staff(db, publisher, "content_manager")
    r = await publisher.post(f"/studio/courses/{cid}/publish", {"change_type": "major"})
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"
    r = await publisher.post(f"/studio/courses/{cid}/publish", {"change_type": "major"}, headers=idem())
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "media_processing"
    st = await browser.get(f"/media/assets/{asset_id}/status")
    assert st.status_code == 200 and st.json()["status"] == "ready" and st.json()["duration_seconds"] == 600
    key = idem()
    r = await publisher.post(f"/studio/courses/{cid}/publish", {"change_type": "major"}, headers=key)
    assert r.status_code == 200, r.text
    assert r.json()["course"]["status"] == "published" and r.json()["version"]["status"] == "published"
    replay = await publisher.post(f"/studio/courses/{cid}/publish", {"change_type": "major"}, headers=key)
    assert replay.status_code == 200 and replay.headers.get("Idempotency-Replayed") == "true"
    # public catalogue / detail / search (no session at all)
    anon = browser.fork()
    listed = await anon.get("/catalog/courses", params={"price_type": "free", "category": "dsa"})
    assert listed.status_code == 200 and listed.headers["Cache-Control"].startswith("public")
    assert cid in [c["id"] for c in listed.json()["data"]]
    d = await anon.get("/catalog/courses/dsa-placements")
    assert d.status_code == 200 and [m["title"] for m in d.json()["syllabus"]] == ["Start here", "Arrays"]
    assert "article_body" not in d.json()["syllabus"][1]["lessons"][0]
    assert cid in [
        c["id"] for c in (await anon.get("/catalog/search", params={"q": "arrays"})).json()["data"]
    ]
    # a draft-only course never appears publicly
    await _create(browser, slug="secret-draft", title="Secret Draft Course")
    assert (await anon.get("/catalog/courses/secret-draft")).status_code == 404
    assert (await anon.get("/catalog/search", params={"q": "Secret"})).json()["data"] == []
    # editing a published course creates draft v2 that keeps lesson keys; published lessons immutable
    r = await browser.patch(f"/studio/courses/{cid}/draft", {"title": "DSA for Placements 2027"})
    assert r.status_code == 200 and r.json()["version_no"] == 2
    keys_v2 = {le["lesson_key"] for m in r.json()["modules"] for le in m["lessons"]}
    assert keys_v2 == {vid.json()["lesson_key"], art.json()["lesson_key"]}
    r = await browser.patch(f"/studio/lessons/{art.json()['id']}", {"title": "changed"})
    assert r.status_code == 409 and r.json()["code"] == "invalid_state_transition"
    versions = (await browser.get(f"/studio/courses/{cid}/versions")).json()["data"]
    assert [(v["version_no"], v["status"]) for v in versions] == [(2, "draft"), (1, "published")]
    assert (await anon.get("/catalog/courses/dsa-placements")).json()["title"] == "DSA for Placements"
    # preview of a draft lesson
    draft_lesson = r = (await browser.get(f"/studio/courses/{cid}")).json()["draft"]["modules"][1]["lessons"][
        0
    ]
    pv = await browser.get(f"/studio/lessons/{draft_lesson['id']}/preview")
    assert pv.status_code == 200 and pv.json()["banner"].startswith("Preview")
    # archive (audited)
    r = await publisher.post(f"/studio/courses/{cid}/archive")
    assert r.status_code == 200 and r.json()["status"] == "archived"
    assert {"course.create", "course.submit_review", "course.publish", "course.archive"} <= set(audited)
    await system_context(db, "t")
    events = (await db.execute(text("SELECT event_type FROM outbox_events"))).scalars().all()
    assert "course.published" in events and author


async def test_permission_denials_and_company_courses(browser, db) -> None:
    """Single company: no org picker. A batch trainer authors company courses (internal
    organization = the company); ``organization_id`` / ``org_only`` are rejected."""
    org = company_org()
    creator = await make_user(db)
    batch = await make_batch(db, org, creator.id)
    # student: no authoring
    s = await student(db, browser)
    await add_member(db, org, s.id)
    r = await browser.post("/studio/courses", {"title": "Nope course", "slug": "nope-course"})
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"
    assert (await browser.get("/studio/courses")).status_code == 403
    # batch trainer authors a company course
    ta = browser.fork()
    trainer = await staff(db, ta, "trainer", "batch", batch)
    await add_member(db, org, trainer.id, "staff", batch_id=batch)
    c = await _create(ta, slug="company-course", visibility="private", is_free=False)
    assert c["organization_id"] == str(org)
    assert [x["id"] for x in (await ta.get("/studio/courses")).json()["data"]] == [c["id"]]
    # the org picker and org_only are gone
    r = await ta.post(
        "/studio/courses", {"title": "B course", "slug": "b-course", "organization_id": str(org)}
    )
    assert r.status_code == 400
    r = await ta.post("/studio/courses", {"title": "O course", "slug": "o-course", "visibility": "org_only"})
    assert r.status_code == 400
    # trainer may not publish (course.publish is content manager @P)
    r = await ta.post(f"/studio/courses/{c['id']}/draft/lessons", {"title": "A1", "lesson_type": "article"})
    assert r.status_code == 201, r.text
    # the author previews the lesson (course.edit covers preview; QA 2026-11)
    pv = await ta.get(f"/studio/lessons/{r.json()['id']}/preview")
    assert pv.status_code == 200 and pv.json()["banner"].startswith("Preview"), pv.text
    r = await ta.post(f"/studio/courses/{c['id']}/submit-review")
    assert r.status_code == 200, r.text
    r = await ta.post(f"/studio/courses/{c['id']}/publish", {"change_type": "major"}, headers=idem())
    assert r.status_code == 403
    cm = browser.fork()
    await staff(db, cm, "content_manager", "platform")
    r = await cm.post(f"/studio/courses/{c['id']}/publish", {"change_type": "major"}, headers=idem())
    assert r.status_code == 200, r.text
    # company courses never appear in the public catalogue
    assert (await browser.fork().get("/catalog/courses/company-course")).status_code == 404
    # RLS (TN): a public learner (no company membership) cannot read the row; the trainer can
    # (through the catalog loader, so the same check runs against the Firestore store)
    outsider = await make_user(db)
    await tenant_context(db, Principal(user_id=outsider.id, session_id=uuid7()))
    with pytest.raises(ProblemError):
        await cat.get_course(db, uuid.UUID(c["id"]))
    await tenant_context(db, Principal(user_id=trainer.id, session_id=uuid7(), org_ids=(org,)))
    assert (await cat.get_course(db, uuid.UUID(c["id"]))).organization_id == org
    # validation: bad slug and unknown field
    r = await ta.post("/studio/courses", {"title": "x" * 5, "slug": "Bad Slug"})
    assert r.status_code == 400 and r.json()["code"] == "validation_failed"
    r = await ta.post("/studio/courses", {"title": "xxxxx", "slug": "ok-slug", "price": 1})
    assert r.status_code == 400


async def test_restricted_principal_cannot_author(browser, db) -> None:
    from app.modules.sessions import hooks
    from app.modules.sessions.hooks import RestrictionState

    await staff(db, browser, "content_manager")
    hooks.register_restriction_lookup(lambda s, u: _restricted())
    try:
        r = await browser.post("/studio/courses", {"title": "Blocked", "slug": "blocked-course"})
        assert r.status_code == 403 and r.json()["code"] == "account_restricted"
    finally:
        hooks.register_restriction_lookup(None)
    assert RestrictionState


async def _restricted():
    from app.modules.sessions.hooks import RestrictionState

    return RestrictionState(level=3, case_ref="SEC-2611-AAAAAA")


async def test_resources_and_free_resources(browser, db) -> None:
    cm = await staff(db, browser, "content_manager")
    pc = await make_published_course(db, cm.id)
    r = await browser.post(
        "/studio/resources",
        {
            "title": "Cheat sheet",
            "resource_type": "cheatsheet",
            "access_level": "public",
            "course_id": str(pc.course_id),
            "url": "https://example.com/cs.pdf",
        },
    )
    assert r.status_code == 201, r.text
    bad = await browser.post(
        "/studio/resources",
        {
            "title": "x",
            "resource_type": "file",
            "course_id": str(pc.course_id),
            "s3_key": "uploads/assignment_submission/someone/x.pdf",
        },
    )
    assert bad.status_code == 422
    free = (await browser.fork().get("/catalog/free-resources")).json()["data"]
    assert r.json()["id"] in [x["id"] for x in free["resources"]]
    assert str(pc.course_id) in [x["id"] for x in free["free_courses"]]
    r2 = await browser.patch(f"/studio/resources/{r.json()['id']}", {"access_level": "entitled"})
    assert r2.status_code == 200 and r2.json()["access_level"] == "entitled"
    await system_context(db, "t")
    v = await db.get(CourseVersion, pc.version_id)
    assert v is not None and v.status == "published"
