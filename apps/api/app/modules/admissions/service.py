"""Admissions workflow: registrations, payment claims, staff decisions, ledger, enrolment.

Callers own the transaction. Public flows run under ``system_context`` (platform RLS); staff
flows run under the principal's context (platform grant) and switch to system context only for
the cross-module writes of enrolment (identity, entitlements, learning, orgs).

Ledger rule (also a deferred DB trigger): ``verified_total`` moves only together with ONE claim's
verification (+amount) or reversal (-amount), in the same transaction, with the registration row
locked (``FOR UPDATE``), so two reviewers can never double-count a payment.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import structlog
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.db import as_system
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import ist_date, utcnow
from app.modules.admissions import datastore as ads
from app.modules.admissions import files as fs
from app.modules.admissions import rules as R
from app.modules.admissions.models import (
    AdmissionEvent,
    AdmissionFeePlan,
    AdmissionPaymentClaim,
    AdmissionPaySettings,
    AdmissionRegistration,
)
from app.modules.identity import public as identity_public
from app.modules.orgs import public as orgs_public

log = structlog.get_logger("app.admissions")

CONSENT_TEXT = (
    "I agree that Tech Drona may store and use my details, payment proof and resume to process this "
    "registration, verify my payment and contact me about this course (see the Privacy Policy)."
)
NOTICE_VERSION = "admissions-2026-11"


def vf(field: str, code: str, message: str, status: int = 422) -> ProblemError:
    return ProblemError(
        "validation_failed", status, errors=[{"field": field, "code": code, "message": message}]
    )


def conflict(field: str, code: str, message: str) -> ProblemError:
    return ProblemError(
        "conflict", 409, detail=message, errors=[{"field": field, "code": code, "message": message}]
    )


def iso(v: datetime | date | None) -> str | None:
    return v.isoformat() if v else None


# --------------------------------------------------------------------------- terms / views


def plan_terms(p: AdmissionFeePlan | AdmissionRegistration) -> R.PlanTerms:
    return R.clean_terms(
        fee_paise=p.fee_paise,
        allow_instalments=p.allow_instalments,
        schedule=list(p.schedule or []),
        min_first_paise=p.min_first_paise,
        access_min_paise=p.access_min_paise,
    )


def reg_terms(r: AdmissionRegistration) -> R.PlanTerms:
    """The registration's own terms (fee may have been adjusted: keep its access threshold)."""
    t = plan_terms(r)
    return R.PlanTerms(
        r.fee_paise, t.allow_instalments, t.schedule, r.policy, r.min_first_paise, r.access_min_paise
    )


async def pay_settings(session: AsyncSession) -> AdmissionPaySettings | None:
    return await ads.get(session, AdmissionPaySettings, 1)


def pay_settings_out(s: AdmissionPaySettings | None) -> dict[str, Any]:
    return {
        "phone": (s.phone if s else None) or "",
        "preferred_app": (s.preferred_app if s else "PhonePe") or "",
        "upi_id": (s.upi_id if s else None) or "",
        "payee_name": (s.payee_name if s else None) or "",
        "instructions": (s.instructions if s else None) or "",
    }


def pay_configured(plan: AdmissionFeePlan, pay: dict[str, Any]) -> bool:
    return bool(pay.get("phone") or pay.get("upi_id") or plan.upi_id or plan.bank_details)


def plan_out(p: AdmissionFeePlan, *, staff: bool = False) -> dict[str, Any]:
    t = plan_terms(p)
    out: dict[str, Any] = {
        "slug": p.course_slug,
        "title": p.title,
        "fee_paise": p.fee_paise,
        "allow_instalments": t.allow_instalments,
        "schedule": [x.as_dict() for x in t.schedule],
        "policy": t.policy,
        "min_first_paise": t.min_first_paise,
        "access_min_paise": t.access_min_paise,
        "upi_id": p.upi_id or "",
        "payee_name": p.payee_name or "",
        "bank_details": p.bank_details or "",
        "instructions": p.instructions or "",
        "active": p.active,
    }
    if staff:
        out |= {
            "fee_plan_id": str(p.id),
            "course_id": str(p.course_id) if p.course_id else None,
            "batch_id": str(p.batch_id) if p.batch_id else None,
            "updated_at": iso(p.updated_at),
            "problems": list(t.problems),
        }
    return out


def registration_out(r: AdmissionRegistration, *, full: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {
        "registration_id": str(r.id),
        "reg_no": r.reg_no,
        "name": r.name,
        "email": r.email,
        "phone": r.phone,
        "college": r.college,
        "course_slug": r.course_slug,
        "course_title": r.course_title,
        "fee_paise": r.fee_paise,
        "access_min_paise": r.access_min_paise,
        "verified_total_paise": r.verified_total_paise,
        "balance_paise": r.balance_paise,
        "payment_state": R.pay_state(r.verified_total_paise, r.fee_paise),
        "status": r.status,
        "open_claims": r.open_claims,
        "enrolled_at": iso(r.enrolled_at),
        "user_id": str(r.user_id) if r.user_id else None,
        "login_email_sent_at": iso(r.login_email_sent_at),
        "created_at": iso(r.created_at),
        "updated_at": iso(r.updated_at),
    }
    if full:
        t = reg_terms(r)
        covered = r.verified_total_paise
        sched = []
        for x in t.schedule:
            c = max(0, min(x.amount_paise, covered))
            covered -= c
            sched.append({**x.as_dict(), "covered_paise": c, "done": c >= x.amount_paise})
        out |= {
            "branch": r.branch,
            "year": r.year,
            "current_status": r.current_status,
            "preferred_mode": r.preferred_mode,
            "message": r.message,
            "policy": r.policy,
            "allow_instalments": r.allow_instalments,
            "schedule": sched,
            "next_due": R.next_due(t, r.verified_total_paise),
            "status_note": r.status_note,
            "has_resume": bool(r.resume_key),
            "resume_name": r.resume_name,
            "consent_text": r.consent_text,
            "consent_at": iso(r.consent_at),
            "show_public": r.show_public,
            "marketing_consent": r.marketing_consent_at is not None,
            "source": r.source,
            "entitlement_id": str(r.entitlement_id) if r.entitlement_id else None,
            "enrolment_id": str(r.enrolment_id) if r.enrolment_id else None,
            "enrolled_course_id": str(r.enrolled_course_id) if r.enrolled_course_id else None,
            "enrolled_batch_id": str(r.enrolled_batch_id) if r.enrolled_batch_id else None,
            "eligible": R.eligible(
                status=r.status,
                verified=r.verified_total_paise,
                access_min=r.access_min_paise,
                fee=r.fee_paise,
            ),
        }
    return out


def claim_out(c: AdmissionPaymentClaim, reg: AdmissionRegistration | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "claim_id": str(c.id),
        "registration_id": str(c.registration_id),
        "provider": c.provider,
        "method": c.method,
        "amount_paise": c.amount_paise,
        "utr": c.utr,
        "paid_on": iso(c.paid_on),
        "note": c.note,
        "has_proof": bool(c.proof_key),
        "proof_name": c.proof_name,
        "proof_type": c.proof_type,
        "status": c.status,
        "verified_amount_paise": c.verified_amount_paise,
        "locks_released": c.locks_released,
        "reviewed_by": str(c.reviewed_by) if c.reviewed_by else None,
        "reviewed_at": iso(c.reviewed_at),
        "review_note": c.review_note,
        "submitted_at": iso(c.submitted_at),
    }
    if reg is not None:
        out["registration"] = registration_out(reg)
        out["flags"] = review_flags(c, reg)
    return out


def review_flags(c: AdmissionPaymentClaim, reg: AdmissionRegistration) -> list[str]:
    """Things the reviewer should look at twice (never decisive on their own)."""
    f: list[str] = []
    if c.amount_paise > max(0, reg.balance_paise):
        f.append("Claimed amount is more than the balance due")
    if c.method == "upi" and c.utr and not (c.utr.isdigit() and len(c.utr) == 12):
        f.append("Reference is not the usual 12-digit UPI format")
    if c.paid_on and c.submitted_at and c.paid_on > ist_date(c.submitted_at):
        f.append("Payment date is after the submission date")
    if c.proof_type == "application/pdf":
        f.append("Proof is a PDF (check it's a genuine bank/app receipt)")
    return f


def event_out(e: AdmissionEvent) -> dict[str, Any]:
    return {
        "event_id": str(e.id),
        "registration_id": str(e.registration_id) if e.registration_id else None,
        "claim_id": str(e.claim_id) if e.claim_id else None,
        "action": e.action,
        "amount_paise": e.amount_paise,
        "actor": e.actor_label,
        "detail": e.detail,
        "at": iso(e.at),
    }


# --------------------------------------------------------------------------- actors / trail


@dataclass(frozen=True)
class Actor:
    """Who acted: a staff principal or the student (public form)."""

    principal: Principal | None
    label: str

    @property
    def user_id(self) -> uuid.UUID | None:
        return self.principal.user_id if self.principal else None

    def audit_actor(self) -> Principal | AuditActor:
        return self.principal if self.principal is not None else AuditActor.system("admissions.public")


async def staff_actor(session: AsyncSession, principal: Principal) -> Actor:

    staff = await identity_public.get_user(session, principal.user_id)
    email = staff.email if staff is not None else None
    return Actor(principal, str(email or f"staff {str(principal.user_id)[:8]}"))


def student_actor(email: str) -> Actor:
    return Actor(None, f"student <{email}>"[:160])


async def trail(
    session: AsyncSession,
    actor: Actor,
    action: str,
    reg_id: uuid.UUID | None,
    *,
    claim_id: uuid.UUID | None = None,
    amount: int = 0,
    detail: str = "",
) -> None:
    ads.add(
        session,
        AdmissionEvent(
            id=uuid7(),
            registration_id=reg_id,
            claim_id=claim_id,
            action=action,
            amount_paise=amount,
            actor_user_id=actor.user_id,
            actor_label=actor.label,
            detail=detail[:400] or None,
            at=utcnow(),
        ),
    )
    await ads.flush(session)


async def _emit(session: AsyncSession, event: str, reg: AdmissionRegistration, **payload: Any) -> None:
    await emit_event(
        session,
        f"admissions.{event}",
        {
            "registration_id": str(reg.id),
            **{k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in payload.items()},
        },
        aggregate_type="admission_registration",
        aggregate_id=reg.id,
    )


def _restatus(reg: AdmissionRegistration, *, current: str | None = None) -> None:
    reg.balance_paise = reg.fee_paise - reg.verified_total_paise
    reg.status = R.derive_status(
        current=current or reg.status,
        verified=reg.verified_total_paise,
        access_min=reg.access_min_paise,
        open_claims=reg.open_claims,
        enrolled=reg.enrolled_at is not None,
        fee=reg.fee_paise,
    )


# --------------------------------------------------------------------------- lookups


async def plan_by_slug(session: AsyncSession, slug: str) -> AdmissionFeePlan | None:
    return (
        await ads.execute(session, select(AdmissionFeePlan).where(AdmissionFeePlan.course_slug == slug))
    ).scalar_one_or_none()


async def lock_registration(session: AsyncSession, reg_id: uuid.UUID) -> AdmissionRegistration:
    r = (
        await ads.execute(
            session,
            select(AdmissionRegistration)
            .where(AdmissionRegistration.id == reg_id)
            .with_for_update()
            .execution_options(populate_existing=True),
        )
    ).scalar_one_or_none()
    if r is None:
        raise ProblemError("not_found")
    return r


async def lock_claim(
    session: AsyncSession, claim_id: uuid.UUID
) -> tuple[AdmissionPaymentClaim, AdmissionRegistration]:
    c = await ads.get(session, AdmissionPaymentClaim, claim_id)
    if c is None:
        raise ProblemError("not_found")
    reg = await lock_registration(session, c.registration_id)  # registration first: one lock order
    c = (
        await ads.execute(
            session,
            select(AdmissionPaymentClaim)
            .where(AdmissionPaymentClaim.id == claim_id)
            .with_for_update()
            .execution_options(populate_existing=True),
        )
    ).scalar_one()
    return c, reg


async def find_by_reg_no_email(
    session: AsyncSession, reg_no: str, email: str
) -> AdmissionRegistration | None:
    return (
        await ads.execute(
            session,
            select(AdmissionRegistration).where(
                AdmissionRegistration.reg_no == reg_no, AdmissionRegistration.email == email
            ),
        )
    ).scalar_one_or_none()


async def _check_locks(session: AsyncSession, utr: str | None, proof: fs.PreparedFile | None) -> None:
    live = AdmissionPaymentClaim.locks_released.is_(False)
    if utr:
        hit = (
            await ads.execute(
                session, select(AdmissionPaymentClaim.id).where(AdmissionPaymentClaim.utr == utr, live)
            )
        ).first()
        if hit:
            raise conflict(
                "utr",
                "utr_taken",
                "This transaction reference was already submitted. Each payment can be claimed only once. "
                "If you think this is a mistake, contact Tech Drona.",
            )
    if proof is not None:
        hashes = [h for h in (proof.sha256, proof.original_sha256) if h]
        hit = (
            await ads.execute(
                session,
                select(AdmissionPaymentClaim.id).where(
                    live,
                    or_(
                        AdmissionPaymentClaim.proof_sha256.in_(hashes),
                        AdmissionPaymentClaim.proof_original_sha256.in_(hashes),
                    ),
                ),
            )
        ).first()
        if hit:
            raise conflict(
                "proof",
                "proof_taken",
                "This exact screenshot was already uploaded for another payment. Upload the "
                "receipt of this payment.",
            )


# --------------------------------------------------------------------------- public: register / claim


@dataclass
class ClaimInput:
    amount_paise: int
    method: str
    utr: str
    paid_on: date
    note: str | None


def check_student_claim(c: ClaimInput, terms: R.PlanTerms, balance: int, *, first: bool) -> str:
    """Validate a student claim; returns the normalised UTR."""
    if c.method not in R.STUDENT_METHODS:
        raise vf("method", "invalid_method", "Choose how you paid.")
    lo, hi = R.amount_range(terms, balance, first_payment=first)
    if hi <= 0:
        raise vf("amount_paise", "nothing_due", "Nothing is due on this registration.")
    if c.amount_paise > hi:
        raise vf(
            "amount_paise",
            "above_balance",
            f"That's more than the amount due ({R.rupees(hi)}). Enter what you actually paid.",
        )
    if c.amount_paise < lo:
        raise vf(
            "amount_paise",
            "below_minimum",
            f"The minimum {'first ' if first else ''}payment is {R.rupees(lo)}."
            if terms.allow_instalments
            else f"This course is paid in full: {R.rupees(hi)}.",
        )
    prob = R.ref_problem(c.utr, c.method)
    if prob:
        raise vf("utr", "invalid_reference", prob)
    prob = R.paid_on_problem(c.paid_on, ist_date(utcnow()))
    if prob:
        raise vf("paid_on", "invalid_date", prob)
    return R.normalize_ref(c.utr)


async def _store_claim(
    session: AsyncSession,
    reg: AdmissionRegistration,
    c: ClaimInput,
    utr: str,
    proof: fs.PreparedFile,
    actor: Actor,
) -> AdmissionPaymentClaim:
    claim_id = uuid7()
    key = fs.object_key(reg.id, "proof", claim_id, proof.content_type)
    claim = AdmissionPaymentClaim(
        id=claim_id,
        registration_id=reg.id,
        provider="manual_upi",
        method=c.method,
        amount_paise=c.amount_paise,
        utr=utr,
        paid_on=c.paid_on,
        note=(c.note or "").strip()[:500] or None,
        proof_key=key,
        proof_name=proof.name,
        proof_type=proof.content_type,
        proof_size=len(proof.data),
        proof_sha256=proof.sha256,
        proof_original_sha256=proof.original_sha256,
        status="pending",
        verified_amount_paise=0,
        submitted_at=utcnow(),
    )
    ads.add(session, claim)
    reg.open_claims += 1
    _restatus(reg)
    await ads.flush(session)
    await trail(
        session,
        actor,
        "payment.submitted",
        reg.id,
        claim_id=claim.id,
        amount=c.amount_paise,
        detail=f"{R.rupees(c.amount_paise)} · ref {utr}",
    )
    # Bytes last: a refused claim (409) never leaves an object behind.
    await ads.before_side_effect(session)
    await fs.store(key, proof)
    return claim


@dataclass
class RegistrationInput:
    course_slug: str
    reg_no: str | None
    name: str
    email: str
    phone: str
    college: str
    branch: str
    year: str
    current_status: str | None
    preferred_mode: str | None
    message: str | None
    consent_text: str | None
    show_public: bool
    marketing: bool


async def register(
    session: AsyncSession,
    d: RegistrationInput,
    claim: ClaimInput,
    proof: fs.PreparedFile,
    resume: fs.PreparedFile | None,
) -> AdmissionRegistration:
    """Registration + first payment claim + files + trail, all or nothing (system context)."""
    from app.modules.admissions import courses

    plan = await plan_by_slug(session, d.course_slug)
    await courses.require_open(session, d.course_slug, plan)
    pay = pay_settings_out(await pay_settings(session))
    if plan is None or not plan.active or plan.fee_paise <= 0:
        raise ProblemError("not_found", detail="Online registration isn't open for this course.")
    if not pay_configured(plan, pay):
        raise ProblemError(
            "invalid_state_transition",
            detail="Online payment details aren't set up for this course yet. Please contact Tech Drona.",
        )
    terms = plan_terms(plan)
    if terms.problems:
        raise ProblemError(
            "invalid_state_transition", detail="Online registration isn't open for this course."
        )
    utr = check_student_claim(claim, terms, plan.fee_paise, first=True)
    taken = (
        await ads.execute(
            session,
            select(AdmissionRegistration.id).where(
                AdmissionRegistration.course_slug == plan.course_slug,
                AdmissionRegistration.email == d.email,
                AdmissionRegistration.status.not_in(tuple(R.ENDED_STATUSES)),
            ),
        )
    ).first()
    if taken:
        raise conflict(
            "email",
            "already_registered",
            f"This email is already registered for {plan.title}. To pay an instalment, use "
            f'"Already registered? '
            'Pay the next installment" with your registration number. If you need help, contact Tech Drona.',
        )
    await _check_locks(session, utr, proof)
    reg_no = d.reg_no or R.new_reg_no()
    if (
        await ads.execute(
            session, select(AdmissionRegistration.id).where(AdmissionRegistration.reg_no == reg_no)
        )
    ).first():
        if d.reg_no:
            raise conflict(
                "reg_no",
                "reg_no_taken",
                "This registration number is already in use. Reload the page and start again "
                "(don't pay twice: "
                "if you already paid, upload the same receipt).",
            )
        reg_no = R.new_reg_no()
    now = utcnow()
    reg_id = uuid7()
    reg = AdmissionRegistration(
        id=reg_id,
        reg_no=reg_no,
        fee_plan_id=plan.id,
        course_slug=plan.course_slug,
        course_title=plan.title[:160],
        name=d.name,
        email=d.email,
        phone=d.phone,
        college=d.college,
        branch=d.branch,
        year=d.year,
        current_status=d.current_status,
        preferred_mode=d.preferred_mode,
        message=d.message,
        fee_paise=terms.fee_paise,
        access_min_paise=terms.access_min_paise,
        policy=terms.policy,
        allow_instalments=terms.allow_instalments,
        min_first_paise=terms.min_first_paise,
        schedule=[x.as_dict() for x in terms.schedule],
        verified_total_paise=0,
        balance_paise=terms.fee_paise,
        status="registered",
        open_claims=0,
        consent_text=CONSENT_TEXT,
        consent_at=now,
        show_public=d.show_public,
        marketing_consent_at=now if d.marketing else None,
        source="website",
        created_at=now,
        updated_at=now,
    )
    if resume is not None:
        reg.resume_key = fs.object_key(reg_id, "resume", reg_id, resume.content_type)
        reg.resume_name, reg.resume_type, reg.resume_size = resume.name, resume.content_type, len(resume.data)
    ads.add(session, reg)
    await ads.flush(session)
    actor = student_actor(d.email)
    await trail(
        session,
        actor,
        "registration.created",
        reg.id,
        detail=f"{reg.course_title} · fee {R.rupees(reg.fee_paise)}",
    )
    c = await _store_claim(session, reg, claim, utr, proof, actor)
    if resume is not None and reg.resume_key:
        await ads.before_side_effect(session)
        await fs.store(reg.resume_key, resume)
    await audit(
        session,
        AuditActor.system("admissions.public"),
        "admissions.registration.created",
        "admission_registration",
        reg.id,
        after={
            "reg_no": reg.reg_no,
            "course_slug": reg.course_slug,
            "fee_paise": reg.fee_paise,
            "has_resume": resume is not None,
        },
    )
    await _emit(session, "registration_received", reg, claim_id=c.id, amount_paise=c.amount_paise)
    return reg


SUPERSEDED_NOTE = "Replaced by a newer upload"


async def _supersede(
    session: AsyncSession, reg: AdmissionRegistration, asked: list[AdmissionPaymentClaim], actor: Actor
) -> None:
    """A new upload answers the team's correction requests: close those claims (``rejected`` with
    a "replaced" reason, out of the queue and the open-claim cap) and free their UTR / screenshot so
    the corrected upload may reuse them."""
    if not asked:
        return
    now = utcnow()
    for old in asked:
        before = old.review_note or ""
        old.status, old.reviewed_at, old.locks_released = "rejected", now, True
        old.review_note = (f"{SUPERSEDED_NOTE} (asked: {before})" if before else SUPERSEDED_NOTE)[:500]
        reg.open_claims = max(0, reg.open_claims - 1)
    _restatus(reg)
    await ads.flush(session)
    for old in asked:
        await trail(
            session,
            actor,
            "payment.superseded",
            reg.id,
            claim_id=old.id,
            amount=old.amount_paise,
            detail=f"{R.rupees(old.amount_paise)} · ref {old.utr or '-'} · {SUPERSEDED_NOTE}",
        )
        await audit(
            session,
            actor.audit_actor(),
            "admissions.payment.superseded",
            "admission_payment_claim",
            old.id,
            reason=SUPERSEDED_NOTE,
            before={"status": "needs_info"},
            after={"status": "rejected", "released_locks": True},
        )


async def add_claim(
    session: AsyncSession, reg_no: str, email: str, claim: ClaimInput, proof: fs.PreparedFile
) -> AdmissionRegistration:
    """A later instalment (or a corrected proof) on an existing registration (system context)."""
    found = await find_by_reg_no_email(session, reg_no, email)
    if found is None:
        raise ProblemError(
            "not_found",
            detail="We couldn't find a registration with that number and email. Check both, or "
            "contact Tech Drona.",
        )
    reg = await lock_registration(session, found.id)
    if reg.status in R.MANUAL_STATUSES:
        raise ProblemError(
            "invalid_state_transition",
            detail=f"This registration is closed. Please contact Tech Drona with your "
            f"registration number {reg.reg_no}.",
        )
    asked = list(
        (
            await ads.execute(
                session,
                select(AdmissionPaymentClaim)
                .where(
                    AdmissionPaymentClaim.registration_id == reg.id,
                    AdmissionPaymentClaim.status == "needs_info",
                )
                .with_for_update(),
            )
        ).scalars()
    )
    if reg.open_claims - len(asked) >= R.MAX_OPEN_CLAIMS:
        raise ProblemError(
            "invalid_state_transition",
            detail=f"{R.MAX_OPEN_CLAIMS} payments are already waiting for verification. Please "
            f"wait for our team, "
            f"or contact Tech Drona with your registration number {reg.reg_no}.",
        )
    utr = check_student_claim(claim, reg_terms(reg), reg.balance_paise, first=False)
    await _supersede(session, reg, asked, student_actor(email))
    await _check_locks(session, utr, proof)
    c = await _store_claim(session, reg, claim, utr, proof, student_actor(email))
    await _emit(session, "claim_received", reg, claim_id=c.id, amount_paise=c.amount_paise)
    return reg


def status_for_student(reg: AdmissionRegistration) -> dict[str, Any]:
    t = reg_terms(reg)
    return {
        "reg_no": reg.reg_no,
        "email": reg.email,
        "course_slug": reg.course_slug,
        "course_title": reg.course_title,
        "status": reg.status,
        "fee_paise": reg.fee_paise,
        "verified_total_paise": reg.verified_total_paise,
        "balance_paise": reg.balance_paise,
        "open_claims": reg.open_claims,
        "next_due": R.next_due(t, reg.verified_total_paise),
        "enrolled": reg.enrolled_at is not None,
    }


# --------------------------------------------------------------------------- staff: decisions


def _reason(text: str | None, field: str, message: str) -> str:
    t = (text or "").strip()
    if len(t) < 4:
        raise vf(field, "reason_required", message)
    return t[:500]


async def verify_claim(
    session: AsyncSession,
    actor: Actor,
    claim_id: uuid.UUID,
    *,
    amount_paise: int,
    note: str | None,
    checked: bool,
    auto_enrol: bool = True,
) -> dict[str, Any]:
    """Verify one claim. ``auto_enrol=False`` (Verify & Add to Batch) leaves enrolment to the
    caller, which creates the account and picks the batch itself."""
    if checked is not True:
        raise vf(
            "checked",
            "confirmation_required",
            "Confirm that you found this payment in the bank account or UPI app.",
        )
    if amount_paise <= 0:
        raise vf("amount_paise", "invalid_amount", "Enter the amount received.")
    c, reg = await lock_claim(session, claim_id)
    if c.status == "verified" and c.verified_amount_paise == amount_paise:
        # Approve pressed twice (double tap, two reviewers, a retried request): the money is
        # already counted, so nothing moves. Enrolment is retried in case it didn't finish the
        # first time (e.g. the plan was linked to a course since).
        out = (
            await finish_enrolment(session, actor, reg)
            if auto_enrol
            else {"registration": registration_out(reg, full=True), "enrolled": reg.enrolled_at is not None}
        )
        return {**out, "claim": claim_out(c), "already_verified": True}
    if not R.can_move_claim(c.status, "verified"):
        raise ProblemError(
            "invalid_state_transition",
            detail=f"This payment is already {c.status.replace('_', ' ')}.",
            current_state=c.status,
            allowed=["pending", "needs_info"],
        )
    total = reg.verified_total_paise + amount_paise
    if total > reg.fee_paise:
        raise vf(
            "amount_paise",
            "above_fee",
            f"That would make the verified total {R.rupees(total)}, more than the fee of "
            f"{R.rupees(reg.fee_paise)}. "
            "Check the amount, or adjust the fee first.",
        )
    now = utcnow()
    c.status, c.verified_amount_paise = "verified", amount_paise
    c.reviewed_by, c.reviewed_at, c.review_note = actor.user_id, now, (note or "").strip()[:500] or None
    reg.verified_total_paise = total
    reg.open_claims = max(0, reg.open_claims - 1)
    _restatus(reg)
    await ads.flush(session)
    await trail(
        session,
        actor,
        "payment.verified",
        reg.id,
        claim_id=c.id,
        amount=amount_paise,
        detail=f"{R.rupees(amount_paise)} verified (claimed {R.rupees(c.amount_paise)}) · ref {c.utr or '-'}",
    )
    await audit(
        session,
        actor.audit_actor(),
        "admissions.payment.verified",
        "admission_payment_claim",
        c.id,
        after={"amount_paise": amount_paise, "claimed_paise": c.amount_paise, "verified_total_paise": total},
    )
    await _emit(session, "payment_verified", reg, claim_id=c.id, amount_paise=amount_paise)
    out = (
        await finish_enrolment(session, actor, reg)
        if auto_enrol
        else {"registration": registration_out(reg, full=True), "enrolled": reg.enrolled_at is not None}
    )
    return {**out, "claim": claim_out(c), "already_verified": False}


async def decide_claim(
    session: AsyncSession,
    actor: Actor,
    claim_id: uuid.UUID,
    to: str,
    reason: str | None,
    *,
    release: bool = False,
) -> dict[str, Any]:
    assert to in ("needs_info", "rejected")
    text = _reason(
        reason,
        "reason",
        "Write the reason for rejecting." if to == "rejected" else "Write what the student should correct.",
    )
    c, reg = await lock_claim(session, claim_id)
    if not R.can_move_claim(c.status, to):
        raise ProblemError(
            "invalid_state_transition",
            detail=f"This payment is already {c.status.replace('_', ' ')}.",
            current_state=c.status,
            allowed=["pending"] if to == "needs_info" else ["pending", "needs_info"],
        )
    c.status, c.reviewed_by, c.reviewed_at, c.review_note = to, actor.user_id, utcnow(), text
    if to == "rejected":
        reg.open_claims = max(0, reg.open_claims - 1)
        if release:
            c.locks_released = True
    _restatus(reg)
    await ads.flush(session)
    await trail(
        session,
        actor,
        "payment.rejected" if to == "rejected" else "payment.correction",
        reg.id,
        claim_id=c.id,
        amount=c.amount_paise,
        detail=f"{R.rupees(c.amount_paise)} · ref {c.utr or '-'} · {text}",
    )
    await audit(
        session,
        actor.audit_actor(),
        f"admissions.payment.{to}",
        "admission_payment_claim",
        c.id,
        reason=text,
        after={"released_locks": bool(release and to == "rejected")},
    )
    await _emit(
        session, "claim_rejected" if to == "rejected" else "claim_needs_info", reg, claim_id=c.id, reason=text
    )
    return {"claim": claim_out(c), "registration": registration_out(reg, full=True)}


async def reverse_claim(
    session: AsyncSession, actor: Actor, claim_id: uuid.UUID, reason: str | None
) -> dict[str, Any]:
    text = _reason(reason, "reason", "Write why this verification is being reversed.")
    c, reg = await lock_claim(session, claim_id)
    if not R.can_move_claim(c.status, "reversed"):
        raise ProblemError(
            "invalid_state_transition",
            detail="Only a verified payment can be reversed.",
            current_state=c.status,
            allowed=["verified"],
        )
    c.status, c.reviewed_by, c.reviewed_at, c.review_note = "reversed", actor.user_id, utcnow(), text
    reg.verified_total_paise -= c.verified_amount_paise
    _restatus(reg)
    await ads.flush(session)
    await trail(
        session,
        actor,
        "payment.reversed",
        reg.id,
        claim_id=c.id,
        amount=-c.verified_amount_paise,
        detail=f"{R.rupees(c.verified_amount_paise)} reversed · {text}",
    )
    await audit(
        session,
        actor.audit_actor(),
        "admissions.payment.reversed",
        "admission_payment_claim",
        c.id,
        reason=text,
        after={"amount_paise": c.verified_amount_paise, "verified_total_paise": reg.verified_total_paise},
    )
    warning = None
    if reg.enrolled_at is not None and reg.verified_total_paise < reg.access_min_paise:
        await revoke_access(session, actor, reg, f"Verified total fell below the access threshold: {text}")
        warning = "Course access was removed: the verified total is now below the access threshold."
    return {"claim": claim_out(c), "registration": registration_out(reg, full=True), "warning": warning}


async def release_locks(session: AsyncSession, actor: Actor, claim_id: uuid.UUID) -> dict[str, Any]:
    c, reg = await lock_claim(session, claim_id)
    if c.status in ("pending", "needs_info", "verified"):
        raise ProblemError(
            "invalid_state_transition",
            detail="Only a rejected or reversed claim's reference and screenshot can be used again.",
            current_state=c.status,
            allowed=["rejected", "reversed"],
        )
    if not c.locks_released:
        c.locks_released = True
        await ads.flush(session)
        await trail(
            session,
            actor,
            "payment.released",
            reg.id,
            claim_id=c.id,
            detail=f"Reference {c.utr or '-'} and screenshot may be used again",
        )
        await audit(
            session, actor.audit_actor(), "admissions.payment.released", "admission_payment_claim", c.id
        )
    return {"claim": claim_out(c)}


async def record_payment(
    session: AsyncSession,
    actor: Actor,
    reg_id: uuid.UUID,
    *,
    amount_paise: int,
    method: str,
    utr: str | None,
    paid_on: date,
    note: str | None,
    checked: bool,
) -> dict[str, Any]:
    """Money received outside the form (cash, a direct transfer): verified at once."""
    if checked is not True:
        raise vf("checked", "confirmation_required", "Confirm that this money was received.")
    if amount_paise <= 0:
        raise vf("amount_paise", "invalid_amount", "Enter the amount received.")
    if method not in R.STAFF_METHODS:
        raise vf("method", "invalid_method", "Choose how the money was received.")
    ref = R.normalize_ref(utr) or None
    if ref and not R.STAFF_REF_RE.match(ref):
        raise vf("utr", "invalid_reference", "The reference should be letters and digits only.")
    if paid_on > ist_date(utcnow()):
        raise vf("paid_on", "invalid_date", "The date can't be in the future.")
    reg = await lock_registration(session, reg_id)
    await _check_locks(session, ref, None)
    total = reg.verified_total_paise + amount_paise
    if total > reg.fee_paise:
        raise vf(
            "amount_paise",
            "above_fee",
            f"That would take the verified total above the fee ({R.rupees(reg.fee_paise)}).",
        )
    now = utcnow()
    c = AdmissionPaymentClaim(
        id=uuid7(),
        registration_id=reg.id,
        provider="admin_entry",
        method=method,
        amount_paise=amount_paise,
        utr=ref,
        paid_on=paid_on,
        note=(note or "").strip()[:500] or None,
        status="verified",
        verified_amount_paise=amount_paise,
        reviewed_by=actor.user_id,
        reviewed_at=now,
        submitted_at=now,
    )
    ads.add(session, c)
    reg.verified_total_paise = total
    _restatus(reg)
    await ads.flush(session)
    await trail(
        session,
        actor,
        "payment.recorded",
        reg.id,
        claim_id=c.id,
        amount=amount_paise,
        detail=f"{R.rupees(amount_paise)} {method} entered by the team{f' · ref {ref}' if ref else ''}",
    )
    await audit(
        session,
        actor.audit_actor(),
        "admissions.payment.recorded",
        "admission_payment_claim",
        c.id,
        after={"amount_paise": amount_paise, "method": method},
    )
    await _emit(session, "payment_verified", reg, claim_id=c.id, amount_paise=amount_paise)
    return await finish_enrolment(session, actor, reg)


async def set_status(
    session: AsyncSession, actor: Actor, reg_id: uuid.UUID, status: str, reason: str | None
) -> dict[str, Any]:
    if status not in ("rejected", "cancelled", "completed", "reopen"):
        raise vf("status", "invalid_status", "Unknown status.")
    text = (reason or "").strip()[:500]
    if status != "completed" and len(text) < 4:
        raise vf("reason", "reason_required", "Write a short reason.")
    reg = await lock_registration(session, reg_id)
    before = reg.status
    ending = status in ("rejected", "cancelled")
    if status == "reopen":
        if before not in R.MANUAL_STATUSES:
            raise ProblemError(
                "invalid_state_transition",
                detail="Only a closed registration can be reopened.",
                current_state=before,
                allowed=sorted(R.MANUAL_STATUSES),
            )
        if before in R.ENDED_STATUSES:
            other = (
                await ads.execute(
                    session,
                    select(AdmissionRegistration.id).where(
                        AdmissionRegistration.course_slug == reg.course_slug,
                        AdmissionRegistration.email == reg.email,
                        AdmissionRegistration.id != reg.id,
                        AdmissionRegistration.status.not_in(tuple(R.ENDED_STATUSES)),
                    ),
                )
            ).first()
            if other:
                raise ProblemError(
                    "invalid_state_transition",
                    detail="The student has registered for this course "
                    "again since; reopen that registration instead.",
                )
        _restatus(reg, current="registered")
    else:
        if before == status:
            raise ProblemError(
                "invalid_state_transition",
                detail=f"The registration is already {status}.",
                current_state=before,
                allowed=[],
            )
        if ending and reg.enrolled_at is not None:
            await revoke_access(session, actor, reg, f"Registration {status}: {text}")
        reg.status = status
    reg.status_note = text or None
    await ads.flush(session)
    await trail(
        session,
        actor,
        f"registration.{status}",
        reg.id,
        detail=f"{before} -> {reg.status}{f' · {text}' if text else ''}",
    )
    await audit(
        session,
        actor.audit_actor(),
        f"admissions.registration.{status}",
        "admission_registration",
        reg.id,
        reason=text or None,
        before={"status": before},
        after={"status": reg.status},
    )
    out: dict[str, Any] = {"registration": registration_out(reg, full=True)}
    if status == "reopen":
        out |= await finish_enrolment(session, actor, reg)
    return out


async def set_contact(
    session: AsyncSession,
    actor: Actor,
    reg_id: uuid.UUID,
    *,
    name: str | None,
    email: str | None,
    phone: str | None,
) -> dict[str, Any]:
    reg = await lock_registration(session, reg_id)
    changed = []
    if name is not None and name.strip() != reg.name:
        if len(name.strip()) < 2:
            raise vf("name", "invalid_name", "Enter the student's name.")
        reg.name = name.strip()[:120]
        changed.append("name")
    if email is not None and email != reg.email:
        if (
            reg.status not in R.ENDED_STATUSES
            and (
                await ads.execute(
                    session,
                    select(AdmissionRegistration.id).where(
                        AdmissionRegistration.course_slug == reg.course_slug,
                        AdmissionRegistration.email == email,
                        AdmissionRegistration.id != reg.id,
                        AdmissionRegistration.status.not_in(tuple(R.ENDED_STATUSES)),
                    ),
                )
            ).first()
        ):
            raise conflict(
                "email", "already_registered", "That email already has a registration for this course."
            )
        reg.email = email
        changed.append("email")
    if phone is not None and phone != reg.phone:
        reg.phone = phone
        changed.append("mobile")
    if not changed:
        return {"registration": registration_out(reg, full=True), "changed": []}
    await ads.flush(session)
    await trail(session, actor, "registration.contact", reg.id, detail=f"Changed {', '.join(changed)}")
    await audit(
        session,
        actor.audit_actor(),
        "admissions.registration.contact",
        "admission_registration",
        reg.id,
        after={"changed": changed},
    )
    warning = None
    if "email" in changed and reg.enrolled_at is not None:
        warning = (
            "This student is already enrolled: course access stays with the LMS account of the old email. "
            "Change the email on that account (Admin > Users) if needed."
        )
    return {"registration": registration_out(reg, full=True), "changed": changed, "warning": warning}


async def adjust_fee(
    session: AsyncSession, actor: Actor, reg_id: uuid.UUID, fee_paise: int, reason: str | None
) -> dict[str, Any]:
    text = _reason(reason, "reason", "Write why the fee is changing.")
    if not (0 <= fee_paise <= R.MAX_FEE_PAISE):
        raise vf("fee_paise", "invalid_fee", "Enter a fee between Rs 0 and Rs 10,00,000.")
    reg = await lock_registration(session, reg_id)
    if fee_paise < reg.verified_total_paise:
        raise vf(
            "fee_paise",
            "below_verified",
            f"The fee can't be lower than what's already verified ({R.rupees(reg.verified_total_paise)}).",
        )
    old = reg.fee_paise
    reg.fee_paise = fee_paise
    reg.access_min_paise = fee_paise if reg.policy == "full" else min(reg.access_min_paise, fee_paise)
    reg.min_first_paise = min(reg.min_first_paise, fee_paise)
    _restatus(reg)
    await ads.flush(session)
    await trail(
        session,
        actor,
        "registration.fee",
        reg.id,
        amount=fee_paise - old,
        detail=f"Fee {R.rupees(old)} -> {R.rupees(fee_paise)} · {text}",
    )
    await audit(
        session,
        actor.audit_actor(),
        "admissions.registration.fee",
        "admission_registration",
        reg.id,
        reason=text,
        before={"fee_paise": old},
        after={"fee_paise": fee_paise},
    )
    return await finish_enrolment(session, actor, reg)


# --------------------------------------------------------------------------- enrolment


async def finish_enrolment(session: AsyncSession, actor: Actor, reg: AdmissionRegistration) -> dict[str, Any]:
    """After money moves: enrol when the access policy is met. Never fails the money change; a
    problem (plan not linked, course unpublished) is reported as ``warning``."""
    out: dict[str, Any] = {
        "registration": registration_out(reg, full=True),
        "enrolled": reg.enrolled_at is not None,
    }
    if reg.enrolled_at is not None or not R.eligible(
        status=reg.status,
        verified=reg.verified_total_paise,
        access_min=reg.access_min_paise,
        fee=reg.fee_paise,
    ):
        return out
    if actor.principal is None:  # only staff decisions enrol
        return out
    try:
        async with await ads.begin_nested(session):
            created = await enrol(session, actor, reg)
    except ProblemError as e:
        await ads.refresh(session, reg)
        out["registration"] = registration_out(reg, full=True)
        out["warning"] = f"Payment saved, but enrolment didn't finish: {e.detail}"
        return out
    out["registration"] = registration_out(reg, full=True)
    out["enrolled"] = True
    out["just_enrolled"] = True
    out["new_account"] = created
    return out


async def _course_and_batch(
    session: AsyncSession, reg: AdmissionRegistration, batch_id: uuid.UUID | None = None
) -> tuple[Any, Any]:
    """The LMS course and batch to enrol into: the fee plan's, or ``batch_id`` (chosen by staff in
    Verify & Add to Batch) for the batch."""
    from app.modules.catalog import api as catalog_api

    plan = await ads.get(session, AdmissionFeePlan, reg.fee_plan_id)
    if batch_id is not None:
        batch = await orgs_public.get_batch(session, batch_id)
        if batch is None:
            raise vf("batch_id", "unknown_batch", "Choose an existing batch.")
        if batch.status == "archived":
            raise ProblemError(
                "invalid_state_transition", detail="That batch is archived. Choose a current batch."
            )
    else:
        batch = await orgs_public.get_batch(session, plan.batch_id) if plan and plan.batch_id else None
    if batch is not None and batch.status == "archived":
        raise ProblemError(
            "invalid_state_transition",
            detail="The batch linked to this fee plan is archived. "
            "Link the plan to a current batch (Admissions > Fee plans).",
        )
    course_id = (plan.course_id if plan else None) or (getattr(batch, "course_id", None) if batch else None)
    if course_id is None and batch is None:
        raise ProblemError(
            "invalid_state_transition",
            detail="This course's fee plan isn't linked to an LMS course "
            "or batch. Open Admissions > Fee plans, link it, then press Enrol.",
        )
    course = None
    if course_id is not None:
        course = (await catalog_api.get_courses(session, [course_id])).get(course_id)
        if course is None or course.deleted_at is not None:
            raise ProblemError(
                "invalid_state_transition", detail="The LMS course linked to this fee plan was not found."
            )
        if course.status != "published" or course.current_version_id is None:
            raise ProblemError(
                "invalid_state_transition",
                detail="The LMS course linked to this fee plan isn't published yet.",
            )
    return course, batch


async def find_or_create_user(
    session: AsyncSession, actor: Actor, reg: AdmissionRegistration
) -> tuple[Any, bool]:
    from app.modules.identity import service as ids
    from app.modules.identity.public import User, UserProfile

    user = None
    if reg.user_id is not None:
        # Registered from inside the LMS (signed in): enrol that account, whatever its email.
        user = await identity_public.get_user(session, reg.user_id)
    if user is None:
        user = await ids.find_user(session, "email", reg.email)
    if user is not None:
        if user.status in ("deactivated", "deleted"):
            raise ProblemError(
                "invalid_state_transition",
                detail="The LMS account for this email is deactivated. "
                "Reactivate it (Admin > Users) or correct the email, then press Enrol.",
            )
        return user, False
    now = utcnow()
    uid = uuid7()
    user = User(
        id=uid,
        email=reg.email,
        # Staff verified this person's payment and the account is unusable until the password-set
        # link sent to this address is used, which proves the inbox (like staff-created accounts).
        email_verified_at=now,
        status="active",
        is_minor=False,
        age_verified_at=now,
        age_verification_method="self_declared",
        account_origin="staff_created",
    )
    await identity_public.create_user(session, user, UserProfile(user_id=uid, full_name=reg.name))
    await audit(
        session,
        actor.audit_actor(),
        "admin.user.created",
        "user",
        uid,
        subject_user_id=uid,
        reason=f"Admissions enrolment {reg.reg_no}",
        after={"status": "active", "account_origin": "staff_created", "source": "admissions"},
    )
    await emit_event(
        session,
        "identity.user_registered",
        {"user_id": str(uid), "is_minor": False},
        aggregate_type="user",
        aggregate_id=uid,
    )
    return user, True


async def enrol(
    session: AsyncSession,
    actor: Actor,
    reg: AdmissionRegistration,
    *,
    batch_id: uuid.UUID | None = None,
    login_details: bool = False,
) -> bool:
    """Give course access (entitlement + enrolment) and batch membership; True when a new LMS
    account was created for the registration's email.

    ``batch_id`` overrides the fee plan's batch; ``login_details`` tells the "enrolled" email that
    the sign-in details (username + temporary password) come in a separate email."""
    from app.modules.entitlements import public as ent_public
    from app.modules.entitlements import service as ent
    from app.modules.identity import service as ids
    from app.modules.learning import service as learning
    from app.modules.orgs.public import BatchMember
    from app.modules.orgs.service import ensure_org_membership

    assert actor.principal is not None
    course, batch = await _course_and_batch(session, reg, batch_id)
    now = utcnow()
    async with as_system(session, "admissions.enrol"):
        user, created = await find_or_create_user(session, actor, reg)
        if batch is not None:
            await ensure_org_membership(
                session, batch.organization_id, user.id, member_type="student", added_by=actor.user_id
            )
            found = await orgs_public.batch_members(
                session, batch_ids=[batch.id], user_ids=[user.id], member_role="student"
            )
            live = found[0] if found else None
            if live is None:
                live = BatchMember(
                    id=uuid7(),
                    batch_id=batch.id,
                    organization_id=batch.organization_id,
                    user_id=user.id,
                    member_role="student",
                    added_by=actor.user_id,
                )
                live = await orgs_public.add_batch_member(session, live)
            reg.batch_member_id = live.id
            reg.enrolled_batch_id = batch.id
        if course is not None:
            e_row = (
                await ent_public.get_entitlement(session, reg.entitlement_id) if reg.entitlement_id else None
            )
            if e_row is None or e_row.status == "revoked":
                e_row, _ = await ent.grant(
                    session,
                    ent.Actor.user(actor.principal),
                    user_id=user.id,
                    source_type="admin_grant",
                    course_id=course.id,
                    granted_by=actor.user_id,
                    starts_at=now,
                    ends_at=None,
                    reason=f"admissions {reg.reg_no}",
                    source_ref=reg.id,
                )
            reg.entitlement_id = e_row.id
            await learning.lock_enrolment(session, user.id, course.id)
            enr = await learning.get_enrolment(session, user.id, course.id)
            if enr is None:
                enr = await learning.create_enrolment(
                    session,
                    user_id=user.id,
                    course=course,
                    source="entitlement",
                    entitlement_id=e_row.id,
                    organization_id=batch.organization_id if batch is not None else None,
                    batch_id=batch.id if batch is not None else None,
                )
            elif enr.status not in ("active", "completed"):
                enr.status, enr.source, enr.entitlement_id, enr.expires_at = (
                    "active",
                    "entitlement",
                    e_row.id,
                    None,
                )
                await ads.flush(session)
            reg.enrolment_id = enr.id
            reg.enrolled_course_id = course.id
        reg.user_id = user.id
        reg.enrolled_at = now
        reg.status = "enrolled"
        await ads.flush(session)
        send_link = created or await ids.get_credential(session, user.id) is None
        if send_link:
            from app.modules.identity.router import issue_password_reset

            await issue_password_reset(session, user, ip=None, actor=actor.audit_actor())
    await trail(
        session,
        actor,
        "enrolment.activated",
        reg.id,
        detail=f"{reg.course_title}: course access given ({R.rupees(reg.verified_total_paise)} verified)"
        f"{' · new LMS account' if created else ''}",
    )
    await audit(
        session,
        actor.audit_actor(),
        "admissions.enrolment.activated",
        "admission_registration",
        reg.id,
        subject_user_id=user.id,
        after={
            "course_id": reg.enrolled_course_id,
            "batch_id": reg.enrolled_batch_id,
            "entitlement_id": reg.entitlement_id,
            "new_account": created,
        },
    )
    await _emit(
        session,
        "enrolled",
        reg,
        user_id=user.id,
        new_account=created,
        password_link=bool(send_link),
        login_details=login_details,
    )
    return bool(created)


async def revoke_access(session: AsyncSession, actor: Actor, reg: AdmissionRegistration, note: str) -> None:
    """Undo ``enrol``: revoke the entitlement, withdraw the enrolment, end the batch membership."""
    from app.modules.entitlements import public as ent_public
    from app.modules.entitlements import service as ent
    from app.modules.learning import public as learning_public
    from app.modules.orgs.service import end_student_membership_if_no_batches

    async with as_system(session, "admissions.revoke"):
        if reg.entitlement_id:
            e_row = await ent_public.get_entitlement(session, reg.entitlement_id, for_update=True)
            if e_row is not None and e_row.status != "revoked":
                ent_actor = (
                    ent.Actor.user(actor.principal) if actor.principal else ent.Actor.system("admissions")
                )
                await ent.revoke(
                    session, e_row, ent_actor, reason_code="admin", note=note[:300], source_ref=reg.id
                )
        if reg.enrolment_id:
            await learning_public.withdraw_enrolment(session, reg.enrolment_id, reg.entitlement_id)
        if reg.batch_member_id:
            bm = await orgs_public.get_batch_member(session, reg.batch_member_id)
            if bm is not None and bm.status == "active":
                bm.status, bm.removed_at = "removed", utcnow()
                await orgs_public.save_batch_member(session, bm)
                await end_student_membership_if_no_batches(session, bm.organization_id, bm.user_id)
        reg.enrolled_at = None
        reg.entitlement_id = None
        reg.batch_member_id = None
        _restatus(reg)
        await ads.flush(session)
    await trail(session, actor, "enrolment.revoked", reg.id, detail=f"Course access removed · {note}"[:400])
    await audit(
        session,
        actor.audit_actor(),
        "admissions.enrolment.revoked",
        "admission_registration",
        reg.id,
        subject_user_id=reg.user_id,
        reason=note[:300],
    )


async def manual_enrol(session: AsyncSession, actor: Actor, reg_id: uuid.UUID) -> dict[str, Any]:
    reg = await lock_registration(session, reg_id)
    if reg.enrolled_at is not None:
        return {"registration": registration_out(reg, full=True), "enrolled": True}
    if not R.eligible(
        status=reg.status,
        verified=reg.verified_total_paise,
        access_min=reg.access_min_paise,
        fee=reg.fee_paise,
    ):
        raise ProblemError(
            "invalid_state_transition",
            detail=(
                f"Not eligible yet: {R.rupees(reg.verified_total_paise)} verified of the "
                f"{R.rupees(reg.access_min_paise)} needed for access."
            ),
        )
    created = await enrol(session, actor, reg)
    return {
        "registration": registration_out(reg, full=True),
        "enrolled": True,
        "just_enrolled": True,
        "new_account": created,
    }


# --------------------------------------------------------------------------- plans / settings


async def save_pay_settings(session: AsyncSession, actor: Actor, body: dict[str, Any]) -> dict[str, Any]:
    import re

    digits = re.sub(r"\D", "", str(body.get("phone") or ""))
    digits = re.sub(r"^(91|0)(?=[6-9]\d{9}$)", "", digits)
    phone = digits if re.fullmatch(r"[6-9]\d{9}", digits) else None
    if body.get("phone") and phone is None:
        raise vf("phone", "invalid_mobile", "Enter a 10-digit Indian mobile number.")
    upi = str(body.get("upi_id") or "").strip() or None
    if upi and not R.UPI_ID_RE.match(upi):
        raise vf("upi_id", "invalid_upi", "The UPI ID doesn't look right (it should look like name@bank).")
    if not phone and not upi:
        raise vf(
            "phone",
            "pay_to_required",
            "Enter the 10-digit payment number (or a UPI ID) students should pay to.",
        )
    s = await pay_settings(session)
    if s is None:
        s = AdmissionPaySettings(id=1)
        ads.add(session, s)
    s.phone, s.upi_id = phone, upi
    s.preferred_app = str(body.get("preferred_app") or "").strip()[:40]
    s.payee_name = str(body.get("payee_name") or "").strip()[:80] or None
    s.instructions = str(body.get("instructions") or "").strip()[:800] or None
    s.updated_by, s.updated_at = actor.user_id, utcnow()
    await ads.flush(session)
    await audit(
        session,
        actor.audit_actor(),
        "admissions.pay_settings.updated",
        "admission_pay_settings",
        None,
        after={"has_phone": bool(phone), "has_upi": bool(upi), "preferred_app": s.preferred_app},
    )
    return pay_settings_out(s)


async def save_plan(session: AsyncSession, actor: Actor, body: dict[str, Any]) -> dict[str, Any]:

    slug = str(body.get("slug") or "").strip().lower()
    if not R.SLUG_RE.match(slug):
        raise vf(
            "slug", "invalid_slug", "Enter the website course slug (lower-case letters, digits and dashes)."
        )
    title = str(body.get("title") or "").strip()[:160]
    if not title:
        raise vf("title", "title_required", "Enter the course title.")
    terms = R.clean_terms(
        fee_paise=int(body.get("fee_paise") or 0),
        allow_instalments=bool(body.get("allow_instalments")),
        schedule=list(body.get("schedule") or []),
        min_first_paise=body.get("min_first_paise"),
        access_min_paise=body.get("access_min_paise"),
    )
    if terms.problems:
        raise vf("fee_paise", "invalid_plan", " ".join(terms.problems))
    upi = str(body.get("upi_id") or "").strip() or None
    if upi and not R.UPI_ID_RE.match(upi):
        raise vf("upi_id", "invalid_upi", "The UPI ID doesn't look right (it should look like name@bank).")
    batch_id = body.get("batch_id")
    if batch_id and await orgs_public.get_batch(session, batch_id) is None:
        raise vf("batch_id", "unknown_batch", "Choose an existing batch.")
    course_id = body.get("course_id")
    if course_id:
        from app.modules.catalog import api as catalog_api

        course = (await catalog_api.get_courses(session, [course_id])).get(course_id)
        if course is None or course.deleted_at is not None:
            raise vf(
                "course_id",
                "unknown_course",
                "No LMS course has that id. Leave it empty to use the batch's course.",
            )
    p = await plan_by_slug(session, slug)
    plan_id = body.get("fee_plan_id")
    if plan_id is not None:
        # Edit of an existing plan: the slug keys the course status, the website page and the
        # registrations, so it can't move (saving under another slug used to create a second plan).
        current = await ads.get(session, AdmissionFeePlan, plan_id)
        if current is None:
            raise ProblemError("not_found", detail="That fee plan no longer exists. Reload the page.")
        if current.course_slug != slug:
            raise conflict(
                "slug",
                "slug_locked",
                "The website course slug of a saved plan can't be changed. "
                "Add a new fee plan for the other course.",
            )
    payee = str(body.get("payee_name") or "").strip()[:80] or None
    bank = str(body.get("bank_details") or "").strip()[:600] or None
    active = bool(body.get("active"))
    # Checked before anything is written (a new slug also inserts its course status row).
    if active and not _pay_to_ok(upi, bank, pay_settings_out(await pay_settings(session))):
        raise _pay_to_missing()
    created = p is None
    if p is None:
        p = AdmissionFeePlan(id=uuid7(), course_slug=slug)
        ads.add(session, p)
    p.title = title
    p.course_id, p.batch_id = course_id or None, batch_id or None
    p.fee_paise, p.allow_instalments = terms.fee_paise, terms.allow_instalments
    p.schedule = [x.as_dict() for x in terms.schedule]
    p.policy, p.min_first_paise, p.access_min_paise = (
        terms.policy,
        terms.min_first_paise,
        terms.access_min_paise,
    )
    p.upi_id = upi
    p.payee_name = payee
    p.bank_details = bank
    p.instructions = str(body.get("instructions") or "").strip()[:800] or None
    p.active = active
    p.updated_by, p.updated_at = actor.user_id, utcnow()
    if created:
        from app.modules.admissions import courses

        await courses.ensure_row(session, slug)
    await ads.flush(session)
    await audit(
        session,
        actor.audit_actor(),
        "admissions.fee_plan.saved",
        "admission_fee_plan",
        p.id,
        after={
            "slug": slug,
            "fee_paise": p.fee_paise,
            "instalments": len(p.schedule),
            "active": p.active,
            "created": created,
        },
    )
    return await _plan_with_status(session, p)


def _pay_to_ok(plan_upi: str | None, plan_bank: str | None, pay: dict[str, Any]) -> bool:
    return bool(pay.get("phone") or pay.get("upi_id") or plan_upi or plan_bank)


def _pay_to_missing() -> ProblemError:
    return vf(
        "active",
        "pay_to_missing",
        "Set the payment number in Payment details (or this course's UPI ID / "
        "bank details) before opening online registration.",
    )


async def _plan_with_status(session: AsyncSession, p: AdmissionFeePlan) -> dict[str, Any]:
    """``plan_out(staff)`` + the course's registration switch (``course_status``) and what
    students see (``effective_status``): an ``open`` course whose plan is off reads ``closed``."""
    from app.modules.admissions import courses

    raw = await courses.raw_status(session, p.course_slug)
    return {
        **plan_out(p, staff=True),
        "course_status": raw or courses.DEFAULT,
        "effective_status": courses.effective(raw, p),
    }


async def set_plan_active(session: AsyncSession, actor: Actor, slug: str, active: bool) -> dict[str, Any]:
    """Switch one plan on / off without resending (and overwriting) the rest of it."""
    p = await plan_by_slug(session, slug.strip().lower())
    if p is None:
        raise ProblemError("not_found", detail="That fee plan no longer exists. Reload the page.")
    await ads.get(session, AdmissionFeePlan, p.id, with_for_update=True)
    if active:
        terms = plan_terms(p)
        if terms.problems:
            raise vf("fee_paise", "invalid_plan", " ".join(terms.problems))
        if not _pay_to_ok(p.upi_id, p.bank_details, pay_settings_out(await pay_settings(session))):
            raise _pay_to_missing()
    before = p.active
    p.active = active
    p.updated_by, p.updated_at = actor.user_id, utcnow()
    await ads.flush(session)
    await audit(
        session,
        actor.audit_actor(),
        "admissions.fee_plan.saved",
        "admission_fee_plan",
        p.id,
        before={"active": before},
        after={"slug": p.course_slug, "active": active, "created": False},
    )
    return await _plan_with_status(session, p)


# --------------------------------------------------------------------------- figures


async def overview(session: AsyncSession) -> dict[str, Any]:
    if ads.on_firestore():
        # Firestore (SQL engine): registrations and claims are each read ONCE and grouped here
        # (the Postgres statements below read registrations twice and claims twice: a
        # GROUP BY, then a join for the pending count per course). Same numbers.
        reg_rows = (
            await ads.execute(
                session,
                select(
                    AdmissionRegistration.id,
                    AdmissionRegistration.course_slug,
                    AdmissionRegistration.course_title,
                    AdmissionRegistration.status,
                    AdmissionRegistration.fee_paise,
                    AdmissionRegistration.verified_total_paise,
                    AdmissionRegistration.balance_paise,
                ),
            )
        ).all()
        regs = [tuple(r[1:]) for r in reg_rows]
        slug_of = {r[0]: r[1] for r in reg_rows}
        grouped: dict[str, list[int]] = {}
        pending_by_course: dict[str, int] = {}
        for status, amount, reg_id in (
            await ads.execute(
                session,
                select(
                    AdmissionPaymentClaim.status,
                    AdmissionPaymentClaim.amount_paise,
                    AdmissionPaymentClaim.registration_id,
                ),
            )
        ).all():
            g = grouped.setdefault(status, [0, 0])
            g[0] += 1
            g[1] += amount or 0
            if status == "pending" and reg_id in slug_of:
                pending_by_course[slug_of[reg_id]] = pending_by_course.get(slug_of[reg_id], 0) + 1
        claim_rows: Any = [(st, n, a) for st, (n, a) in grouped.items()]
    else:
        regs = (
            await ads.execute(
                session,
                select(
                    AdmissionRegistration.course_slug,
                    AdmissionRegistration.course_title,
                    AdmissionRegistration.status,
                    AdmissionRegistration.fee_paise,
                    AdmissionRegistration.verified_total_paise,
                    AdmissionRegistration.balance_paise,
                ),
            )
        ).all()
        claim_rows = (
            await ads.execute(
                session,
                select(
                    AdmissionPaymentClaim.status,
                    func.count(),
                    func.coalesce(func.sum(AdmissionPaymentClaim.amount_paise), 0),
                ).group_by(AdmissionPaymentClaim.status),
            )
        ).all()
        pending_by_course = dict(
            (
                await ads.execute(
                    session,
                    select(AdmissionRegistration.course_slug, func.count())
                    .join(
                        AdmissionPaymentClaim,
                        AdmissionPaymentClaim.registration_id == AdmissionRegistration.id,
                    )
                    .where(AdmissionPaymentClaim.status == "pending")
                    .group_by(AdmissionRegistration.course_slug),
                )
            ).all()
        )
    claims = {s: (int(n), int(a)) for s, n, a in claim_rows}
    courses: dict[str, dict[str, Any]] = {}
    for slug, title, status, fee, verified, balance in regs:
        c = courses.setdefault(
            slug,
            {
                "slug": slug,
                "title": title,
                "registered": 0,
                "enrolled": 0,
                "expected_paise": 0,
                "collected_paise": 0,
                "outstanding_paise": 0,
                "pending": 0,
                "rejected": 0,
            },
        )
        c["registered"] += 1
        c["enrolled"] += status in ("enrolled", "completed")
        c["collected_paise"] += verified
        if status not in R.ENDED_STATUSES:
            c["expected_paise"] += fee
            c["outstanding_paise"] += max(0, balance)
        c["rejected"] += status == "rejected"
    for slug, n in pending_by_course.items():
        if slug in courses:
            courses[slug]["pending"] = int(n)
    rows = sorted(courses.values(), key=lambda c: c["title"])
    total = lambda k: sum(c[k] for c in rows)  # noqa: E731
    events = (
        await ads.execute(
            session,
            select(AdmissionEvent).order_by(AdmissionEvent.at.desc(), AdmissionEvent.id.desc()).limit(20),
        )
    ).scalars()
    return {
        "registered": len(regs),
        "enrolled": total("enrolled"),
        "pending_claims": claims.get("pending", (0, 0))[0],
        "pending_amount_paise": claims.get("pending", (0, 0))[1],
        "needs_info_claims": claims.get("needs_info", (0, 0))[0],
        "rejected_claims": claims.get("rejected", (0, 0))[0],
        "closed_registrations": sum(1 for r in regs if r[2] in R.ENDED_STATUSES),
        "collected_paise": total("collected_paise"),
        "expected_paise": total("expected_paise"),
        "outstanding_paise": total("outstanding_paise"),
        "courses": rows,
        "recent": [event_out(e) for e in events],
    }
