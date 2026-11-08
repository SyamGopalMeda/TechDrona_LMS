"""Corporate enquiries (owner decision D8): the public ``/enquiries`` form replaces the old
B2B marketing page.

* ``POST /public/enquiries`` — no account needed. Strict validation (``extra=forbid``, length
  limits, single-line name/company, normalised email/phone), ``consent`` must be ``true``,
  rate-limited per client IP and per email digest (``app.core.ratelimit``). A filled honeypot
  field (``website``) is accepted with the same ``202`` body and silently dropped. Errors never
  echo the submitted values, and nothing personal is logged or written to the audit record.
* ``GET /support/enquiries``, ``GET/PATCH /support/enquiries/{id}`` — the Admin support queue
  (``user.read`` at platform scope — Admin only — plus the all-categories support lane; PATCH
  also needs ``ticket.assign``).

Stored in ``corporate_enquiries`` (platform-only RLS); the public route writes under a system
context. Every Admin is told through the notifications module (in-app + email to their own
address; the message carries only the enquiry reference).
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select, text, tuple_

from app.core import ratelimit as rl
from app.core.audit import AuditActor, audit
from app.core.auth import PLATFORM_SCOPE, require_permission
from app.core.db import DbSession, PrincipalDbSession, system_context
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router, public_router
from app.core.time import to_rfc3339
from app.modules.identity import clock
from app.modules.identity.contacts import identifier_digest, normalize_email, normalize_phone
from app.modules.support import service as sv
from app.modules.support.models import CorporateEnquiry

log = structlog.get_logger("app.support.enquiries")

NOTICE_VERSION = "corporate-enquiry-2026-11"
TEMPLATE_KEY = "support.corporate_enquiry_received"
LIMITS_IP = (rl.Rule(5, rl.HOUR), rl.Rule(20, rl.DAY))
LIMITS_EMAIL = (rl.Rule(3, rl.DAY),)
Status = Literal["new", "in_progress", "closed", "spam"]

pub = public_router(tags=["support"])
staff = authenticated_router(tags=["support"], route_tag="default", idle="extends")

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LINE_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def _vf(field: str, code: str, message: str) -> ProblemError:
    # Never echo the submitted value (PII).
    return ProblemError("validation_failed", 422, errors=[{"field": field, "code": code, "message": message}])


def _one_line(v: str) -> str:
    v = " ".join(v.split())
    if _LINE_CTRL.search(v):
        raise ValueError("Use letters, numbers and punctuation only")
    return v


class EnquiryIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=100)
    company: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=3, max_length=254)
    phone: str | None = Field(default=None, max_length=20)
    message: str = Field(min_length=10, max_length=4000)
    consent: bool
    # Honeypot: hidden in the web form; humans leave it empty.
    website: str | None = Field(default=None, max_length=200)

    @field_validator("name", "company")
    @classmethod
    def _single_line(cls, v: str) -> str:
        return _one_line(v)

    @field_validator("message")
    @classmethod
    def _no_control(cls, v: str) -> str:
        if _CTRL.search(v):
            raise ValueError("Remove control characters from the message")
        return v


ACCEPTED = {"status": "received"}


def _client_ip(request: Request) -> str | None:
    from app.modules.sessions.service import client_info

    return client_info(request).ip


async def _admin_recipients(session: Any) -> list[tuple[uuid.UUID, str | None]]:
    from app.modules.identity.models import User
    from app.modules.rbac.catalogue import admin_roles
    from app.modules.rbac.models import Role, RoleGrant

    now = clock.now()
    rows = await session.execute(
        select(RoleGrant.user_id, User.email)
        .join(Role, Role.id == RoleGrant.role_id)
        .join(User, User.id == RoleGrant.user_id)
        .where(
            Role.role_key.in_(sorted(admin_roles())),
            RoleGrant.scope_type == "platform",
            RoleGrant.revoked_at.is_(None),
            (RoleGrant.expires_at.is_(None)) | (RoleGrant.expires_at > now),
            User.status == "active",
        )
        .distinct()
    )
    return [(r[0], r[1]) for r in rows.all()]


async def _notify_admins(session: Any, e: CorporateEnquiry) -> int:
    from app.modules.notifications.service import notify

    sent = 0
    for uid, email in await _admin_recipients(session):
        nid = await notify(
            session,
            uid,
            TEMPLATE_KEY,
            category="system",
            data={"enquiry_id": str(e.id), "reference": e.reference, "summary": "New corporate enquiry"},
            channels=("in_app", "email") if email else ("in_app",),
            priority="normal",
            dedupe_key=f"enquiry:{e.id}:{uid}",
            email_to=email,
            email_subject=f"New corporate enquiry {e.reference}",
            email_text=(
                f"A new corporate enquiry ({e.reference}) was received through the website.\n"
                "Open Admin > Support > Enquiries to read and answer it."
            ),
        )
        sent += nid is not None
    return sent


# --------------------------------------------------------------------------- public form


@pub.post("/public/enquiries", status_code=202, operation_id="sup_16_corporate_enquiry")
async def create_enquiry(body: EnquiryIn, request: Request, session: DbSession) -> JSONResponse:
    ip = _client_ip(request)
    # Per-IP limit first (also counts honeypot hits, so bots are throttled too).
    await rl.hit(f"sup16_enquiry_ip:{ip or 'unknown'}", LIMITS_IP, scope="sup16")
    if body.website:
        log.info("enquiry_honeypot")
        return JSONResponse(ACCEPTED, status_code=202)
    if body.consent is not True:
        raise _vf("consent", "consent_required", "Please agree to be contacted about your enquiry")
    email = normalize_email(body.email)
    if email is None:
        raise _vf("email", "invalid_email", "Enter a valid email address")
    phone: str | None = None
    if body.phone:
        phone = normalize_phone(body.phone)
        if phone is None:
            raise _vf("phone", "invalid_mobile", "Enter a valid phone number")
    await rl.hit(
        f"sup16_enquiry_email:{identifier_digest('email', email)[1].hex()}", LIMITS_EMAIL, scope="sup16"
    )

    await system_context(session, "support.corporate_enquiry")
    now = clock.now()
    n = (await session.execute(text("SELECT nextval('corporate_enquiry_number_seq')"))).scalar_one()
    e = CorporateEnquiry(
        id=uuid7(),
        reference=f"TD-E-{now.year}-{int(n):06d}",
        name=body.name,
        company=body.company,
        email=email,
        phone=phone,
        message=body.message,
        consent_at=now,
        notice_version=NOTICE_VERSION,
        status="new",
        created_at=now,
        updated_at=now,
    )
    session.add(e)
    await session.flush()
    # Audit without PII: the record identifies the enquiry, not the sender.
    await audit(
        session,
        AuditActor.system("support.corporate_enquiry"),
        "support.enquiry.received",
        "corporate_enquiry",
        e.id,
        after={"reference": e.reference, "has_phone": phone is not None, "notice_version": NOTICE_VERSION},
    )
    await _notify_admins(session, e)
    return JSONResponse(ACCEPTED, status_code=202)


# --------------------------------------------------------------------------- Admin queue


def _out(e: CorporateEnquiry, *, full: bool) -> dict[str, Any]:
    out: dict[str, Any] = {
        "enquiry_id": str(e.id),
        "reference": e.reference,
        "name": e.name,
        "company": e.company,
        "email": e.email,
        "phone": e.phone,
        "status": e.status,
        "assigned_to": str(e.assigned_to) if e.assigned_to else None,
        "created_at": to_rfc3339(e.created_at),
        "updated_at": to_rfc3339(e.updated_at),
        "closed_at": to_rfc3339(e.closed_at) if e.closed_at else None,
    }
    if full:
        out |= {
            "message": e.message,
            "staff_note": e.staff_note,
            "consent_at": to_rfc3339(e.consent_at),
            "notice_version": e.notice_version,
        }
    else:
        out["message_preview"] = e.message[:160]
    return out


async def _require_admin_lane(session: Any, principal: Principal) -> sv.StaffScope:
    sc = await sv.staff_scope(session, principal)
    if not sc.all_categories:
        raise ProblemError("permission_denied", permission="user.read")
    return sc


class EnquiryPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Status | None = None
    assign_to_me: bool | None = None
    staff_note: str | None = Field(default=None, max_length=4000)


@staff.get("/support/enquiries", openapi_extra={"x-td-idle": "neutral"})
async def list_enquiries(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.read", PLATFORM_SCOPE)),
    status: Status | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> dict[str, Any]:
    await _require_admin_lane(session, principal)
    q = select(CorporateEnquiry)
    if status:
        q = q.where(CorporateEnquiry.status == status)
    if cursor:
        pos = decode_cursor(cursor)
        try:
            at, eid = datetime.fromisoformat(str(pos["at"])), uuid.UUID(str(pos["id"]))
        except (KeyError, ValueError) as ex:
            raise ProblemError("invalid_cursor") from ex
        q = q.where(tuple_(CorporateEnquiry.created_at, CorporateEnquiry.id) < tuple_(at, eid))
    rows = list(
        (
            await session.execute(
                q.order_by(CorporateEnquiry.created_at.desc(), CorporateEnquiry.id.desc()).limit(limit + 1)
            )
        ).scalars()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    new_count = (
        await session.execute(
            select(func.count()).select_from(CorporateEnquiry).where(CorporateEnquiry.status == "new")
        )
    ).scalar_one()
    return {
        "data": [_out(e, full=False) for e in rows],
        "page": page_meta(
            {"at": rows[-1].created_at.isoformat(), "id": str(rows[-1].id)} if more and rows else None, limit
        ),
        "counts": {"new": int(new_count)},
    }


async def _load(session: Any, enquiry_id: uuid.UUID, *, for_update: bool = False) -> CorporateEnquiry:
    q = select(CorporateEnquiry).where(CorporateEnquiry.id == enquiry_id)
    if for_update:
        q = q.with_for_update()
    e = (await session.execute(q)).scalar_one_or_none()
    if e is None:
        raise ProblemError("not_found")
    return e


@staff.get("/support/enquiries/{enquiry_id}", openapi_extra={"x-td-idle": "neutral"})
async def get_enquiry(
    enquiry_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.read", PLATFORM_SCOPE)),
) -> dict[str, Any]:
    await _require_admin_lane(session, principal)
    e = await _load(session, enquiry_id)
    await audit(session, principal, "support.enquiry.viewed", "corporate_enquiry", e.id)
    return _out(e, full=True)


@staff.patch("/support/enquiries/{enquiry_id}")
async def patch_enquiry(
    enquiry_id: uuid.UUID,
    body: EnquiryPatch,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_permission("user.read", PLATFORM_SCOPE)),
) -> dict[str, Any]:
    if not (await _require_admin_lane(session, principal)).can_assign:
        raise ProblemError("permission_denied", permission="ticket.assign")
    e = await _load(session, enquiry_id, for_update=True)
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise _vf("body", "empty", "Nothing to change")
    before = {"status": e.status, "assigned_to": str(e.assigned_to) if e.assigned_to else None}
    if fields.get("assign_to_me"):
        e.assigned_to = principal.user_id
    if body.status is not None:
        e.status = body.status
        e.closed_at = clock.now() if body.status in ("closed", "spam") else None
    if "staff_note" in fields:
        e.staff_note = body.staff_note
    e.updated_at = clock.now()
    await session.flush()
    await audit(
        session,
        principal,
        "support.enquiry.updated",
        "corporate_enquiry",
        e.id,
        before=before,
        after={
            "status": e.status,
            "assigned_to": str(e.assigned_to) if e.assigned_to else None,
            "staff_note_changed": "staff_note" in fields,
        },
    )
    return _out(e, full=True)


router = APIRouter()
for _r in (pub, staff):
    router.include_router(_r)
