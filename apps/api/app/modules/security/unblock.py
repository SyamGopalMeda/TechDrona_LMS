"""Unblock requests (UNB §3-§4; API UNB-01..18) and the unblock procedure (UNB §6; AUTH-21/22)."""

from __future__ import annotations

import html
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.outbox import emit_event
from app.core.principal import Principal
from app.core.time import to_rfc3339
from app.modules.admin.policy import get_value
from app.modules.identity import clock
from app.modules.identity.models import User
from app.modules.security import engine
from app.modules.security import restrictions as rx
from app.modules.security.cases import (
    APPEAL_DAYS,
    MANUAL_VERIFICATION,
    OPEN_UR,
    case_restriction,
    contact_eligible,
    get_case,
    has_eligible_contact,
    require_no_conflict,
    set_ur_state,
    vf,
)
from app.modules.security.models import (
    AccountRestriction,
    CaseDecision,
    SecurityCase,
    UnblockRequest,
)
from app.modules.security.refs import make_ref
from app.modules.security.signals import bump, count_since
from app.modules.sessions import service as ss
from app.modules.sessions.models import Device, UserDevice

WHAT_HAPPENED = (
    "all_devices_mine",
    "family_member_used",
    "shared_with_friend",
    "account_may_be_hacked",
    "shared_computer",
    "travelling_or_vpn",
    "other",
)
STATE_LABELS = {
    "draft": "Draft",
    "submitted": "Submitted",
    "under_review": "Under review",
    "info_requested": "Additional information requested",
    "escalated": "With senior reviewer",
    "approved": "Approved",
    "rejected": "Rejected",
    "closed": "Closed",
}
INFO_TEMPLATES = {
    "confirm_second_location": "Please tell us where you were on the dates shown.",
    "identify_devices": "Please tell us who uses each device listed on your devices page.",
    "shared_computer_details": "Please tell us where the shared computer you used is (an office, a café...).",
    "travel_details": "Please tell us the dates and places of your travel.",
    "other": "Please give us more information.",
}
DLP_REJECT = (
    re.compile(r"\b(otp|code|pin|passcode)\b\W{0,5}\d{4,8}\b", re.I),
    re.compile(r"\b\d{4,8}\b\W{0,5}\b(otp|code|pin)\b", re.I),
    re.compile(r"\bpass(word|wd)?\s*[:=]", re.I),
)
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
AADHAAR = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
DRAFT_TTL = timedelta(days=7)
INFO_DUE = timedelta(days=7)


# --------------------------------------------------------------------------- validation


def clean_text(raw: str | None) -> str:
    s = re.sub(r"<[^>]*>", "", raw or "")
    s = html.unescape(s).replace("\r\n", "\n").replace("\r", "\n")
    return s.strip()


def dlp(text_value: str) -> str:
    """Reject password/OTP-like content; mask card/Aadhaar-like numbers before storage."""
    for p in DLP_REJECT:
        if p.search(text_value):
            raise ProblemError("dlp_rejected", hint="Please don't include passwords or codes")
    text_value = CARD.sub("[removed]", text_value)
    return AADHAAR.sub("[removed]", text_value)


def validate_explanation(raw: str | None) -> str:
    s = clean_text(raw)
    if not 30 <= len(s) <= 2000:
        raise vf("explanation", "length", "Your explanation must be 30-2,000 characters")
    return dlp(s)


async def _user_devices(session: AsyncSession, user_id: uuid.UUID) -> list[UserDevice]:
    return list(
        (
            await session.execute(
                select(UserDevice).where(UserDevice.user_id == user_id, UserDevice.trust_status != "removed")
            )
        ).scalars()
    )


async def form(session: AsyncSession, principal: Principal, case_ref: str | None) -> dict[str, Any]:
    """Form meta (UNB §3): 5 loads per minute; devices to recognise; allowed contacts."""
    now = clock.now()
    key = f"unbform:{principal.user_id}"
    if await count_since(session, key, now - timedelta(minutes=1)) >= 5:
        raise ProblemError("unblock_rate_limited", headers={"Retry-After": "60"})
    await bump(session, key, now)
    user = await session.get(User, principal.user_id)
    devices = []
    # E2E-13: only devices that finished verification; never-verified ones are not offered
    # (they are still revoked on submit unless recognised -- they cannot be).
    for ud in await _user_devices(session, principal.user_id):
        if ud.trust_status != "trusted":
            continue
        dev = await session.get(Device, ud.device_id)
        devices.append(
            {
                "user_device_id": str(ud.id),
                "label": ud.user_label or (dev.label_hint if dev else None),
                "last_used_at": to_rfc3339(ud.last_used_at) if ud.last_used_at else None,
            }
        )
    return {
        "case_ref": case_ref,
        "what_happened_options": list(WHAT_HAPPENED),
        "devices": devices,
        "preferred_contact_options": _verified_channels(user),
        "explanation": {"min": 30, "max": 2000},
        "attachments": {
            "max_files": ATTACH_MAX_FILES,
            "max_bytes": ATTACH_MAX_BYTES,
            "content_types": sorted(ATTACH_TYPES),
            "hint": "Do not upload ID documents unless we ask; if asked, mask all but the last 4 digits.",
        },
        "declaration": "The information I've given is true. I understand one account is for one person.",
    }


def _verified_channels(user: User | None) -> list[str]:
    out = ["in_app"]
    if user and user.email and user.email_verified_at:
        out.append("email")
    if user and user.phone_e164 and user.phone_verified_at:
        out.append("sms")
    return out


async def own_case_by_ref(session: AsyncSession, user_id: uuid.UUID, case_ref: str) -> SecurityCase:
    c = (
        await session.execute(select(SecurityCase).where(SecurityCase.case_ref == case_ref))
    ).scalar_one_or_none()
    if c is None or c.user_id != user_id:
        raise ProblemError("not_found")  # no existence disclosure
    return c


# --------------------------------------------------------------------------- attachments (UNB-03/16)

ATTACH_TYPES = frozenset({"application/pdf", "image/png", "image/jpeg"})
ATTACH_MAX_BYTES = 5 * 1024 * 1024
ATTACH_MAX_FILES = 2
ATTACH_STATES = ("draft", "info_requested", "rejected")


def attachment_meta(a: dict[str, Any]) -> dict[str, Any]:
    """Attachment list entry without the storage key."""
    return {k: a.get(k) for k in ("attachment_id", "filename", "content_type", "size_bytes", "scan_status")}


async def new_attachment(
    session: AsyncSession,
    principal: Principal,
    ur: UnblockRequest,
    *,
    filename: str,
    content_type: str,
    size_bytes: int,
) -> dict[str, Any]:
    """UNB-03: presigned S3 POST into the private uploads bucket (no binaries via the API).
    At most 2 files per request, each <= 5 MB, PDF/PNG/JPG; viewed only after the malware scan."""
    from app.modules.media.storage import presign_post, safe_filename, storage_settings

    if ur.state not in ATTACH_STATES or (ur.state == "rejected" and ur.appeal_used):
        raise ProblemError("invalid_state_transition", current_state=ur.state, allowed=list(ATTACH_STATES))
    if content_type not in ATTACH_TYPES:
        raise ProblemError("unsupported_media_type", detail="Upload a PDF, PNG or JPG file.")
    if size_bytes > ATTACH_MAX_BYTES:
        raise ProblemError("payload_too_large", detail="Each file can be at most 5 MB.")
    if len(ur.attachments) >= ATTACH_MAX_FILES:
        raise vf("attachments", "too_many", "You can attach at most 2 files")
    att_id = uuid7()
    name = safe_filename(filename)
    s = storage_settings()
    key = f"uploads/unblock_request/{ur.user_id}/{ur.id}/{att_id}/{name}"
    post = presign_post(s.S3_BUCKET_UPLOADS, key, content_type=content_type, max_bytes=size_bytes)
    ur.attachments = [
        *ur.attachments,
        {
            "attachment_id": str(att_id),
            "filename": name,
            "content_type": content_type,
            "size_bytes": size_bytes,
            "s3_key": key,
            "scan_status": "pending",
            "added_at": to_rfc3339(clock.now()),
        },
    ]
    ur.version += 1
    await session.flush()
    await audit(
        session,
        principal,
        "unblock.attachment_added",
        "unblock_request",
        ur.id,
        subject_user_id=ur.user_id,
        after={"attachment_id": str(att_id), "content_type": content_type, "size_bytes": size_bytes},
    )
    return {
        "attachment_id": str(att_id),
        "filename": name,
        "upload": {"url": post.url, "fields": post.fields},
        "expires_at": to_rfc3339(post.expires_at),
        "max_bytes": size_bytes,
    }


async def attachment_view_url(
    session: AsyncSession, ur: UnblockRequest, attachment_id: str
) -> tuple[str, datetime, dict[str, Any]]:
    """UNB-16: 5-minute inline (no download disposition) URL for a scanned-clean attachment."""
    from app.modules.media.providers import get_scanner
    from app.modules.media.storage import presign_get, storage_settings

    att = next((a for a in ur.attachments if a.get("attachment_id") == attachment_id), None)
    if att is None:
        raise ProblemError("not_found")
    if att.get("scan_status") == "pending":
        result = get_scanner().immediate_result(att["s3_key"])
        if result in ("clean", "infected"):
            att = {**att, "scan_status": result}
            ur.attachments = [att if a.get("attachment_id") == attachment_id else a for a in ur.attachments]
            await session.flush()
    if att.get("scan_status") != "clean":
        state = "scan_pending" if att.get("scan_status") == "pending" else "quarantined"
        raise ProblemError("invalid_state_transition", current_state=state, allowed=["clean"])
    url, expires_at = presign_get(storage_settings().S3_BUCKET_UPLOADS, att["s3_key"])
    return url, expires_at, att


def request_out(ur: UnblockRequest, *, case_ref: str | None = None) -> dict[str, Any]:
    return {
        "request_id": str(ur.id),
        "reference": ur.reference,
        "case_ref": case_ref,
        "state": ur.state,
        "state_label": STATE_LABELS[ur.state],
        "closure_reason": ur.closure_reason,
        "submitted_at": to_rfc3339(ur.submitted_at) if ur.submitted_at else None,
        "is_second_level_appeal": ur.is_second_level_appeal,
        "version": ur.version,
    }


async def student_view(session: AsyncSession, ur: UnblockRequest) -> dict[str, Any]:
    case = await session.get(SecurityCase, ur.case_id)
    d = (
        await session.execute(
            select(CaseDecision)
            .where(CaseDecision.unblock_request_id == ur.id)
            .order_by(CaseDecision.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    deadline = (
        d.created_at + timedelta(days=APPEAL_DAYS)
        if d is not None and d.outcome in ("uphold", "convert_L4")
        else None
    )
    appeal_allowed = bool(
        ur.state == "rejected" and deadline is not None and clock.now() < deadline and not ur.appeal_used
    )
    timeline = [
        {
            k: v
            for k, v in e.items()
            if k in ("at", "state", "question_template", "message", "closure_reason", "appeal_deadline")
        }
        for e in ur.timeline
    ]
    return {
        **request_out(ur, case_ref=case.case_ref if case else None),
        "timeline": timeline,
        "attachments": [attachment_meta(a) for a in ur.attachments],
        "info_requested_due": to_rfc3339(ur.info_requested_due) if ur.info_requested_due else None,
        "decision": {
            "outcome": d.outcome,
            "summary": d.student_summary,
            "decided_at": to_rfc3339(d.created_at),
            "appeal_deadline": to_rfc3339(deadline) if deadline else None,
        }
        if d
        else None,
        "appeal": {"allowed": appeal_allowed, "deadline": to_rfc3339(deadline) if deadline else None},
        "grievance_route": "/help/grievance",
    }


async def create_request(
    session: AsyncSession, principal: Principal, body: dict[str, Any], idem_key: str | None
) -> dict[str, Any]:
    case = await own_case_by_ref(session, principal.user_id, str(body.get("case_ref") or ""))
    if case.status == "closed":
        raise ProblemError("not_found")
    existing = (
        await session.execute(
            select(UnblockRequest).where(
                UnblockRequest.case_id == case.id, UnblockRequest.state.in_(("draft", *OPEN_UR))
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ProblemError("unblock_request_open", reference=existing.reference)
    ur = UnblockRequest(
        id=uuid7(),
        created_at=clock.now(),
        reference=make_ref("APL"),
        case_id=case.id,
        user_id=principal.user_id,
        state="draft",
        timeline=[],
        idempotency_key=idem_key,
        version=1,
    )
    _apply_fields(ur, body, partial=not body.get("submit"))
    r = await case_restriction(session, case)
    ur.restriction_id = r.id if r else None
    session.add(ur)
    await session.flush()
    await audit(
        session,
        principal,
        "unblock.created",
        "unblock_request",
        ur.id,
        subject_user_id=principal.user_id,
        after={"reference": ur.reference, "case_ref": case.case_ref},
    )
    if body.get("submit"):
        return await submit(session, principal, ur, case, none_recognised=bool(body.get("none_recognised")))
    return {**request_out(ur, case_ref=case.case_ref), "devices_revoked": []}


def _apply_fields(ur: UnblockRequest, body: dict[str, Any], *, partial: bool) -> None:
    if "what_happened" in body or not partial:
        wh = list(body.get("what_happened") or [])
        if any(w not in WHAT_HAPPENED for w in wh):
            raise vf("what_happened", "invalid", "Unknown option")
        ur.what_happened = wh
    if "explanation" in body and body.get("explanation") is not None:
        s = clean_text(body["explanation"])
        ur.explanation = validate_explanation(s) if (not partial or len(s) >= 30) else None
    if "recognised_user_device_ids" in body:
        ur.recognised_device_ids = [uuid.UUID(str(x)) for x in body.get("recognised_user_device_ids") or []]
    if "lab_location_text" in body:
        lab = clean_text(body.get("lab_location_text"))[:200] or None
        ur.lab_location_text = lab
    if "preferred_contact" in body:
        ur.preferred_contact = body.get("preferred_contact")
    if "guardian_assisted" in body:
        ur.guardian_assisted = bool(body.get("guardian_assisted"))
    if body.get("declaration"):
        ur.declaration_at = clock.now()


async def update_draft(
    session: AsyncSession, principal: Principal, ur: UnblockRequest, body: dict[str, Any]
) -> dict[str, Any]:
    if ur.state != "draft":
        raise ProblemError("invalid_state_transition", current_state=ur.state, allowed=["draft"])
    _apply_fields(ur, body, partial=True)
    ur.version += 1
    await session.flush()
    case = await session.get(SecurityCase, ur.case_id)
    return request_out(ur, case_ref=case.case_ref if case else None)


async def submit(
    session: AsyncSession,
    principal: Principal,
    ur: UnblockRequest,
    case: SecurityCase | None = None,
    *,
    none_recognised: bool = False,
) -> dict[str, Any]:
    if ur.state != "draft":
        raise ProblemError("invalid_state_transition", current_state=ur.state, allowed=["draft"])
    case = case or await get_case(session, ur.case_id)
    user = await session.get(User, principal.user_id)
    now = clock.now()
    limit = int(await get_value(session, "unblock.max_requests_per_30d", user_id=principal.user_id))
    used = (
        await session.execute(
            select(func.count())
            .select_from(UnblockRequest)
            .where(
                UnblockRequest.user_id == principal.user_id,
                UnblockRequest.submitted_at > now - timedelta(days=30),
            )
        )
    ).scalar_one()
    if used >= limit:
        raise ProblemError("unblock_rate_limited", headers={"Retry-After": "86400"})
    if not ur.what_happened:
        raise vf("what_happened", "required", "Choose at least one option")
    if ur.explanation is None:
        raise vf("explanation", "length", "Your explanation must be 30-2,000 characters")
    if ur.declaration_at is None:
        raise vf("declaration", "required", "Please accept the declaration")
    if ur.preferred_contact is None:
        ur.preferred_contact = "in_app"  # E2E-13: optional in the API, in-app is always available
    if ur.preferred_contact not in _verified_channels(user):
        raise vf("preferred_contact", "not_verified", "Choose a verified contact channel")
    devices = await _user_devices(session, principal.user_id)
    mine = {ud.id for ud in devices}
    recognised = set(ur.recognised_device_ids)
    if not recognised and not none_recognised:
        raise vf(
            "recognised_user_device_ids", "required", "Select the devices you recognise, or 'None of these'"
        )
    if not recognised <= mine:
        raise ProblemError("not_found")
    # Unrecognised devices are revoked on submit.
    revoked: list[dict[str, Any]] = []
    unrec: list[uuid.UUID] = []
    for ud in devices:
        if ud.id in recognised:
            continue
        dev = await session.get(Device, ud.device_id)
        unrec.append(ud.id)
        await ss.remove_user_device(session, ud, "security_action", removed_by=principal.user_id)
        revoked.append(
            {"user_device_id": str(ud.id), "label": ud.user_label or (dev.label_hint if dev else None)}
        )
    ur.unrecognised_device_ids = unrec
    ur.submitted_at = now
    await set_ur_state(session, ur, "submitted")
    channels = ["in_app"] + ([ur.preferred_contact] if ur.preferred_contact in ("email", "sms") else [])
    await engine.notify_user(
        session,
        principal.user_id,
        "security.unblock_received",
        subject=f"We've received your request {ur.reference}",
        text_body=f"We've received your review request {ur.reference} for case {case.case_ref}. "
        "A person will "
        "look at it, usually within 24 hours.",
        data={"reference": ur.reference, "case_ref": case.case_ref},
        sms=ur.preferred_contact == "sms",
    )
    await audit(
        session,
        principal,
        "unblock.submitted",
        "unblock_request",
        ur.id,
        subject_user_id=principal.user_id,
        after={"reference": ur.reference, "devices_revoked": len(revoked)},
    )
    return {
        **request_out(ur, case_ref=case.case_ref),
        "devices_revoked": revoked,
        "sla": {
            "first_response_due": to_rfc3339(case.sla_first_response_due)
            if case.sla_first_response_due
            else None,
            "decision_due": to_rfc3339(case.sla_decision_due) if case.sla_decision_due else None,
        },
        "acknowledgement_sent_via": channels,
    }


async def respond(
    session: AsyncSession, principal: Principal, ur: UnblockRequest, body: dict[str, Any]
) -> dict[str, Any]:
    if ur.state != "info_requested":
        raise ProblemError("invalid_state_transition", current_state=ur.state, allowed=["info_requested"])
    text_value = validate_explanation(body.get("explanation"))
    case = await get_case(session, ur.case_id, lock=True)
    if ur.info_requested_at is not None:  # SLA clock was paused
        paused = clock.now() - ur.info_requested_at
        if case.sla_decision_due:
            case.sla_decision_due += paused
        if case.sla_first_response_due and case.first_response_at is None:
            case.sla_first_response_due += paused
    ur.info_requested_at = None
    ur.info_requested_due = None
    await set_ur_state(session, ur, "under_review", note={"message": text_value[:2000], "by": "student"})
    case.status = "under_review"
    case.version += 1
    await audit(
        session, principal, "unblock.responded", "unblock_request", ur.id, subject_user_id=principal.user_id
    )
    return request_out(ur, case_ref=case.case_ref)


async def withdraw(session: AsyncSession, principal: Principal, ur: UnblockRequest) -> dict[str, Any]:
    if ur.state not in ("draft", "submitted", "under_review", "info_requested"):
        raise ProblemError(
            "invalid_state_transition",
            current_state=ur.state,
            allowed=["draft", "submitted", "under_review", "info_requested"],
        )
    await set_ur_state(session, ur, "closed", closure="withdrawn")
    await audit(
        session, principal, "unblock.withdrawn", "unblock_request", ur.id, subject_user_id=principal.user_id
    )
    return request_out(ur)


async def appeal(
    session: AsyncSession, principal: Principal, ur: UnblockRequest, body: dict[str, Any]
) -> dict[str, Any]:
    if ur.appeal_used or ur.is_second_level_appeal:
        raise ProblemError("appeal_already_used")
    if ur.state != "rejected":
        raise ProblemError("invalid_state_transition", current_state=ur.state, allowed=["rejected"])
    if ur.decided_at is None or clock.now() > ur.decided_at + timedelta(days=APPEAL_DAYS):
        raise ProblemError("appeal_window_closed")
    text_value = validate_explanation(body.get("explanation"))
    ur.appeal_used = True
    ur.is_second_level_appeal = True
    ur.escalated_at = clock.now()
    await set_ur_state(
        session, ur, "escalated", note={"message": text_value[:2000], "by": "student", "appeal": True}
    )
    case = await get_case(session, ur.case_id, lock=True)
    case.status = "escalated"
    case.escalated_at = clock.now()
    first_h, dec_h = 24, 72
    sla = await get_value(session, "unblock.sla.decision_hours")
    dec_h = int(sla.get("escalated", dec_h))
    case.sla_first_response_due = clock.now() + timedelta(hours=first_h)
    case.sla_decision_due = clock.now() + timedelta(hours=dec_h)
    case.assignee_id = None
    case.version += 1
    await audit(
        session, principal, "unblock.appealed", "unblock_request", ur.id, subject_user_id=principal.user_id
    )
    return {"state": "escalated", "state_label": STATE_LABELS["escalated"], "is_second_level_appeal": True}


# --------------------------------------------------------------------------- reviewer transitions


async def claim(session: AsyncSession, principal: Principal, ur: UnblockRequest) -> dict[str, Any]:
    from app.modules.security.cases import require_no_conflict

    if ur.state not in ("submitted", "escalated"):
        raise ProblemError(
            "invalid_state_transition", current_state=ur.state, allowed=["submitted", "escalated"]
        )
    case = await get_case(session, ur.case_id, lock=True)
    r = await case_restriction(session, case)
    await require_no_conflict(session, principal.user_id, case, r)
    if ur.is_second_level_appeal and ur.rejected_by == principal.user_id:
        raise ProblemError("conflict_of_interest", reasons=["decided_original_request"])
    now = clock.now()
    ur.assigned_to = principal.user_id
    if ur.state == "submitted":
        await set_ur_state(session, ur, "under_review")
    else:
        ur.version += 1
    case.assignee_id = principal.user_id
    if case.status in ("open", "awaiting_user"):
        case.status = "under_review"
    if case.first_response_at is None:
        case.first_response_at = now
    case.version += 1
    await session.flush()
    await engine.notify_user(
        session,
        ur.user_id,
        "security.unblock_under_review",
        subject="A reviewer is looking at your case",
        text_body="A member of our security team is reviewing your request.",
        data={"reference": ur.reference},
    )
    await audit(
        session,
        principal,
        "unblock.claimed",
        "unblock_request",
        ur.id,
        subject_user_id=ur.user_id,
        reason_code="case_review",
    )
    return request_out(ur, case_ref=case.case_ref)


async def request_info(
    session: AsyncSession, principal: Principal, ur: UnblockRequest, template_key: str, message: str | None
) -> dict[str, Any]:
    if ur.state != "under_review":
        raise ProblemError("invalid_state_transition", current_state=ur.state, allowed=["under_review"])
    if template_key not in INFO_TEMPLATES:
        raise vf("template_key", "invalid", "Unknown template")
    if ur.assigned_to != principal.user_id:
        raise ProblemError("permission_denied", permission="security.unblock.triage")
    now = clock.now()
    ur.info_requested_at = now
    ur.info_requested_due = now + INFO_DUE
    msg = clean_text(message)[:1000] or INFO_TEMPLATES[template_key]
    await set_ur_state(
        session, ur, "info_requested", note={"question_template": template_key, "message": msg}
    )
    case = await get_case(session, ur.case_id, lock=True)
    case.status = "awaiting_user"
    case.version += 1
    await engine.notify_user(
        session,
        ur.user_id,
        "security.unblock_info_requested",
        subject="We need a little more information",
        text_body=msg,
        data={"reference": ur.reference},
        sms=ur.preferred_contact == "sms",
    )
    await audit(
        session, principal, "unblock.info_requested", "unblock_request", ur.id, subject_user_id=ur.user_id
    )
    return {
        "state": "info_requested",
        "info_requested_due": to_rfc3339(ur.info_requested_due),
        "sla_paused": True,
    }


async def escalate(
    session: AsyncSession, principal: Principal | None, ur: UnblockRequest, reason: str
) -> dict[str, Any]:
    if ur.state not in ("submitted", "under_review"):
        raise ProblemError(
            "invalid_state_transition", current_state=ur.state, allowed=["submitted", "under_review"]
        )
    ur.escalated_at = clock.now()
    await set_ur_state(session, ur, "escalated", note={"reason": reason})
    case = await get_case(session, ur.case_id, lock=True)
    case.status = "escalated"
    case.escalated_at = clock.now()
    case.version += 1
    actor: Principal | AuditActor = principal or AuditActor.system("security.sla")
    await audit(
        session,
        actor,
        "unblock.escalated",
        "unblock_request",
        ur.id,
        subject_user_id=ur.user_id,
        reason=reason,
    )
    return request_out(ur, case_ref=case.case_ref)


async def send_back_request(
    session: AsyncSession, principal: Principal, ur: UnblockRequest, note: str
) -> dict[str, Any]:
    if ur.state != "escalated":
        raise ProblemError("invalid_state_transition", current_state=ur.state, allowed=["escalated"])
    if ur.assigned_to == principal.user_id:
        raise ProblemError("sod_violation", rule="SoD-06", detail="A second reviewer must send it back.")
    await set_ur_state(session, ur, "under_review", note={"note": "sent_back"})
    case = await get_case(session, ur.case_id, lock=True)
    case.status = "under_review"
    case.version += 1
    from app.modules.security.cases import case_note

    await case_note(session, case.id, principal.user_id, "internal", note)
    await audit(
        session,
        principal,
        "unblock.sent_back",
        "unblock_request",
        ur.id,
        subject_user_id=ur.user_id,
        reason=note,
    )
    return request_out(ur, case_ref=case.case_ref)


# --------------------------------------------------------------------------- AUTH-21 / AUTH-22


async def reverifiable(session: AsyncSession, user_id: uuid.UUID) -> AccountRestriction:
    """The restriction a re-verification ends: lift pending after a decision, or an L3 whose
    ``ends_at`` passed (auto-expiry; RE §6.1, UNB §6)."""
    now = clock.now()
    for r in await rx.active_restrictions(session, user_id):
        if r.family == "sharing" and r.level >= 3:
            if r.lift_pending_at is not None:
                return r
            if r.level == 3 and r.ends_at is not None and r.ends_at <= now:
                return r
    raise ProblemError(
        "invalid_state_transition",
        current_state="no_lift_pending",
        allowed=[],
        detail="There is nothing to re-verify yet.",
    )


async def reverify_start(
    session: AsyncSession, principal: Principal, channel: str, ip: str | None
) -> dict[str, Any]:
    from app.modules.identity import service as ids
    from app.modules.identity.contacts import mask_email, mask_phone
    from app.modules.notifications.service import send_email, send_sms

    r = await reverifiable(session, principal.user_id)
    user = await session.get(User, principal.user_id)
    assert user is not None
    if channel == "sms":
        dest, verified_at = user.phone_e164, user.phone_verified_at
    else:
        dest, verified_at = user.email, user.email_verified_at
    if not dest or not contact_eligible(verified_at, r.starts_at):
        raise ProblemError(
            "invalid_state_transition",
            current_state="contact_not_eligible",
            allowed=[],
            detail="This contact changed recently, so a senior reviewer will verify you manually.",
        )
    wait = await ids.otp_send_allowed(session, channel, dest)
    if wait:
        raise ProblemError("otp_send_limited", headers={"Retry-After": str(wait)})
    _, code = await ids.create_otp(
        session,
        user_id=user.id,
        purpose="step_up_otp",
        channel=channel,
        destination=dest,
        auth_session_id=principal.session_id,
        ip=ip,
    )
    msg = f"{code} is your Tech Drona code to restore access. It expires in 5 minutes. Never share it."
    if channel == "sms":
        await send_sms(dest, msg, template_key="otp")
        masked = mask_phone(dest)
    else:
        await send_email(dest, "Your code to restore access", msg, template_key="security.reverify_otp")
        masked = mask_email(dest)
    return {"sent_to": masked, "expires_in_seconds": int(await get_value(session, "otp.ttl_seconds"))}


async def reverify_complete(
    session: AsyncSession, principal: Principal, body: dict[str, Any]
) -> dict[str, Any]:
    """UNB §6 steps 3-9: OTP (+ MFA, + password reset when required), device review, revoke
    ALL sessions, end the restriction, entitlement credit for false positives, notifications."""
    from app.modules.identity import service as ids

    r = await reverifiable(session, principal.user_id)
    user = await session.get(User, principal.user_id)
    assert user is not None
    chk = await ids.check_otp(
        session,
        purpose="step_up_otp",
        code=str(body.get("otp_code") or ""),
        user_id=user.id,
        auth_session_id=principal.session_id,
    )
    if not chk.ok:
        assert chk.problem is not None
        raise _Deferred(chk.problem)
    if await ids.has_strong_factor(session, user.id):
        mfa = body.get("mfa") or {}
        if not mfa.get("code") or not await ids.verify_totp_code(session, user.id, str(mfa["code"])):
            raise _Deferred(
                ProblemError("otp_invalid", attempts_remaining=None, detail="Authenticator code needed")
            )
    decision = await session.get(CaseDecision, r.decision_id) if r.decision_id else None
    needs_pw = decision is not None and bool((decision.conditions or {}).get("password_reset"))
    if needs_pw or user.must_change_password:
        pw = body.get("new_password")
        if not pw or len(str(pw)) < 12:
            raise ProblemError(
                "validation_failed",
                422,
                errors=[
                    {
                        "field": "new_password",
                        "code": "password_reset_required",
                        "message": "Choose a new password",
                    }
                ],
            )
        await ids.set_password(session, user.id, str(pw))
    # Device review: unconfirmed devices removed without consuming replacement quota.
    keep = {str(d.get("user_device_id")) for d in body.get("devices") or [] if d.get("keep")}
    removed = 0
    for ud in await _user_devices(session, user.id):
        if str(ud.id) not in keep:
            await ss.remove_user_device(session, ud, "unblock_reset", removed_by=user.id)
            removed += 1
    actor = AuditActor("user", user_id=user.id, session_id=principal.session_id)
    revoked, credit_days, reason = await _restore_access(
        session, user.id, r, decision, actor, ended_by=user.id
    )
    await audit(
        session,
        actor,
        "security.reverified",
        "account_restriction",
        r.id,
        subject_user_id=user.id,
        after={"sessions_revoked": revoked, "devices_removed": removed, "end_reason": reason},
    )
    return {
        "result": "reverified",
        "restriction_ended": True,
        "sessions_revoked": revoked,
        "devices_removed": removed,
        "extension_days_credited": credit_days,
        "next": "login",
    }


async def _restore_access(
    session: AsyncSession,
    user_id: uuid.UUID,
    r: AccountRestriction,
    decision: CaseDecision | None,
    actor: Principal | AuditActor,
    *,
    ended_by: uuid.UUID,
) -> tuple[int, int, str]:
    """UNB §6 steps 5-9 shared by OTP re-verification and senior manual verification: revoke ALL
    sessions, end the restriction, close the case and its requests, false-positive credit,
    notify. Returns (sessions_revoked, credit_days, end_reason)."""
    revoked = await ss.revoke_all_sessions(session, user_id, "unblock_reset")
    reason = "case_decision" if decision is not None else "expired_reverified"
    await rx.end_restriction(session, r, reason, ended_by=ended_by, decision_id=r.decision_id, actor=actor)
    case = await session.get(SecurityCase, r.case_id) if r.case_id else None
    credit_days = 0
    if case is not None:
        urs = (
            (
                await session.execute(
                    select(UnblockRequest)
                    .where(
                        UnblockRequest.case_id == case.id,
                        UnblockRequest.state.in_(
                            (
                                "draft",
                                "submitted",
                                "under_review",
                                "info_requested",
                                "escalated",
                                "approved",
                                "rejected",
                            )
                        ),
                    )
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
        for u in urs:
            done = u.state == "approved" or (u.state == "escalated" and awaiting_manual_verification(u))
            await set_ur_state(session, u, "closed", closure="completed" if done else "moot")
        case.status = "closed"
        case.closed_at = clock.now()
        case.version += 1
        if decision is not None and decision.outcome == "lift_false_positive":
            credit_days = await false_positive_credit(session, user_id, case, decision)
    await engine.notify_user(
        session,
        user_id,
        "security.access_restored",
        subject="Access restored",
        text_body="Your learning access is back. Sign in again to continue. Keep your "
        "password private and remove devices you don't use.",
        data={"case_ref": case.case_ref if case else None},
    )
    return revoked, credit_days, reason


def awaiting_manual_verification(ur: UnblockRequest) -> bool:
    return any(e.get("escalation_reason") == MANUAL_VERIFICATION for e in ur.timeline)


MANUAL_METHODS = ("video_call", "callback_known_number", "document_check", "in_person")


async def manual_verification(
    session: AsyncSession, principal: Principal, r: AccountRestriction, method: str, note: str
) -> dict[str, Any]:
    """UNB §6.3a / §4.2: a senior reviewer (not the decider, no conflict) records a manual identity
    verification for a student without a contact that predates the restriction, then the unblock
    procedure runs as after an OTP re-verification. The student re-reviews devices at next login."""
    if r.ended_at is not None or r.family != "sharing" or r.level < 3:
        raise ProblemError("not_found")
    expired_l3 = r.level == 3 and r.ends_at is not None and r.ends_at <= clock.now()
    if r.lift_pending_at is None and not expired_l3:
        raise ProblemError(
            "invalid_state_transition", current_state="active", allowed=["lift_pending", "expired"]
        )
    user = await session.get(User, r.user_id)
    if has_eligible_contact(user, r.starts_at):
        raise ProblemError(
            "invalid_state_transition",
            current_state="student_reverification",
            allowed=[],
            detail="The student has an eligible contact and re-verifies by code.",
        )
    decision = await session.get(CaseDecision, r.decision_id) if r.decision_id else None
    if decision is not None and principal.user_id in (decision.decided_by, decision.approved_by):
        raise ProblemError(
            "sod_violation", rule="SoD-06", detail="A different, senior reviewer must verify the student."
        )
    if r.case_id is not None:
        await require_no_conflict(session, principal.user_id, await get_case(session, r.case_id), r)
    elif r.user_id == principal.user_id:
        raise ProblemError("conflict_of_interest", reasons=["own_account"])
    if decision is not None and (decision.conditions or {}).get("password_reset"):
        await session.execute(update(User).where(User.id == r.user_id).values(must_change_password=True))
    revoked, credit_days, reason = await _restore_access(
        session, r.user_id, r, decision, principal, ended_by=principal.user_id
    )
    await audit(
        session,
        principal,
        "security.manual_verification",
        "account_restriction",
        r.id,
        subject_user_id=r.user_id,
        reason_code="case_review",
        reason=note[:500],
        after={"method": method, "sessions_revoked": revoked, "end_reason": reason},
    )
    return {
        "result": "manually_verified",
        "restriction_ended": True,
        "sessions_revoked": revoked,
        "extension_days_credited": credit_days,
    }


class _Deferred(Exception):
    """An OTP failure whose attempt counter must still be committed (returned, not raised)."""

    def __init__(self, problem: ProblemError) -> None:
        super().__init__(problem.code)
        self.problem = problem


async def false_positive_credit(
    session: AsyncSession, user_id: uuid.UUID, case: SecurityCase, decision: CaseDecision
) -> int:
    """UNB §6 step 8 (PO-10): restricted days from the original start of the case (L3 and any L4)
    are credited to time-bound entitlements by commerce via the outbox."""
    if not await get_value(session, "unblock.false_positive_extension", user_id=user_id):
        return 0
    first = (
        await session.execute(
            select(func.min(AccountRestriction.starts_at)).where(
                AccountRestriction.case_id == case.id, AccountRestriction.level >= 3
            )
        )
    ).scalar_one()
    if first is None:
        return 0
    seconds = (clock.now() - first).total_seconds()
    days = max(int(decision.extension_days or 0), int(-(-seconds // 86400)))
    await emit_event(
        session,
        "security.false_positive_credit",
        {
            "user_id": str(user_id),
            "case_ref": case.case_ref,
            "restricted_days": days,
            "decision_id": str(decision.id),
            "reason": "security_false_positive_credit",
        },
        aggregate_type="security_case",
        aggregate_id=case.id,
    )
    await audit(
        session,
        AuditActor.system("security.unblock"),
        "security.extension_credited",
        "security_case",
        case.id,
        subject_user_id=user_id,
        after={"restricted_days": days},
    )
    return days
