"""SCN-02 — several tabs on the same laptop (testing-and-acceptance §4.3), backend part.

Runs on a *committed* database (no shared rolled-back connection) so the tabs' requests are
genuinely concurrent, as they are in a browser: every tab shares the one session cookie and
device cookie. Expected: one session, one device, no security signal, no stream-cap event;
a second tab's playback silently takes over the first tab's stream *within the session*
(previous playback ends ``taken_over``); 5- and 7-tab bursts all succeed.

(The attempt-in-two-tabs half of SCN-02 is covered by
``tests/assessments/test_attempts.py::test_autosave_idempotent_and_order_safe`` (``client_seq``
idempotency on one session-bound attempt); M2 = union of tabs by
``tests/analytics/test_timemodel.py::test_example1_overlapping_windows_union_not_sum`` and
``test_union_invariant_random_multi_tab``.)
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core import access
from app.core.db import system_context
from app.modules.media.models import PlaybackSession
from app.modules.security.models import SecuritySignal
from app.modules.sessions.models import AuthSession, UserDevice
from tests.catalog.factory import make_published_course
from tests.identity.factory import Browser, make_user


@pytest.fixture
def fake_video() -> Any:
    from app.modules.media import providers

    fake = providers.FakeVideoProvider()
    providers.set_video_provider(fake)
    prev = access.get_access_checker()
    access.register_access_checker(None)
    yield fake
    access.register_access_checker(prev)
    providers.set_video_provider(None)


@pytest.fixture
async def committed(committed_engine: AsyncEngine) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Factories write through a real committed connection; the app uses its own pooled engine
    (``set_sessionmaker`` is untouched, so each request gets its own connection)."""
    yield async_sessionmaker(committed_engine, expire_on_commit=False)


async def _count(sm: async_sessionmaker[AsyncSession], stmt: Any) -> int:
    async with sm() as s, s.begin():
        await system_context(s, "test.scn02")
        return int((await s.execute(stmt)).scalar_one())


async def test_scn02_many_tabs_one_session_concurrent_requests_and_in_session_takeover(
    client: Any, committed: async_sessionmaker[AsyncSession], fake_video: Any, mail: Any
) -> None:
    async with committed() as s, s.begin():
        author = await make_user(s)
        u = await make_user(s)
        course = await make_published_course(s, author.id, is_free=True)
    laptop = Browser(client)
    r = await laptop.login(u.email)
    assert r.status_code == 200 and r.json()["result"] == "authenticated", r.text
    assert (await laptop.post("/me/enrolments", {"course_id": str(course.course_id)})).status_code == 201
    asset = str(course.assets["video"])

    def tab_call(method: str, path: str, body: Any = None) -> Any:
        # Every tab sends the same cookies (session + device) through the BFF.
        return client.request(
            method, f"/api/v1{path}", json=body, headers=laptop.headers({"Idempotency-Key": uuid.uuid4().hex})
        )

    # 1. Three tabs load concurrently (video lesson, practice list, dashboard).
    burst = await asyncio.gather(
        tab_call("GET", "/me"),
        tab_call("GET", "/me/dashboard"),
        tab_call("GET", "/me/enrolments"),
    )
    assert [x.status_code for x in burst] == [200, 200, 200], [x.text for x in burst]

    # 2. Tab A plays; tab C starts playback -> silent takeover inside the same session.
    tab_a, tab_c = str(uuid.uuid4()), str(uuid.uuid4())
    a = await tab_call("POST", "/media/playback-tokens", {"lesson_asset_id": asset, "tab_id": tab_a})
    assert a.status_code == 201, a.text
    c = await tab_call("POST", "/media/playback-tokens", {"lesson_asset_id": asset, "tab_id": tab_c})
    assert c.status_code == 201, c.text  # no 409 playback_conflict within one session
    ps_a, ps_c = a.json()["playback_session_id"], c.json()["playback_session_id"]

    # Concurrent heartbeats from both tabs plus page traffic: A learns it was taken over, C plays on.
    hb = await asyncio.gather(
        tab_call("POST", f"/media/playback-sessions/{ps_a}/heartbeat", {"position_seconds": 10}),
        tab_call("POST", f"/media/playback-sessions/{ps_c}/heartbeat", {"position_seconds": 3}),
        tab_call("POST", f"/media/playback-sessions/{ps_c}/heartbeat", {"position_seconds": 3}),
        tab_call("GET", "/me/dashboard"),
    )
    assert hb[0].status_code == 410 and hb[0].json()["end_reason"] == "taken_over", hb[0].text
    assert hb[1].status_code == 200 and hb[2].status_code == 200, (hb[1].text, hb[2].text)
    assert hb[3].status_code == 200

    # 4. Boundary bursts: 5 and 7 tabs open at once.
    for n in (5, 7):
        pages = ("/me", "/me/dashboard", "/me/enrolments", "/me/sessions", "/me/devices")
        res = await asyncio.gather(*(tab_call("GET", pages[i % len(pages)]) for i in range(n)))
        assert all(x.status_code == 200 for x in res), [(x.status_code, x.text[:200]) for x in res]

    # Expected: one session, one device, no security signal, no stream-cap event.
    sessions = await _count(
        committed,
        select(func.count())
        .select_from(AuthSession)
        .where(AuthSession.user_id == u.id, AuthSession.status == "active"),
    )
    assert sessions == 1
    devices = await _count(
        committed, select(func.count()).select_from(UserDevice).where(UserDevice.user_id == u.id)
    )
    assert devices == 1
    signals = await _count(
        committed, select(func.count()).select_from(SecuritySignal).where(SecuritySignal.user_id == u.id)
    )
    assert signals == 0
    cap_events = await _count(
        committed,
        text(
            "SELECT count(*) FROM outbox_events WHERE event_type LIKE 'media.stream_cap%' "
            "AND payload::text LIKE :u"
        ).bindparams(u=f"%{u.id}%"),
    )
    assert cap_events == 0
    async with committed() as s, s.begin():
        await system_context(s, "test.scn02")
        rows = {
            str(p.id): p
            for p in (
                await s.execute(select(PlaybackSession).where(PlaybackSession.user_id == u.id))
            ).scalars()
        }
    assert rows[ps_a].status != "active" and rows[ps_a].end_reason == "taken_over"
    assert rows[ps_c].status == "active"
    # Tab C ends its stream normally.
    r = await tab_call("POST", f"/media/playback-sessions/{ps_c}/stop", {})
    assert r.status_code == 200 and r.json()["end_reason"] == "stopped"
