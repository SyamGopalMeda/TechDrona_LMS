"""Media domain logic: playback token issuance with the per-user stream cap, heartbeats,
watermark payload, upload credentials, asset status, scan results.

Stream cap (brief §5, RE §7.3, architecture §12): inside the issuing transaction take
``pg_advisory_xact_lock(hashtext('play:' || user_id))``, end the user's stale sessions (no
heartbeat for 90 s), then count active sessions. Another tab of the **same auth session**
is taken over silently; a different session/device at the cap gets ``409 playback_conflict``
(with ``takeover_allowed``) unless the client confirms with ``take_over_playback_session_id``.
The taken-over session ends with ``end_reason = taken_over`` and its next heartbeat answers
``410 playback_revoked``.

Policy values (``playback.max_concurrent_streams`` = 1, ``playback.otp_ttl_seconds`` = 300,
``playback.heartbeat_seconds`` = 30, ``playback.stale_after_seconds`` = 90) are read from the
admin ``policy_settings`` store (user > org > plan > platform) through
``identity.policy.get_policy``; the module constants below are the safe fallbacks used when a
value is missing or invalid. 30 tokens/hour/user stays a constant (no policy key).
"""

from __future__ import annotations

import base64
import hashlib
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import to_rfc3339, utcnow
from app.modules.catalog import api as catalog_api
from app.modules.catalog.api import Course, CourseVersion, Lesson, LessonAsset
from app.modules.learning import service as learning
from app.modules.media.models import PlaybackSession
from app.modules.media.providers import Watermark, get_video_provider

MAX_CONCURRENT_STREAMS = 1
OTP_TTL_SECONDS = 300
HEARTBEAT_SECONDS = 30
STALE_AFTER_SECONDS = 90
TOKENS_PER_HOUR = 30


@dataclass(frozen=True, slots=True)
class PlaybackPolicy:
    max_concurrent_streams: int = MAX_CONCURRENT_STREAMS
    otp_ttl_seconds: int = OTP_TTL_SECONDS
    heartbeat_seconds: int = HEARTBEAT_SECONDS
    stale_after_seconds: int = STALE_AFTER_SECONDS


async def _int_policy(
    session: AsyncSession, key: str, default: int, user_id: uuid.UUID, lo: int, hi: int
) -> int:
    from app.modules.identity.policy import get_policy

    try:
        async with session.begin_nested():
            raw = await get_policy(session, key, user_id=user_id)
        v = int(raw)
    except Exception:  # policy store unavailable or malformed value: fail safe to the default
        return default
    return v if lo <= v <= hi else default


async def playback_policy(session: AsyncSession, user_id: uuid.UUID) -> PlaybackPolicy:
    return PlaybackPolicy(
        max_concurrent_streams=await _int_policy(
            session, "playback.max_concurrent_streams", MAX_CONCURRENT_STREAMS, user_id, 1, 3
        ),
        otp_ttl_seconds=await _int_policy(
            session, "playback.otp_ttl_seconds", OTP_TTL_SECONDS, user_id, 60, 900
        ),
        heartbeat_seconds=await _int_policy(
            session, "playback.heartbeat_seconds", HEARTBEAT_SECONDS, user_id, 15, 60
        ),
        stale_after_seconds=await _int_policy(
            session, "playback.stale_after_seconds", STALE_AFTER_SECONDS, user_id, 60, 180
        ),
    )


async def stale_after_policy(session: AsyncSession, user_id: uuid.UUID) -> int:
    """``playback.stale_after_seconds`` alone: the only policy a heartbeat uses (cost-media: one
    policy lookup per MED-05 instead of all four; same value as ``playback_policy``)."""
    return await _int_policy(session, "playback.stale_after_seconds", STALE_AFTER_SECONDS, user_id, 60, 180)


@dataclass(frozen=True, slots=True)
class LessonContext:
    asset: LessonAsset
    lesson: Lesson
    version: CourseVersion
    course: Course


async def student_asset(session: AsyncSession, asset_id: uuid.UUID) -> LessonContext:
    row = await catalog_api.asset_with_parents(session, asset_id, version_statuses=learning.STUDENT_VISIBLE)
    if row is None:
        raise ProblemError("not_found")
    return LessonContext(row[0], row[1], row[2], row[3])


def _short_code(user_id: uuid.UUID) -> str:
    return base64.b32encode(hashlib.sha256(user_id.bytes).digest()).decode()[:4].lower()


def _mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    digits = phone[3:] if phone.startswith("+91") else phone.lstrip("+")
    if len(digits) < 6:
        return None
    return f"{digits[:2]}xxxxxx{digits[-2:]}"


async def watermark_for(session: AsyncSession, principal: Principal) -> Watermark:
    """Masked first name + masked mobile (or masked email) + short user code (FR-MED-001)."""
    from app.modules.identity.contacts import mask_email
    from app.modules.media import adapters

    email, phone, name = await adapters.watermark_contact(session, principal.user_id)
    first = (name or "").strip().split(" ")[0][:20] or "Learner"
    contact = _mask_phone(phone) or mask_email(email) or "—"
    return Watermark(text=f"{first} • {contact} • {_short_code(principal.user_id)}", moving=True)


async def _device_label(session: AsyncSession, device_id: uuid.UUID | None) -> str:
    if device_id is None:
        return "another device"
    from app.modules.media import adapters

    row = await adapters.device_families(session, device_id)
    if row is None or not (row[0] or row[1]):
        return "another device"
    ua, os_ = row
    return f"{ua or 'Browser'} on {os_ or 'unknown OS'}"


async def _record_cap_signal(
    session: AsyncSession, user_id: uuid.UUID, other_id: uuid.UUID, is_minor: bool
) -> None:
    """Deterministic ``cap.stream`` signal for the security module (rule key ``cap.stream``).
    The conflict is answered without rolling back, so the signal and the stale-session
    clean-up commit with the request."""
    await emit_event(
        session,
        "media.stream_cap_hit",
        {
            "user_id": str(user_id),
            "other_playback_session_id": str(other_id),
            "rule_key": "cap.stream",
            "is_minor": is_minor,
        },
        aggregate_type="user",
        aggregate_id=user_id,
    )


def _fs() -> bool:
    return uses_firestore("media")


def _repo() -> Any:
    from app.modules.media.repo_firestore import repo

    return repo()


async def _end(session: AsyncSession, ps: PlaybackSession, reason: str) -> None:
    ps.status = "ended"
    ps.ended_at = utcnow()
    ps.end_reason = reason
    if _fs():
        await _repo().end(ps.user_id, ps.id, reason, ps.ended_at)
        return
    await session.flush()


async def issue_playback(
    session: AsyncSession,
    principal: Principal,
    *,
    asset_id: uuid.UUID,
    tab_id: uuid.UUID | None,
    take_over_id: uuid.UUID | None,
) -> dict[str, Any] | ProblemError:
    """Issue a playback token, or return the ``playback_conflict`` problem (not raised: the
    cap signal and stale clean-up must commit)."""
    if "video_locked" in principal.restrictions or principal.restriction_level >= 3:
        raise ProblemError("account_restricted", level=principal.restriction_level)
    ctx = await student_asset(session, asset_id)
    if ctx.asset.asset_type != "video" or ctx.asset.provider != "vdocipher":
        raise ProblemError("not_found")
    # 1. entitlement (free-preview lessons: any signed-in user)
    decision = await learning.check_lesson_access(session, principal, ctx.lesson, ctx.course)
    if ctx.asset.status != "available" or ctx.asset.provider_asset_id is None:
        raise ProblemError("invalid_state_transition", detail="This video is still processing.")
    if _fs():
        return await _issue_playback_fs(session, principal, ctx, decision, tab_id, take_over_id)
    # 2. L2 owner verification of this device: sessions/security hook (Planned).
    # 3. stream cap under a per-user transaction advisory lock
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"play:{principal.user_id}"}
    )
    pol = await playback_policy(session, principal.user_id)
    now = utcnow()
    stale_cut = now - timedelta(seconds=pol.stale_after_seconds)
    await session.execute(
        update(PlaybackSession)
        .where(
            PlaybackSession.user_id == principal.user_id,
            PlaybackSession.status == "active",
            PlaybackSession.last_heartbeat_at <= stale_cut,
        )
        .values(status="ended", ended_at=now, end_reason="stale")
        .execution_options(synchronize_session=False)
    )
    active = list(
        (
            await session.execute(
                select(PlaybackSession)
                .where(PlaybackSession.user_id == principal.user_id, PlaybackSession.status == "active")
                .order_by(PlaybackSession.started_at)
            )
        ).scalars()
    )
    others = []
    for ps in active:
        if ps.auth_session_id == principal.session_id:
            await _end(session, ps, "taken_over")  # another tab of this session: silent takeover
        else:
            others.append(ps)
    if len(others) >= pol.max_concurrent_streams:
        target = next((o for o in others if o.id == take_over_id), None) if take_over_id else None
        if target is None:
            other = others[-1]
            await _record_cap_signal(session, principal.user_id, other.id, principal.is_minor)
            label = await _device_label(session, other.device_id)
            return ProblemError(
                "playback_conflict",
                title="Playing on another device",
                detail=f"This account is already playing a video on {label}. Play here instead?",
                other_device_label=label,
                other_playback_session_id=str(other.id),
                takeover_allowed=True,
            )
        await _end(session, target, "taken_over")
        others.remove(target)
        if len(others) >= pol.max_concurrent_streams:  # pragma: no cover - cap > 1 with several others
            raise ProblemError("playback_conflict", takeover_allowed=True)
    # 4. per-user token rate limit
    issued = (
        await session.execute(
            select(func.count())
            .select_from(PlaybackSession)
            .where(
                PlaybackSession.user_id == principal.user_id,
                PlaybackSession.started_at > now - timedelta(hours=1),
            )
        )
    ).scalar_one()
    if issued >= TOKENS_PER_HOUR:
        raise ProblemError("rate_limited", headers={"Retry-After": "600"})
    # 5. resume position from progress (pinned version by lesson_key)
    resume = None
    enr = await learning.get_enrolment(session, principal.user_id, ctx.course.id)
    if enr is not None:
        lp = await learning.get_progress(session, enr, ctx.lesson.lesson_key, create=False)
        resume = lp.video_position_s if lp else None
    ps = PlaybackSession(
        id=uuid7(),
        started_at=now,
        user_id=principal.user_id,
        auth_session_id=principal.session_id,
        device_id=principal.device_id,
        tab_id=tab_id,
        lesson_asset_id=ctx.asset.id,
        provider="vdocipher",
        status="active",
        otp_expires_at=now + timedelta(seconds=pol.otp_ttl_seconds),
        last_heartbeat_at=now,
        last_position_s=resume or 0,
    )
    session.add(ps)
    await session.flush()
    wm = await watermark_for(session, principal)
    otp = await get_video_provider().issue_otp(
        ctx.asset.provider_asset_id, ttl_seconds=pol.otp_ttl_seconds, watermark=wm
    )
    ps.provider_otp_ref_hash = hashlib.sha256(otp.otp.encode()).digest()
    await session.flush()
    await emit_event(
        session,
        "media.playback_started",
        {
            "playback_session_id": str(ps.id),
            "user_id": str(principal.user_id),
            "lesson_asset_id": str(ctx.asset.id),
            "course_id": str(ctx.course.id),
            "access_reason": decision.reason,
        },
        aggregate_type="playback_session",
        aggregate_id=ps.id,
    )
    return {
        "playback_session_id": str(ps.id),
        "provider": "vdocipher",
        "otp": otp.otp,
        "playback_info": otp.playback_info,
        "otp_expires_at": to_rfc3339(ps.otp_expires_at),
        "heartbeat_interval_seconds": pol.heartbeat_seconds,
        "stale_after_seconds": pol.stale_after_seconds,
        "resume_position_seconds": resume or 0,
        "watermark": {"text": wm.text, "moving": wm.moving},
    }


async def _issue_playback_fs(
    session: AsyncSession,
    principal: Principal,
    ctx: Any,
    decision: Any,
    tab_id: uuid.UUID | None,
    take_over_id: uuid.UUID | None,
) -> dict[str, Any] | ProblemError:
    """Steps 3-5 of ``issue_playback`` on Firestore (``TD_STORE_MEDIA=firestore``): the advisory
    lock section is one transaction on the user's lock document (``repo_firestore.claim``);
    the OTP is fetched after the commit (no external I/O inside a transaction) and the session is
    discarded if that fails, which is what the Postgres rollback does."""
    pol = await playback_policy(session, principal.user_id)
    now = utcnow()
    resume = None
    enr = await learning.get_enrolment(session, principal.user_id, ctx.course.id)
    if enr is not None:
        lp = await learning.get_progress(session, enr, ctx.lesson.lesson_key, create=False)
        resume = lp.video_position_s if lp else None
    new = PlaybackSession(
        id=uuid7(),
        started_at=now,
        user_id=principal.user_id,
        auth_session_id=principal.session_id,
        device_id=principal.device_id,
        tab_id=tab_id,
        lesson_asset_id=ctx.asset.id,
        provider="vdocipher",
        status="active",
        otp_expires_at=now + timedelta(seconds=pol.otp_ttl_seconds),
        last_heartbeat_at=now,
        last_position_s=resume or 0,
    )
    r = _repo()
    claim = await r.claim(
        principal.user_id,
        auth_session_id=principal.session_id,
        take_over_id=take_over_id,
        now=now,
        stale_cut=now - timedelta(seconds=pol.stale_after_seconds),
        hour_cut=now - timedelta(hours=1),
        cap=pol.max_concurrent_streams,
        tokens_per_hour=TOKENS_PER_HOUR,
        new=new,
    )
    if claim.kind == "conflict":
        other = claim.session
        await _record_cap_signal(session, principal.user_id, other.id, principal.is_minor)
        label = await _device_label(session, other.device_id)
        return ProblemError(
            "playback_conflict",
            title="Playing on another device",
            detail=f"This account is already playing a video on {label}. Play here instead?",
            other_device_label=label,
            other_playback_session_id=str(other.id),
            takeover_allowed=True,
        )
    ps = claim.session
    try:
        wm = await watermark_for(session, principal)
        otp = await get_video_provider().issue_otp(
            ctx.asset.provider_asset_id, ttl_seconds=pol.otp_ttl_seconds, watermark=wm
        )
    except BaseException:
        await r.discard(principal.user_id, ps.id)
        raise
    ps.provider_otp_ref_hash = hashlib.sha256(otp.otp.encode()).digest()
    await r.update(principal.user_id, ps.id, {"provider_otp_ref_hash": ps.provider_otp_ref_hash})
    await emit_event(
        session,
        "media.playback_started",
        {
            "playback_session_id": str(ps.id),
            "user_id": str(principal.user_id),
            "lesson_asset_id": str(ctx.asset.id),
            "course_id": str(ctx.course.id),
            "access_reason": decision.reason,
        },
        aggregate_type="playback_session",
        aggregate_id=ps.id,
    )
    return {
        "playback_session_id": str(ps.id),
        "provider": "vdocipher",
        "otp": otp.otp,
        "playback_info": otp.playback_info,
        "otp_expires_at": to_rfc3339(ps.otp_expires_at),
        "heartbeat_interval_seconds": pol.heartbeat_seconds,
        "stale_after_seconds": pol.stale_after_seconds,
        "resume_position_seconds": resume or 0,
        "watermark": {"text": wm.text, "moving": wm.moving},
    }


async def own_playback(session: AsyncSession, principal: Principal, ps_id: uuid.UUID) -> PlaybackSession:
    if _fs():
        fps = await _repo().get(principal.user_id, ps_id)
        if fps is None or fps.auth_session_id != principal.session_id:
            raise ProblemError("not_found")
        return fps
    ps = (
        await session.execute(
            select(PlaybackSession).where(
                PlaybackSession.id == ps_id, PlaybackSession.user_id == principal.user_id
            )
        )
    ).scalar_one_or_none()
    if ps is None or ps.auth_session_id != principal.session_id:
        raise ProblemError("not_found")
    return ps


async def heartbeat(
    session: AsyncSession, principal: Principal, ps_id: uuid.UUID, *, position_s: int, playing: bool
) -> tuple[ProblemError | None, bool]:
    """Returns (problem to answer with but keep committed, engagement credited)."""
    ps = await own_playback(session, principal, ps_id)
    if ps.status == "ended":
        return ProblemError("playback_revoked", end_reason=ps.end_reason), False
    now = utcnow()
    elapsed = (now - ps.last_heartbeat_at).total_seconds()
    stale_after = await stale_after_policy(session, principal.user_id)
    if elapsed > stale_after:
        await _end(session, ps, "stale")
        return ProblemError("playback_revoked", end_reason="stale"), False
    if principal.restriction_level >= 3 or "video_locked" in principal.restrictions:
        await _end(session, ps, "revoked")
        return ProblemError("playback_revoked", end_reason="revoked"), False
    # BE-19: the entitlement is re-checked on every heartbeat; a withdrawn entitlement ends
    # the session (no further progress credit) instead of crediting until the OTP expires.
    try:
        ctx = await student_asset(session, ps.lesson_asset_id)
        await learning.check_lesson_access(session, principal, ctx.lesson, ctx.course)
    except ProblemError as exc:
        if exc.status not in (403, 404):
            raise
        await _end(session, ps, "revoked")
        return ProblemError("playback_revoked", end_reason="revoked"), False
    prev = ps.last_position_s
    ps.last_heartbeat_at = now
    ps.last_position_s = position_s
    if _fs():
        await _repo().update(ps.user_id, ps.id, {"last_heartbeat_at": now, "last_position_s": position_s})
    else:
        await session.flush()
    credited = False
    credited = await learning.record_video_heartbeat(
        session,
        principal,
        ctx.lesson,
        ctx.course,
        prev_pos=prev,
        new_pos=position_s,
        elapsed_s=elapsed,
        playing=playing,
        duration_s=ctx.asset.duration_seconds,
    )
    return None, credited


async def stop(session: AsyncSession, principal: Principal, ps_id: uuid.UUID) -> PlaybackSession:
    ps = await own_playback(session, principal, ps_id)
    if ps.status == "active":
        await _end(session, ps, "stopped")
    return ps


async def refresh_asset_status(session: AsyncSession, asset: LessonAsset) -> LessonAsset:
    """Pull provider status for VdoCipher assets; apply synchronous scan results for S3."""
    from app.modules.media.providers import get_scanner

    before = asset.status
    changes: dict[str, Any] = {}
    if (
        asset.provider == "vdocipher"
        and asset.status in ("uploading", "processing")
        and asset.provider_asset_id
    ):
        st = await get_video_provider().get_status(asset.provider_asset_id)
        changes["status"] = st.status
        if st.duration_seconds:
            changes["duration_seconds"] = st.duration_seconds
            lesson = (await catalog_api.get_lessons(session, [asset.lesson_id])).get(asset.lesson_id)
            if lesson is not None and lesson.duration_seconds is None:
                await catalog_api.update_lesson(session, lesson.id, duration_seconds=st.duration_seconds)
    elif asset.provider == "s3" and asset.scan_status == "pending" and asset.s3_key:
        result = await scan_result_for(get_scanner(), asset.s3_key)
        if result is not None:
            changes = scan_changes(result)
    if changes:
        asset = await catalog_api.update_asset(session, asset.id, **changes)
    await session.flush()
    if before != "available" and asset.status == "available":
        await emit_event(
            session,
            "media.asset_ready",
            {"lesson_asset_id": str(asset.id), "lesson_id": str(asset.lesson_id)},
            aggregate_type="lesson_asset",
            aggregate_id=asset.id,
            organization_id=asset.organization_id,
        )
    return asset


UNBLOCK_ATTACHMENT_PREFIX = "uploads/unblock_request/"


async def scan_result_for(scanner: Any, s3_key: str, bucket: str | None = None) -> str | None:
    """Synchronous result (fake scanner) or the GuardDuty object-tag lookup. Lesson files live in
    the content bucket; unblock attachments in the uploads bucket."""
    result: str | None = scanner.immediate_result(s3_key)
    fetch = getattr(scanner, "fetch_result", None)
    if result is None and fetch is not None:
        from app.modules.media.storage import storage_settings

        s = storage_settings()
        if bucket is None:
            bucket = s.S3_BUCKET_UPLOADS if s3_key.startswith("uploads/") else s.S3_BUCKET_CONTENT
        result = await fetch(bucket, s3_key)
    return result


async def apply_unblock_attachment_scan(session: AsyncSession, s3_key: str, result: str) -> int:
    """INV-12 (requested by secadmin): set ``scan_status`` of the pending unblock-request
    attachment stored under ``s3_key`` (``clean`` / ``infected``; the reviewer view treats any
    non-clean status as quarantined). Caller supplies a system context. Returns rows updated."""
    if result not in ("clean", "infected"):
        raise ValueError("result must be clean or infected")
    from app.modules.media import adapters

    return await adapters.set_unblock_attachment_scan(session, s3_key, result)


async def sweep_pending_scans(session: AsyncSession, *, limit: int = 200) -> int:
    """Malware-scan consumer job: pull results for S3 lesson assets still ``pending`` (oldest
    first) so uploads become ``available`` without anyone polling MED-03. Caller supplies a
    system context (named job ``media.scan_sweep``). Returns the number of assets resolved."""
    from app.modules.media.providers import get_scanner

    scanner = get_scanner()
    pending = await catalog_api.lock_pending_scan_assets(session, limit=limit)
    done = 0
    for asset in pending:
        assert asset.s3_key is not None
        result = await scan_result_for(scanner, asset.s3_key)
        if result is None:
            continue
        asset = await catalog_api.update_asset(session, asset.id, **scan_changes(result))
        done += 1
        if asset.status == "available":
            await emit_event(
                session,
                "media.asset_ready",
                {"lesson_asset_id": str(asset.id), "lesson_id": str(asset.lesson_id)},
                aggregate_type="lesson_asset",
                aggregate_id=asset.id,
                organization_id=asset.organization_id,
            )
    # INV-12: unblock-request attachments (uploads bucket) are consumed by the same job.
    from app.modules.media import adapters

    keys = await adapters.pending_unblock_attachment_keys(session, limit)
    for key in keys:
        result = await scan_result_for(scanner, key)
        if result is not None and await apply_unblock_attachment_scan(session, key, result):
            done += 1
    return done


def scan_changes(result: str) -> dict[str, str]:
    """``lesson_assets`` column changes for a malware-scan result."""
    if result == "clean":
        return {"scan_status": "clean", "status": "available"}
    return {"scan_status": "infected", "status": "failed"}


async def apply_scan_result(session: AsyncSession, s3_key: str, result: str) -> int:
    """Consumer entry point for malware-scan results (GuardDuty → EventBridge, Planned).
    Caller supplies a system context. Returns the number of assets updated."""
    if result not in ("clean", "infected"):
        raise ValueError("result must be clean or infected")
    if s3_key.startswith(UNBLOCK_ATTACHMENT_PREFIX):
        return await apply_unblock_attachment_scan(session, s3_key, result)
    assets = await catalog_api.assets_by_s3_key(session, s3_key)
    for a in assets:
        await catalog_api.update_asset(session, a.id, **scan_changes(result))
    await session.flush()
    return len(assets)
