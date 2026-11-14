"""Public admissions endpoints (no account). Called by the company website through the LMS BFF
route ``/api/public/admissions/*`` (apps/web), which enforces the CORS allow-list, multipart size
and type limits, and forwards JSON (files base64) with the service token and the client IP.

* ``GET  /public/courses/status`` — every website course's registration status (cacheable).
* ``GET  /public/admissions/plans/{slug}`` — fee plan + where to pay + ``course_status`` (404 when
  none; still served when registration is closed, so registered students can pay instalments).
* ``POST /public/admissions/registrations`` — registration + first payment claim (+ resume).
* ``POST /public/admissions/claims`` — another claim on a registration (reg_no + email).
* ``POST /public/admissions/status`` — status / balance by reg_no + email (POST: no email in URLs).

Writes need the BFF service token (browsers never reach the API directly). Rate-limited per
client IP and per email / registration; a filled honeypot (``website``) is accepted and dropped.
Errors never echo submitted values; logs and audit records carry no personal data.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core import ratelimit as rl
from app.core.db import system_context
from app.core.errors import ProblemError
from app.core.firestore.sqlstore import StoreDbSession as DbSession
from app.core.routing import public_router
from app.modules.admissions import courses
from app.modules.admissions import files as fs
from app.modules.admissions import rules as R
from app.modules.admissions import service as sv
from app.modules.identity.contacts import identifier_digest, normalize_email

log = structlog.get_logger("app.admissions.public")

pub = public_router(tags=["admissions"])

LIMITS_IP_WRITE = (rl.Rule(10, rl.HOUR), rl.Rule(40, rl.DAY))
LIMITS_IP_READ = (rl.Rule(120, rl.HOUR),)
LIMITS_EMAIL = (rl.Rule(5, rl.DAY),)
LIMITS_LOOKUP = (rl.Rule(20, rl.HOUR),)
LIMITS_STATUS = (rl.Rule(600, rl.HOUR),)
STATUS_CACHE = "public, max-age=30"
# JSON bodies carry up to two base64 files of <= 2 MiB each (see core.middleware.register_body_limit).
BODY_LIMIT = 6 * 1024 * 1024

_LINE_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _one_line(v: str | None) -> str | None:
    if v is None:
        return None
    v = " ".join(v.split())
    if _LINE_CTRL.search(v):
        raise ValueError("Use letters, numbers and punctuation only")
    return v


class AdmissionFileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=200)
    data_b64: str = Field(min_length=100, max_length=2_900_000)
    original_sha256: str | None = Field(default=None, max_length=64)


class AdmissionClaimIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    amount_paise: int = Field(gt=0, le=R.MAX_FEE_PAISE)
    method: str = Field(max_length=10)
    utr: str = Field(min_length=1, max_length=40)
    paid_on: date
    note: str | None = Field(default=None, max_length=500)

    @field_validator("note")
    @classmethod
    def _no_ctrl(cls, v: str | None) -> str | None:
        if v and _CTRL.search(v):
            raise ValueError("Remove control characters")
        return v

    def to_input(self) -> sv.ClaimInput:
        return sv.ClaimInput(self.amount_paise, self.method, self.utr, self.paid_on, self.note)


class AdmissionRegistrationIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    course_slug: str = Field(min_length=1, max_length=80)
    reg_no: str | None = Field(default=None, max_length=20)
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=3, max_length=160)
    phone: str = Field(min_length=10, max_length=20)
    college: str = Field(min_length=1, max_length=160)
    branch: str = Field(min_length=1, max_length=60)
    year: str = Field(min_length=1, max_length=30)
    current_status: str | None = Field(default=None, max_length=60)
    preferred_mode: str | None = Field(default=None, max_length=30)
    message: str | None = Field(default=None, max_length=2000)
    consent: bool
    show_public: bool = False
    marketing: bool = False
    website: str | None = Field(default=None, max_length=200)  # honeypot
    claim: AdmissionClaimIn
    proof: AdmissionFileIn
    resume: AdmissionFileIn | None = None

    @field_validator("name", "college", "branch", "year", "current_status", "preferred_mode")
    @classmethod
    def _single_line(cls, v: str | None) -> str | None:
        return _one_line(v)

    @field_validator("message")
    @classmethod
    def _no_ctrl(cls, v: str | None) -> str | None:
        if v and _CTRL.search(v):
            raise ValueError("Remove control characters from the message")
        return v


class AdmissionClaimRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reg_no: str = Field(min_length=8, max_length=20)
    email: str = Field(min_length=3, max_length=160)
    website: str | None = Field(default=None, max_length=200)
    claim: AdmissionClaimIn
    proof: AdmissionFileIn


class AdmissionLookupIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reg_no: str = Field(min_length=8, max_length=20)
    email: str = Field(min_length=3, max_length=160)


def _ip(request: Request) -> str:
    from app.modules.sessions.service import client_info

    return client_info(request).ip or "unknown"


def _require_bff(request: Request) -> None:
    if not getattr(request.state, "service_authenticated", False):
        raise ProblemError("permission_denied", detail="Submit this form through the Tech Drona website.")


def _email(raw: str) -> str:
    e = normalize_email(raw)
    if e is None or len(e) > 160:
        raise sv.vf("email", "invalid_email", "Enter a valid email address.")
    return e.lower()


def _reg_no(raw: str) -> str:
    r = R.normalize_reg_no(raw)
    if r is None:
        raise sv.vf(
            "reg_no",
            "invalid_reg_no",
            "Enter the registration number as shown on your confirmation, e.g. TDR-1A2B3C4D.",
        )
    return r


def _email_key(email: str) -> str:
    return identifier_digest("email", email)[1].hex()


ACCEPTED = {"status": "received"}


@pub.get("/public/admissions/plans/{slug}", operation_id="adm_pub_plan")
async def public_plan(slug: str, request: Request, session: DbSession) -> dict[str, Any]:
    await rl.hit(f"adm_plan_ip:{_ip(request)}", LIMITS_IP_READ, scope="admissions")
    if not R.SLUG_RE.match(slug):
        raise ProblemError("not_found")
    await system_context(session, "admissions.public_plan")
    p = await sv.plan_by_slug(session, slug)
    if p is None or p.fee_paise <= 0:
        raise ProblemError("not_found")
    pay = sv.pay_settings_out(await sv.pay_settings(session))
    status = await courses.status_of(session, p.course_slug, p)
    return {
        **sv.plan_out(p),
        "course_status": status,
        "registration_open": status == "open",
        "pay": pay,
        "pay_configured": sv.pay_configured(p, pay),
        "consent_text": sv.CONSENT_TEXT,
    }


@pub.get("/public/courses/status", operation_id="adm_pub_course_status")
async def public_course_status(request: Request, response: Response, session: DbSession) -> dict[str, Any]:
    """``{"data": {"<slug>": "open"|"coming_soon"|"closed"}, "updated_at": iso}`` — no personal data."""
    await rl.hit(f"adm_status_ip:{_ip(request)}", LIMITS_STATUS, scope="admissions")
    await system_context(session, "admissions.public_course_status")
    out = await courses.public_map(session)
    response.headers["Cache-Control"] = STATUS_CACHE
    return out


@pub.post("/public/admissions/registrations", status_code=201, operation_id="adm_pub_register")
async def public_register(
    body: AdmissionRegistrationIn, request: Request, session: DbSession
) -> JSONResponse:
    _require_bff(request)
    await rl.hit(f"adm_write_ip:{_ip(request)}", LIMITS_IP_WRITE, scope="admissions")
    if body.website:
        log.info("admissions_honeypot")
        return JSONResponse(ACCEPTED, status_code=202)
    if body.consent is not True:
        raise sv.vf(
            "consent", "consent_required", "Please agree so we can process your registration and payment."
        )
    email = _email(body.email)
    phone = R.indian_mobile(body.phone)
    if phone is None:
        raise sv.vf("phone", "invalid_mobile", "Enter a 10-digit Indian mobile number (starting with 6-9).")
    reg_no = _reg_no(body.reg_no) if body.reg_no else None
    await rl.hit(f"adm_email:{_email_key(email)}", LIMITS_EMAIL, scope="admissions")
    proof = fs.prepare(
        "proof",
        filename=body.proof.filename,
        data_b64=body.proof.data_b64,
        original_sha256=body.proof.original_sha256,
    )
    resume = (
        fs.prepare("resume", filename=body.resume.filename, data_b64=body.resume.data_b64)
        if body.resume is not None
        else None
    )
    await system_context(session, "admissions.public_register")
    reg = await sv.register(
        session,
        sv.RegistrationInput(
            course_slug=body.course_slug.lower(),
            reg_no=reg_no,
            name=body.name,
            email=email,
            phone=phone,
            college=body.college,
            branch=body.branch,
            year=body.year,
            current_status=body.current_status,
            preferred_mode=body.preferred_mode,
            message=body.message,
            consent_text=sv.CONSENT_TEXT,
            show_public=body.show_public,
            marketing=body.marketing,
        ),
        body.claim.to_input(),
        proof,
        resume,
    )
    return JSONResponse(
        {"reg_no": reg.reg_no, "email": reg.email, "status": reg.status, "course_title": reg.course_title},
        status_code=201,
    )


@pub.post("/public/admissions/claims", status_code=201, operation_id="adm_pub_claim")
async def public_claim(body: AdmissionClaimRequestIn, request: Request, session: DbSession) -> JSONResponse:
    _require_bff(request)
    await rl.hit(f"adm_write_ip:{_ip(request)}", LIMITS_IP_WRITE, scope="admissions")
    if body.website:
        log.info("admissions_honeypot")
        return JSONResponse(ACCEPTED, status_code=202)
    reg_no, email = _reg_no(body.reg_no), _email(body.email)
    await rl.hit(f"adm_lookup_reg:{reg_no}", LIMITS_LOOKUP, scope="admissions")
    proof = fs.prepare(
        "proof",
        filename=body.proof.filename,
        data_b64=body.proof.data_b64,
        original_sha256=body.proof.original_sha256,
    )
    await system_context(session, "admissions.public_claim")
    reg = await sv.add_claim(session, reg_no, email, body.claim.to_input(), proof)
    return JSONResponse(
        {"reg_no": reg.reg_no, "status": reg.status, "claim_status": "pending"}, status_code=201
    )


@pub.post("/public/admissions/status", operation_id="adm_pub_status")
async def public_status(body: AdmissionLookupIn, request: Request, session: DbSession) -> dict[str, Any]:
    _require_bff(request)
    await rl.hit(f"adm_lookup_ip:{_ip(request)}", LIMITS_LOOKUP, scope="admissions")
    reg_no, email = _reg_no(body.reg_no), _email(body.email)
    await rl.hit(f"adm_lookup_reg:{reg_no}", LIMITS_LOOKUP, scope="admissions")
    await system_context(session, "admissions.public_status")
    reg = await sv.find_by_reg_no_email(session, reg_no, email)
    if reg is None:
        raise ProblemError(
            "not_found",
            detail="We couldn't find a registration with that number and email. Check both, or "
            "contact Tech Drona.",
        )
    return sv.status_for_student(reg)
