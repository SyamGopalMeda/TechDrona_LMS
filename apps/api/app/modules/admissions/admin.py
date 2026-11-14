"""Staff admissions API (Admin > Admissions in the LMS web app).

Permissions (rbac catalogue; Admin holds all of them at platform scope):

* ``payment.read``    — overview, queue, registrations, events, proof / resume view links;
* ``payment.verify``  — verify / request correction / reject claims, record a payment, release a
  claim's locks, change status or contact details, enrol;
* ``payment.reverse`` — reverse a verified payment, change a registration's fee (owner-level);
* ``price.manage``    — fee plans and the "pay to" settings.

Every proof / resume view is audited. Mutations are audited in ``service``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_, select, tuple_

from app.core.audit import audit
from app.core.auth import require_permission
from app.core.errors import ProblemError
from app.core.firestore.sqlstore import StorePrincipalDbSession as PrincipalDbSession
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.modules.admissions import courses
from app.modules.admissions import datastore as ads
from app.modules.admissions import files as fs
from app.modules.admissions import onboarding as ob
from app.modules.admissions import rules as R
from app.modules.admissions import service as sv
from app.modules.admissions.models import (
    AdmissionEvent,
    AdmissionFeePlan,
    AdmissionPaymentClaim,
    AdmissionRegistration,
)
from app.modules.identity.contacts import normalize_email
from app.modules.orgs import public as orgs_public

staff = authenticated_router(tags=["admissions"], route_tag="default", idle="extends")
NEUTRAL = {"x-td-idle": "neutral"}
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
READ = Depends(require_permission("payment.read"))
VERIFY = Depends(require_permission("payment.verify"))
REVERSE = Depends(require_permission("payment.reverse"))
PLANS = Depends(require_permission("price.manage"))

ClaimStatus = Literal["pending", "needs_info", "verified", "rejected", "reversed", "open"]
RegStatus = Literal[
    "registered",
    "pending_verification",
    "partially_paid",
    "payment_verified",
    "enrolled",
    "rejected",
    "cancelled",
    "completed",
]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _cursor(cursor: str | None) -> tuple[datetime, uuid.UUID] | None:
    if not cursor:
        return None
    pos = decode_cursor(cursor)
    try:
        return datetime.fromisoformat(str(pos["at"])), uuid.UUID(str(pos["id"]))
    except (KeyError, ValueError) as e:
        raise ProblemError("invalid_cursor") from e


# --------------------------------------------------------------------------- overview / queue


@staff.get("/admin/admissions/overview", openapi_extra=NEUTRAL)
async def overview(session: PrincipalDbSession, principal: Principal = READ) -> dict[str, Any]:
    return await sv.overview(session)


@staff.get("/admin/admissions/claims", openapi_extra=NEUTRAL)
async def list_claims(
    session: PrincipalDbSession,
    principal: Principal = READ,
    status: ClaimStatus = "open",
    registration_id: uuid.UUID | None = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    q = select(AdmissionPaymentClaim, AdmissionRegistration).join(
        AdmissionRegistration, AdmissionRegistration.id == AdmissionPaymentClaim.registration_id
    )
    if status == "open":
        q = q.where(AdmissionPaymentClaim.status.in_(tuple(R.OPEN_CLAIM_STATUSES)))
    else:
        q = q.where(AdmissionPaymentClaim.status == status)
    if registration_id:
        q = q.where(AdmissionPaymentClaim.registration_id == registration_id)
    pos = _cursor(cursor)
    # The queue reads oldest first (first come, first verified).
    if pos:
        q = q.where(tuple_(AdmissionPaymentClaim.submitted_at, AdmissionPaymentClaim.id) > tuple_(*pos))
    rows = (
        await ads.execute(
            session, q.order_by(AdmissionPaymentClaim.submitted_at, AdmissionPaymentClaim.id).limit(limit + 1)
        )
    ).all()
    more = len(rows) > limit
    rows = rows[:limit]
    last = rows[-1][0] if rows else None
    accounts = await _accounts(session, [r for _, r in rows])
    data = []
    for c, r in rows:
        item = sv.claim_out(c, r)
        has, username = accounts.get(r.id, (False, None))
        item["registration"]["has_account"] = has
        item["registration"]["account_username"] = username
        data.append(item)
    return {
        "data": data,
        "page": page_meta(
            {"at": last.submitted_at.isoformat(), "id": str(last.id)} if more and last else None, limit
        ),
    }


async def _accounts(
    session: Any, regs: list[AdmissionRegistration]
) -> dict[uuid.UUID, tuple[bool, str | None]]:
    """Per registration: whether it already has an LMS account (linked, or an account with its
    email) and that account's username. Approving enrols that account; otherwise Verify & Add to
    Batch creates one (username + temporary password)."""
    from app.modules.identity import public as identity

    ids = {r.user_id for r in regs if r.user_id is not None}
    emails = {r.email for r in regs if r.user_id is None}
    by_id: dict[uuid.UUID, str | None] = {}
    by_email: dict[str, str | None] = {}
    if ids:
        by_id = {uid: u.username for uid, u in (await identity.get_users(session, ids)).items()}
    if emails:  # live accounts by lower-case email
        by_email = {e: u.username for e, u in (await identity.users_by_emails(session, emails)).items()}
    out: dict[uuid.UUID, tuple[bool, str | None]] = {}
    for r in regs:
        if r.user_id is not None:
            out[r.id] = (True, by_id.get(r.user_id))
        else:
            out[r.id] = (r.email in by_email, by_email.get(r.email))
    return out


@staff.get("/admin/admissions/claims/{claim_id}/proof", openapi_extra=NEUTRAL)
async def claim_proof(
    claim_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = READ
) -> dict[str, Any]:
    c = await ads.get(session, AdmissionPaymentClaim, claim_id)
    if c is None or not c.proof_key:
        raise ProblemError("not_found")
    url, exp = fs.view_url(c.proof_key, c.proof_name or "proof")
    await audit(session, principal, "admissions.proof.viewed", "admission_payment_claim", c.id)
    return {"url": url, "expires_at": exp.isoformat(), "content_type": c.proof_type, "filename": c.proof_name}


async def _read_private(key: str) -> bytes:
    """The stored bytes of a private admissions file (at most ``fs.MAX_BYTES``)."""
    import asyncio

    from app.modules.commerce.documents import MemoryDocumentStore, S3DocumentStore, get_document_store

    store = get_document_store()
    if isinstance(store, MemoryDocumentStore):
        hit = store.objects.get((fs.bucket(), key))
        if hit is None:
            raise ProblemError("not_found")
        return hit[0]
    if isinstance(store, S3DocumentStore):
        client = store._client()

        def _get() -> bytes:
            obj = client.get_object(Bucket=fs.bucket(), Key=key)
            return obj["Body"].read(fs.MAX_BYTES + 1)

        try:
            return await asyncio.to_thread(_get)
        except Exception as e:  # missing object / storage down
            raise ProblemError("not_found") from e
    raise ProblemError("not_found")


@staff.get(
    "/admin/admissions/claims/{claim_id}/proof/file",
    openapi_extra=NEUTRAL,
    response_class=Response,
    responses={200: {"content": {t: {} for t in fs.PROOF_TYPES}}},
)
async def claim_proof_file(
    claim_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = READ
) -> Response:
    """The receipt itself, through the session (the web shows it inline as a blob: image; the
    presigned link's storage origin isn't allowed by the LMS CSP)."""
    c = await ads.get(session, AdmissionPaymentClaim, claim_id)
    if c is None or not c.proof_key or c.proof_type not in fs.PROOF_TYPES:
        raise ProblemError("not_found")
    data = await _read_private(c.proof_key)
    await audit(session, principal, "admissions.proof.viewed", "admission_payment_claim", c.id)
    return Response(
        content=data,
        media_type=c.proof_type,
        headers={
            "cache-control": "private, no-store",
            "x-content-type-options": "nosniff",
            "content-security-policy": "default-src 'none'; sandbox",
            "content-disposition": "inline",
        },
    )


class AdmissionVerifyIn(Strict):
    amount_paise: int = Field(gt=0, le=R.MAX_FEE_PAISE)
    note: str | None = Field(default=None, max_length=500)
    checked: bool


class AdmissionReasonIn(Strict):
    reason: str = Field(min_length=1, max_length=500)


class AdmissionRejectIn(AdmissionReasonIn):
    release_locks: bool = False


@staff.post("/admin/admissions/claims/{claim_id}/verify")
async def verify(
    claim_id: uuid.UUID, body: AdmissionVerifyIn, session: PrincipalDbSession, principal: Principal = VERIFY
) -> dict[str, Any]:
    actor = await sv.staff_actor(session, principal)
    return await sv.verify_claim(
        session, actor, claim_id, amount_paise=body.amount_paise, note=body.note, checked=body.checked
    )


@staff.post("/admin/admissions/claims/{claim_id}/needs-info")
async def needs_info(
    claim_id: uuid.UUID, body: AdmissionReasonIn, session: PrincipalDbSession, principal: Principal = VERIFY
) -> dict[str, Any]:
    return await sv.decide_claim(
        session, await sv.staff_actor(session, principal), claim_id, "needs_info", body.reason
    )


@staff.post("/admin/admissions/claims/{claim_id}/reject")
async def reject(
    claim_id: uuid.UUID, body: AdmissionRejectIn, session: PrincipalDbSession, principal: Principal = VERIFY
) -> dict[str, Any]:
    return await sv.decide_claim(
        session,
        await sv.staff_actor(session, principal),
        claim_id,
        "rejected",
        body.reason,
        release=body.release_locks,
    )


@staff.post("/admin/admissions/claims/{claim_id}/reverse")
async def reverse(
    claim_id: uuid.UUID, body: AdmissionReasonIn, session: PrincipalDbSession, principal: Principal = REVERSE
) -> dict[str, Any]:
    return await sv.reverse_claim(session, await sv.staff_actor(session, principal), claim_id, body.reason)


@staff.post("/admin/admissions/claims/{claim_id}/release-locks")
async def release(
    claim_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = VERIFY
) -> dict[str, Any]:
    return await sv.release_locks(session, await sv.staff_actor(session, principal), claim_id)


class AdmissionVerifyEnrolIn(Strict):
    amount_paise: int | None = Field(default=None, gt=0, le=R.MAX_FEE_PAISE)
    batch_id: uuid.UUID | None = None  # null: the course fee plan's batch
    must_change_password: bool = True
    send_email: bool = True
    note: str | None = Field(default=None, max_length=500)


@staff.post("/admin/admissions/claims/{claim_id}/verify-and-enrol")
async def verify_and_enrol(
    claim_id: uuid.UUID,
    body: AdmissionVerifyEnrolIn,
    session: PrincipalDbSession,
    principal: Principal = VERIFY,
) -> dict[str, Any]:
    """Verify the payment, find / create the LMS account, add to the batch, enrol, email the login
    details. ``account.temporary_password`` is returned once (only when the account was created now)."""
    return await ob.verify_and_enrol(
        session,
        await sv.staff_actor(session, principal),
        claim_id,
        amount_paise=body.amount_paise,
        batch_id=body.batch_id,
        must_change_password=body.must_change_password,
        send_email=body.send_email,
        note=body.note,
    )


# --------------------------------------------------------------------------- registrations


class AdmissionLoginEmailIn(Strict):
    reset_password: bool = True
    must_change_password: bool = True


@staff.post("/admin/admissions/registrations/{registration_id}/login-email")
async def login_email(
    registration_id: uuid.UUID,
    body: AdmissionLoginEmailIn,
    session: PrincipalDbSession,
    principal: Principal = VERIFY,
) -> dict[str, Any]:
    """Send / resend the LMS login email. With ``reset_password`` a new temporary password is set
    (returned once, also when email isn't connected) and the student is signed out everywhere."""
    return await ob.send_login_email(
        session,
        await sv.staff_actor(session, principal),
        registration_id,
        reset_password=body.reset_password,
        must_change_password=body.must_change_password,
    )


@staff.get("/admin/admissions/registrations", openapi_extra=NEUTRAL)
async def list_registrations(
    session: PrincipalDbSession,
    principal: Principal = READ,
    status: RegStatus | None = None,
    course_slug: str | None = Query(default=None, max_length=80),
    q: str | None = Query(default=None, max_length=120),
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    stmt = select(AdmissionRegistration)
    if status:
        stmt = stmt.where(AdmissionRegistration.status == status)
    if course_slug:
        stmt = stmt.where(AdmissionRegistration.course_slug == course_slug)
    if q and q.strip():
        term = q.strip()
        like = f"%{term.replace('%', '').replace('_', '')}%"
        stmt = stmt.where(
            or_(
                AdmissionRegistration.reg_no == (R.normalize_reg_no(term) or term.upper()),
                AdmissionRegistration.name.ilike(like),
                AdmissionRegistration.email.ilike(like),
                AdmissionRegistration.phone.ilike(like),
                AdmissionRegistration.college.ilike(like),
            )
        )
    pos = _cursor(cursor)
    if pos:
        stmt = stmt.where(tuple_(AdmissionRegistration.created_at, AdmissionRegistration.id) < tuple_(*pos))
    rows = list(
        (
            await ads.execute(
                session,
                stmt.order_by(AdmissionRegistration.created_at.desc(), AdmissionRegistration.id.desc()).limit(
                    limit + 1
                ),
            )
        ).scalars()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    last_pay = await _last_payments(session, [r.id for r in rows])
    accounts = await _accounts(session, rows)
    return {
        "data": [
            {
                **sv.registration_out(r),
                **last_pay.get(r.id, _NO_PAYMENT),
                "has_account": accounts.get(r.id, (False, None))[0],
                "account_username": accounts.get(r.id, (False, None))[1],
            }
            for r in rows
        ],
        "page": page_meta(
            {"at": rows[-1].created_at.isoformat(), "id": str(rows[-1].id)} if more and rows else None, limit
        ),
    }


_NO_PAYMENT: dict[str, Any] = {"last_utr": None, "last_paid_on": None, "last_claim_status": None}


async def _last_payments(session: Any, reg_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """Each registration's most recent payment (reference, date, status) for the list view."""
    if not reg_ids:
        return {}
    rows = (
        await ads.execute(
            session,
            select(
                AdmissionPaymentClaim.registration_id,
                AdmissionPaymentClaim.utr,
                AdmissionPaymentClaim.paid_on,
                AdmissionPaymentClaim.status,
            )
            .where(AdmissionPaymentClaim.registration_id.in_(reg_ids))
            .distinct(AdmissionPaymentClaim.registration_id)
            .order_by(AdmissionPaymentClaim.registration_id, AdmissionPaymentClaim.submitted_at.desc()),
        )
    ).all()
    return {
        rid: {"last_utr": utr, "last_paid_on": sv.iso(paid_on), "last_claim_status": status}
        for rid, utr, paid_on, status in rows
    }


async def _reg(session: Any, reg_id: uuid.UUID) -> AdmissionRegistration:
    r = await ads.get(session, AdmissionRegistration, reg_id)
    if r is None:
        raise ProblemError("not_found")
    return r


@staff.get("/admin/admissions/registrations/{registration_id}", openapi_extra=NEUTRAL)
async def get_registration(
    registration_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = READ
) -> dict[str, Any]:
    r = await _reg(session, registration_id)
    claims = (
        await ads.execute(
            session,
            select(AdmissionPaymentClaim)
            .where(AdmissionPaymentClaim.registration_id == r.id)
            .order_by(AdmissionPaymentClaim.submitted_at.desc()),
        )
    ).scalars()
    events = (
        await ads.execute(
            session,
            select(AdmissionEvent)
            .where(AdmissionEvent.registration_id == r.id)
            .order_by(AdmissionEvent.at.desc())
            .limit(200),
        )
    ).scalars()
    await audit(session, principal, "admissions.registration.viewed", "admission_registration", r.id)
    has, username = (await _accounts(session, [r])).get(r.id, (False, None))
    batch = None
    if r.enrolled_batch_id:
        b = await orgs_public.get_batch(session, r.enrolled_batch_id)
        batch = {"batch_id": str(b.id), "name": b.name} if b is not None else None
    return {
        **sv.registration_out(r, full=True),
        "has_account": has,
        "account_username": username,
        "batch": batch,
        "claims": [sv.claim_out(c) for c in claims],
        "events": [sv.event_out(e) for e in events],
    }


@staff.get("/admin/admissions/registrations/{registration_id}/resume", openapi_extra=NEUTRAL)
async def registration_resume(
    registration_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = READ
) -> dict[str, Any]:
    r = await _reg(session, registration_id)
    if not r.resume_key:
        raise ProblemError("not_found")
    url, exp = fs.view_url(r.resume_key, r.resume_name or "resume")
    await audit(session, principal, "admissions.resume.viewed", "admission_registration", r.id)
    return {
        "url": url,
        "expires_at": exp.isoformat(),
        "content_type": r.resume_type,
        "filename": r.resume_name,
    }


class AdmissionRecordIn(Strict):
    amount_paise: int = Field(gt=0, le=R.MAX_FEE_PAISE)
    method: Literal["upi", "bank", "cash", "other"]
    utr: str | None = Field(default=None, max_length=40)
    paid_on: date
    note: str | None = Field(default=None, max_length=500)
    checked: bool


@staff.post("/admin/admissions/registrations/{registration_id}/payments")
async def record(
    registration_id: uuid.UUID,
    body: AdmissionRecordIn,
    session: PrincipalDbSession,
    principal: Principal = VERIFY,
) -> dict[str, Any]:
    return await sv.record_payment(
        session,
        await sv.staff_actor(session, principal),
        registration_id,
        amount_paise=body.amount_paise,
        method=body.method,
        utr=body.utr,
        paid_on=body.paid_on,
        note=body.note,
        checked=body.checked,
    )


class AdmissionStatusIn(Strict):
    status: Literal["rejected", "cancelled", "completed", "reopen"]
    reason: str | None = Field(default=None, max_length=500)


@staff.post("/admin/admissions/registrations/{registration_id}/status")
async def set_status(
    registration_id: uuid.UUID,
    body: AdmissionStatusIn,
    session: PrincipalDbSession,
    principal: Principal = VERIFY,
) -> dict[str, Any]:
    return await sv.set_status(
        session, await sv.staff_actor(session, principal), registration_id, body.status, body.reason
    )


class AdmissionContactIn(Strict):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    email: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=20)


@staff.patch("/admin/admissions/registrations/{registration_id}/contact")
async def set_contact(
    registration_id: uuid.UUID,
    body: AdmissionContactIn,
    session: PrincipalDbSession,
    principal: Principal = VERIFY,
) -> dict[str, Any]:
    email = None
    if body.email is not None:
        email = normalize_email(body.email)
        if email is None:
            raise sv.vf("email", "invalid_email", "Enter a valid email address.")
    phone = None
    if body.phone is not None:
        phone = R.indian_mobile(body.phone)
        if phone is None:
            raise sv.vf("phone", "invalid_mobile", "Enter a valid 10-digit Indian mobile number.")
    return await sv.set_contact(
        session,
        await sv.staff_actor(session, principal),
        registration_id,
        name=body.name,
        email=email,
        phone=phone,
    )


class AdmissionFeeIn(Strict):
    fee_paise: int = Field(ge=0, le=R.MAX_FEE_PAISE)
    reason: str = Field(min_length=1, max_length=500)


@staff.post("/admin/admissions/registrations/{registration_id}/fee")
async def set_fee(
    registration_id: uuid.UUID,
    body: AdmissionFeeIn,
    session: PrincipalDbSession,
    principal: Principal = REVERSE,
) -> dict[str, Any]:
    return await sv.adjust_fee(
        session, await sv.staff_actor(session, principal), registration_id, body.fee_paise, body.reason
    )


@staff.post("/admin/admissions/registrations/{registration_id}/enrol")
async def enrol(
    registration_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = VERIFY
) -> dict[str, Any]:
    return await sv.manual_enrol(session, await sv.staff_actor(session, principal), registration_id)


# --------------------------------------------------------------------------- fee plans / pay-to


@staff.get("/admin/admissions/plans", openapi_extra=NEUTRAL)
async def list_plans(session: PrincipalDbSession, principal: Principal = READ) -> dict[str, Any]:

    plans = (await ads.execute(session, select(AdmissionFeePlan).order_by(AdmissionFeePlan.title))).scalars()
    batches = await orgs_public.list_batches(session, exclude_status="archived", order="name")
    return {
        "data": [sv.plan_out(p, staff=True) for p in plans],
        "pay": sv.pay_settings_out(await sv.pay_settings(session)),
        "batches": [
            {
                "batch_id": str(b.id),
                "name": b.name,
                "code": b.code,
                "course_id": str(b.course_id) if getattr(b, "course_id", None) else None,
                "website_course_slug": getattr(b, "website_course_slug", None),
            }
            for b in batches
        ],
    }


class AdmissionInstalmentIn(Strict):
    label: str = Field(default="", max_length=60)
    amount_paise: int = Field(ge=0, le=R.MAX_FEE_PAISE)
    due: str = Field(default="", max_length=10)


class AdmissionPlanIn(Strict):
    slug: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=160)
    course_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    fee_paise: int = Field(ge=0, le=R.MAX_FEE_PAISE)
    allow_instalments: bool = False
    schedule: list[AdmissionInstalmentIn] = Field(default_factory=list, max_length=R.MAX_INSTALMENTS)
    min_first_paise: int | None = Field(default=None, ge=0, le=R.MAX_FEE_PAISE)
    access_min_paise: int | None = Field(default=None, ge=0, le=R.MAX_FEE_PAISE)
    upi_id: str | None = Field(default=None, max_length=330)
    payee_name: str | None = Field(default=None, max_length=80)
    bank_details: str | None = Field(default=None, max_length=600)
    instructions: str | None = Field(default=None, max_length=800)
    active: bool = False


@staff.put("/admin/admissions/plans")
async def save_plan(
    body: AdmissionPlanIn, session: PrincipalDbSession, principal: Principal = PLANS
) -> dict[str, Any]:
    return await sv.save_plan(session, await sv.staff_actor(session, principal), body.model_dump())


class AdmissionPayIn(Strict):
    phone: str | None = Field(default=None, max_length=20)
    preferred_app: str | None = Field(default="PhonePe", max_length=40)
    upi_id: str | None = Field(default=None, max_length=330)
    payee_name: str | None = Field(default=None, max_length=80)
    instructions: str | None = Field(default=None, max_length=800)


@staff.put("/admin/admissions/pay-settings")
async def save_pay(
    body: AdmissionPayIn, session: PrincipalDbSession, principal: Principal = PLANS
) -> dict[str, Any]:
    return await sv.save_pay_settings(session, await sv.staff_actor(session, principal), body.model_dump())


# --------------------------------------------------------------------------- course registration status


@staff.get("/admin/courses/status", openapi_extra=NEUTRAL)
async def list_course_status(session: PrincipalDbSession, principal: Principal = PLANS) -> dict[str, Any]:
    """Every website course known from status rows, fee plans and ``web-*`` batches."""
    return await courses.admin_list(session)


class CourseStatusIn(Strict):
    status: Literal["open", "coming_soon", "closed"]


@staff.put("/admin/courses/{slug}/status")
async def put_course_status(
    slug: str, body: CourseStatusIn, session: PrincipalDbSession, principal: Principal = PLANS
) -> dict[str, Any]:
    """Open for registration / Coming soon / Closed (audited ``admissions.course_status.changed``)."""
    return await courses.set_status(session, await sv.staff_actor(session, principal), slug, body.status)
