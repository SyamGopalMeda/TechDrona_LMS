"""Verify & Add to Batch, and the LMS login email (owner requirement 2026-11-12).

* ``verify_and_enrol`` â€” staff verified the payment in the bank / UPI app: in ONE transaction the
  claim is verified (``service.verify_claim``, idempotent), the access minimum is checked, the
  student's LMS account is found or created (random ``td`` + 6-digit username, random temporary
  password, ``must_change_password`` per the staff choice), and ``service.enrol`` gives the
  entitlement / enrolment / batch membership and marks the registration ``enrolled``. Then the
  login email is sent (optional).
* ``send_login_email`` â€” (re)send the login email; by default with a NEW temporary password
  (we never store a plaintext password), which also signs the student out everywhere.

The temporary password is returned to staff only in the response that created it, and is never
logged, audited or written to the admissions trail. When email isn't integrated (Mailpit / memory
sink) the response says ``sent=false, reason="email_not_connected"`` instead of pretending.
"""

from __future__ import annotations

import secrets
import uuid
from dataclasses import dataclass
from html import escape
from typing import Any

import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.db import as_system
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.time import utcnow
from app.modules.admissions import datastore as ads
from app.modules.admissions import rules as R
from app.modules.admissions.models import AdmissionFeePlan, AdmissionPaymentClaim, AdmissionRegistration
from app.modules.admissions.service import (
    Actor,
    iso,
    lock_registration,
    registration_out,
    trail,
    verify_claim,
    vf,
)
from app.modules.identity import public as identity_public
from app.modules.orgs import public as orgs_public

log = structlog.get_logger("app.admissions.onboarding")

# no 0/O, 1/l/I: read aloud or typed from a phone without mistakes
PASSWORD_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"  # noqa: S105
PASSWORD_LENGTH = 10
USERNAME_ATTEMPTS = 20


def new_temp_password() -> str:
    """10 characters of letters + digits (at least one of each kind), no ambiguous characters."""
    while True:
        pw = "".join(secrets.choice(PASSWORD_ALPHABET) for _ in range(PASSWORD_LENGTH))
        if any(c.isdigit() for c in pw) and any(c.islower() for c in pw) and any(c.isupper() for c in pw):
            return pw


def new_username() -> str:
    return "td" + "".join(secrets.choice("0123456789") for _ in range(6))


def login_url() -> str:
    from app.modules.identity.links import web_link

    return web_link("login")


# --------------------------------------------------------------------------- account


@dataclass
class Account:
    user: Any
    created: bool
    temporary_password: str | None


async def _free_username(session: AsyncSession) -> str:
    for _ in range(USERNAME_ATTEMPTS):
        u = new_username()
        if not await identity_public.username_taken(session, u):
            return u
    raise ProblemError("conflict", detail="Couldn't pick a free username. Please try again.")


async def find_account(session: AsyncSession, reg: AdmissionRegistration) -> Any | None:
    """The registration's LMS account: the linked one, else the account with its email."""
    from app.modules.identity import service as ids

    user = await identity_public.get_user(session, reg.user_id) if reg.user_id is not None else None
    if user is None:
        user = await ids.find_user(session, "email", reg.email)
    return user


async def ensure_account(
    session: AsyncSession, actor: Actor, reg: AdmissionRegistration, *, must_change_password: bool
) -> Account:
    """Find the registration's LMS account or create it (username + temporary password). An
    existing account is never changed (its password stays). Call under system context."""
    from app.core.firestore.errors import UniqueViolationError
    from app.modules.identity import service as ids
    from app.modules.identity.public import User, UserProfile

    user = await find_account(session, reg)
    if user is not None:
        if user.status in ("deactivated", "deleted"):
            raise ProblemError(
                "invalid_state_transition",
                detail="The LMS account for this email is deactivated. "
                "Reactivate it (Admin > Users) or correct the email, then try again.",
            )
        return Account(user, False, None)

    phone = reg.phone if reg.phone and await ids.find_user(session, "phone", reg.phone) is None else None
    now = utcnow()
    user = None
    for attempt in range(3):
        uid = uuid7()
        candidate = User(
            id=uid,
            email=reg.email,
            # staff verified this person's payment; the login details go to this address
            email_verified_at=now,
            phone_e164=phone,
            username=await _free_username(session),
            status="active",
            is_minor=False,
            age_verified_at=now,
            age_verification_method="self_declared",
            account_origin="staff_created",
        )
        try:
            async with await ads.begin_nested(session):
                await identity_public.create_user(session, candidate)
        except (IntegrityError, UniqueViolationError):
            # lost a race on the username (or the email): pick again
            if attempt == 2:
                raise ProblemError(
                    "conflict", detail="Couldn't create the account. Please try again."
                ) from None
            existing = await find_account(session, reg)
            if existing is not None:
                return Account(existing, False, None)
            continue
        user = candidate
        break
    assert user is not None
    await identity_public.save_profile(session, UserProfile(user_id=user.id, full_name=reg.name[:200]))
    temp = new_temp_password()
    await ids.set_password(session, user.id, temp, must_change_password=must_change_password)
    reg.user_id = user.id
    await ads.flush(session)
    await audit(
        session,
        actor.audit_actor(),
        "admin.user.created",
        "user",
        user.id,
        subject_user_id=user.id,
        reason=f"Admissions enrolment {reg.reg_no}",
        after={
            "status": "active",
            "account_origin": "staff_created",
            "source": "admissions",
            "username": user.username,
            "temporary_password": True,  # set, never recorded
            "must_change_password": must_change_password,
        },
    )
    await emit_event(
        session,
        "identity.user_registered",
        {"user_id": str(user.id), "is_minor": False},
        aggregate_type="user",
        aggregate_id=user.id,
    )
    return Account(user, True, temp)


# --------------------------------------------------------------------------- email


def _batch_name(batch: Any) -> str | None:
    return getattr(batch, "name", None) if batch is not None else None


def login_message(
    reg: AdmissionRegistration,
    user: Any,
    *,
    batch_name: str | None,
    temporary_password: str | None,
    must_change_password: bool,
) -> tuple[str, str, str]:
    """(subject, plain text, simple HTML) of the login email."""
    url = login_url()
    subject = "Your Tech Drona LMS login"
    lines = [
        f"Hello {reg.name},",
        "",
        f"You're enrolled in {reg.course_title}" + (f" (batch: {batch_name})." if batch_name else "."),
        "Here are your Tech Drona LMS sign-in details:",
        "",
        f"Sign in: {url}",
    ]
    if user.username:
        lines.append(f"Username: {user.username}")
    lines.append(f"Email: {user.email or reg.email}")
    if temporary_password:
        lines.append(f"Temporary password: {temporary_password}")
    else:
        lines.append(
            'Password: the one you already use (forgot it? use "Forgot password" on the sign-in page)'
        )
    lines.append("")
    lines.append("You can sign in with your username or your email.")
    if must_change_password and temporary_password:
        lines.append("You'll be asked to choose your own password when you first sign in.")
    lines.append("After signing in, open My classes on your dashboard to see your course.")
    lines.append("Keep these details private. If you didn't expect this email, reply to let us know.")
    plain = "\n".join(lines) + "\n\nTech Drona\ninfo@techdrona.com"

    def row(label: str, value: str, mono: bool = False) -> str:
        style = "font-family:monospace;font-size:15px;" if mono else ""
        return (
            f'<tr><td style="padding:4px 12px 4px 0;color:#555">{escape(label)}</td>'
            f'<td style="padding:4px 0;{style}"><strong>{escape(value)}</strong></td></tr>'
        )

    rows = [row("Sign in", url)]
    if user.username:
        rows.append(row("Username", user.username, True))
    rows.append(row("Email", user.email or reg.email))
    if temporary_password:
        rows.append(row("Temporary password", temporary_password, True))
    notes = []
    if must_change_password and temporary_password:
        notes.append("You'll be asked to choose your own password when you first sign in.")
    if not temporary_password:
        notes.append(
            'Use the password you already have (forgot it? use "Forgot password" on the sign-in page).'
        )
    notes.append("After signing in, open <em>My classes</em> on your dashboard to see your course.")
    html = (
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#222;line-height:1.5">'
        f"<p>Hello {escape(reg.name)},</p>"
        f"<p>You're enrolled in <strong>{escape(reg.course_title)}</strong>"
        + (f" (batch: {escape(batch_name)})" if batch_name else "")
        + ". Here are your Tech Drona LMS sign-in details:</p>"
        f'<table style="border-collapse:collapse">{"".join(rows)}</table>'
        f'<p><a href="{escape(url)}" style="display:inline-block;background:#1a56db;color:#fff;'
        'padding:10px 18px;border-radius:6px;text-decoration:none">Sign in to Tech Drona LMS</a></p>'
        + "".join(f"<p>{n}</p>" for n in notes)
        + "<p>Keep these details private.</p><p>Tech Drona<br>info@techdrona.com</p></div>"
    )
    return subject, plain, html


async def deliver_login_email(
    session: AsyncSession,
    actor: Actor,
    reg: AdmissionRegistration,
    user: Any,
    *,
    batch_name: str | None,
    temporary_password: str | None,
    must_change_password: bool,
) -> dict[str, Any]:
    """Send the login email. ``sent`` is true only when a real provider accepted it."""
    from app.modules.notifications.adapters import email_integrated
    from app.modules.notifications.service import send_email

    to = user.email or reg.email
    subject, plain, html = login_message(
        reg,
        user,
        batch_name=batch_name,
        temporary_password=temporary_password,
        must_change_password=must_change_password,
    )
    # Deferred checks (ledger trigger) now, so a commit can't fail after the password left.
    # Firestore: the same checks the commit will run (ledger, uniques, row versions), so a
    # transaction that cannot commit never sends the email.
    await ads.constraints_immediate(session)
    integrated = email_integrated()
    accepted = await send_email(
        to, subject, plain, template_key="admissions.login_details", category="transactional", html=html
    )
    sent = integrated and accepted
    reason = None if sent else ("email_not_connected" if not integrated else "send_failed")
    if sent:
        reg.login_email_sent_at = utcnow()
        await ads.flush(session)
    await trail(
        session,
        actor,
        "account.login_email",
        reg.id,
        detail=(
            "Login email sent"
            if sent
            else "Login email not sent: email isn't connected yet"
            if reason == "email_not_connected"
            else "Login email not sent: delivery failed"
        )
        + (" Â· new temporary password" if temporary_password else ""),
    )
    await audit(
        session,
        actor.audit_actor(),
        "admissions.login_email.sent" if sent else "admissions.login_email.failed",
        "admission_registration",
        reg.id,
        subject_user_id=user.id,
        after={"sent": sent, "reason": reason, "with_temporary_password": bool(temporary_password)},
    )
    return {"attempted": True, "sent": sent, "reason": reason}


def _account_out(user: Any, *, created: bool | None, temporary_password: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "user_id": str(user.id),
        "username": user.username,
        "email": user.email,
        "temporary_password": temporary_password,
        "must_change_password": bool(user.must_change_password),
    }
    if created is not None:
        out = {**out, "created": created}
    return out


# --------------------------------------------------------------------------- verify & add to batch


async def verify_and_enrol(
    session: AsyncSession,
    actor: Actor,
    claim_id: uuid.UUID,
    *,
    amount_paise: int | None,
    batch_id: uuid.UUID | None,
    must_change_password: bool,
    send_email: bool,
    note: str | None,
) -> dict[str, Any]:
    from app.modules.admissions import service as sv

    c = await ads.get(session, AdmissionPaymentClaim, claim_id)
    if c is None:
        raise ProblemError("not_found")
    reg = await lock_registration(session, c.registration_id)
    await ads.refresh(session, c)
    if reg.status in R.MANUAL_STATUSES:
        raise ProblemError(
            "invalid_state_transition",
            detail=f"This registration is {reg.status}. Reopen it before adding the student to a batch.",
            current_state=reg.status,
            allowed=["registered", "pending_verification", "partially_paid", "payment_verified", "enrolled"],
        )
    amount = (
        amount_paise
        if amount_paise is not None
        else (c.verified_amount_paise if c.status == "verified" else c.amount_paise)
    )
    already = c.status == "verified" and c.verified_amount_paise == amount
    if not already and R.can_move_claim(c.status, "verified"):
        total = reg.verified_total_paise + amount
        if total <= reg.fee_paise and not R.eligible(
            status=reg.status, verified=total, access_min=reg.access_min_paise, fee=reg.fee_paise
        ):
            raise _insufficient(reg, total)
    # verify (idempotent; refuses rejected / reversed claims and amounts above the fee)
    await verify_claim(
        session, actor, claim_id, amount_paise=amount, note=note, checked=True, auto_enrol=False
    )
    reg = await lock_registration(session, reg.id)
    if not R.eligible(
        status=reg.status,
        verified=reg.verified_total_paise,
        access_min=reg.access_min_paise,
        fee=reg.fee_paise,
    ):
        raise _insufficient(reg, reg.verified_total_paise)

    plan = await ads.get(session, AdmissionFeePlan, reg.fee_plan_id)
    target = batch_id or (plan.batch_id if plan else None) or reg.enrolled_batch_id
    if target is None:
        raise vf(
            "batch_id",
            "batch_required",
            "Choose the batch to add this student to (or link a batch to this course's fee plan).",
        )
    batch = await orgs_public.get_batch(session, target)
    if batch is None:
        raise vf("batch_id", "unknown_batch", "Choose an existing batch.")

    async with as_system(session, "admissions.verify_and_enrol"):
        acct = await ensure_account(session, actor, reg, must_change_password=must_change_password)
    in_batch = reg.enrolled_at is not None and reg.enrolled_batch_id == batch.id
    if not in_batch:
        await sv.enrol(session, actor, reg, batch_id=batch.id, login_details=send_email or acct.created)
    out: dict[str, Any] = {
        "registration_id": str(reg.id),
        "status": reg.status,
        "batch": {"batch_id": str(batch.id), "name": batch.name},
        "account": _account_out(acct.user, created=acct.created, temporary_password=acct.temporary_password),
        "email": {"attempted": False, "sent": False, "reason": None},
        "login_url": login_url(),
        "registration": registration_out(reg, full=True),
    }
    if send_email:
        out["email"] = await deliver_login_email(
            session,
            actor,
            reg,
            acct.user,
            batch_name=batch.name,
            temporary_password=acct.temporary_password,
            must_change_password=bool(acct.user.must_change_password),
        )
        out["registration"] = registration_out(reg, full=True)
    log.info(
        "admissions_verify_and_enrol",
        registration_id=str(reg.id),
        new_account=acct.created,
        email_sent=out["email"]["sent"],
    )
    return out


def _insufficient(reg: AdmissionRegistration, total: int) -> ProblemError:
    return ProblemError(
        "insufficient_payment",
        detail=(
            f"{R.rupees(total)} verified of the {R.rupees(reg.access_min_paise)} needed for course "
            "access. Verify the payment only (without adding to a batch) or record the rest first."
        ),
        verified_total_paise=total,
        access_min_paise=reg.access_min_paise,
    )


# --------------------------------------------------------------------------- login email (re)send


async def _refuse_staff_accounts(session: AsyncSession, user_id: uuid.UUID) -> None:
    """A staff account's password is never reset from Admissions (Admin > Users / own settings)."""
    from app.modules.rbac.service import active_grants

    if any(g.role != "student" for g in await active_grants(session, user_id)):
        raise ProblemError(
            "permission_denied",
            detail="This LMS account belongs to a staff member: its password can't be reset from "
            "Admissions. Send the email without a new password.",
        )


async def _reload_user(session: AsyncSession, user: Any) -> Any:
    """The user row after a password change: ``session.refresh`` on Postgres, a fresh read from
    the identity store on Firestore."""
    from app.core.firestore.backend import uses_firestore

    if uses_firestore("identity"):
        return await identity_public.get_user(session, user.id) or user
    await session.refresh(user)
    return user


async def send_login_email(
    session: AsyncSession,
    actor: Actor,
    reg_id: uuid.UUID,
    *,
    reset_password: bool,
    must_change_password: bool,
) -> dict[str, Any]:
    from app.modules.identity import service as ids
    from app.modules.sessions import service as ss

    reg = await lock_registration(session, reg_id)
    if reg.enrolled_at is None or reg.user_id is None:
        raise ProblemError(
            "invalid_state_transition",
            detail="Add the student to a batch first (Verify & Add to Batch).",
            current_state=reg.status,
            allowed=["enrolled"],
        )
    temp: str | None = None
    async with as_system(session, "admissions.login_email"):
        user = await identity_public.get_user(session, reg.user_id)
        if user is None or user.status in ("deactivated", "deleted"):
            raise ProblemError(
                "invalid_state_transition",
                detail="The student's LMS account is deactivated. Reactivate it (Admin > Users) first.",
            )
        if reset_password:
            await _refuse_staff_accounts(session, user.id)
            temp = new_temp_password()
            await ids.set_password(session, user.id, temp, must_change_password=must_change_password)
            n = await ss.revoke_all_sessions(session, user.id, "password_changed", ended_by=actor.user_id)
            await audit(
                session,
                actor.audit_actor(),
                "admissions.account.password_reset",
                "user",
                user.id,
                subject_user_id=user.id,
                reason=f"Admissions login email {reg.reg_no}",
                after={"sessions_revoked": n, "must_change_password": must_change_password},
            )
        batch = await orgs_public.get_batch(session, reg.enrolled_batch_id) if reg.enrolled_batch_id else None
        user = await _reload_user(session, user)
        email = await deliver_login_email(
            session,
            actor,
            reg,
            user,
            batch_name=_batch_name(batch),
            temporary_password=temp,
            must_change_password=bool(user.must_change_password),
        )
    return {
        "account": _account_out(user, created=None, temporary_password=temp),
        "email": email,
        "login_url": login_url(),
        "login_email_sent_at": iso(reg.login_email_sent_at),
    }
