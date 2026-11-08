"""Media (api-spec §11, MED-01..07): upload credentials (VdoCipher direct upload, S3
presigned POST — metadata only, no binaries through the API), asset status, playback tokens
with the stream cap, heartbeats, stop, short-lived downloads.

All routes are ``default`` (full scope only): L3/L4 sessions never reach playback.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.access import require_access
from app.core.auth import PLATFORM_SCOPE, ScopeRef, require_active_principal, require_feature
from app.core.db import PrincipalDbSession
from app.core.errors import PROBLEM_CONTENT_TYPE, ProblemError, problem_response
from app.core.idempotency import IdemResult, idempotent
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.request_context import get_request_id
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339, utcnow
from app.modules.catalog import service as catalog
from app.modules.catalog.models import Course, LessonAsset, Resource
from app.modules.media import service as svc
from app.modules.media.providers import get_video_provider
from app.modules.media.storage import presign_get, presign_post, safe_filename, storage_settings

r = authenticated_router(prefix="/media", tags=["media"])

MB = 1024 * 1024
FILE_LIMITS: dict[str, int] = {
    "lesson_file": 200 * MB,
    "resource_file": 100 * MB,
    "assignment_submission": 20 * MB,  # FR-LRN-004
    "support_attachment": 10 * MB,  # SUP-01/04 attachments (BE-17)
}
ALLOWED_TYPES: dict[str, set[str]] = {
    "lesson_file": {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/webp",
        "text/vtt",
        "application/zip",
    },
    "resource_file": {"application/pdf", "image/png", "image/jpeg", "application/zip"},
    "assignment_submission": {
        "application/pdf",
        "application/zip",
        "application/x-zip-compressed",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/x-python",
        "text/x-java-source",
        "text/x-c",
        "text/x-c++src",
        "application/javascript",
    },
}
ALLOWED_TYPES["support_attachment"] = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/webp",
    "text/plain",
}
SUPPORT_ATTACHMENT_PREFIX = "uploads/support_attachment/"
ASSET_TYPE_FOR_MIME = {"application/pdf": "pdf", "text/vtt": "captions"}


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


async def _editable_lesson_scope(
    request: Request, session: Any, principal: Principal, lesson_id: uuid.UUID
) -> tuple[uuid.UUID, Any]:
    course_id, _ = await catalog.lesson_scope(session, principal, lesson_id)
    await catalog.ensure_permission(
        request, session, principal, "media.upload", ScopeRef("course", course_id)
    )
    lesson, _version = await catalog.editable_lesson(session, lesson_id)
    return course_id, lesson


# --------------------------------------------------------------------------- uploads


class VideoUploadIn(Strict):
    lesson_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)


@r.post("/uploads/video", status_code=201, operation_id="med_01_video_upload")
async def video_upload(
    request: Request,
    body: VideoUploadIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    _course_id, lesson = await _editable_lesson_scope(request, session, principal, body.lesson_id)
    if lesson.lesson_type != "video":
        raise catalog.vf("lesson_id", "not_video", "Videos can only be attached to video lessons")

    async def op() -> IdemResult:
        creds = await get_video_provider().create_upload(body.title)
        asset = LessonAsset(
            id=uuid7(),
            lesson_id=lesson.id,
            organization_id=lesson.organization_id,
            asset_type="video",
            provider="vdocipher",
            provider_asset_id=creds.video_id,
            status="uploading",
            scan_status="not_required",
        )
        session.add(asset)
        await session.flush()
        return IdemResult(
            {
                "lesson_asset_id": str(asset.id),
                "provider": "vdocipher",
                "status": "uploading",
                "upload": {"url": creds.upload_link, "fields": creds.fields},
            },
            201,
            asset.id,
        )

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


class FileUploadIn(Strict):
    purpose: Literal["lesson_file", "resource_file", "assignment_submission", "support_attachment"]
    filename: str = Field(min_length=1, max_length=200)
    content_type: str = Field(min_length=3, max_length=120)
    size_bytes: int = Field(gt=0)
    lesson_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    asset_type: Literal["pdf", "image", "attachment", "captions"] | None = None


@r.post("/uploads/file", status_code=201, operation_id="med_02_file_upload")
async def file_upload(
    request: Request,
    body: FileUploadIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    limit = FILE_LIMITS[body.purpose]
    if body.size_bytes > limit:
        raise ProblemError(
            "payload_too_large", detail=f"Files for {body.purpose} can be at most {limit // MB} MB."
        )
    if body.content_type not in ALLOWED_TYPES[body.purpose]:
        raise ProblemError("unsupported_media_type", detail="This file type is not allowed here.")
    name = safe_filename(body.filename)
    s = storage_settings()
    lesson = None
    if body.purpose == "lesson_file":
        if body.lesson_id is None:
            raise catalog.vf("lesson_id", "required", "lesson_id is required")
        _cid, lesson = await _editable_lesson_scope(request, session, principal, body.lesson_id)
        bucket, key = s.S3_BUCKET_CONTENT, f"content/lesson_file/{uuid7()}/{name}"
    elif body.purpose == "resource_file":
        scope = ScopeRef("course", body.course_id) if body.course_id else PLATFORM_SCOPE
        await catalog.ensure_permission(request, session, principal, "media.upload", scope)
        bucket, key = s.S3_BUCKET_CONTENT, f"content/resource_file/{uuid7()}/{name}"
    elif body.purpose == "support_attachment":  # ownership (S); attached via SUP-01/04
        bucket, key = (
            s.S3_BUCKET_UPLOADS,
            f"{SUPPORT_ATTACHMENT_PREFIX}{principal.user_id}/{uuid7()}/{name}",
        )
    else:  # assignment_submission: ownership (S)
        bucket, key = (
            s.S3_BUCKET_UPLOADS,
            f"uploads/assignment_submission/{principal.user_id}/{uuid7()}/{name}",
        )

    async def op() -> IdemResult:
        post = presign_post(bucket, key, content_type=body.content_type, max_bytes=body.size_bytes)
        out: dict[str, Any] = {
            "purpose": body.purpose,
            "s3_key": key,
            "upload": {"url": post.url, "fields": post.fields},
            "expires_at": to_rfc3339(post.expires_at),
            "max_bytes": body.size_bytes,
        }
        if lesson is not None:
            asset = LessonAsset(
                id=uuid7(),
                lesson_id=lesson.id,
                organization_id=lesson.organization_id,
                asset_type=body.asset_type or ASSET_TYPE_FOR_MIME.get(body.content_type, "attachment"),
                provider="s3",
                s3_key=key,
                mime_type=body.content_type,
                size_bytes=body.size_bytes,
                status="uploading",
                scan_status="pending",
            )
            session.add(asset)
            await session.flush()
            out["lesson_asset_id"] = str(asset.id)
        return IdemResult(out, 201)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@r.get(
    "/assets/{lesson_asset_id}/status",
    operation_id="med_03_asset_status",
    openapi_extra={"x-td-idle": "neutral"},
)
async def asset_status(
    request: Request,
    lesson_asset_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    row = await catalog.system_lookup(
        session, principal, select(LessonAsset.lesson_id).where(LessonAsset.id == lesson_asset_id)
    )
    if row is None:
        raise ProblemError("not_found")
    course_id, _ = await catalog.lesson_scope(session, principal, row[0])
    await catalog.ensure_permission(
        request, session, principal, "media.upload", ScopeRef("course", course_id)
    )
    asset = await session.get(LessonAsset, lesson_asset_id)
    if asset is None:
        raise ProblemError("not_found")
    await svc.refresh_asset_status(session, asset)
    return catalog.asset_out(asset)


# --------------------------------------------------------------------------- playback


class PlaybackIn(Strict):
    lesson_asset_id: uuid.UUID
    tab_id: uuid.UUID | None = None
    take_over_playback_session_id: uuid.UUID | None = None


@r.post(
    "/playback-tokens",
    status_code=201,
    operation_id="med_04_playback_token",
    dependencies=[Depends(require_feature("video"))],
)
async def playback_token(
    request: Request,
    body: PlaybackIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    async def op() -> IdemResult:
        out = await svc.issue_playback(
            session,
            principal,
            asset_id=body.lesson_asset_id,
            tab_id=body.tab_id,
            take_over_id=body.take_over_playback_session_id,
        )
        if isinstance(out, ProblemError):
            return IdemResult(
                out.to_body(get_request_id()), out.status, headers={"Content-Type": PROBLEM_CONTENT_TYPE}
            )
        return IdemResult(out, 201, uuid.UUID(out["playback_session_id"]))

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


class HeartbeatIn(Strict):
    position_seconds: int = Field(ge=0, le=86_400)
    buffering: bool = False
    playing: bool = True


@r.post(
    "/playback-sessions/{playback_session_id}/heartbeat",
    operation_id="med_05_heartbeat",
    openapi_extra={"x-td-idle": "engaged_only"},
)
async def heartbeat(
    playback_session_id: uuid.UUID,
    body: HeartbeatIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    problem, credited = await svc.heartbeat(
        session,
        principal,
        playback_session_id,
        position_s=body.position_seconds,
        playing=body.playing and not body.buffering,
    )
    if problem is not None:
        # Keep the transaction (the session is marked ended) and answer 410.
        return problem_response(problem)
    if credited:
        from app.modules.sessions.resolver import touch_engaged

        await touch_engaged(principal.session_id)
    return JSONResponse({"state": "active", "server_time": to_rfc3339(utcnow())})


@r.post("/playback-sessions/{playback_session_id}/stop", operation_id="med_06_stop")
async def stop(
    playback_session_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    ps = await svc.stop(session, principal, playback_session_id)
    return {"playback_session_id": str(ps.id), "state": ps.status, "end_reason": ps.end_reason}


# --------------------------------------------------------------------------- downloads


class DownloadIn(Strict):
    resource_id: uuid.UUID | None = None
    lesson_asset_id: uuid.UUID | None = None


@r.post("/downloads", operation_id="med_07_download")
async def download(
    request: Request,
    body: DownloadIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> Any:
    if (body.resource_id is None) == (body.lesson_asset_id is None):
        raise catalog.vf("resource_id", "one_of", "Give exactly one of resource_id or lesson_asset_id")
    s = storage_settings()

    async def op() -> IdemResult:
        if body.resource_id is not None:
            res = await session.get(Resource, body.resource_id)
            if res is None:
                raise ProblemError("not_found")
            if res.access_level == "entitled":
                course = await session.get(Course, res.course_id) if res.course_id else None
                if course is not None:
                    await require_access(session, principal, "course", course.id, is_free=course.is_free)
                else:
                    await require_access(session, principal, "resource", res.id)
            if res.s3_key is None:
                return IdemResult({"url": res.url, "expires_at": None, "watermarked": False})
            url, exp = presign_get(s.S3_BUCKET_CONTENT, res.s3_key, filename=res.s3_key.rsplit("/", 1)[-1])
            return IdemResult({"url": url, "expires_at": to_rfc3339(exp), "watermarked": False})
        assert body.lesson_asset_id is not None
        ctx = await svc.student_asset(session, body.lesson_asset_id)
        if ctx.asset.provider != "s3" or ctx.asset.s3_key is None:
            raise ProblemError("not_found")
        from app.modules.learning import service as learning

        await learning.check_lesson_access(session, principal, ctx.lesson, ctx.course)
        if ctx.asset.status != "available" or ctx.asset.scan_status != "clean":
            raise ProblemError("invalid_state_transition", detail="This file is not available yet.")
        url, exp = presign_get(
            s.S3_BUCKET_CONTENT, ctx.asset.s3_key, filename=ctx.asset.s3_key.rsplit("/", 1)[-1]
        )
        return IdemResult({"url": url, "expires_at": to_rfc3339(exp), "watermarked": False})

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


router = APIRouter()
router.include_router(r)


# Core request 7: register this module's erasure provider with admin privacy (import time).
from app.modules.media import privacy as _privacy  # noqa: E402

_privacy.register()
