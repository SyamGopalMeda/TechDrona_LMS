"""Résumé builder (module ``mentoring``) over HTTP through the real FastAPI app on Firestore, **no
Postgres** (data-learning agent). Session: the harness ``FirebaseSession`` (falsy like
``NO_POSTGRES``; any SQL fails the test). The mentoring sessions feature was removed
(docs/cleanup/feature-removal-plan.md §3.1). Run with ``TD_TEST_NO_PG=1 TD_TEST_DB_NAME=learning_test``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from tests.learning.fs.harness import FirebaseSession, client_for, close_app, login, open_app

API = "/api/v1"
STORES = (
    "mentoring",
    "entitlements",
    "core",
    "ai",
    "identity",
    "orgs",
    "admin",
    "notifications",
    "rbac",
    "placement",
    "learning",
    "catalog",
)
STUBBED = (
    "app.modules.mentoring.service",
    "app.modules.mentoring.service_fs",
)


@pytest.fixture
async def web(
    fs_client: Any, monkeypatch: pytest.MonkeyPatch, auth: Any
) -> AsyncIterator[tuple[httpx.AsyncClient, Any, list[tuple[str, Any]]]]:
    app, calls = await open_app(
        fs_client, monkeypatch, stores=STORES, stubbed=STUBBED, session_cls=FirebaseSession
    )
    try:
        async with client_for(app) as c:
            yield c, auth, calls
    finally:
        close_app(app, monkeypatch, STORES)


async def test_resumes(web: Any, make_principal: Any) -> None:
    c, auth, _calls = web
    _stu, sh = login(auth, make_principal)
    _, oh = login(auth, make_principal)
    body = {"template_key": "ats_classic", "content": {"headline": "Backend developer", "skills": ["python"]}}
    r = await c.post(f"{API}/me/resumes", json=body, headers=sh)
    assert r.status_code in (200, 201), r.text
    rid = r.json()["id"]
    assert r.json()["version_no"] == 1 and "reviews" not in r.json()
    r2 = await c.post(f"{API}/me/resumes", json=body, headers=sh)
    assert r2.json()["version_no"] == 2
    got = (await c.get(f"{API}/me/resumes", headers=sh)).json()
    assert "quota" not in got
    listed = got["data"]
    assert [x["version_no"] for x in listed] == [2, 1] and [x["is_current"] for x in listed] == [True, False]
    # owner-only: another learner can neither overwrite nor download it
    assert (await c.put(f"{API}/me/resumes/{rid}", json=body, headers=oh)).status_code == 404
    assert (await c.get(f"{API}/me/resumes/{rid}/pdf", headers=oh)).status_code == 404
    # mentor review routes are gone
    gone = await c.post(f"{API}/me/resumes/{rid}/review-requests", json={}, headers=sh)
    assert gone.status_code in (404, 405), gone.text
