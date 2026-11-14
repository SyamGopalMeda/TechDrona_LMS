"""Idle analytics jobs on Firestore must report zero work (emulator only, no Postgres).

Live 2026-11-13: ``analytics.interval_builder`` re-discovered the same 20 abandoned page instances
every minute through its 2-minute ``received_at`` overlap (the watermark only moved to the newest
row's ``received_at``), so ``page_instances`` never reached 0 and the scheduler gate never skipped
it. ``analytics.video_coverage`` had the same overlap loop on its newest video heartbeat.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core.ids import uuid7
from tests.analytics.conftest import Page, principal_for
from tests.analytics.fs.test_pipeline_firestore import _ingest, world  # noqa: F401 (fixture)
from tests.paths.fs.http_harness import FakeSession

FS_MODULES = ("analytics",)
pytestmark = pytest.mark.usefixtures("fs_env", "world")


async def _intervals(page: Page) -> list[Any]:
    from app.modules.analytics import fs_raw

    return [
        d
        for d in await fs_raw.all_docs(fs_raw.INTERVALS)
        if d.get("page_instance_id") == page.page_instance_id
    ]


async def test_abandoned_open_interval_closes_then_builder_is_idle() -> None:
    from app.modules.analytics import fs_raw
    from app.modules.analytics.jobs import run_interval_builder

    now = datetime.now(UTC)
    t0 = now - timedelta(minutes=10)
    uid = uuid7()
    page = Page("practice", {})
    hbs = [t0 + timedelta(seconds=15 * i) for i in range(1, 5)]
    ev = [page.view(t0)] + [page.hb(t) for t in hbs]  # tab closed: no page.hide
    received = hbs[-1] + timedelta(seconds=5)
    session = FakeSession()
    assert {r["status"] for r in await _ingest(session, principal_for(uid), ev, received)} == {"accepted"}

    # Built while the tab was still alive: one open interval.
    res = await run_interval_builder(session, now=hbs[-1] + timedelta(seconds=30))
    assert res == {"page_instances": 1, "intervals": 1}
    (iv,) = await _intervals(page)
    assert iv.get("is_open") is True and iv.get("ended_at") is None

    # The state live was stuck in: watermark == the newest row's received_at.
    await fs_raw.set_state("interval_builder", received, {})

    # First run after the abandon timeout closes it ...
    res = await run_interval_builder(session, now=now)
    assert res == {"page_instances": 1, "intervals": 1}
    (iv,) = await _intervals(page)
    assert iv.get("is_open") is False
    assert iv.get("close_reason") == "grace_timeout"
    assert iv.get("ended_at") == iv.get("provisional_end")
    assert len(await fs_raw.intervals(is_open=True)) == 0

    # ... and the next runs find nothing (the scheduler gate can now skip the job).
    for k in (1, 2):
        assert await run_interval_builder(session, now=now + timedelta(minutes=k)) == {
            "page_instances": 0,
            "intervals": 0,
        }
    (iv2,) = await _intervals(page)
    assert iv2.id == iv.id  # not rewritten


async def test_page_with_new_heartbeats_is_still_processed() -> None:
    from app.modules.analytics.jobs import run_interval_builder

    now = datetime.now(UTC)
    t0 = now - timedelta(minutes=8)
    uid = uuid7()
    p = principal_for(uid)
    page = Page("practice", {})
    session = FakeSession()
    first = [page.view(t0)] + [page.hb(t0 + timedelta(seconds=15 * i)) for i in range(1, 5)]
    await _ingest(session, p, first, t0 + timedelta(seconds=65))
    assert (await run_interval_builder(session, now=now))["page_instances"] == 1
    assert (await run_interval_builder(session, now=now))["page_instances"] == 0
    before = await _intervals(page)

    # The learner comes back to the same page instance: new heartbeats are picked up.
    t1 = now - timedelta(seconds=60)
    more = [page.hb(t1 + timedelta(seconds=15 * i)) for i in range(0, 3)]
    await _ingest(session, p, more, t1 + timedelta(seconds=35))
    res = await run_interval_builder(session, now=now)
    assert res["page_instances"] == 1
    after = await _intervals(page)
    assert len(after) == len(before) + 1  # the 7-minute gap starts a second interval
    # The new interval is still live (last heartbeat 30 s ago); the old one stays closed.
    assert sorted((d.get("is_open"), d.get("close_reason")) for d in after) == [
        (False, "grace_timeout"),
        (True, None),
    ]
    # Open intervals are rebuilt every run until they close (65 s without a heartbeat).
    later = now + timedelta(minutes=1)
    assert (await run_interval_builder(session, now=later))["page_instances"] == 1
    assert {d.get("is_open") for d in await _intervals(page)} == {False}


async def test_video_coverage_goes_idle(request: pytest.FixtureRequest) -> None:
    stubs: dict[str, Any] = request.getfixturevalue("world")
    from app.modules.analytics.jobs import run_video_coverage

    now = datetime.now(UTC)
    t0 = now - timedelta(minutes=8)
    uid = uuid7()
    asset = stubs["asset"]
    page = Page(
        "lesson_video",
        {"course_id": stubs["course"], "lesson_id": stubs["lesson"], "lesson_asset_id": asset},
    )
    ev = [page.view(t0)]
    for i in range(1, 5):
        media = {
            "lesson_asset_id": str(asset),
            "position_s": 15.0 * i,
            "rate": 1.0,
            "played_ranges": [[15.0 * (i - 1), 15.0 * i]],
        }
        ev.append(page.hb(t0 + timedelta(seconds=15 * i), media=True, media_info=media))
    session = FakeSession()
    await _ingest(session, principal_for(uid), ev, t0 + timedelta(seconds=65))
    assert await run_video_coverage(session, now=now) == {"assets": 1}
    assert await run_video_coverage(session, now=now + timedelta(minutes=1)) == {"assets": 0}
