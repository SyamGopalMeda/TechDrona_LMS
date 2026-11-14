"""Student emails for admissions events (outbox handlers, sent after the business commit).

Registrants have no LMS account until enrolment, so these go through the notifications email
adapter directly (``send_email``; SMTP -> Mailpit on the demo VM). Delivery is best effort and
never fails the relay. Templates are plain text, same wording as the website confirmations.
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.outbox import OutboxMessage, register_handler
from app.modules.admissions import datastore as ads
from app.modules.admissions import rules as R
from app.modules.admissions.models import AdmissionRegistration

log = structlog.get_logger("app.admissions.notify")
SIGN = "\n\nTech Drona\ninfo@techdrona.com"


def _site_pay_link(reg: AdmissionRegistration) -> str:
    import os

    if reg.user_id is not None:
        # Registered inside the LMS (or already has an account): pay / resend from "My registrations".
        from app.modules.identity.links import web_base_url

        return f"{web_base_url()}/app/registrations"
    base = (os.environ.get("TD_WEBSITE_URL") or "https://35-244-50-26.sslip.io").rstrip("/")
    return f"{base}/pay-installment?course={reg.course_slug}&reg={reg.reg_no}"


def _message(event: str, reg: AdmissionRegistration, p: dict[str, Any]) -> tuple[str, str] | None:
    amount = R.rupees(int(p.get("amount_paise") or 0))
    head = f"Hello {reg.name},\n\n"
    ref = f"Registration number: {reg.reg_no}\nCourse: {reg.course_title}\n"
    if event == "registration_received":
        return (
            f"Registration received: {reg.course_title} ({reg.reg_no})",
            head
            + f"Thank you for registering. We received your payment proof of {amount}.\n\n"
            + ref
            + "Status: pending verification\n\nOur team checks every payment in PhonePe / our bank "
            "account (usually within "
            "1 working day). Course access is given to this email once the payment is verified." + SIGN,
        )
    if event == "claim_received":
        return (
            f"Payment proof received ({reg.reg_no})",
            head
            + f"We received your payment proof of {amount}. It is pending verification.\n\n"
            + ref
            + SIGN,
        )
    if event == "payment_verified":
        return (
            f"Payment verified ({reg.reg_no})",
            head
            + f"Your payment of {amount} has been verified.\n\n"
            + ref
            + f"Verified so far: {R.rupees(reg.verified_total_paise)} of {R.rupees(reg.fee_paise)}\n"
            f"Balance: {R.rupees(reg.balance_paise)}\n"
            + (f"\nPay the next instalment here: {_site_pay_link(reg)}\n" if reg.balance_paise > 0 else "")
            + SIGN,
        )
    if event == "claim_needs_info":
        return (
            f"Please correct your payment proof ({reg.reg_no})",
            head
            + "We couldn't confirm your payment yet. Our team asks:\n\n"
            + f"  {p.get('reason') or ''}\n\n"
            + ref
            + f"\nPlease submit a corrected proof here: {_site_pay_link(reg)}"
            + SIGN,
        )
    if event == "claim_rejected":
        return (
            f"Payment proof not accepted ({reg.reg_no})",
            head + "We could not match this payment to our bank account, so the proof was not accepted.\n\n"
            f"Reason: {p.get('reason') or ''}\n\n"
            + ref
            + "\nIf you think this is a mistake, reply to this email with your registration number."
            + SIGN,
        )
    if event == "enrolled":
        from app.modules.identity.links import web_link

        if p.get("login_details"):
            extra = (
                "\nYour Tech Drona LMS sign-in details (username and temporary password) are sent "
                "in a separate email.\n"
            )
        elif p.get("new_account") or p.get("password_link"):
            extra = (
                "\nWe created your Tech Drona learning account for this email. A separate email "
                "has a link to set "
                'your password (it expires soon; if it did, use "Forgot password" on the sign-in page).\n'
            )
        else:
            extra = "\nSign in with your existing Tech Drona account.\n"
        return (
            f"You're enrolled: {reg.course_title}",
            head
            + f"Your payment is verified and you are now enrolled in {reg.course_title}.\n\n"
            + ref
            + extra
            + f"Sign in: {web_link('login')}"
            + SIGN,
        )
    return None


async def on_admissions_event(session: AsyncSession, msg: OutboxMessage) -> None:
    from app.modules.notifications.service import send_email

    event = msg.event_type.split(".", 1)[1]
    try:
        rid = uuid.UUID(str(msg.payload.get("registration_id")))
    except ValueError:
        return
    reg = await ads.get(session, AdmissionRegistration, rid)
    if reg is None:
        return
    out = _message(event, reg, msg.payload)
    if out is None:
        return
    subject, text = out
    await send_email(reg.email, subject, text, template_key=f"admissions.{event}", category="transactional")


EVENTS = (
    "registration_received",
    "claim_received",
    "payment_verified",
    "claim_needs_info",
    "claim_rejected",
    "enrolled",
)


def register_outbox_handlers() -> None:
    for e in EVENTS:
        register_handler(f"admissions.{e}", on_admissions_event)
