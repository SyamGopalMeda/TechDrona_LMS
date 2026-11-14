"""Parity: paid-course learning flow over HTTP on the Firebase stack (no Postgres).

VM expectations from ``tests/learning`` (Postgres): LRN-03 201 then 200 on repeat, LRN-05 200
with ``access.reason`` ``entitlement`` for a paid lesson (``free_preview`` for a preview lesson),
403 ``entitlement_required`` without an entitlement, LRN-06 200 ``completed``, ENT-01 200.
"""

from __future__ import annotations

from typing import Any

from tests.parity.harness import grant_course, publish_paid_course


async def test_paid_course_grant_enrol_open_complete(web: Any, monkeypatch: Any) -> None:
    from datetime import timedelta

    from app.core.time import utcnow
    from app.modules.learning import service as lsvc

    w = web
    course = await publish_paid_course(w)
    student, sh = await w.learner()

    # Without an entitlement: the catalogue shows it, enrolment is refused, ENT-01 says no.
    await w.call("GET", f"/catalog/courses/{course.slug}", {})
    r = await w.call(
        "POST", "/entitlements/check", sh, json={"resource": {"kind": "course", "id": course.id}}
    )
    assert r.json()["allowed"] is False and r.json()["reason_code"] == "NO_ENTITLEMENT"
    await w.call("POST", "/me/enrolments", sh, expect=403, json={"course_id": course.id})

    await grant_course(w, student.user_id, course.id)
    r = await w.call(
        "POST", "/entitlements/check", sh, json={"resource": {"kind": "course", "id": course.id}}
    )
    assert r.json()["allowed"] is True, r.text
    r = await w.call("GET", "/me/entitlements", sh)
    assert len(r.json()["data"]) == 1

    r = await w.call("POST", "/me/enrolments", sh, expect=201, json={"course_id": course.id})
    assert r.json()["status"] == "active"
    await w.call("POST", "/me/enrolments", sh, expect=200, json={"course_id": course.id})
    await w.call("GET", "/me/enrolments", sh)

    lessons = await course.outline(w, sh)
    paid, intro = lessons["Paid"], lessons["Intro"]
    # LRN-05 paid, non-preview lesson (was 500 on Firebase)
    r = await w.call("GET", f"/me/courses/{course.id}/lessons/{paid['id']}", sh)
    assert r.json()["access"]["reason"] == "entitlement", r.text
    assert r.json()["progress"]["status"] in ("in_progress", "not_started")
    r = await w.call("GET", f"/me/courses/{course.id}/lessons/{intro['id']}", sh)
    # LRN-06 completion of the paid lesson (after the minimum reading time)
    monkeypatch.setattr(lsvc, "utcnow", lambda: utcnow() + timedelta(minutes=10))
    r = await w.call(
        "POST",
        f"/me/lessons/{paid['lesson_key']}/completion",
        sh,
        json={"evidence": {"scrolled_to_end": True}},
    )
    assert r.json()["status"] == "completed", r.text
    r = await w.call("GET", f"/me/courses/{course.id}", sh)
    statuses = {le["title"]: le["status"] for m in r.json()["modules"] for le in m["lessons"]}
    assert statuses["Paid"] == "completed"
    await w.call("GET", "/me/dashboard", sh)

    # Another learner without an entitlement: 403 entitlement_required (not 500)
    _, oh = await w.learner("other")
    r = await w.call("GET", f"/me/courses/{course.id}/lessons/{paid['id']}", oh, expect=403)
    assert r.json()["code"] == "entitlement_required"


async def test_assignment_submit_grade_and_certificate(web: Any) -> None:
    """LRN-14/10/17/18 on a paid course (LRN-10 runs the entitlement check), then LRN-20 manual
    certificate, LRN-11/12/13, LRN-30/32/33 admin certificate views. VM: 201/201/200/200/201/200."""
    w = web
    course = await publish_paid_course(w)
    student, sh = await w.learner("submitter")
    _, staff = await w.staff("grader")
    await grant_course(w, student.user_id, course.id)
    enr = (await w.call("POST", "/me/enrolments", sh, expect=201, json={"course_id": course.id})).json()

    r = await w.call(
        "POST",
        "/assignments",
        staff,
        expect=201,
        idem=True,
        json={
            "course_id": course.id,
            "title": "Essay",
            "instructions_md": "Write it.",
            "submission_type": "text",
            "max_score": "10",
        },
    )
    aid = r.json()["id"]
    await w.call("GET", "/me/assignments", sh)
    await w.call("GET", f"/me/assignments/{aid}", sh)
    r = await w.call(
        "POST",
        f"/me/assignments/{aid}/submissions",
        sh,
        expect=201,
        idem=True,
        json={"body_text": "My essay."},
    )
    sub_id = r.json()["id"]
    # someone without an entitlement: 403 (not 500)
    _, oh = await w.learner("nosub")
    await w.call(
        "POST",
        f"/me/assignments/{aid}/submissions",
        oh,
        expect=(403, 404),
        idem=True,
        json={"body_text": "x"},
    )
    await w.call("GET", f"/assignments/{aid}/submissions", staff)
    await w.call(
        "POST",
        f"/assignment-submissions/{sub_id}/grade",
        staff,
        idem=True,
        json={"action": "grade", "score": "8", "feedback_md": "Good"},
    )
    await w.call("POST", f"/assignments/{aid}/release-grades", staff, idem=True)

    r = await w.call(
        "POST",
        "/certificates",
        staff,
        expect=(200, 201),
        idem=True,
        json={"enrolment_id": enr["id"], "reason": "Parity manual issue"},
    )
    await w.relay()  # learning.certificate_issued -> PDF + queued e-mail, as the worker does
    certs = (await w.call("GET", "/me/certificates", sh)).json()["data"]
    assert len(certs) == 1, certs
    cert = certs[0]
    await w.call("GET", f"/me/certificates/{cert['id']}/pdf", sh, expect=200)
    await w.call("GET", f"/certificates/verify/{cert['public_code']}", {})
    await w.call("GET", "/admin/certificates", staff)
    await w.call("GET", "/admin/certificates/due", staff)
    await w.call("POST", "/admin/certificates/due/issue", staff, idem=True, json={})
    await w.call("GET", f"/admin/certificates/{cert['id']}", staff)

    # the certificate jobs (learning/tasks.py) on the Firebase stack: no Postgres session factory
    from app.modules.learning import tasks

    assert isinstance(await tasks._send(), dict)
    assert isinstance(await tasks._batch_end(), dict)
    assert await tasks._backfill(10) >= 0
    await w.relay()
