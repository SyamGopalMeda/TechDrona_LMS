"""Subscription resume (COM-13), plan change (COM-14) and GST register exports (COM-37).

Plan change rules (FR-COM-006; documented in apps/api/README / implementation-status):

* Only an ``active`` subscription with a known current period and no scheduled cancellation;
  the target must be another active **recurring** price of a different plan with the same
  billing interval.
* **Upgrade** (higher price): effective immediately. Proration =
  ``ceil((new - old) x remaining_seconds / period_seconds)`` paise — "remaining days x daily
  price difference" computed on seconds so partial days are fair. It is not charged
  separately: it is added to the **next renewal debit** as a gateway add-on, so the student
  sees one debit. ``next_debit = new price + pending add-ons + proration`` must stay
  ≤ ₹15,000 (RBI e-mandate without AFA, ``recurring_amount_exceeds_mandate_limit``).
  The subscription entitlement moves to the new product at once (``plan_changed`` event).
* **Downgrade** (lower price): scheduled for the next renewal (``scheduled_*`` columns); no
  refund or credit for the current period; access to the current plan continues until then.
* ``preview: true`` computes the same figures without changing anything.
"""

from __future__ import annotations

import math
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.errors import ProblemError
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import utcnow
from app.modules.commerce import documents, policy
from app.modules.commerce.gateway import GatewayUnavailable, PaymentGateway
from app.modules.commerce.models import (
    GstExport,
    Invoice,
    Plan,
    Price,
    Subscription,
)
from app.modules.commerce.pricing import load_price
from app.modules.commerce.service import TERMINAL_SUB, sub_json
from app.modules.entitlements import service as ent
from app.modules.entitlements.models import Entitlement

log = structlog.get_logger("commerce.billing")


def _vf(field: str, code: str, message: str) -> ProblemError:
    return ProblemError("validation_failed", errors=[{"field": field, "code": code, "message": message}])


async def _compensate_addon(gw: PaymentGateway, sub: Subscription, addon_id: str, amount_paise: int) -> None:
    """COM-16: undo the prorated add-on when the plan update after it failed, so the provider
    does not bill an upgrade that our database rolled back. If the delete fails too, an error
    log (``subscription_addon_orphaned``) is the finance alert: the DB write is rolled back."""
    try:
        await gw.delete_subscription_addon(addon_id)
    except (GatewayUnavailable, ProblemError) as e:
        log.error(
            "subscription_addon_orphaned",
            subscription_id=str(sub.id),
            addon_id=addon_id,
            amount_paise=amount_paise,
            error=type(e).__name__,
        )


# --------------------------------------------------------------------------- COM-13


async def resume_subscription(
    session: AsyncSession, principal: Principal, gw: PaymentGateway, sub: Subscription
) -> dict[str, Any]:
    now = utcnow()
    if sub.status in TERMINAL_SUB or not sub.cancel_at_period_end:
        raise ProblemError(
            "invalid_state_transition",
            current_state=sub.status if sub.status in TERMINAL_SUB else "not_scheduled_for_cancellation",
            allowed=["cancel_at_period_end"],
        )
    if sub.current_period_end is not None and sub.current_period_end <= now:
        raise ProblemError("invalid_state_transition", current_state="period_ended", allowed=[])
    try:
        await gw.undo_scheduled_cancel(sub.gateway_subscription_id)
    except GatewayUnavailable as e:
        raise ProblemError("service_unavailable") from e
    sub.cancel_at_period_end = False
    sub.cancel_reason = None
    await session.flush()
    await audit(
        session,
        principal,
        "subscription.resume",
        "subscription",
        sub.id,
        subject_user_id=sub.user_id,
        after={"cancel_at_period_end": False},
    )
    await emit_event(
        session,
        "subscription.resumed",
        {"subscription_id": str(sub.id)},
        aggregate_type="subscription",
        aggregate_id=sub.id,
    )
    return sub_json(sub)


# --------------------------------------------------------------------------- COM-14


async def change_plan(
    session: AsyncSession,
    principal: Principal,
    gw: PaymentGateway,
    sub: Subscription,
    price_id: uuid.UUID,
    *,
    preview: bool,
) -> dict[str, Any]:
    now = utcnow()
    if sub.status != "active" or sub.cancel_at_period_end:
        raise ProblemError(
            "invalid_state_transition",
            current_state="cancel_scheduled" if sub.cancel_at_period_end else sub.status,
            allowed=["active"],
        )
    start, end = sub.current_period_start, sub.current_period_end
    if start is None or end is None or end <= now or end <= start:
        raise ProblemError("invalid_state_transition", current_state="no_current_period", allowed=["active"])
    try:
        price, plan, product = await load_price(session, price_id)
    except ProblemError as e:
        raise _vf("price_id", "unknown_price", "This plan is not available.") from e
    cur_price = (await session.execute(select(Price).where(Price.id == sub.price_id))).scalar_one()
    cur_plan = (await session.execute(select(Plan).where(Plan.id == sub.plan_id))).scalar_one()
    if not price.is_recurring or plan.billing_type != "recurring":
        raise _vf("price_id", "not_recurring", "Choose a subscription plan.")
    if plan.id == cur_plan.id:
        raise _vf("price_id", "same_plan", "You are already on this plan.")
    if (plan.interval_unit, plan.interval_count) != (cur_plan.interval_unit, cur_plan.interval_count):
        raise _vf("price_id", "interval_mismatch", "Plan changes keep the same billing interval.")
    if price.amount_paise == cur_price.amount_paise:
        raise _vf("price_id", "same_price", "The new plan costs the same; nothing to change.")
    if price.amount_paise > policy.MANDATE_MAX_PAISE:
        raise ProblemError("recurring_amount_exceeds_mandate_limit", max_paise=policy.MANDATE_MAX_PAISE)
    gplan = (plan.gateway_plan_ids or {}).get(gw.name)
    if not gplan:
        raise ProblemError("service_unavailable", detail="This plan is not yet available for subscription.")

    period_s = (end - start).total_seconds()
    remaining_s = max(0.0, (end - now).total_seconds())
    upgrade = price.amount_paise > cur_price.amount_paise
    proration = 0
    if upgrade:
        proration = math.ceil(
            Decimal(price.amount_paise - cur_price.amount_paise) * Decimal(remaining_s) / Decimal(period_s)
        )
    next_debit = price.amount_paise + sub.pending_addon_paise + proration if upgrade else price.amount_paise
    if next_debit > policy.MANDATE_MAX_PAISE:
        raise ProblemError("recurring_amount_exceeds_mandate_limit", max_paise=policy.MANDATE_MAX_PAISE)
    out: dict[str, Any] = {
        "subscription_id": str(sub.id),
        "direction": "upgrade" if upgrade else "downgrade",
        "effective": "now" if upgrade else "renewal",
        "effective_at": (now if upgrade else end).isoformat(),
        "from_price_id": str(cur_price.id),
        "to_price_id": str(price.id),
        "from_amount_paise": cur_price.amount_paise,
        "to_amount_paise": price.amount_paise,
        "remaining_days": math.ceil(remaining_s / 86_400),
        "period_days": round(period_s / 86_400),
        "proration_paise": proration,
        "next_debit_paise": next_debit,
        "preview": preview,
    }
    if preview:
        return {**out, "subscription": sub_json(sub)}

    # COM-16: the add-on goes first. If the plan update then fails, the add-on is deleted again
    # so the provider is left as it was (the DB transaction rolls back on the raised error).
    addon_id: str | None = None
    try:
        if proration > 0:
            addon_id = await gw.add_subscription_addon(
                sub.gateway_subscription_id, proration, f"Prorated upgrade to {product.name}"
            )
        await gw.update_subscription_plan(sub.gateway_subscription_id, str(gplan), at_cycle_end=not upgrade)
    except (GatewayUnavailable, ProblemError) as e:
        if addon_id:
            await _compensate_addon(gw, sub, addon_id, proration)
        if isinstance(e, ProblemError):
            raise
        raise ProblemError("service_unavailable") from e
    before = {"price_id": str(sub.price_id), "plan_id": str(sub.plan_id)}
    actor = ent.Actor.user(principal)
    if upgrade:
        sub.plan_id, sub.price_id = plan.id, price.id
        sub.scheduled_plan_id = sub.scheduled_price_id = sub.scheduled_change_at = None
        sub.pending_addon_paise += proration
        # COM-16: ``mandate_max_amount_paise`` records what the customer authorised; it is no
        # longer raised locally (a DB-only raise does not change the bank mandate).
        await session.flush()
        sub_ent = (
            await session.execute(
                select(Entitlement).where(Entitlement.subscription_id == sub.id).with_for_update()
            )
        ).scalar_one_or_none()
        if sub_ent is not None:
            await ent.change_product(
                session, sub_ent, product.id, actor, reason="subscription_upgrade", source_ref=sub.id
            )
    else:
        sub.scheduled_plan_id, sub.scheduled_price_id, sub.scheduled_change_at = plan.id, price.id, end
        await session.flush()
    await audit(
        session,
        principal,
        "subscription.plan_change",
        "subscription",
        sub.id,
        subject_user_id=sub.user_id,
        before=before,
        after={
            "to_price_id": str(price.id),
            "direction": out["direction"],
            "proration_paise": proration,
            "next_debit_paise": next_debit,
        },
    )
    await emit_event(
        session,
        "subscription.plan_changed",
        {"subscription_id": str(sub.id), "direction": out["direction"], "to_price_id": str(price.id)},
        aggregate_type="subscription",
        aggregate_id=sub.id,
    )
    return {**out, "subscription": sub_json(sub)}


# --------------------------------------------------------------------------- COM-37


def gst_export_json(x: GstExport) -> dict[str, Any]:
    return {
        "gst_export_id": str(x.id),
        "period_from": x.period_from.isoformat(),
        "period_to": x.period_to.isoformat(),
        "status": "expired"
        if x.status == "ready" and x.download_expires_at and x.download_expires_at <= utcnow()
        else x.status,
        "row_count": x.row_count,
        "approval_request_id": str(x.approval_request_id) if x.approval_request_id else None,
        "requested_by": str(x.requested_by),
        "created_at": x.created_at.isoformat() if x.created_at else None,
        "completed_at": x.completed_at.isoformat() if x.completed_at else None,
        "download_expires_at": x.download_expires_at.isoformat() if x.download_expires_at else None,
    }


async def count_gst_rows(session: AsyncSession, period_from: date, period_to: date) -> int:
    return int(
        (
            await session.execute(
                select(func.count())
                .select_from(Invoice)
                .where(Invoice.issue_date >= period_from, Invoice.issue_date <= period_to)
            )
        ).scalar_one()
    )


async def render_gst_export(session: AsyncSession, job: GstExport) -> GstExport:
    rows = await documents.gst_rows(session, job.period_from, job.period_to)
    now = utcnow()
    watermark = (
        f"Tech Drona GST register {job.period_from.isoformat()}..{job.period_to.isoformat()}; "
        f"export {job.id}; requested by {job.requested_by}; generated {now.isoformat()}; CONFIDENTIAL"
    )
    data = documents.gst_csv(rows, watermark=watermark)
    key = f"gst-exports/{job.period_from:%Y/%m}/{job.id}.csv"
    await documents.get_document_store().put(documents.bucket(), key, data, "text/csv")
    job.s3_key = key
    job.row_count = len(rows)
    job.status = "ready"
    job.completed_at = now
    job.download_expires_at = now + timedelta(hours=policy.GST_EXPORT_DOWNLOAD_HOURS)
    await session.flush()
    return job


def gst_filename(job: GstExport) -> str:
    return f"gst-register-{job.period_from.isoformat()}-to-{job.period_to.isoformat()}.csv"
