"""Signed-in student admissions: register for a course and upload payment proofs inside the LMS.

* ``GET  /me/admissions``               — my registrations (status, balance, claims, reasons).
* ``GET  /me/admissions/plans/{slug}``  — a course's fee plan + where to pay + form prefill + my
  registration for it (``plan`` is null when online registration isn't open: never a 404).
* ``POST /me/admissions/registrations`` — registration + first payment claim (base64 proof).
* ``POST /me/admissions/claims``        — another payment claim on one of MY registrations.

Same workflow as the public website routes (``service.register`` / ``service.add_claim``), but the
registration is bound to the signed-in account: the email is the account's email (never typed)
and ``user_id`` is set at once, so staff approval enrols THIS account (``find_or_create_user``)
and the student needs no registration number + email lookup. Rate limits and file validation are
the public ones (per account instead of per client IP).
"""

from __future__ import annotations

import uuid
from typing import Any

import structlog
from fastapi import Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select

from app.core import ratelimit as rl
from app.core.auth import require_active_principal
from app.core.db import as_system
from app.core.errors import ProblemError
from app.core.firestore.sqlstore import StorePrincipalDbSession as PrincipalDbSession
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.modules.admissions import courses
from app.modules.admissions import datastore as ads
from app.modules.admissions import files as fs
from app.modules.admissions import rules as R
from app.modules.admissions import service as sv
from app.modules.admissions.models import AdmissionFeePlan, AdmissionPaymentClaim, AdmissionRegistration
from app.modules.admissions.public import AdmissionClaimIn, AdmissionFileIn, _one_line, _reg_no
from app.modules.identity import public as identity_public
from app.modules.orgs import public as orgs_public

log = structlog.get_logger("app.admissions.student")

me = authenticated_router(prefix="/me/admissions", tags=["admissions"])
ME = Depends(require_active_principal)

LIMITS_READ = (rl.Rule(240, rl.HOUR),)
LIMITS_WRITE = (rl.Rule(10, rl.HOUR), rl.Rule(30, rl.DAY))
# JSON bodies carry one base64 proof (<= 2 MiB -> ~2.8 MB of base64).
BODY_LIMIT = 4 * 1024 * 1024
REGISTER_PATH = "/api/v1/me/admissions/registrations"
CLAIM_PATH = "/api/v1/me/admissions/claims"


class MyRegistrationIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    course_slug: str = Field(min_length=1, max_length=80)
    # shown to the student as the payment note before submitting (the QR's note), like the website
    reg_no: str | None = Field(default=None, max_length=20)
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=10, max_length=20)
    college: str = Field(min_length=1, max_length=160)
    branch: str = Field(min_length=1, max_length=60)
    year: str = Field(min_length=1, max_length=30)
    consent: bool
    claim: AdmissionClaimIn
    proof: AdmissionFileIn

    @field_validator("name", "college", "branch", "year")
    @classmethod
    def _single_line(cls, v: str | None) -> str | None:
        return _one_line(v)


class MyClaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    registration_id: uuid.UUID
    claim: AdmissionClaimIn
    proof: AdmissionFileIn


# --------------------------------------------------------------------------- helpers


async def _account(session: Any, principal: Principal) -> tuple[Any, Any]:

    user = await identity_public.get_user(session, principal.user_id)
    if user is None:
        raise ProblemError("not_found")
    profile = await identity_public.get_profile(session, principal.user_id)
    return user, profile


def _account_email(user: Any) -> str:
    email = (user.email or "").strip().lower()
    if not email:
        raise sv.vf(
            "email",
            "email_required",
            "Add an email address to your account (Settings > Account) before registering for a course.",
        )
    return email


def _verified_email(user: Any) -> str | None:
    """The account's email for matching website registrations -- only once the address is
    verified. An unverified self-signup email proves nothing: matching on it would let anyone
    who signs up with a website registrant's address read that registration and link it to
    their own account (RBAC audit 2026-11-13)."""
    if getattr(user, "email_verified_at", None) is None:
        return None
    return (user.email or "").strip().lower() or None


def _mine(user_id: uuid.UUID, email: str | None) -> Any:
    """Registrations of this account: linked to it, or made on the website with its email."""
    cond = AdmissionRegistration.user_id == user_id
    return or_(cond, AdmissionRegistration.email == email) if email else cond


def _payment(plan: AdmissionFeePlan, pay: dict[str, Any]) -> dict[str, Any]:
    """Where to pay, resolved the way the website does (site-wide settings first, then the plan)."""
    return {
        "upi_id": pay.get("upi_id") or plan.upi_id or "",
        "payee_name": pay.get("payee_name") or plan.payee_name or "",
        "phone": pay.get("phone") or "",
        "preferred_app": pay.get("preferred_app") or "",
        "bank_details": plan.bank_details or "",
        "instructions": [t for t in (pay.get("instructions"), plan.instructions) if t],
    }


def _first_options(t: R.PlanTerms) -> list[dict[str, Any]]:
    """Amounts the student can pay first: the full fee, or the first instalment."""
    opts = [{"label": "Full fee", "amount_paise": t.fee_paise}]
    if t.allow_instalments and t.schedule:
        first = max(t.schedule[0].amount_paise, t.min_first_paise)
        if 0 < first < t.fee_paise:
            opts.append({"label": t.schedule[0].label, "amount_paise": first})
    return opts


def _pay_options(reg: AdmissionRegistration) -> list[dict[str, Any]]:
    """What the student can pay next on a registration (the next instalment, or the balance)."""
    if reg.balance_paise <= 0:
        return []
    t = sv.reg_terms(reg)
    opts: list[dict[str, Any]] = []
    nd = R.next_due(t, reg.verified_total_paise)
    if t.allow_instalments and nd and 0 < nd["amount_paise"] < reg.balance_paise:
        opts.append({"label": nd["label"], "amount_paise": nd["amount_paise"]})
    opts.append(
        {
            "label": "Full balance" if reg.verified_total_paise else "Full fee",
            "amount_paise": reg.balance_paise,
        }
    )
    return opts


def _claim_view(c: AdmissionPaymentClaim) -> dict[str, Any]:
    return {
        "claim_id": str(c.id),
        "amount_paise": c.amount_paise,
        "method": c.method,
        "utr": c.utr,
        "paid_on": sv.iso(c.paid_on),
        "status": c.status,
        # staff notes are written for the student only on needs-info / rejection
        "reason": c.review_note if c.status in ("needs_info", "rejected") else None,
        "proof_name": c.proof_name,
        "submitted_at": sv.iso(c.submitted_at),
        "reviewed_at": sv.iso(c.reviewed_at),
    }


def student_state(reg: AdmissionRegistration, claims: list[AdmissionPaymentClaim]) -> tuple[str, str | None]:
    """One state for the student's screen + the reason to show (staff note), newest claim first."""
    if reg.enrolled_at is not None or reg.status in ("enrolled", "completed"):
        return "enrolled", None
    if reg.status == "rejected":
        return "rejected", reg.status_note
    if reg.status == "cancelled":
        return "cancelled", reg.status_note
    latest = claims[0] if claims else None
    if latest is not None and latest.status == "needs_info":
        return "needs_info", latest.review_note
    if reg.open_claims > 0:
        return "pending", None
    if reg.status == "payment_verified":
        return "verified", None
    if latest is not None and latest.status == "rejected":
        return "payment_rejected", latest.review_note
    if reg.status == "partially_paid":
        return "partially_paid", None
    return "awaiting_payment", None


async def _course_hrefs(session: Any, regs: list[AdmissionRegistration]) -> dict[uuid.UUID, str]:
    from app.modules.catalog import public as catalog

    ids = {r.enrolled_course_id for r in regs if r.enrolled_course_id}
    if not ids:
        return {}
    return {cid: f"/app/courses/{c.slug}" for cid, c in (await catalog.get_courses(session, ids)).items()}


async def _batches(session: Any, regs: list[AdmissionRegistration]) -> dict[uuid.UUID, dict[str, str]]:

    ids = {r.enrolled_batch_id for r in regs if r.enrolled_batch_id}
    if not ids:
        return {}
    rows = list((await orgs_public.batch_names(session, ids)).items())
    return {bid: {"batch_id": str(bid), "name": name} for bid, name in rows}


# The learner's batch / classes page: website courses often have no LMS catalog course.
CLASSES_HREF = "/app/classes"


def _registration_view(
    reg: AdmissionRegistration,
    claims: list[AdmissionPaymentClaim],
    hrefs: dict[uuid.UUID, str],
    batches: dict[uuid.UUID, dict[str, str]] | None = None,
) -> dict[str, Any]:
    state, reason = student_state(reg, claims)
    can_pay = (
        reg.status not in R.MANUAL_STATUSES
        and reg.balance_paise > 0
        and reg.open_claims < R.MAX_OPEN_CLAIMS
        and state not in ("pending",)
    )
    return {
        "registration_id": str(reg.id),
        "reg_no": reg.reg_no,
        "course_slug": reg.course_slug,
        "course_title": reg.course_title,
        "status": reg.status,
        "state": state,
        "reason": reason,
        "fee_paise": reg.fee_paise,
        "verified_total_paise": reg.verified_total_paise,
        "balance_paise": reg.balance_paise,
        "open_claims": reg.open_claims,
        "next_due": R.next_due(sv.reg_terms(reg), reg.verified_total_paise),
        "can_pay": can_pay,
        "pay_options": _pay_options(reg) if can_pay else [],
        "enrolled": reg.enrolled_at is not None,
        "enrolled_at": sv.iso(reg.enrolled_at),
        "course_href": (
            (hrefs.get(reg.enrolled_course_id) if reg.enrolled_course_id else None) or CLASSES_HREF
            if state == "enrolled"
            else None
        ),
        "batch": (batches or {}).get(reg.enrolled_batch_id) if reg.enrolled_batch_id else None,
        "created_at": sv.iso(reg.created_at),
        "claims": [_claim_view(c) for c in claims],
    }


async def _views(session: Any, regs: list[AdmissionRegistration]) -> list[dict[str, Any]]:
    if not regs:
        return []
    claims = (
        (
            await ads.execute(
                session,
                select(AdmissionPaymentClaim)
                .where(AdmissionPaymentClaim.registration_id.in_([r.id for r in regs]))
                .order_by(AdmissionPaymentClaim.submitted_at.desc(), AdmissionPaymentClaim.id.desc()),
            )
        )
        .scalars()
        .all()
    )
    by_reg: dict[uuid.UUID, list[AdmissionPaymentClaim]] = {}
    for c in claims:
        by_reg.setdefault(c.registration_id, []).append(c)
    hrefs = await _course_hrefs(session, regs)
    batches = await _batches(session, regs)
    return [_registration_view(r, by_reg.get(r.id, []), hrefs, batches) for r in regs]


async def _my_regs(
    session: Any, user_id: uuid.UUID, email: str | None, *, slug: str | None = None
) -> list[AdmissionRegistration]:
    q = select(AdmissionRegistration).where(_mine(user_id, email))
    if slug is not None:
        q = q.where(AdmissionRegistration.course_slug == slug)
    q = q.order_by(AdmissionRegistration.created_at.desc(), AdmissionRegistration.id.desc()).limit(50)
    return list((await ads.execute(session, q)).scalars().all())


def _prefill(user: Any, profile: Any) -> dict[str, Any]:
    e164 = user.phone_e164 or ""
    phone = e164[3:] if e164.startswith("+91") else ""
    year = getattr(profile, "graduation_year", None)
    return {
        "name": (getattr(profile, "full_name", None) or "")[:120],
        "email": user.email or "",
        "phone": phone,
        "college": (getattr(profile, "college_name_text", None) or "")[:160],
        "branch": (getattr(profile, "branch", None) or "")[:60],
        "year": f"Graduating {year}" if year else "",
    }


# --------------------------------------------------------------------------- routes


@me.get("", operation_id="adm_me_list", openapi_extra={"x-td-idle": "neutral"})
async def my_admissions(session: PrincipalDbSession, principal: Principal = ME) -> dict[str, Any]:
    await rl.hit(f"adm_me_read:{principal.user_id}", LIMITS_READ, scope="admissions")
    user, _ = await _account(session, principal)
    email = _verified_email(user)
    async with as_system(session, "admissions.me_list"):
        regs = await _my_regs(session, principal.user_id, email)
        return {"data": await _views(session, regs)}


@me.get("/plans/{slug}", operation_id="adm_me_plan", openapi_extra={"x-td-idle": "neutral"})
async def my_plan(slug: str, session: PrincipalDbSession, principal: Principal = ME) -> dict[str, Any]:
    await rl.hit(f"adm_me_read:{principal.user_id}", LIMITS_READ, scope="admissions")
    slug = slug.strip().lower()
    if not R.SLUG_RE.match(slug):
        raise ProblemError("not_found")
    user, profile = await _account(session, principal)
    email = _verified_email(user)
    async with as_system(session, "admissions.me_plan"):
        p = await sv.plan_by_slug(session, slug)
        pay = sv.pay_settings_out(await sv.pay_settings(session))
        regs = await _my_regs(session, principal.user_id, email, slug=slug)
        views = await _views(session, regs)
        course_status = await courses.status_of(session, slug, p)
    # payment details stay available while the fee plan is active (instalments on an existing
    # registration); the registration form (``plan``) only while the course is open
    open_plan = p is not None and p.active and p.fee_paise > 0 and not sv.plan_terms(p).problems
    current = next((v for v in views if v["status"] not in R.ENDED_STATUSES), None)
    plan: dict[str, Any] | None = None
    if open_plan and p is not None and course_status == "open":
        plan = {
            **{k: v for k, v in sv.plan_out(p).items() if k not in ("upi_id", "payee_name", "bank_details")},
            "amount_options": _first_options(sv.plan_terms(p)),
        }
    return {
        "course_slug": slug,
        "course_status": course_status,
        "registration_open": plan is not None,
        "plan": plan,
        "pay_configured": open_plan and p is not None and sv.pay_configured(p, pay),
        "payment": _payment(p, pay) if (open_plan and p is not None) else None,
        "consent_text": sv.CONSENT_TEXT,
        "prefill": _prefill(user, profile),
        "registration": current,
        "past": [v for v in views if v is not current],
    }


@me.post("/registrations", status_code=201, operation_id="adm_me_register")
async def my_register(
    body: MyRegistrationIn, session: PrincipalDbSession, principal: Principal = ME
) -> JSONResponse:
    await rl.hit(f"adm_me_write:{principal.user_id}", LIMITS_WRITE, scope="admissions")
    if body.consent is not True:
        raise sv.vf(
            "consent", "consent_required", "Please agree so we can process your registration and payment."
        )
    user, _ = await _account(session, principal)
    email = _account_email(user)
    phone = R.indian_mobile(body.phone)
    if phone is None:
        raise sv.vf("phone", "invalid_mobile", "Enter a 10-digit Indian mobile number (starting with 6-9).")
    slug = body.course_slug.strip().lower()
    if not R.SLUG_RE.match(slug):
        raise ProblemError("not_found", detail="Online registration isn't open for this course.")
    proof = fs.prepare(
        "proof",
        filename=body.proof.filename,
        data_b64=body.proof.data_b64,
        original_sha256=body.proof.original_sha256,
    )
    async with as_system(session, "admissions.me_register"):
        active = [
            r
            for r in await _my_regs(session, principal.user_id, _verified_email(user), slug=slug)
            if r.status not in R.ENDED_STATUSES
        ]
        if active:
            raise sv.conflict(
                "course_slug",
                "already_registered",
                f"You're already registered for {active[0].course_title} "
                f"({active[0].reg_no}). Open My registrations to see its status or upload a payment.",
            )
        reg = await sv.register(
            session,
            sv.RegistrationInput(
                course_slug=slug,
                reg_no=_reg_no(body.reg_no) if body.reg_no else None,
                name=body.name,
                email=email,
                phone=phone,
                college=body.college,
                branch=body.branch,
                year=body.year,
                current_status=None,
                preferred_mode=None,
                message=None,
                consent_text=sv.CONSENT_TEXT,
                show_public=False,
                marketing=False,
            ),
            body.claim.to_input(),
            proof,
            None,
        )
        reg.user_id = principal.user_id  # approval enrols THIS account (service.find_or_create_user)
        await ads.flush(session)
        view = (await _views(session, [reg]))[0]
    log.info("admissions_me_registered", registration_id=str(reg.id))
    return JSONResponse(view, status_code=201)


@me.post("/claims", status_code=201, operation_id="adm_me_claim")
async def my_claim(body: MyClaimIn, session: PrincipalDbSession, principal: Principal = ME) -> JSONResponse:
    await rl.hit(f"adm_me_write:{principal.user_id}", LIMITS_WRITE, scope="admissions")
    user, _ = await _account(session, principal)
    email = _verified_email(user)
    proof = fs.prepare(
        "proof",
        filename=body.proof.filename,
        data_b64=body.proof.data_b64,
        original_sha256=body.proof.original_sha256,
    )
    async with as_system(session, "admissions.me_claim"):
        found = (
            await ads.execute(
                session,
                select(AdmissionRegistration).where(
                    AdmissionRegistration.id == body.registration_id, _mine(principal.user_id, email)
                ),
            )
        ).scalar_one_or_none()
        if found is None:
            raise ProblemError("not_found", detail="We couldn't find that registration on your account.")
        reg = await sv.add_claim(session, found.reg_no, found.email, body.claim.to_input(), proof)
        if reg.user_id is None:
            reg.user_id = principal.user_id
        await ads.flush(session)
        view = (await _views(session, [reg]))[0]
    return JSONResponse(view, status_code=201)
