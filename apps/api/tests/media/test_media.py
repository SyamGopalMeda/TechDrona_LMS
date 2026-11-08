"""Playback tokens (entitlement fail-closed, free preview, watermark, OTP never stored),
stream cap (409 playback_conflict, takeover, same-session tab takeover, cap signal),
heartbeats (progress evidence, 410 revoked/stale), uploads (presigned POST conditions),
downloads (short-lived presigned GET), fake-adapter production gate, restricted principals."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import select, text, update

from app.core import access
from app.core.db import system_context
from app.core.time import utcnow
from app.modules.learning.models import LessonProgress
from app.modules.media.models import PlaybackSession
from tests.catalog.factory import login_new_device, make_published_course, staff, student
from tests.identity.factory import FIREFOX_LINUX, make_user


@pytest.fixture(autouse=True)
def fake_video():
    from app.modules.media import providers

    fake = providers.FakeVideoProvider()
    providers.set_video_provider(fake)
    prev = access.get_access_checker()
    access.register_access_checker(None)
    yield fake
    access.register_access_checker(prev)
    providers.set_video_provider(None)


async def _token(b, asset, **kw):
    return await b.post("/media/playback-tokens", {"lesson_asset_id": str(asset), **kw})


async def test_playback_token_watermark_entitlement_and_free_preview(browser, db, fake_video) -> None:
    author = await make_user(db)
    free = await make_published_course(db, author.id, is_free=True)
    paid = await make_published_course(db, author.id, is_free=False)
    preview = await make_published_course(db, author.id, is_free=False, video_preview=True)
    u = await student(db, browser, full_name="Ananya Reddy", phone="+919876543221")
    # paid content without an entitlements checker: fail closed
    r = await _token(browser, paid.assets["video"])
    assert r.status_code == 403 and r.json()["code"] == "entitlement_required"
    # free-preview lesson of a paid course: allowed for any signed-in user
    r = await _token(browser, preview.assets["video"])
    assert r.status_code == 201, r.text
    await browser.post(f"/media/playback-sessions/{r.json()['playback_session_id']}/stop")
    # free course
    r = await _token(browser, free.assets["video"])
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["provider"] == "vdocipher" and body["otp"].startswith("FAKE-OTP-")
    assert body["heartbeat_interval_seconds"] == 30 and body["stale_after_seconds"] == 90
    assert body["watermark"]["moving"] is True
    wm = body["watermark"]["text"]
    assert wm.startswith("Ananya • 98xxxxxx21 • ") and "9876543221" not in wm and "Reddy" not in wm
    assert fake_video.issued[-1][1] == 300  # OTP ttl
    await system_context(db, "t")
    ps = (
        await db.execute(
            select(PlaybackSession).where(PlaybackSession.user_id == u.id, PlaybackSession.status == "active")
        )
    ).scalar_one()
    assert ps.provider_otp_ref_hash == hashlib.sha256(body["otp"].encode()).digest()
    assert body["otp"] not in str(ps.__dict__)
    # unknown asset -> 404; provider down -> 503
    import uuid

    assert (await _token(browser, uuid.uuid4())).status_code == 404
    fake_video.fail_otp = True
    r = await _token(browser, free.assets["video"])
    assert r.status_code == 503


async def test_stream_cap_conflict_takeover_and_heartbeats(browser, db, mail) -> None:
    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=True)
    u = await student(db, browser)
    assert (await browser.post("/me/enrolments", {"course_id": str(pc.course_id)})).status_code == 201
    first = await _token(browser, pc.assets["video"])
    assert first.status_code == 201
    ps1 = first.json()["playback_session_id"]
    # another tab of the same auth session takes over silently
    tab = await _token(browser, pc.assets["video"], tab_id=str(__import__("uuid").uuid4()))
    assert tab.status_code == 201
    r = await browser.post(f"/media/playback-sessions/{ps1}/heartbeat", {"position_seconds": 5})
    assert (
        r.status_code == 410
        and r.json()["code"] == "playback_revoked"
        and r.json()["end_reason"] == "taken_over"
    )
    ps_tab = tab.json()["playback_session_id"]
    # second device of the same account: 409 with takeover option
    phone = browser.fork(ua=FIREFOX_LINUX)
    await login_new_device(phone, mail, u.email)
    r = await _token(phone, pc.assets["video"])
    assert r.status_code == 409 and r.json()["code"] == "playback_conflict", r.text
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["takeover_allowed"] is True and r.json()["other_playback_session_id"] == ps_tab
    assert r.json()["other_device_label"]
    await system_context(db, "t")
    assert (
        await db.execute(text("SELECT count(*) FROM outbox_events WHERE event_type = 'media.stream_cap_hit'"))
    ).scalar() == 1
    # the phone cannot heartbeat or stop the laptop's playback session
    assert (
        await phone.post(f"/media/playback-sessions/{ps_tab}/heartbeat", {"position_seconds": 1})
    ).status_code == 404
    # confirm takeover
    r = await _token(phone, pc.assets["video"], take_over_playback_session_id=ps_tab)
    assert r.status_code == 201, r.text
    ps_phone = r.json()["playback_session_id"]
    r = await browser.post(f"/media/playback-sessions/{ps_tab}/heartbeat", {"position_seconds": 5})
    assert r.status_code == 410 and r.json()["end_reason"] == "taken_over"
    # heartbeats credit watched seconds only for plausible advances (server time)
    await system_context(db, "t")

    async def backdate(seconds):
        await system_context(db, "t")
        await db.execute(
            update(PlaybackSession)
            .where(PlaybackSession.id == ps_phone)
            .values(last_heartbeat_at=utcnow() - timedelta(seconds=seconds))
        )
        await db.flush()

    await backdate(30)
    r = await phone.post(
        f"/media/playback-sessions/{ps_phone}/heartbeat", {"position_seconds": 30, "playing": True}
    )
    assert r.status_code == 200 and r.json()["state"] == "active", r.text
    await backdate(30)
    # a jump of 500 s in 30 s is not credited (seeking/forgery)
    await phone.post(
        f"/media/playback-sessions/{ps_phone}/heartbeat", {"position_seconds": 530, "playing": True}
    )
    await system_context(db, "t")
    lp = (
        await db.execute(
            select(LessonProgress).where(
                LessonProgress.user_id == u.id, LessonProgress.lesson_key == pc.keys["video"]
            )
        )
    ).scalar_one()
    assert lp.watched_seconds == 30 and lp.status == "in_progress" and lp.video_position_s == 530
    # watch the rest at 1x: 30 s steps -> completes at >= 90 % (540 s)
    pos = 0
    for _ in range(18):
        await backdate(31)
        pos += 30
        r = await phone.post(f"/media/playback-sessions/{ps_phone}/heartbeat", {"position_seconds": pos})
        assert r.status_code == 200
    await system_context(db, "t")
    await db.refresh(lp)
    assert lp.status == "completed" and lp.evidence["kind"] == "video_coverage" and lp.watched_seconds >= 540
    # stale session (no heartbeat for > 90 s) -> 410 stale
    await backdate(120)
    r = await phone.post(f"/media/playback-sessions/{ps_phone}/heartbeat", {"position_seconds": pos + 30})
    assert r.status_code == 410 and r.json()["end_reason"] == "stale"
    # and a stale session no longer blocks the laptop
    r = await _token(browser, pc.assets["video"])
    assert r.status_code == 201
    r = await browser.post(f"/media/playback-sessions/{r.json()['playback_session_id']}/stop")
    assert r.json()["end_reason"] == "stopped"


async def test_restricted_principal_cannot_play(browser, db) -> None:
    from app.modules.sessions import hooks
    from app.modules.sessions.hooks import RestrictionState

    author = await make_user(db)
    pc = await make_published_course(db, author.id, is_free=True)
    await student(db, browser)

    async def video_locked(session, user_id):
        return RestrictionState(level=2, restrictions=frozenset({"video_locked"}))

    hooks.register_restriction_lookup(video_locked)
    try:
        r = await _token(browser, pc.assets["video"])
        assert r.status_code == 403 and r.json()["code"] == "account_restricted"
    finally:
        hooks.register_restriction_lookup(None)

    async def l3(session, user_id):
        return RestrictionState(level=3)

    hooks.register_restriction_lookup(l3)
    try:
        r = await _token(browser, pc.assets["video"])
        assert r.status_code == 403 and r.json()["code"] == "account_restricted"
    finally:
        hooks.register_restriction_lookup(None)


async def test_uploads_presign_and_permissions(browser, db) -> None:
    author = await make_user(db)
    pc = await make_published_course(db, author.id)
    await student(db, browser)
    ok = await browser.post(
        "/media/uploads/file",
        {
            "purpose": "assignment_submission",
            "filename": "../../etc/passwd.pdf",
            "content_type": "application/pdf",
            "size_bytes": 1000,
        },
    )
    assert ok.status_code == 201, ok.text
    f = ok.json()["upload"]["fields"]
    assert "/../" not in ok.json()["s3_key"] and f["key"] == ok.json()["s3_key"]
    assert f["x-amz-algorithm"] == "AWS4-HMAC-SHA256" and len(f["x-amz-signature"]) == 64
    import base64
    import json

    policy = json.loads(base64.b64decode(f["policy"]))
    assert ["content-length-range", 1, 1000] in policy["conditions"]
    assert ["eq", "$Content-Type", "application/pdf"] in policy["conditions"]
    big = await browser.post(
        "/media/uploads/file",
        {
            "purpose": "assignment_submission",
            "filename": "a.pdf",
            "content_type": "application/pdf",
            "size_bytes": 21 * 1024 * 1024,
        },
    )
    assert big.status_code == 413
    exe = await browser.post(
        "/media/uploads/file",
        {
            "purpose": "assignment_submission",
            "filename": "a.exe",
            "content_type": "application/x-msdownload",
            "size_bytes": 10,
        },
    )
    assert exe.status_code == 415
    # lesson files / videos need media.upload on the course
    r = await browser.post(
        "/media/uploads/file",
        {
            "purpose": "lesson_file",
            "filename": "notes.pdf",
            "content_type": "application/pdf",
            "size_bytes": 10,
            "lesson_id": str(pc.lessons["article"]),
        },
    )
    assert r.status_code == 403
    r = await browser.post("/media/uploads/video", {"lesson_id": str(pc.lessons["video"]), "title": "x"})
    assert r.status_code == 403
    # content manager: lesson file on a draft lesson -> asset row (no binary), scan via fake scanner
    cm = browser.fork()
    await staff(db, cm, "content_manager")
    c = await cm.post("/studio/courses", {"title": "Notes course", "slug": "notes-course"})
    les = await cm.post(
        f"/studio/courses/{c.json()['id']}/draft/lessons", {"title": "Notes", "lesson_type": "article"}
    )
    r = await cm.post(
        "/media/uploads/file",
        {
            "purpose": "lesson_file",
            "filename": "notes.pdf",
            "content_type": "application/pdf",
            "size_bytes": 10,
            "lesson_id": les.json()["id"],
        },
    )
    assert r.status_code == 201 and r.json()["lesson_asset_id"]
    st = await cm.get(f"/media/assets/{r.json()['lesson_asset_id']}/status")
    assert st.json()["status"] == "ready" and st.json()["scan_status"] == "clean"
    # published lessons are immutable: no uploads onto them
    r = await cm.post("/media/uploads/video", {"lesson_id": str(pc.lessons["video"]), "title": "x"})
    assert r.status_code == 409


async def test_downloads_short_lived_and_entitlement(browser, db) -> None:
    author = await make_user(db)
    paid = await make_published_course(db, author.id, is_free=False)
    cm = browser.fork()
    await staff(db, cm, "content_manager")
    pub = await cm.post(
        "/studio/resources",
        {
            "title": "Free sheet",
            "resource_type": "file",
            "access_level": "public",
            "course_id": str(paid.course_id),
            "s3_key": "content/resource_file/abc/sheet.pdf",
        },
    )
    ent = await cm.post(
        "/studio/resources",
        {
            "title": "Paid sheet",
            "resource_type": "file",
            "access_level": "entitled",
            "course_id": str(paid.course_id),
            "s3_key": "content/resource_file/def/paid.pdf",
        },
    )
    assert pub.status_code == 201 and ent.status_code == 201
    await student(db, browser)
    r = await browser.post("/media/downloads", {"resource_id": pub.json()["id"]})
    assert r.status_code == 200, r.text
    q = parse_qs(urlsplit(r.json()["url"]).query)
    assert int(q["X-Amz-Expires"][0]) <= 300 and len(q["X-Amz-Signature"][0]) == 64
    r = await browser.post("/media/downloads", {"resource_id": ent.json()["id"]})
    assert r.status_code == 403 and r.json()["code"] == "entitlement_required"


def test_fake_adapters_refused_in_production() -> None:
    from app.core.startup_checks import production_problems
    from tests.core.test_logging_and_startup import _prod

    assert not [p for p in production_problems(_prod()) if "media" in p]
    problems = production_problems(_prod(VDOCIPHER_MODE="stub"))
    assert any("FakeVideoProvider" in p for p in problems)
    assert any("FakeMalwareScanner" in p for p in production_problems(_prod(S3_KMS_KEY_ID="local")))


def test_fake_provider_refused_at_runtime_in_production(monkeypatch) -> None:
    from app.core.config import get_settings, reset_settings_cache
    from app.core.errors import ProblemError
    from app.modules.media import providers

    providers.set_video_provider(providers.FakeVideoProvider())
    monkeypatch.setenv("APP_ENV", "prod")
    reset_settings_cache()
    try:
        assert get_settings().is_production
        with pytest.raises(ProblemError):
            providers.get_video_provider()
    finally:
        monkeypatch.setenv("APP_ENV", "test")
        reset_settings_cache()
