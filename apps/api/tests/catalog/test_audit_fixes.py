"""Regression tests for audit Phase B fixes in catalog (fix agent ``learn``): ADM-57 (lesson
and outline mutations are audited), BE-34 (catalog ``limit`` validated, not clamped)."""

from __future__ import annotations

from tests.catalog.factory import staff


async def test_adm57_lesson_and_outline_mutations_are_audited(browser, db, audited) -> None:
    await staff(db, browser, "content_manager")
    r = await browser.post(
        "/studio/courses",
        {"title": "Audit course", "slug": "audit-course", "visibility": "public", "is_free": True},
    )
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    art = await browser.post(
        f"/studio/courses/{cid}/draft/lessons",
        {"title": "Arrays", "lesson_type": "article", "article_body": {"doc": "x"}, "est_reading_minutes": 3},
    )
    assert art.status_code == 201, art.text
    lid = art.json()["id"]
    assert (await browser.patch(f"/studio/lessons/{lid}", {"title": "Arrays 101"})).status_code == 200
    r = await browser.request(
        "PUT", f"/studio/courses/{cid}/draft/outline", json={"modules": [{"title": "M", "lesson_ids": [lid]}]}
    )
    assert r.status_code == 200, r.text
    r = await browser.request("PUT", f"/studio/lessons/{lid}/topics", json={"topics": []})
    assert r.status_code == 200, r.text
    for action in (
        "course.lesson.add",
        "course.lesson.edit",
        "course.outline.replace",
        "course.lesson.topics",
    ):
        assert action in audited, (action, audited)


async def test_be34_studio_limit_out_of_range_is_400(browser, db) -> None:
    await staff(db, browser, "content_manager")
    r = await browser.get("/studio/courses", params={"limit": 101})
    assert r.status_code == 400 and r.json()["code"] == "validation_failed"
    assert (await browser.get("/studio/courses", params={"limit": 100})).status_code == 200
