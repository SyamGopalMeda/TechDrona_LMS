"""Entitlement endpoints (api-specification §19, ENT-01..10) and registration of the
``app.core.access`` checker."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from app.core.access import register_access_checker
from app.core.auth import require_active_principal, require_permission, require_step_up
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError
from app.core.idempotency import IdemResult, idempotent
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import utcnow
from app.modules.commerce import policy
from app.modules.commerce.models import Product
from app.modules.commerce.pricing import as_system
from app.modules.commerce.ratelimit import limit
from app.modules.entitlements import service as svc
from app.modules.entitlements.models import Entitlement, EntitlementEvent

register_access_checker(svc.EntitlementAccessChecker())
svc.register_outbox_handlers()

r = authenticated_router(tags=["entitlements"])
acct = authenticated_router(tags=["entitlements"], route_tag="account_status", idle="neutral")

REASON_CODE = {
    "free": "ENTITLED",
    "staff": "ENTITLED",
    "entitlement": "ENTITLED",
    "in_grace": "IN_GRACE",
    "no_entitlement": "NO_ENTITLEMENT",
    "expired": "EXPIRED",
    "suspended_payment": "SUSPENDED_PAYMENT",
    "restricted": "ACCOUNT_RESTRICTED",
    "minor_consent_pending": "MINOR_CONSENT_PENDING",
}
Kind = Literal[
    "course", "lesson", "resource", "test", "question_set", "coding_problem", "company_path", "product"
]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceIn(_In):
    kind: Kind
    id: uuid.UUID
    is_free: bool = False


class CheckIn(_In):
    resource: ResourceIn
    action: Literal["view", "attempt", "download", "enrol"] = "view"


class CheckBatchIn(_In):
    resources: list[ResourceIn] = Field(min_length=1, max_length=50)


class GrantTarget(_In):
    product_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    feature_key: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]{1,62}$")

    @model_validator(mode="after")
    def _one(self) -> GrantTarget:
        if sum(x is not None for x in (self.product_id, self.course_id, self.feature_key)) != 1:
            raise ValueError("exactly one of product_id, course_id, feature_key")
        return self


class GrantIn(_In):
    user_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    target: GrantTarget
    source_type: Literal["admin_grant", "trial"]
    starts_at: datetime | None = None
    ends_at: datetime
    reason: str = Field(min_length=10, max_length=1000)


class RevokeIn(_In):
    reason_code: Literal["admin", "fraud"]
    note: str = Field(min_length=3, max_length=1000)


async def _check_one(session: Any, principal: Principal, res: ResourceIn) -> dict[str, Any]:
    ev = await svc.evaluate(session, principal, res.kind, res.id, is_free=res.is_free)
    d = ev.decision
    out: dict[str, Any] = {
        "resource": {"kind": res.kind, "id": str(res.id)},
        "allowed": d.allowed,
        "reason_code": REASON_CODE.get(d.reason, "NO_ENTITLEMENT"),
        "via": ev.via,
        "cache_ttl_seconds": 60,
    }
    if ev.winner is not None:
        out.update(
            entitlement_id=str(ev.winner.id),
            source_type=ev.winner.source_type,
            status="grace" if d.reason == "in_grace" else "active",
            ends_at=d.expires_at.isoformat() if d.expires_at else None,
        )
    if d.reason == "restricted":
        out["status_url"] = "/app/account-status"
    elif not d.allowed:
        products, _, _ = await svc.covering_scope(session, res.kind, res.id)
        opts = []
        if products:
            from app.modules.commerce.admin import catalogue

            for p in await catalogue(session, include_drafts=False):
                if uuid.UUID(p["product_id"]) in products:
                    for pl in p["plans"]:
                        for pr in pl["prices"]:
                            opts.append(
                                {
                                    "sku": p["sku"],
                                    "price_id": pr["price_id"],
                                    "total_paise": pr["amount_paise"],
                                }
                            )
        out["upsell"] = {"purchase_options": opts[:5]}
    return out


@r.post("/entitlements/check")
async def check(
    body: CheckIn, session: PrincipalDbSession, principal: Principal = Depends(limit("ent01_check"))
) -> dict[str, Any]:
    """ENT-01: denials are 200 with ``allowed=false`` (content routes map them to 403)."""
    return await _check_one(session, principal, body.resource)


@r.post("/entitlements/check-batch")
async def check_batch(
    body: CheckBatchIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(limit("ent02_check_batch")),
) -> dict[str, Any]:
    return {"results": [await _check_one(session, principal, x) for x in body.resources]}


async def _titles(session: Any, ents: list[Entitlement]) -> dict[uuid.UUID, str]:
    ids = {e.product_id for e in ents if e.product_id}
    if not ids:
        return {}
    rows = await session.execute(select(Product.id, Product.name).where(Product.id.in_(ids)))
    return {i: n for i, n in rows.all()}


@acct.get("/me/entitlements")
async def my_entitlements(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    """ENT-03 (account_status: visible during a restriction; dates are unchanged)."""
    ents = list(
        (
            await session.execute(
                select(Entitlement)
                .where(Entitlement.user_id == principal.user_id)
                .order_by(Entitlement.created_at.desc())
            )
        ).scalars()
    )
    titles = await _titles(session, ents)
    now = utcnow()
    data = []
    for e in ents:
        j = svc.entitlement_json(e)
        j["title"] = titles.get(e.product_id) if e.product_id else (e.feature_key or "Course access")
        j["effective_status"] = svc.effective_state(e, now)
        data.append(j)
    gate = principal.restriction_level >= 3 or bool(svc.RESTRICTION_LOCKS & set(principal.restrictions))
    return {
        "data": data,
        "restriction_gate": {"active": gate},
        "page": {"next_cursor": None, "has_more": False},
    }


@r.get("/users/{user_id}/entitlements")
async def user_entitlements(
    user_id: uuid.UUID,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    """ENT-04: platform staff with ``entitlement.read`` see a user's entitlements."""
    from app.core.auth import PLATFORM_SCOPE, get_permission_checker

    checker = get_permission_checker()

    if checker is None:
        raise ProblemError("permission_denied", permission="entitlement.read")
    if not (
        principal.is_platform
        and await checker.has_permission(principal, "entitlement.read", PLATFORM_SCOPE, request)
    ):
        raise ProblemError("permission_denied", permission="entitlement.read")
    q = select(Entitlement).where(Entitlement.user_id == user_id)
    rows = [svc.entitlement_json(e) for e in (await session.execute(q)).scalars()]
    from app.core.audit import audit

    await audit(session, principal, "entitlement.read", "user", user_id)
    return {"data": rows, "page": {"next_cursor": None, "has_more": False}}


@acct.get("/entitlements/{entitlement_id}/events")
async def entitlement_events(
    entitlement_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    """ENT-05: own entitlement, or anyone the RLS lets see it (org staff / platform)."""
    e = (
        await session.execute(select(Entitlement).where(Entitlement.id == entitlement_id))
    ).scalar_one_or_none()
    if e is None or (e.user_id != principal.user_id and not principal.is_platform):
        raise ProblemError("not_found")
    rows = (
        await session.execute(
            select(EntitlementEvent)
            .where(EntitlementEvent.entitlement_id == e.id)
            .order_by(EntitlementEvent.occurred_at)
        )
    ).scalars()
    return {
        "data": [
            {
                "event_type": x.event_type,
                "from_status": x.from_status,
                "to_status": x.to_status,
                "delta": x.delta,
                "reason": x.reason,
                "actor_type": x.actor_type,
                "occurred_at": x.occurred_at.isoformat(),
            }
            for x in rows
        ],
        "page": {"next_cursor": None, "has_more": False},
    }


async def do_manual_grant(
    session: Any, actor_principal: Principal, payload: dict[str, Any], *, granted_by: uuid.UUID
) -> dict[str, Any]:
    """Execute an ENT-06 grant (directly or after the Dual approval)."""
    starts = datetime.fromisoformat(payload["starts_at"])
    ends = datetime.fromisoformat(payload["ends_at"])
    target = payload["target"]
    actor = svc.Actor.user(actor_principal)
    ids: list[str] = []
    for uid in payload["user_ids"]:
        e, _ = await svc.grant(
            session,
            actor,
            user_id=uuid.UUID(uid),
            source_type=payload["source_type"],
            product_id=uuid.UUID(target["product_id"]) if target.get("product_id") else None,
            course_id=uuid.UUID(target["course_id"]) if target.get("course_id") else None,
            feature_key=target.get("feature_key"),
            granted_by=granted_by if payload["source_type"] == "admin_grant" else None,
            reason=payload["reason"],
            starts_at=starts,
            ends_at=ends,
        )
        ids.append(str(e.id))
    return {"granted": len(ids), "entitlement_ids": ids}


@r.post("/entitlements/grants", status_code=201)
async def manual_grant(
    request: Request,
    body: GrantIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("entitlement.grant_manual")),
    _s: Principal = Depends(require_step_up("privileged")),
    _rl: Principal = Depends(limit("ent06_grant")),
) -> JSONResponse:
    """ENT-06: ≤ 500 users, ≤ 365 days, reason required; Dual above 90 days or 50 users."""
    # SoD-01 (security reviewer may not grant) no longer applies: the security and finance
    # duties were folded into Admin (REMOVAL-PLAN §8 D2). Large grants still need a second Admin.
    starts = body.starts_at or utcnow()
    if body.ends_at <= starts:
        raise ProblemError(
            "validation_failed",
            errors=[{"field": "ends_at", "code": "before_start", "message": "End must be after start"}],
        )
    days = (body.ends_at - starts) / timedelta(days=1)
    if days > policy.MANUAL_GRANT_MAX_DAYS:
        raise ProblemError(
            "validation_failed", errors=[{"field": "ends_at", "code": "too_long", "message": "Max 365 days"}]
        )
    payload = {
        "user_ids": [str(u) for u in dict.fromkeys(body.user_ids)],
        "target": body.target.model_dump(mode="json"),
        "source_type": body.source_type,
        "starts_at": starts.isoformat(),
        "ends_at": body.ends_at.isoformat(),
        "reason": body.reason,
    }

    async def op() -> IdemResult:
        if days > policy.MANUAL_GRANT_DUAL_DAYS or len(payload["user_ids"]) > policy.MANUAL_GRANT_DUAL_USERS:
            from app.modules.rbac.service import create_approval_request

            req = await create_approval_request(
                session,
                principal,
                action_type="entitlements.grant.bulk",
                target_type="entitlement",
                target_id=None,
                payload=payload,
                reason=body.reason,
                required_approver_role="super_admin",
            )
            return IdemResult({"status": "approval_pending", "approval_request_id": str(req.id)}, 202)
        async with as_system(session, "entitlements.manual_grant", principal):
            out = await do_manual_grant(session, principal, payload, granted_by=principal.user_id)
        return IdemResult(out, 201)

    return await idempotent(request, session, user_id=principal.user_id, operation=op)


@r.post("/entitlements/{entitlement_id}/revoke")
async def revoke_entitlement(
    entitlement_id: uuid.UUID,
    request: Request,
    body: RevokeIn,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("entitlement.revoke")),
    _s: Principal = Depends(require_step_up("privileged")),
) -> JSONResponse:
    async def op() -> IdemResult:
        e = await svc.lock(session, entitlement_id)
        if e is None:
            raise ProblemError("not_found")
        if e.status == "revoked":
            raise ProblemError("invalid_state_transition", current_state="revoked", allowed=[])
        await svc.revoke(session, e, svc.Actor.user(principal), reason_code=body.reason_code, note=body.note)
        return IdemResult(svc.entitlement_json(e))

    return await idempotent(request, session, user_id=principal.user_id, operation=op)


router = APIRouter()
for _r in (r, acct):
    router.include_router(_r)
