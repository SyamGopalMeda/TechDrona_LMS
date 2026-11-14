"""Catalog over HTTP on Firestore (``TD_STORE_CATALOG=firestore``), no Postgres.

Studio authoring (create, draft patch, lessons, outline, submit, SoD-04, publish with an
idempotency key, archive) and the public catalogue (list, detail) through the real
FastAPI app. Request sessions are ``NO_POSTGRES``: any Postgres use fails the test, which proves
``/catalog/courses`` and the studio routes no longer read the RLS settings from the session (the
TN view is bound from the principal per request). Idempotency runs on Firestore
(``TD_STORE_CORE=firestore``); audit / outbox are recorded.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from tests.paths.fs.http_harness import install_fake_db, restore_switch, stub_core, switch_to_firestore

API = "/api/v1"
PERMS = (
    "course.create",
    "course.edit",
    "course.preview",
    "course.publish",
    "course.submit_review",
    "course.archive",
    "course.settings_change",
    "resource.manage",
)


@pytest.fixture
async def web(
    fs_client: Any, monkeypatch: pytest.MonkeyPatch, auth: Any
) -> AsyncIterator[tuple[httpx.AsyncClient, Any, list[tuple[str, Any]]]]:
    from app.main import create_app
    from app.modules.rbac import service as rbac

    calls: list[tuple[str, Any]] = []
    stub_core(monkeypatch, calls)

    async def role_perms(session: Any) -> dict[str, frozenset[str]]:  # rbac (its own store)
        return {"content_manager": frozenset(PERMS)}

    monkeypatch.setattr(rbac, "role_permission_map", role_perms)
    await switch_to_firestore(fs_client, monkeypatch, "catalog", "core")
    app = create_app()
    install_fake_db(app, session=None)  # see http_harness.install_fake_db (core_store)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c, auth, calls
    finally:
        restore_switch(monkeypatch, "catalog", "core")


def _staff(auth: Any, make_principal: Any) -> tuple[Any, dict[str, str]]:
    p = make_principal(is_platform=True, roles=("content_manager",))
    for perm in PERMS:
        auth.grant(p, perm)
    return p, auth.login(p)


async def test_authoring_publish_and_public_catalogue(web: Any, make_principal: Any) -> None:
    c, auth, calls = web
    _, ah = _staff(auth, make_principal)
    _, ph = _staff(auth, make_principal)
    anon: dict[str, str] = {}

    body = {"title": "DSA for Placements", "slug": "dsa-placements", "visibility": "public", "is_free": True}
    r = await c.post(f"{API}/studio/courses", json=body, headers=ah)
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert r.json()["status"] == "draft" and r.json()["draft"]["version_no"] == 1
    dup = await c.post(f"{API}/studio/courses", json=body, headers=ah)
    assert dup.status_code == 409  # slug unique per catalogue

    r = await c.patch(
        f"{API}/studio/courses/{cid}/draft",
        json={"summary": "Arrays to graphs", "tags": ["dsa"], "level": "beginner", "category": "dsa"},
        headers=ah,
    )
    assert r.status_code == 200 and r.json()["tags"] == ["dsa"], r.text
    lessons = []
    for title in ("Arrays", "Graphs"):
        r = await c.post(
            f"{API}/studio/courses/{cid}/draft/lessons",
            json={
                "title": title,
                "lesson_type": "article",
                "article_body": {"doc": title},
                "est_reading_minutes": 3,
            },
            headers=ah,
        )
        assert r.status_code == 201, r.text
        lessons.append(r.json()["id"])
    r = await c.put(
        f"{API}/studio/courses/{cid}/draft/outline",
        json={
            "modules": [
                {"title": "Start", "lesson_ids": [lessons[1]]},
                {"title": "More", "lesson_ids": [lessons[0]]},
            ]
        },
        headers=ah,
    )
    assert r.status_code == 200, r.text
    assert [m["title"] for m in r.json()["modules"]] == ["Start", "More"]

    assert (await c.get(f"{API}/catalog/courses/dsa-placements", headers=anon)).status_code == 404  # draft
    assert (await c.post(f"{API}/studio/courses/{cid}/submit-review", headers=ah)).status_code == 200
    key = {"Idempotency-Key": str(uuid.uuid4())}
    r = await c.post(
        f"{API}/studio/courses/{cid}/publish", json={"change_type": "major"}, headers={**ah, **key}
    )
    assert r.status_code == 403 and r.json()["code"] == "sod_violation", r.text
    key = {"Idempotency-Key": str(uuid.uuid4())}
    r = await c.post(
        f"{API}/studio/courses/{cid}/publish", json={"change_type": "major"}, headers={**ph, **key}
    )
    assert r.status_code == 200, r.text
    assert r.json()["course"]["status"] == "published" and r.json()["version"]["status"] == "published"

    listed = await c.get(f"{API}/catalog/courses", params={"category": "dsa"}, headers=anon)
    assert listed.status_code == 200, listed.text
    assert [x["id"] for x in listed.json()["data"]] == [cid]
    d = (await c.get(f"{API}/catalog/courses/DSA-Placements", headers=anon)).json()
    assert d["title"] == "DSA for Placements"

    studio = (await c.get(f"{API}/studio/courses", headers=ah)).json()["data"]
    assert [x["id"] for x in studio] == [cid]
    versions = (await c.get(f"{API}/studio/courses/{cid}/versions", headers=ah)).json()["data"]
    assert [v["status"] for v in versions] == ["published"]
    assert (await c.post(f"{API}/studio/courses/{cid}/archive", headers=ph)).status_code == 200
    assert (await c.get(f"{API}/catalog/courses", headers=anon)).json()["data"] == []
    assert ("audit", "course.publish") in calls or any(
        a.startswith("course.") for k, a in calls if k == "audit"
    )


async def test_student_cannot_author(web: Any, make_principal: Any) -> None:
    c, auth, _ = web
    sh = auth.login(make_principal())
    r = await c.post(f"{API}/studio/courses", json={"title": "Nope course", "slug": "nope"}, headers=sh)
    assert r.status_code == 403
    assert (await c.get(f"{API}/studio/courses", headers=sh)).status_code == 403
