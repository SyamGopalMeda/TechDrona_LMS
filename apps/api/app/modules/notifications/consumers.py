"""Commerce event consumers (COM-17): invoice email, cancellation confirmation email, renewal
reminder, and finance alert routing.

Handlers run inside the outbox relay transaction under ``system_context``. Each one is
idempotent on the event: rows are written through ``notify`` with a ``dedupe_key`` derived
from the outbox message id (or subscription period), so a relay retry never sends twice.
Email-only rows carry ``channels=["email"]`` and stay out of the in-app inbox (which lists
``in_app`` rows only).

Data minimisation: amounts, order/invoice numbers and dates only — never card or bank data.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox import OutboxMessage, register_handler
from app.modules.identity.links import web_link
from app.modules.notifications.service import notify

log = structlog.get_logger("app.notifications.consumers")

FINANCE_ALERT_EVENTS = ("commerce.refund_failed", "commerce.refund_submit_stuck", "commerce.webhook_failed")
RENEWAL_REMINDER_DAYS = 7


def _rupees(paise: int | None) -> str:
    return f"₹{(paise or 0) / 100:,.2f}"


async def _user_email(session: AsyncSession, user_id: uuid.UUID | None) -> tuple[str | None, bool]:
    from app.modules.identity import public as identity

    if user_id is None:
        return None, False
    u = await identity.get_user(session, user_id)
    if u is None or u.status in ("deleted", "deactivated"):
        return None, False
    return u.email, u.is_minor


def _uuid(v: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(v)) if v else None
    except ValueError:
        return None


# --------------------------------------------------------------------------- invoice email


async def on_invoice_issued(session: AsyncSession, msg: OutboxMessage) -> None:
    """``invoice.issued`` → email the buyer a link to the order page (PRD "Invoice emailed").
    Institution (contract) invoices have no individual buyer and are skipped."""
    from app.modules.commerce import public as commerce

    inv_id = _uuid(msg.payload.get("invoice_id"))
    inv = await commerce.get_invoice(session, inv_id) if inv_id else None
    if inv is None:
        log.warning("invoice_issued_unknown_invoice", event_id=str(msg.id))
        return
    if inv.user_id is None or inv.invoice_type != "tax_invoice":
        return  # institution invoices go to the org contact; credit notes have their own flow
    order = await commerce.get_order(session, inv.order_id)
    email, is_minor = await _user_email(session, inv.user_id)
    link = web_link("order", order_id=str(inv.order_id))
    text = (
        f"Thank you for your purchase. Invoice {inv.invoice_number} for "
        f"{_rupees(inv.total_paise)} (incl. GST) is ready.\n\n"
        f"Order: {order.order_number if order else inv.order_id}\n"
        f"View and download the invoice: {link}\n"
    )
    await notify(
        session,
        inv.user_id,
        "commerce.invoice_issued",
        category="transactional",
        data={"invoice_id": str(inv.id), "order_id": str(inv.order_id), "invoice_number": inv.invoice_number},
        channels=("in_app", "email") if email else ("in_app",),
        dedupe_key=f"invoice:{inv.id}",
        is_minor=is_minor,
        email_to=email,
        email_subject=f"Your Tech Drona invoice {inv.invoice_number}",
        email_text=text,
    )


# --------------------------------------------------------------------------- cancellation


async def on_subscription_cancel_requested(session: AsyncSession, msg: OutboxMessage) -> None:
    """Email confirmation of a cancellation (FR-COM-005). The in-app confirmation is written
    by commerce in the request transaction; this row is email-only."""
    from app.modules.commerce import public as commerce

    sub_id = _uuid(msg.payload.get("subscription_id"))
    sub = await commerce.get_subscription(session, sub_id) if sub_id else None
    if sub is None:
        return
    email, is_minor = await _user_email(session, sub.user_id)
    if not email:
        return
    until = sub.current_period_end
    when = (
        f"You keep access until {until:%d %b %Y}. You will not be charged again."
        if sub.cancel_at_period_end and until
        else "Your subscription has ended and you will not be charged again."
    )
    await notify(
        session,
        sub.user_id,
        "subscription.cancel_confirmation",
        category="transactional",
        data={"subscription_id": str(sub.id)},
        channels=("email",),
        dedupe_key=f"outbox:{msg.id}",
        is_minor=is_minor,
        email_to=email,
        email_subject="Your Tech Drona subscription is cancelled",
        email_text=f"We've cancelled your subscription as requested. {when}\n\n"
        f"Manage billing: {web_link('billing')}\n",
    )


# --------------------------------------------------------------------------- renewal reminder


async def send_renewal_reminders(session: AsyncSession, now: datetime) -> int:
    """FR-COM-005: remind 7 days before an annual (12-month or longer) renewal. One reminder per
    subscription period (``dedupe_key`` = subscription + period end)."""
    from app.modules.commerce import public as commerce

    horizon = now + timedelta(days=RENEWAL_REMINDER_DAYS)
    rows = await commerce.renewing_subscriptions(session, now, horizon)
    sent = 0
    for sub, plan in rows:
        unit, count = (plan.interval_unit or "").lower(), plan.interval_count or 1
        annual = unit in ("year", "yearly", "annual") or (unit in ("month", "monthly") and count >= 12)
        if not annual:
            continue
        email, is_minor = await _user_email(session, sub.user_id)
        end = sub.current_period_end
        assert end is not None
        nid = await notify(
            session,
            sub.user_id,
            "subscription.renewal_reminder",
            category="transactional",
            data={"subscription_id": str(sub.id), "renews_at": end.isoformat()},
            channels=("in_app", "email") if email else ("in_app",),
            dedupe_key=f"renewal:{sub.id}:{end.date().isoformat()}",
            is_minor=is_minor,
            email_to=email,
            email_subject="Your Tech Drona plan renews in 7 days",
            email_text=f"Your annual plan renews on {end:%d %b %Y}. To stop the renewal, cancel any "
            f"time before then: {web_link('billing')}\n",
        )
        sent += nid is not None
    return sent


# --------------------------------------------------------------------------- finance alerts


async def finance_admin_ids(session: AsyncSession, now: datetime) -> list[uuid.UUID]:
    """Every live Admin (single company, D2: finance duties are folded into ``super_admin``)."""
    from app.modules.rbac import public as rbac
    from app.modules.rbac.catalogue import admin_roles

    # unrevoked, unexpired grants of an admin role at any scope (DISTINCT user ids)
    grants = await rbac.live_grants(session, role_keys=sorted(admin_roles()), now=now)
    return list(dict.fromkeys(g.user_id for g, _k in grants))


_ALERT_FIELDS = (
    "refund_id",
    "order_id",
    "amount_paise",
    "attempts",
    "gateway",
    "event_type",
    "webhook_event_id",
)
_ALERT_TEXT = {
    "commerce.refund_failed": "A provider refund failed; access was reinstated. Review the refund.",
    "commerce.refund_submit_stuck": "A refund could not be submitted to the provider after retries.",
    "commerce.webhook_failed": "A payment webhook could not be processed and was given up.",
}


async def on_finance_alert(session: AsyncSession, msg: OutboxMessage) -> None:
    """Route commerce alert events to every active Admin's inbox (in-app, high)."""
    from app.core.time import utcnow

    data = {k: msg.payload.get(k) for k in _ALERT_FIELDS if msg.payload.get(k) is not None}
    data["summary"] = _ALERT_TEXT.get(msg.event_type, msg.event_type)
    for uid in await finance_admin_ids(session, utcnow()):
        await notify(
            session,
            uid,
            msg.event_type,
            category="system",
            data=data,
            channels=("in_app",),
            priority="high",
            dedupe_key=f"outbox:{msg.id}",
        )


def register_commerce_consumers() -> None:
    register_handler("invoice.issued", on_invoice_issued)
    register_handler("subscription.cancel_requested", on_subscription_cancel_requested)
    for ev in FINANCE_ALERT_EVENTS:
        register_handler(ev, on_finance_alert)
