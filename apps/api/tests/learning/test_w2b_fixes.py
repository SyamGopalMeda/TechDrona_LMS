"""Regression tests for wave-2 fixes in learning (fix agent ``w2b``):

* ``assignments.rubric`` has a defined schema and LRN-17 ``rubric_scores`` are validated
  against it (webstaff request 13, FR-LRN-005);
* ``pdf`` lessons complete on the LRN-06 scrolled-to-end evidence like articles (FR-CAT-001).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import update

from app.core.db import system_context
from app.core.time import utcnow
from app.modules.learning.models import LessonProgress
from tests.catalog.factory import idem, make_published_course, student
from tests.identity.factory import add_member, company_org, grant, make_batch, make_user, staff_login
from tests.learning.test_learning import no_checker  # noqa: F401

RUBRIC = {
    "criteria": [
        {"key": "correctness", "label": "Correctness", "max_points": 6},
        {
            "key": "style",
            "label": "Code style",
            "max_points": 4,
            "levels": [{"label": "Poor", "points": 1}, {"label": "Good", "points": 4}],
        },
    ]
}


async def _trainer_and_student(browser, db):
    org = company_org()
    tr = browser.fork()
    trainer = await make_user(db, with_totp=True)
    await add_member(db, org, trainer.id, "staff")
    batch = await make_batch(db, org, trainer.id)
    await grant(db, trainer.id, "trainer", "batch", batch)
    await staff_login(tr, trainer)
    s = await student(db, browser)
    await add_member(db, org, s.id, "student", batch_id=batch)
    return tr, batch


def _asg(batch, **kw):
    return {
        "batch_id": str(batch),
        "title": "Rubric task",
        "instructions_md": "Write it",
        "submission_type": "text",
        "max_score": 10,
        **kw,
    }


@pytest.mark.usefixtures("catalog_backend")
async def test_rubric_schema_on_create_and_patch(browser, db, no_checker) -> None:  # noqa: F811
    tr, batch = await _trainer_and_student(browser, db)
    r = await tr.post("/assignments", _asg(batch, rubric=RUBRIC))
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    assert [c["key"] for c in r.json()["rubric"]["criteria"]] == ["correctness", "style"]
    bad_cases = [
        ({"criteria": []}, "rubric.criteria"),
        ({"rows": [1]}, "rubric"),
        ({"criteria": [{"key": "a", "label": "A", "max_points": 11}]}, "rubric"),
        (
            {
                "criteria": [
                    {"key": "a", "label": "A", "max_points": 2},
                    {"key": "a", "label": "B", "max_points": 2},
                ]
            },
            "rubric.criteria.1.key",
        ),
        (
            {
                "criteria": [
                    {"key": "a", "label": "A", "max_points": 2, "levels": [{"label": "x", "points": 3}]}
                ]
            },
            "rubric.criteria.0.levels.0.points",
        ),
    ]
    for rubric, field in bad_cases:
        r = await tr.post("/assignments", _asg(batch, rubric=rubric))
        assert r.status_code in (400, 422), (rubric, r.text)
        fields = [e["field"] for e in r.json().get("errors", [])]
        assert any(f.startswith(field) for f in fields), (rubric, fields)
    r = await tr.patch(
        f"/assignments/{aid}", {"rubric": {"criteria": [{"key": "a", "label": "A", "max_points": 20}]}}
    )
    assert r.status_code == 422
    r = await tr.patch(
        f"/assignments/{aid}", {"rubric": {"criteria": [{"key": "a", "label": "A", "max_points": 5}]}}
    )
    assert r.status_code == 200 and r.json()["rubric"]["criteria"][0]["max_points"] == 5


@pytest.mark.usefixtures("catalog_backend")
async def test_rubric_scores_validated_and_totalled(browser, db, no_checker) -> None:  # noqa: F811
    tr, batch = await _trainer_and_student(browser, db)
    aid = (await tr.post("/assignments", _asg(batch, rubric=RUBRIC))).json()["id"]
    r = await browser.post(
        f"/me/assignments/{aid}/submissions", {"body_text": "My answer text"}, headers=idem()
    )
    assert r.status_code == 201, r.text
    sub = r.json()["id"]
    url = f"/assignment-submissions/{sub}/grade"
    for scores, field in (
        ({"correctness": 5}, "rubric_scores.style"),
        ({"correctness": 5, "style": 3, "extra": 1}, "rubric_scores.extra"),
        ({"correctness": 7, "style": 3}, "rubric_scores.correctness"),
    ):
        r = await tr.post(url, {"rubric_scores": scores})
        assert r.status_code == 422, r.text
        assert r.json()["errors"][0]["field"] == field
    r = await tr.post(url, {"score": 9, "rubric_scores": {"correctness": 5, "style": 3}})
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "rubric_mismatch"
    # The score defaults to the rubric total.
    r = await tr.post(url, {"rubric_scores": {"correctness": 5, "style": 3.5}})
    assert r.status_code == 200, r.text
    assert r.json()["score"] == 8.5 and r.json()["rubric_scores"] == {"correctness": 5, "style": 3.5}


@pytest.mark.usefixtures("catalog_backend")
async def test_pdf_lesson_completes_on_scroll_evidence(browser, db, no_checker) -> None:  # noqa: F811
    author = await make_user(db)
    pc = await make_published_course(db, author.id, extra_lessons=[{"name": "notes", "lesson_type": "pdf"}])
    await student(db, browser)
    enr = (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).json()
    r = await browser.get(f"/me/courses/{pc.course_id}/lessons/{pc.lessons['notes']}")
    assert r.status_code == 200, r.text
    await system_context(db, "t")
    await db.execute(
        update(LessonProgress)
        .where(LessonProgress.enrolment_id == uuid.UUID(enr["id"]))
        .values(first_opened_at=utcnow() - timedelta(minutes=5))
    )
    await db.flush()
    r = await browser.post(
        f"/me/lessons/{pc.keys['notes']}/completion", {"evidence": {"scrolled_to_end": True}}
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "completed"
