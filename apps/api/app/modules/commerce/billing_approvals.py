"""Dual control for GST register exports above 10,000 rows (role matrix §5 bulk personal-data
export): decided through the admin approvals queue (ADM-12/14/15) by a ``super_admin``
holding ``report.export.approve``; the admin module enforces approver ≠ requester and the
payload hash before ``_execute`` renders the file.

ADM-25: the other commerce Dual-control requests (refund over ₹25,000 or goodwill, coupon
activation, price create/decrease, bulk manual grant) are registered in
the same admin registry, so the shared approvals queue (``/admin/approvals``, used by the
finance UI) lists them for the eligible second approver and ADM-14/15 decide them. The
executor delegates to ``admin.execute_approval`` — the same code the legacy
``/finance/approval-requests/{id}/approve`` route runs — so both routes behave identically."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.errors import ProblemError
from app.core.principal import Principal
from app.modules.commerce.models import GstExport
from app.modules.rbac.catalogue import admin_roles

GST_EXPORT_ACTION = "commerce.gst_export"


async def _job(session: AsyncSession, req: Any) -> GstExport:
    job = (
        await session.execute(
            select(GstExport).where(GstExport.id == uuid.UUID(req.payload["gst_export_id"])).with_for_update()
        )
    ).scalar_one_or_none()
    if job is None:
        raise ProblemError("not_found")
    return job


async def _execute(session: AsyncSession, principal: Principal, req: Any) -> dict[str, Any]:
    from app.modules.commerce.billing import gst_export_json, render_gst_export

    job = await _job(session, req)
    if job.status != "awaiting_approval":
        raise ProblemError(
            "invalid_state_transition", current_state=job.status, allowed=["awaiting_approval"]
        )
    if job.requested_by == principal.user_id:
        raise ProblemError("sod_violation", rule="SoD-dual-control")
    job.approved_by = principal.user_id
    await render_gst_export(session, job)
    await audit(session, principal, "export.approved", "gst_export", job.id, after={"rows": job.row_count})
    return gst_export_json(job)


async def _on_reject(session: AsyncSession, principal: Principal, req: Any) -> None:
    job = await _job(session, req)
    if job.status == "awaiting_approval":
        job.status = "rejected"
        await session.flush()


# action type -> approver roles (role matrix §5; must match ``required_approver_role`` used
# when the request is created in ``commerce.router`` / ``entitlements.router``).
# Single company (REMOVAL-PLAN §8 D2): Finance admin was folded into Admin, so every commerce
# Dual-control request is decided by a second, different Admin (maker != checker).
COMMERCE_APPROVER_ROLES: dict[str, frozenset[str]] = {
    "commerce.refund": admin_roles(),
    "commerce.coupon.activate": admin_roles(),
    "commerce.price.create": admin_roles(),
    "entitlements.grant.bulk": admin_roles(),
}
APPROVER_PERMISSION = "approval.decide"


async def _execute_commerce(session: AsyncSession, principal: Principal, req: Any) -> dict[str, Any]:
    from app.modules.commerce import admin
    from app.modules.commerce.gateway import get_gateway
    from app.modules.commerce.pricing import as_system

    async with as_system(session, "commerce.approval_execute", principal):
        return await admin.execute_approval(
            session, get_gateway(), principal, req.action_type, req.payload, req.requested_by
        )


async def _reject_commerce(session: AsyncSession, principal: Principal, req: Any) -> None:
    """A rejected/cancelled refund approval rejects the refund (it stays ``requested``
    otherwise and blocks new requests on the order). Coupons stay ``paused``."""
    if req.action_type != "commerce.refund" or req.target_id is None:
        return
    from app.modules.commerce.models import Refund
    from app.modules.commerce.pricing import as_system

    async with as_system(session, "commerce.approval_reject", principal):
        rf = (
            await session.execute(select(Refund).where(Refund.id == req.target_id).with_for_update())
        ).scalar_one_or_none()
        if rf is not None and rf.status == "requested":
            rf.status = "rejected"
            await session.flush()


def register() -> None:
    from app.modules.admin import approvals as apr

    for action_type, roles in COMMERCE_APPROVER_ROLES.items():
        apr.register(
            apr.ApprovalHandler(
                action_type,
                APPROVER_PERMISSION,
                roles,
                _execute_commerce,
                on_reject=_reject_commerce,
            )
        )
    apr.register(
        apr.ApprovalHandler(
            GST_EXPORT_ACTION,
            "report.export.approve",
            admin_roles(),
            _execute,
            on_reject=_on_reject,
        )
    )
