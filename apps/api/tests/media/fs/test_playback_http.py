"""Playback over HTTP on Firestore (``TD_STORE_MEDIA=firestore``), no Postgres.

MED-04 token issue (stream cap, conflict, take-over), MED-05 heartbeat (active, revoked after a
take-over) and MED-06 stop through the real FastAPI app. Request sessions are ``NO_POSTGRES``: any Postgres use fails
the test. Catalog / learning / identity / policy collaborators are
stubbed at media's boundary (``student_asset``, ``learning.*``, ``playback_policy``, adapters).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from tests.paths.fs.http_harness import install_fake_db, restore_switch, stub_core, switch_to_firestore

API = "/api/v1"


@pytest.fixture
async def web(
    fs_client: Any, monkeypatch: pytest.MonkeyPatch, auth: Any
) -> AsyncIterator[tuple[httpx.AsyncClient, Any, list[tuple[str, Any]], Any]]:
    from app.main import create_app
    from app.modules.media import adapters
    from app.modules.media import service as svc

    calls: list[tuple[str, Any]] = []
    stub_core(monkeypatch, calls)
    asset = SimpleNamespace(
        id=uuid.uuid4(),
        asset_type="video",
        provider="vdocipher",
        status="available",
        provider_asset_id="vdo-1",
        duration_seconds=600,
        lesson_id=uuid.uuid4(),
    )
    ctx = svc.LessonContext(
        asset, SimpleNamespace(lesson_key=uuid.uuid4()), None, SimpleNamespace(id=uuid.uuid4())
    )

    async def student_asset(session: Any, asset_id: uuid.UUID) -> Any:
        if asset_id != asset.id:
            from app.core.errors import ProblemError

            raise ProblemError("not_found")
        return ctx

    async def access(*a: Any, **k: Any) -> Any:
        return SimpleNamespace(allowed=True, reason="entitlement")

    async def none(*a: Any, **k: Any) -> Any:
        return None

    async def no_credit(*a: Any, **k: Any) -> bool:
        return False

    async def policy(session: Any, user_id: uuid.UUID) -> Any:
        return svc.PlaybackPolicy()

    async def contact(session: Any, user_id: uuid.UUID) -> Any:
        return ("asha@example.test", "+919876543210", "Asha K")

    async def device(session: Any, device_id: uuid.UUID) -> Any:
        return ("Chrome", "Windows")

    monkeypatch.setattr(svc, "student_asset", student_asset)
    monkeypatch.setattr(svc.learning, "check_lesson_access", access)
    monkeypatch.setattr(svc.learning, "get_enrolment", none)
    monkeypatch.setattr(svc.learning, "record_video_heartbeat", no_credit)
    monkeypatch.setattr(svc, "playback_policy", policy)
    monkeypatch.setattr(adapters, "watermark_contact", contact)
    monkeypatch.setattr(adapters, "device_families", device)
    await switch_to_firestore(fs_client, monkeypatch, "media")
    app = create_app()
    install_fake_db(app)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            yield c, auth, calls, asset
    finally:
        restore_switch(monkeypatch, "media")


async def test_token_cap_takeover_heartbeat_and_stop(web: Any, make_principal: Any) -> None:
    c, auth, calls, asset = web
    uid = uuid.uuid4()
    laptop = make_principal(user_id=uid, device_id=uuid.uuid4())
    phone = make_principal(user_id=uid, device_id=uuid.uuid4())
    lh, ph = auth.login(laptop), auth.login(phone)
    body = {"lesson_asset_id": str(asset.id)}

    r = await c.post(f"{API}/media/playback-tokens", json=body, headers=lh)
    assert r.status_code == 201, r.text
    first = r.json()
    assert first["provider"] == "vdocipher" and first["otp"] and first["watermark"]["text"].startswith("Asha")
    assert first["heartbeat_interval_seconds"] == 30 and first["resume_position_seconds"] == 0

    r = await c.post(f"{API}/media/playback-tokens", json=body, headers=ph)
    assert r.status_code == 409 and r.json()["code"] == "playback_conflict", r.text
    assert r.json()["other_playback_session_id"] == first["playback_session_id"]
    assert r.json()["other_device_label"] == "Chrome on Windows"
    assert ("event", "media.stream_cap_hit") in calls

    hb = {"position_seconds": 42}
    r = await c.post(
        f"{API}/media/playback-sessions/{first['playback_session_id']}/heartbeat", json=hb, headers=lh
    )
    assert r.status_code == 200 and r.json()["state"] == "active", r.text
    # another auth session cannot see this playback session
    r = await c.post(
        f"{API}/media/playback-sessions/{first['playback_session_id']}/heartbeat", json=hb, headers=ph
    )
    assert r.status_code == 404

    take = {**body, "take_over_playback_session_id": first["playback_session_id"]}
    r = await c.post(f"{API}/media/playback-tokens", json=take, headers=ph)
    assert r.status_code == 201, r.text
    second = r.json()["playback_session_id"]
    r = await c.post(
        f"{API}/media/playback-sessions/{first['playback_session_id']}/heartbeat", json=hb, headers=lh
    )
    assert r.status_code == 410 and r.json()["end_reason"] == "taken_over"

    r = await c.post(f"{API}/media/playback-sessions/{second}/stop", headers=ph)
    assert r.json() == {"playback_session_id": second, "state": "ended", "end_reason": "stopped"}
    r = await c.post(f"{API}/media/playback-tokens", json=body, headers=lh)  # the cap is free again
    assert r.status_code == 201, r.text
    assert sum(1 for k, e in calls if e == "media.playback_started") == 3
