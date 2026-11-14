"""Regression tests for wave-2 fixes in catalog (fix agent ``w2b``):

* CAT-13 / FR-CAT-001 lesson types ``pdf`` and ``practice_set`` (webstaff request 8);
* studio lesson output carries ``topics`` (CAT-15 read side);
* ``GET /studio/resources`` lists a course's or lesson's resources (CAT-21/22 read side).
"""

from __future__ import annotations

import uuid

import pytest

from tests.catalog.factory import make_published_course, staff, student

pytestmark = pytest.mark.usefixtures("catalog_backend")


async def _course(browser) -> str:
    r = await browser.post(
        "/studio/courses",
        {
            "title": "W2B course",
            "slug": f"w2b-{uuid.uuid4().hex[:10]}",
            "visibility": "public",
            "is_free": True,
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def test_pdf_and_practice_set_lesson_types(browser, db) -> None:
    await staff(db, browser, "content_manager")
    cid = await _course(browser)
    pdf = await browser.post(f"/studio/courses/{cid}/draft/lessons", {"title": "Notes", "lesson_type": "pdf"})
    assert pdf.status_code == 201, pdf.text
    assert pdf.json()["lesson_type"] == "pdf"
    # An embedded practice set is a practice_set test (assessments), like a quiz needs test_id.
    missing = await browser.post(
        f"/studio/courses/{cid}/draft/lessons", {"title": "Practice", "lesson_type": "practice_set"}
    )
    assert missing.status_code == 422
    assert missing.json()["errors"][0]["field"] == "test_id"
    ps = await browser.post(
        f"/studio/courses/{cid}/draft/lessons",
        {"title": "Practice", "lesson_type": "practice_set", "test_id": str(uuid.uuid4())},
    )
    assert ps.status_code == 201, ps.text
    assert ps.json()["lesson_type"] == "practice_set"
    # Unknown types are still rejected.
    bad = await browser.post(f"/studio/courses/{cid}/draft/lessons", {"title": "X", "lesson_type": "slides"})
    assert bad.status_code in (400, 422)


async def test_studio_lesson_output_includes_topics(browser, db) -> None:
    await staff(db, browser, "content_manager")
    cid = await _course(browser)
    r = await browser.post(
        f"/studio/courses/{cid}/draft/lessons",
        {"title": "Arrays", "lesson_type": "article", "article_body": {"doc": "x"}},
    )
    lid = r.json()["id"]
    assert r.json()["topics"] == []
    t1, t2 = str(uuid.uuid4()), str(uuid.uuid4())
    r = await browser.request(
        "PUT",
        f"/studio/lessons/{lid}/topics",
        json={"topics": [{"topic_id": t1, "is_primary": True}, {"topic_id": t2, "is_primary": False}]},
    )
    assert r.status_code == 200, r.text
    want = sorted([{"topic_id": t1, "is_primary": True}, {"topic_id": t2, "is_primary": False}], key=str)
    detail = (await browser.get(f"/studio/courses/{cid}")).json()
    lesson = next(le for m in detail["draft"]["modules"] for le in m["lessons"] if le["id"] == lid)
    assert sorted(lesson["topics"], key=str) == want
    patched = await browser.patch(f"/studio/lessons/{lid}", {"title": "Arrays 2"})
    assert sorted(patched.json()["topics"], key=str) == want
    prev = (await browser.get(f"/studio/lessons/{lid}/preview")).json()
    assert sorted(prev["lesson"]["topics"], key=str) == want


async def test_studio_resources_list(browser, db) -> None:
    cm = await staff(db, browser, "content_manager")
    pc = await make_published_course(db, cm.id)
    other = await make_published_course(db, cm.id)
    lesson_id = next(iter(pc.lessons.values()))
    made = []
    for title, lid in (("Course sheet", None), ("Lesson sheet", lesson_id)):
        body = {
            "title": title,
            "resource_type": "cheatsheet",
            "course_id": str(pc.course_id),
            "url": "https://example.com/cs.pdf",
        }
        if lid:
            body["lesson_id"] = str(lid)
        r = await browser.post("/studio/resources", body)
        assert r.status_code == 201, r.text
        made.append(r.json()["id"])
    await browser.post(
        "/studio/resources",
        {
            "title": "Other",
            "resource_type": "link",
            "course_id": str(other.course_id),
            "url": "https://e.x/a",
        },
    )
    r = await browser.get("/studio/resources", params={"course_id": str(pc.course_id)})
    assert r.status_code == 200, r.text
    assert sorted(x["id"] for x in r.json()["data"]) == sorted(made)
    assert "next_cursor" in r.json()["page"]
    r = await browser.get("/studio/resources", params={"lesson_id": str(lesson_id)})
    assert [x["id"] for x in r.json()["data"]] == [made[1]]
    # Paginates.
    r = await browser.get("/studio/resources", params={"course_id": str(pc.course_id), "limit": 1})
    assert len(r.json()["data"]) == 1 and r.json()["page"]["next_cursor"]
    r2 = await browser.get(
        "/studio/resources",
        params={"course_id": str(pc.course_id), "limit": 1, "cursor": r.json()["page"]["next_cursor"]},
    )
    assert len(r2.json()["data"]) == 1 and r2.json()["data"][0]["id"] != r.json()["data"][0]["id"]
    # A target is required.
    assert (await browser.get("/studio/resources")).status_code == 422


async def test_studio_resources_list_needs_resource_manage(browser, db) -> None:
    cm = await staff(db, browser.fork(), "content_manager")
    pc = await make_published_course(db, cm.id)
    await student(db, browser)
    r = await browser.get("/studio/resources", params={"course_id": str(pc.course_id)})
    assert r.status_code in (403, 404), r.text
