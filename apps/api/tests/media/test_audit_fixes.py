"""Regression tests for audit Phase B fixes in media (fix agent ``learn``): BE-19 (heartbeat
re-checks the entitlement), malware-scan consumer (GuardDuty tag pull + sweep job)."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.core import access
from app.core.access import AccessDecision
from app.core.db import system_context
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.catalog import api as catalog_api
from app.modules.catalog.models import LessonAsset
from app.modules.learning.models import LessonProgress
from app.modules.media import providers
from app.modules.media import service as media
from app.modules.media.models import PlaybackSession
from tests.catalog.factory import make_published_course, student, sync_catalog
from tests.identity.factory import make_user


@pytest.fixture(autouse=True)
def fake_video():
    fake = providers.FakeVideoProvider()
    providers.set_video_provider(fake)
    prev = access.get_access_checker()
    access.register_access_checker(None)
    yield fake
    access.register_access_checker(prev)
    providers.set_video_provider(None)


class Switch:
    allowed = True

    async def check(self, session, principal, rt, rid, *, is_free=False):
        return AccessDecision(
            self.allowed, "entitlement" if self.allowed else "no_entitlement", (uuid.uuid4(),)
        )


@pytest.mark.usefixtures("catalog_backend")
async def test_be19_heartbeat_after_entitlement_revoked_ends_session_without_credit(browser, db) -> None:
    chk = Switch()
    access.register_access_checker(chk)
    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=False)
    await student(db, browser)
    assert (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).status_code == 201
    r = await browser.post("/media/playback-tokens", {"lesson_asset_id": str(pc.assets["video"])})
    assert r.status_code == 201, r.text
    ps = uuid.UUID(r.json()["playback_session_id"])
    chk.allowed = False
    await system_context(db, "t")
    await db.execute(
        update(PlaybackSession)
        .where(PlaybackSession.id == ps)
        .values(last_heartbeat_at=utcnow() - timedelta(seconds=30))
    )
    await db.flush()
    r = await browser.post(
        f"/media/playback-sessions/{ps}/heartbeat", {"position_seconds": 60, "playing": True}
    )
    assert r.status_code == 410 and r.json()["code"] == "playback_revoked", r.text
    await system_context(db, "t")
    row = (
        await db.execute(
            select(PlaybackSession).where(PlaybackSession.id == ps).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert row.status == "ended" and row.end_reason == "revoked"
    lp = (
        (await db.execute(select(LessonProgress).where(LessonProgress.lesson_key == pc.keys["video"])))
        .scalars()
        .all()
    )
    assert all(x.watched_seconds == 0 for x in lp)


def test_guardduty_tag_parsing() -> None:
    body = (
        '<?xml version="1.0" encoding="UTF-8"?><Tagging xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        "<TagSet><Tag><Key>other</Key><Value>x</Value></Tag>"
        "<Tag><Key>GuardDutyMalwareScanStatus</Key><Value>{}</Value></Tag></TagSet></Tagging>"
    )
    assert providers.parse_guardduty_tagging(body.format("NO_THREATS_FOUND")) == "clean"
    assert providers.parse_guardduty_tagging(body.format("THREATS_FOUND")) == "infected"
    assert providers.parse_guardduty_tagging(body.format("UNSUPPORTED")) is None
    assert providers.parse_guardduty_tagging("<Tagging><TagSet/></Tagging>") is None
    assert providers.parse_guardduty_tagging("not xml") is None


class FakeGuardDuty:
    is_fake = False

    def __init__(self, results: dict[str, str | None]) -> None:
        self.results = results
        self.calls: list[tuple[str, str]] = []

    def immediate_result(self, s3_key: str) -> str | None:
        return None

    async def fetch_result(self, bucket: str, s3_key: str) -> str | None:
        self.calls.append((bucket, s3_key))
        return self.results.get(s3_key)


@pytest.mark.usefixtures("catalog_backend")
async def test_scan_sweep_consumes_guardduty_results(browser, db, monkeypatch, catalog_backend) -> None:
    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=True)
    await system_context(db, "t")
    keys = {name: f"content/lesson_file/{uuid7()}/{name}.pdf" for name in ("clean", "bad", "wait")}
    ids = {}
    for name, key in keys.items():
        aid = uuid7()
        db.add(
            LessonAsset(
                id=aid,
                lesson_id=pc.lessons["article"],
                asset_type="pdf",
                provider="s3",
                s3_key=key,
                mime_type="application/pdf",
                size_bytes=10,
                status="uploading",
                scan_status="pending",
            )
        )
        ids[name] = aid
    await db.flush()
    await sync_catalog(db)
    fake = FakeGuardDuty({keys["clean"]: "clean", keys["bad"]: "infected", keys["wait"]: None})
    monkeypatch.setattr(providers, "get_scanner", lambda: fake)
    done = await media.sweep_pending_scans(db)
    assert done >= 2
    found = await catalog_api.get_assets(db, list(ids.values()))
    got = {n: found.get(i) for n, i in ids.items()}
    for a in got.values():
        assert a is not None
        if catalog_backend == "postgres":
            await db.refresh(a)
    assert (got["clean"].status, got["clean"].scan_status) == ("available", "clean")  # type: ignore[union-attr]
    assert (got["bad"].status, got["bad"].scan_status) == ("failed", "infected")  # type: ignore[union-attr]
    assert got["wait"].scan_status == "pending"  # type: ignore[union-attr]


def test_scan_sweep_is_a_periodic_job() -> None:
    import app.modules.media.tasks  # noqa: F401
    from app.core.jobs import beat_schedule

    assert beat_schedule()["media.scan_sweep"]["task"] == "media.scan_sweep"


@pytest.mark.usefixtures("catalog_backend")
async def test_analytics_coverage_clipped_to_lesson_duration(browser, db) -> None:
    """BE-01 (learning side, requested by ``assess``): a forged analytics coverage larger than the
    video cannot exceed the lesson duration in ``watched_seconds``."""
    from app.modules.learning import service as ls

    async def huge(session, user_id, lesson_key):
        return 100_000

    prev = ls._coverage_lookup
    ls.register_video_coverage_lookup(huge)
    try:
        author = await make_user(db)
        pc = await make_published_course(db, author.id, is_free=True)
        await student(db, browser)
        assert (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).status_code == 201
        r = await browser.post("/media/playback-tokens", {"lesson_asset_id": str(pc.assets["video"])})
        assert r.status_code == 201, r.text
        ps = r.json()["playback_session_id"]
        r = await browser.post(
            f"/media/playback-sessions/{ps}/heartbeat", {"position_seconds": 0, "playing": True}
        )
        assert r.status_code == 200, r.text
        await system_context(db, "t")
        lp = (
            await db.execute(
                select(LessonProgress)
                .where(LessonProgress.lesson_key == pc.keys["video"])
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        assert lp.watched_seconds <= 600
    finally:
        ls.register_video_coverage_lookup(prev)


@pytest.mark.usefixtures("catalog_backend")
async def test_inv12_scan_consumer_updates_unblock_attachments(client, db, sms, monkeypatch) -> None:
    """INV-12 (secadmin request): the media scan consumer also resolves the scan status of
    unblock-request attachments (uploads bucket), both by sweep and by pushed result."""
    from app.modules.security.models import UnblockRequest
    from tests.security.helpers import idem
    from tests.security.test_scn_unblock import restricted_student

    _u, b, case, _r, _ud, _ = await restricted_student(db, client)
    draft = await b.post(
        "/security/unblock-requests", {"case_ref": case.case_ref, "submit": False}, headers=idem()
    )
    assert draft.status_code == 201, draft.text
    rid = draft.json()["request_id"]
    url = f"/security/unblock-requests/{rid}/attachments"
    k1 = (
        await b.post(url, {"filename": "a.pdf", "content_type": "application/pdf", "size_bytes": 10})
    ).json()
    k2 = (await b.post(url, {"filename": "b.png", "content_type": "image/png", "size_bytes": 10})).json()
    key1, key2 = k1["upload"]["fields"]["key"], k2["upload"]["fields"]["key"]
    fake = FakeGuardDuty({key1: "clean"})
    monkeypatch.setattr(providers, "get_scanner", lambda: fake)
    await system_context(db, "t")
    assert await media.sweep_pending_scans(db) >= 1
    from app.modules.media.storage import storage_settings

    assert (storage_settings().S3_BUCKET_UPLOADS, key1) in fake.calls
    assert await media.apply_scan_result(db, key2, "infected") == 1
    row = (
        await db.execute(
            select(UnblockRequest)
            .where(UnblockRequest.id == uuid.UUID(rid))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    status = {a["s3_key"]: a["scan_status"] for a in row.attachments}
    assert status == {key1: "clean", key2: "infected"}
    # idempotent: resolved attachments are not rewritten
    assert await media.apply_scan_result(db, key2, "clean") == 1
    row = (
        await db.execute(
            select(UnblockRequest)
            .where(UnblockRequest.id == uuid.UUID(rid))
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert {a["s3_key"]: a["scan_status"] for a in row.attachments}[key2] == "infected"
