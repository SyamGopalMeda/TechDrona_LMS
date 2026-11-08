"""Résumés and mentor résumé review (PLC-47..52)."""

from __future__ import annotations

import uuid
from typing import Any

from app.core.ids import uuid7
from tests.mentoring.test_mentoring import API, grant_package, mentor
from tests.placement.world import World

CONTENT: dict[str, Any] = {
    "headline": "Final-year CSE student",
    "summary": "Backend-leaning engineer who enjoys databases, APIs and competitive programming.",
    "education": [{"institution": "College A", "degree": "B.Tech", "start_year": 2023, "end_year": "2027"}],
    "skills": ["Python", "SQL", "Java", "Git", "Linux"],
    "projects": [{"title": "LMS", "description": "A learning platform", "tech": ["FastAPI"]}],
    "internships": [],
    "achievements": ["Hackathon finalist"],
    "certifications": [],
}


async def test_resume_crud_and_validation(client, world: World) -> None:
    s = world.personas["student"]
    r = await client.get(f"{API}/me/resumes", headers=s.headers)
    assert r.status_code == 200 and r.json()["data"] == [], r.text
    assert r.json()["quota"]["has_package"] is False and r.json()["suggested_certifications"] == []

    c = await client.post(
        f"{API}/me/resumes", json={"template_key": "ats_modern", "content": CONTENT}, headers=s.headers
    )
    assert c.status_code == 201, c.text
    res = c.json()
    assert res["version_no"] == 1 and res["is_current"] and res["checklist_score"] == 75
    assert {i["key"] for i in res["checklist"] if not i["done"]} == {"internships", "certifications"}

    upd = {**CONTENT, "certifications": [{"title": "AWS CCP", "issuer": "AWS"}]}
    p = await client.put(
        f"{API}/me/resumes/{res['id']}",
        json={"template_key": "ats_classic", "content": upd},
        headers=s.headers,
    )
    assert (
        p.status_code == 200
        and p.json()["checklist_score"] == 88
        and p.json()["template_key"] == "ats_classic"
    )

    new_id = str(uuid7())
    p2 = await client.put(f"{API}/me/resumes/{new_id}", json={"content": CONTENT}, headers=s.headers)
    assert p2.status_code == 201 and p2.json()["version_no"] == 2 and p2.json()["is_current"]
    lst = (await client.get(f"{API}/me/resumes", headers=s.headers)).json()["data"]
    assert [(x["version_no"], x["is_current"]) for x in lst] == [(2, True), (1, False)]

    # someone else's résumé id is not disclosed / not overwritable
    sb = world.personas["student_b"]
    r = await client.put(f"{API}/me/resumes/{res['id']}", json={"content": CONTENT}, headers=sb.headers)
    assert r.status_code == 404
    assert (await client.get(f"{API}/me/resumes/{res['id']}/pdf", headers=sb.headers)).status_code == 404

    for bad in (
        {"template_key": "fancy", "content": CONTENT},
        {"content": {**CONTENT, "skills": [""]}},
        {"content": {**CONTENT, "education": [{"degree": "no institution"}]}},
        {"content": {**CONTENT, "unknown": 1}},
    ):
        r = await client.post(f"{API}/me/resumes", json=bad, headers=s.headers)
        assert r.status_code == 400 and r.json()["code"] == "validation_failed", (bad, r.text)


async def test_resume_pdf_upload_metadata(client, world: World) -> None:
    s = world.personas["student"]
    res = (await client.post(f"{API}/me/resumes", json={"content": CONTENT}, headers=s.headers)).json()
    assert (await client.get(f"{API}/me/resumes/{res['id']}/pdf", headers=s.headers)).status_code == 404
    too_big = await client.post(
        f"{API}/me/resumes/{res['id']}/pdf-upload",
        json={"filename": "cv.pdf", "size_bytes": 6 * 1024 * 1024},
        headers=s.headers,
    )
    assert too_big.status_code == 400
    up = await client.post(
        f"{API}/me/resumes/{res['id']}/pdf-upload",
        json={"filename": "my cv.pdf", "size_bytes": 1000},
        headers=s.headers,
    )
    assert up.status_code == 200, up.text
    body = up.json()
    assert body["fields"]["key"] == body["key"] and body["fields"]["Content-Type"] == "application/pdf"
    assert body["key"].startswith(f"resumes/{s.id}/{res['id']}/")
    wrong = await client.post(
        f"{API}/me/resumes/{res['id']}/pdf-upload/complete", json={"key": "resumes/x.pdf"}, headers=s.headers
    )
    assert wrong.status_code == 400
    done = await client.post(
        f"{API}/me/resumes/{res['id']}/pdf-upload/complete", json={"key": body["key"]}, headers=s.headers
    )
    assert done.status_code == 200 and done.json()["has_pdf"] is True
    dl = await client.get(f"{API}/me/resumes/{res['id']}/pdf", headers=s.headers)
    assert dl.status_code == 200 and "X-Amz-Signature=" in dl.json()["url"]


async def test_review_request_queue_and_feedback(client, db, world: World) -> None:
    s = world.personas["student"]
    res = (await client.post(f"{API}/me/resumes", json={"content": CONTENT}, headers=s.headers)).json()
    url = f"{API}/me/resumes/{res['id']}/review-requests"
    hdr = {**s.headers, "Idempotency-Key": f"rr-{uuid.uuid4().hex}"}

    r = await client.post(url, json={"note": "Please check projects"}, headers=hdr)
    assert r.status_code == 403 and r.json()["code"] == "entitlement_required", r.text
    assert (await client.post(url, json={}, headers=s.headers)).status_code == 400  # Idempotency-Key required

    await grant_package(db, s, reviews=1)
    hdr = {**s.headers, "Idempotency-Key": f"rr-{uuid.uuid4().hex}"}
    r = await client.post(url, json={"note": "Please check projects"}, headers=hdr)
    assert r.status_code == 201, r.text
    review = r.json()
    assert review["status"] == "requested" and review["comments"] == []
    dup = await client.post(url, json={}, headers={**s.headers, "Idempotency-Key": f"rr-{uuid.uuid4().hex}"})
    assert dup.status_code == 409
    q = (await client.get(f"{API}/me/resumes", headers=s.headers)).json()["quota"]
    assert q["resume_reviews_remaining"] == 0

    m = await mentor(world)
    # Single company (D2): every Admin works the same review queue; trainers and students cannot.
    mb = await mentor(world, "mentor_b")
    queue = await client.get(f"{API}/mentor/resume-reviews", headers=m.headers)
    assert queue.status_code == 200, queue.text
    item = queue.json()["data"][0]
    assert item["id"] == review["id"] and item["student_id"] == str(s.id)
    assert (
        item["resume"]["content"]["headline"] == CONTENT["headline"]
        and item["note"] == "Please check projects"
    )
    assert [
        x["id"] for x in (await client.get(f"{API}/mentor/resume-reviews", headers=mb.headers)).json()["data"]
    ] == [review["id"]]
    for who in (s, world.personas["trainer_a"]):
        assert (await client.get(f"{API}/mentor/resume-reviews", headers=who.headers)).status_code == 403

    fb_url = f"{API}/mentor/resume-reviews/{review['id']}/feedback"
    payload = {"comments": [{"section": "projects", "comment": "Quantify impact"}], "summary": "Solid start"}
    assert (
        await client.post(fb_url, json={"comments": [], "summary": ""}, headers=m.headers)
    ).status_code == 400
    bad_section = {"comments": [{"section": "hobbies", "comment": "x"}], "summary": "y"}
    assert (await client.post(fb_url, json=bad_section, headers=m.headers)).status_code == 400
    done = await client.post(fb_url, json=payload, headers=m.headers)
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "completed" and done.json()["reviewer_id"] == str(m.id)
    assert (await client.post(fb_url, json=payload, headers=m.headers)).status_code == 409

    mine = (await client.get(f"{API}/me/resumes", headers=s.headers)).json()["data"][0]["reviews"][0]
    assert (
        mine["status"] == "completed"
        and mine["comments"] == payload["comments"]
        and mine["summary"] == "Solid start"
    )
    completed = await client.get(
        f"{API}/mentor/resume-reviews", params={"status": "completed"}, headers=m.headers
    )
    assert [x["id"] for x in completed.json()["data"]] == [review["id"]]
