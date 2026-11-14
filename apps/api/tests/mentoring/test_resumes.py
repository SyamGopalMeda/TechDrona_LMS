"""Résumés (PLC-47..49). Mentor résumé reviews were removed (feature-removal-plan §3.1)."""

from __future__ import annotations

from typing import Any

from app.core.ids import uuid7
from tests.placement.world import World

API = "/api/v1"

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
    assert "quota" not in r.json() and r.json()["suggested_certifications"] == []

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


async def test_review_routes_are_gone(client, world: World) -> None:
    s = world.personas["student"]
    res = (await client.post(f"{API}/me/resumes", json={"content": CONTENT}, headers=s.headers)).json()
    assert "reviews" not in res
    r = await client.post(f"{API}/me/resumes/{res['id']}/review-requests", json={}, headers=s.headers)
    assert r.status_code in (404, 405)
