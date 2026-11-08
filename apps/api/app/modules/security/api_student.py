"""Student / account-holder endpoints (route tag ``account_status``): SEC-01, SEC-02, SEC-46,
UNB-01..09 (+ form meta, by-reference lookup), AUTH-21/22 unblock re-verification."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from fastapi import Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.core.auth import require_active_principal
from app.core.db import PrincipalDbSession, system_context
from app.core.errors import ProblemError
from app.core.idempotency import IdemResult, idempotent
from app.core.principal import Principal
from app.core.request_context import get_request_id
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339
from app.modules.admin.policy import get_value
from app.modules.identity import clock
from app.modules.identity.links import web_link, web_path
from app.modules.identity.models import User
from app.modules.security import engine
from app.modules.security import restrictions as rx
from app.modules.security import unblock as unb
from app.modules.security.catalogue import RULES_BY_KEY
from app.modules.security.models import (
    AccountRestriction,
    RiskEvaluation,
    SecurityCase,
    SecurityNotice,
    UnblockRequest,
)
from app.modules.sessions import service as ss

r = authenticated_router(tags=["security"], route_tag="account_status", idle="extends")
NEUTRAL = {"x-td-idle": "neutral"}
_KEY_TEXT = {rd.explanation_key: rd.student_text for rd in RULES_BY_KEY.values()}
_CATEGORY = {"C": "concurrency", "D": "device", "N": "network"}


class UnblockIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_ref: str = Field(min_length=10, max_length=20)
    submit: bool = False
    what_happened: list[str] = Field(default_factory=list, max_length=7)
    explanation: str | None = Field(default=None, max_length=4000)
    recognised_user_device_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    none_recognised: bool = False
    lab_location_text: str | None = Field(default=None, max_length=400)
    attachment_ids: list[str] = Field(default_factory=list, max_length=2)
    preferred_contact: Literal["in_app", "email", "sms"] | None = None
    declaration: bool = False
    guardian_assisted: bool = False


class DraftPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    what_happened: list[str] | None = Field(default=None, max_length=7)
    explanation: str | None = Field(default=None, max_length=4000)
    recognised_user_device_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    lab_location_text: str | None = Field(default=None, max_length=400)
    preferred_contact: Literal["in_app", "email", "sms"] | None = None
    declaration: bool | None = None


class SubmitIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    none_recognised: bool = False


class TextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    explanation: str = Field(max_length=4000)
    attachment_ids: list[str] = Field(default_factory=list, max_length=2)


class DisownIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool


class ReverifyStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: Literal["sms", "email"]


class MfaIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: Literal["totp"] = "totp"
    code: str = Field(min_length=6, max_length=10)


class DeviceKeep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_device_id: uuid.UUID
    keep: bool


class ReverifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    otp_code: str = Field(min_length=4, max_length=10)
    mfa: MfaIn | None = None
    new_password: str | None = Field(default=None, max_length=256)
    devices: list[DeviceKeep] = Field(default_factory=list, max_length=50)


# --------------------------------------------------------------------------- SEC-01 / 02 / 46


@r.get("/me/security/status", openapi_extra=NEUTRAL)
async def my_status(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    async with system_context(session, "security.status"):
        uid = principal.user_id
        user = await session.get(User, uid)
        active = await rx.active_restrictions(session, uid)
        sharing = next((x for x in active if x.family == "sharing"), None)
        takeover = next((x for x in active if x.family == "takeover"), None)
        reasons: list[dict[str, str]] = []
        categories: list[str] = []
        case_ref = None
        if sharing is not None and not (user and user.is_minor):
            if sharing.evaluation_id:
                ev = (
                    await session.execute(
                        select(RiskEvaluation).where(RiskEvaluation.id == sharing.evaluation_id)
                    )
                ).scalar_one_or_none()
                if ev is not None:
                    reasons = [
                        {"explanation_key": k, "text": _KEY_TEXT.get(k, "")} for k in ev.explanation_keys
                    ]
                    categories = [
                        _CATEGORY[c] for c in (ev.gates or {}).get("categories", []) if c in _CATEGORY
                    ]
            if sharing.case_id:
                case_ref = (
                    await session.execute(
                        select(SecurityCase.case_ref).where(SecurityCase.id == sharing.case_id)
                    )
                ).scalar_one_or_none()
        ur = None
        if case_ref:
            ur = (
                await session.execute(
                    select(UnblockRequest)
                    .where(UnblockRequest.user_id == uid, UnblockRequest.state.notin_(("closed",)))
                    .order_by(UnblockRequest.created_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        history = (
            (
                await session.execute(
                    select(AccountRestriction)
                    .where(AccountRestriction.user_id == uid, AccountRestriction.ended_at.is_not(None))
                    .order_by(AccountRestriction.ended_at.desc())
                    .limit(10)
                )
            )
            .scalars()
            .all()
        )
        actions = ["manage_devices", "contact_support"]
        if sharing is not None and sharing.level >= 3:
            actions.insert(0, "request_review")
            if sharing.lift_pending_at or (
                sharing.level == 3 and sharing.ends_at and sharing.ends_at <= clock.now()
            ):
                # E2E-01: only advertise OTP re-verification when it can succeed; otherwise a
                # senior reviewer verifies manually (UNB §6.3a).
                actions.insert(
                    0,
                    "reverify"
                    if unb.has_eligible_contact(user, sharing.starts_at)
                    else "await_manual_verification",
                )
        state = await rx.restriction_state(session, uid)
        policy = {
            "max_trusted_devices": await get_value(session, "devices.student.max_trusted", user_id=uid),
            "max_concurrent_sessions": await get_value(
                session, "sessions.student.max_concurrent", user_id=uid
            ),
            "max_concurrent_streams": await get_value(
                session, "playback.max_concurrent_streams", user_id=uid
            ),
            "max_replacements_per_30d": await get_value(
                session, "devices.student.max_replacements_per_30d", user_id=uid
            ),
        }
    return {
        "level": sharing.level if sharing else 0,
        "family": "sharing" if sharing else None,
        "scope": sharing.scope if sharing else None,
        "starts_at": to_rfc3339(sharing.starts_at) if sharing else None,
        "until": to_rfc3339(sharing.ends_at) if sharing and sharing.ends_at else None,
        "deferred_until": to_rfc3339(sharing.deferred_until) if sharing and sharing.deferred_until else None,
        "lift_pending": bool(sharing and sharing.lift_pending_at),
        "case_ref": case_ref,
        "reasons": reasons,
        "categories": categories,
        "available_actions": actions,
        "takeover": {
            "protect_locked": state.takeover_lock,
            "step_up_required": state.step_up_required,
            "since": to_rfc3339(takeover.starts_at) if takeover else None,
        },
        "unblock_request": {"reference": ur.reference if ur else None, "state": ur.state if ur else None},
        "policy": policy,
        "history": [
            {
                "level": h.level,
                "starts_at": to_rfc3339(h.starts_at),
                "ended_at": to_rfc3339(h.ended_at) if h.ended_at else None,
                "end_reason": h.end_reason,
            }
            for h in history
        ],
    }


@r.get("/me/security/cases/{case_ref}", openapi_extra=NEUTRAL)
async def my_case(
    case_ref: str, session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    from app.modules.security.cases import student_projection

    async with system_context(session, "security.status"):
        case = await unb.own_case_by_ref(session, principal.user_id, case_ref)
        return await student_projection(session, case)


@r.post("/me/security/events/{event_ref}/disown")
async def disown(
    event_ref: str,
    body: DisownIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async with system_context(session, "security.disown"):
        n = (
            await session.execute(
                select(SecurityNotice).where(SecurityNotice.event_ref == event_ref).with_for_update()
            )
        ).scalar_one_or_none()
        if n is None or n.user_id != principal.user_id or not body.confirm:
            raise ProblemError("not_found")
        if n.disowned_at is not None:
            raise ProblemError("invalid_state_transition", current_state="disowned", allowed=[])
        user = await session.get(User, principal.user_id)
        assert user is not None
        await engine.disown(session, user, n)
        await session.flush()
    resp = JSONResponse(
        {
            "result": "protected",
            "must_change_password": True,
            "recovery_url": web_path("forgot_password"),
            "recovery_link": web_link("forgot_password"),
        }
    )
    resp.headers.append("Set-Cookie", ss.cookie_header(ss.SESSION_COOKIE, "", 0))
    return resp


# --------------------------------------------------------------------------- UNB-01..09


async def _own_request(session: Any, principal: Principal, request_id: uuid.UUID) -> UnblockRequest:
    ur = (
        await session.execute(select(UnblockRequest).where(UnblockRequest.id == request_id).with_for_update())
    ).scalar_one_or_none()
    if ur is None or ur.user_id != principal.user_id:
        raise ProblemError("not_found")
    return ur


@r.get("/security/unblock-requests/form", openapi_extra=NEUTRAL)
async def unblock_form(
    session: PrincipalDbSession,
    case_ref: str | None = None,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    async with system_context(session, "security.unblock"):
        if case_ref:
            await unb.own_case_by_ref(session, principal.user_id, case_ref)
        return await unb.form(session, principal, case_ref)


@r.post("/security/unblock-requests", status_code=201)
async def create_unblock(
    body: UnblockIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    key = request.headers.get("idempotency-key")

    async def op() -> IdemResult:
        async with system_context(session, "security.unblock"):
            out = await unb.create_request(session, principal, body.model_dump(mode="json"), key)
            await session.flush()
        return IdemResult(status=201, body=out)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


@r.patch("/security/unblock-requests/{request_id}")
async def patch_unblock(
    request_id: uuid.UUID,
    body: DraftPatch,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    async with system_context(session, "security.unblock"):
        ur = await _own_request(session, principal, request_id)
        out = await unb.update_draft(session, principal, ur, body.model_dump(exclude_none=True, mode="json"))
        await session.flush()
    return out


class AttachmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=200)
    content_type: str = Field(max_length=100)
    size_bytes: int = Field(ge=1)


@r.post("/security/unblock-requests/{request_id}/attachments", status_code=201)
async def attach(
    request_id: uuid.UUID,
    body: AttachmentIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def op() -> IdemResult:
        async with system_context(session, "security.unblock"):
            ur = await _own_request(session, principal, request_id)
            out = await unb.new_attachment(
                session,
                principal,
                ur,
                filename=body.filename,
                content_type=body.content_type,
                size_bytes=body.size_bytes,
            )
            await session.flush()
        return IdemResult(status=201, body=out)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@r.post("/security/unblock-requests/{request_id}/submit")
async def submit_unblock(
    request_id: uuid.UUID,
    body: SubmitIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def op() -> IdemResult:
        async with system_context(session, "security.unblock"):
            ur = await _own_request(session, principal, request_id)
            out = await unb.submit(session, principal, ur, none_recognised=body.none_recognised)
            await session.flush()
        return IdemResult(body=out)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


@r.get("/security/unblock-requests", openapi_extra=NEUTRAL)
async def list_unblock(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    async with system_context(session, "security.unblock"):
        rows = (
            await session.execute(
                select(UnblockRequest, SecurityCase.case_ref)
                .join(SecurityCase, SecurityCase.id == UnblockRequest.case_id)
                .where(UnblockRequest.user_id == principal.user_id)
                .order_by(UnblockRequest.created_at.desc())
            )
        ).all()
        return {
            "data": [unb.request_out(u, case_ref=ref) for u, ref in rows],
            "page": {"next_cursor": None, "has_more": False, "limit": 100},
        }


@r.get("/security/unblock-requests/by-reference/{reference}", openapi_extra=NEUTRAL)
async def unblock_by_reference(
    reference: str, session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    """Status by ``APL-`` reference: the reference is not an authenticator — only the owner's
    own requests resolve; anything else (malformed, unknown, someone else's) is the same 404."""
    async with system_context(session, "security.unblock"):
        ur = (
            await session.execute(select(UnblockRequest).where(UnblockRequest.reference == reference.upper()))
        ).scalar_one_or_none()
        if ur is None or ur.user_id != principal.user_id:
            raise ProblemError("not_found")
        return await unb.student_view(session, ur)


@r.get("/security/unblock-requests/{request_id}", openapi_extra=NEUTRAL)
async def get_unblock(
    request_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    async with system_context(session, "security.unblock"):
        ur = await _own_request(session, principal, request_id)
        return await unb.student_view(session, ur)


@r.post("/security/unblock-requests/{request_id}/responses")
async def respond_unblock(
    request_id: uuid.UUID,
    body: TextIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def op() -> IdemResult:
        async with system_context(session, "security.unblock"):
            ur = await _own_request(session, principal, request_id)
            out = await unb.respond(session, principal, ur, body.model_dump())
            await session.flush()
        return IdemResult(body=out)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


@r.post("/security/unblock-requests/{request_id}/withdraw")
async def withdraw_unblock(
    request_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    async with system_context(session, "security.unblock"):
        ur = await _own_request(session, principal, request_id)
        out = await unb.withdraw(session, principal, ur)
        await session.flush()
    return out


@r.post("/security/unblock-requests/{request_id}/appeal")
async def appeal_unblock(
    request_id: uuid.UUID,
    body: TextIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def op() -> IdemResult:
        async with system_context(session, "security.unblock"):
            ur = await _own_request(session, principal, request_id)
            out = await unb.appeal(session, principal, ur, body.model_dump())
            await session.flush()
        return IdemResult(body=out)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


# --------------------------------------------------------------------------- AUTH-21 / AUTH-22


@r.post("/auth/reverify/start")
async def reverify_start(
    body: ReverifyStartIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    async with system_context(session, "security.reverify"):
        out = await unb.reverify_start(session, principal, body.channel, ss.client_info(request).ip)
        await session.flush()
    return out


@r.post("/auth/reverify/complete")
async def reverify_complete(
    body: ReverifyIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> JSONResponse:
    async def op() -> IdemResult:
        async with system_context(session, "security.reverify"):
            deferred: unb._Deferred | None = None
            try:
                out = await unb.reverify_complete(session, principal, body.model_dump(mode="json"))
            except unb._Deferred as d:  # keep the OTP attempt counter: answer without rolling back
                deferred = d
            await session.flush()
        if deferred is not None:
            return IdemResult(status=deferred.problem.status, body=deferred.problem.to_body(get_request_id()))
        return IdemResult(body=out, headers={"Set-Cookie": ss.cookie_header(ss.SESSION_COOKIE, "", 0)})

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)
