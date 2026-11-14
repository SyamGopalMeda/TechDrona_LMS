"""Admission / offer letter step after enrolment (Admin > Admissions).

The letter itself is an issued document of the learning documents register: the SPA previews it
with ``POST /admin/documents/preview`` and issues it with ``POST /admin/documents`` (email per the
auto-send / approval setting), using the draft built here. Corrections go through the register's
re-issue (supersede) flow.

A letter belongs to a registration when it is an ``offer_course`` / ``offer_internship`` document
of the registration's LMS user that names the registration (``recipient.reg_no``, set by the
draft) or its enrolment (``enrolment_id``, e.g. the automatic letter issued on enrolment). Nothing
is stored on the registration: the documents register stays the single source of truth.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from datetime import date
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.errors import ProblemError
from app.core.time import ist_date, utcnow
from app.modules.admissions import datastore as ads
from app.modules.admissions import rules as R
from app.modules.admissions.models import AdmissionPaySettings, AdmissionRegistration
from app.modules.admissions.service import Actor, iso

log = structlog.get_logger("app.admissions.letters")

LETTER_TYPES: tuple[str, ...] = ("offer_course", "offer_internship")
_INTERN = re.compile(r"\bintern(ship)?s?\b", re.I)
_MODES = {"online": "Online", "offline": "On-site", "on-site": "On-site", "onsite": "On-site",
          "classroom": "On-site", "hybrid": "Hybrid"}  # fmt: skip
NOT_READY = "Enrol the student first: the letter is issued once they are in the course."


def letter_type(reg: AdmissionRegistration) -> str:
    """``offer_internship`` for an internship programme (slug or title says so), else the course
    admission letter."""
    text = f"{reg.course_slug} {reg.course_title}".replace("-", " ")
    return "offer_internship" if _INTERN.search(text) else "offer_course"


def _mode(raw: str | None, fallback: str = "Online") -> str:
    return _MODES.get(" ".join((raw or "").lower().split()), fallback)


def _batch_terms(batch: Any) -> tuple[date | None, date | None, str | None]:
    """(start, end, duration) of a batch; the duration as the automatic letter words it."""
    if batch is None or not batch.starts_on:
        return None, None, None
    start, end = batch.starts_on, batch.ends_on
    if end and end > start:
        days = (end - start).days + 1
        return start, end, f"{round(days / 7)} weeks" if days >= 14 else f"{days} days"
    return start, None, None


# --------------------------------------------------------------------------- letters of registrations


async def _letter_docs(session: AsyncSession, user_ids: Iterable[uuid.UUID]) -> list[Any]:
    """Every letter-type document of these users (any status)."""
    from app.modules.learning import fs_docs
    from app.modules.learning import fs_store as fss
    from app.modules.learning.doc_models import IssuedDocument

    ids = sorted({str(u) for u in user_ids if u is not None})
    if not ids:
        return []
    if fss.fs():
        out: list[Any] = []
        for i in range(0, len(ids), 30):  # Firestore ``in`` takes at most 30 values
            out += await fss.find(
                None,
                IssuedDocument,
                filters=(("user_id", "in", ids[i : i + 30]),),
                where=lambda d: d.doc_type in LETTER_TYPES,
                job=fs_docs.JOB,
            )
        return out
    rows = await session.execute(
        select(IssuedDocument).where(
            IssuedDocument.user_id.in_([uuid.UUID(x) for x in ids]),
            IssuedDocument.doc_type.in_(LETTER_TYPES),
        )
    )
    return list(rows.scalars())


def belongs(doc: Any, reg: AdmissionRegistration) -> bool:
    if reg.user_id is None or doc.user_id != reg.user_id or doc.doc_type not in LETTER_TYPES:
        return False
    if reg.enrolment_id is not None and doc.enrolment_id == reg.enrolment_id:
        return True
    return (doc.recipient or {}).get("reg_no") == reg.reg_no


def _newest_first(docs: list[Any]) -> list[Any]:
    return sorted(docs, key=lambda d: (d.created_at or utcnow(), str(d.id)), reverse=True)


async def letters_by_registration(
    session: AsyncSession, regs: list[AdmissionRegistration]
) -> dict[uuid.UUID, list[Any]]:
    """Each registration's letters, newest first (registrations without an LMS user have none)."""
    docs = await _letter_docs(session, [r.user_id for r in regs if r.user_id is not None])
    return {r.id: _newest_first([d for d in docs if belongs(d, r)]) for r in regs}


def current(docs: list[Any]) -> Any | None:
    """The letter in force: the newest valid one."""
    return next((d for d in docs if d.status == "valid"), None)


def summary(doc: Any | None) -> dict[str, Any] | None:
    """Short form for lists and the registration page: "Letter issued: TD-AL-… (date)"."""
    if doc is None:
        return None
    from app.modules.learning import docdefs as dd

    return {
        "id": str(doc.id),
        "doc_type": doc.doc_type,
        "short": dd.DOC_TYPES[doc.doc_type]["short"],
        "ref_no": doc.ref_no,
        "issue_date": doc.issue_date.isoformat(),
        "status": doc.status,
        "origin": doc.origin,
    }


async def letter_info(session: AsyncSession, regs: list[AdmissionRegistration]) -> dict[uuid.UUID, Any]:
    """``summary`` of each registration's letter in force (None when there is none). Never fails
    the caller: a documents-store problem is logged and reads as "no letter"."""
    try:
        by_reg = await letters_by_registration(session, regs)
    except Exception as e:  # an auxiliary column must not break the registrations list
        log.warning("admission_letters_lookup_failed", error=type(e).__name__)
        return {}
    return {rid: summary(current(docs)) for rid, docs in by_reg.items()}


# --------------------------------------------------------------------------- draft


async def draft(session: AsyncSession, reg: AdmissionRegistration) -> dict[str, Any]:
    """The prefilled letter: recipient, the type's fields and the links ``/admin/documents``
    stores with the document (user, enrolment, batch, course)."""
    from app.modules.learning import documents as docs
    from app.modules.orgs import public as orgs_public

    doc_type = letter_type(reg)
    program = reg.course_title
    start: date | None = None
    end: date | None = None
    duration: str | None = None
    mode = _mode(reg.preferred_mode)
    if reg.enrolment_id is not None:
        try:
            pre = (await docs.prefill_from_enrolment(session, reg.enrolment_id))["fields"]
            program = pre.get("program") or program
            start = date.fromisoformat(pre["batch_start"]) if pre.get("batch_start") else None
            duration = pre.get("duration") or None
        except (ProblemError, ValueError):
            pass
    batch = await orgs_public.get_batch(session, reg.enrolled_batch_id) if reg.enrolled_batch_id else None
    b_start, b_end, b_duration = _batch_terms(batch)
    start, end = b_start or start, b_end
    duration = b_duration or duration
    start = start or (ist_date(reg.enrolled_at) if reg.enrolled_at else ist_date(utcnow()))

    fields: dict[str, str]
    if doc_type == "offer_internship":
        course_year = ", ".join(x for x in (reg.branch.strip(), reg.year.strip()) if x)
        fields = {
            "role": program,
            "start_date": start.isoformat(),
            "end_date": end.isoformat() if end else "",
            "duration": duration or "",
            "mode": mode,
            "intern_stipend": "Unpaid",
            "course_year": course_year,
            "no_fee": "Yes" if reg.fee_paise == 0 else "",
        }
    else:
        fields = {
            "program": program,
            "batch_start": start.isoformat(),
            "duration": duration or "self-paced",
            "mode": mode,
            "fee_total": R.rupees(reg.fee_paise) if reg.fee_paise > 0 else "",
            "fee_paid": R.rupees(reg.verified_total_paise) if reg.verified_total_paise > 0 else "",
            "fee_balance": R.rupees(reg.balance_paise) if reg.balance_paise > 0 else "",
        }
    return {
        "doc_type": doc_type,
        "recipient": {"name": reg.name, "email": reg.email, "college": reg.college, "reg_no": reg.reg_no},
        "fields": {k: v for k, v in fields.items() if v},
        "issue_date": ist_date(utcnow()).isoformat(),
        "user_id": str(reg.user_id) if reg.user_id else None,
        "enrolment_id": str(reg.enrolment_id) if reg.enrolment_id else None,
        "batch_id": str(reg.enrolled_batch_id) if reg.enrolled_batch_id else None,
        "course_id": str(reg.enrolled_course_id) if reg.enrolled_course_id else None,
    }


def _letter_out(doc: Any, last_email: Any) -> dict[str, Any]:
    from app.modules.learning import documents as docs
    from app.modules.learning.doc_admin import doc_out

    return {
        **doc_out(doc, last_email=last_email),
        "verify_link": docs.verify_url(doc.ref_no, (doc.content or {}).get("site_url")),
    }


async def letter_steps(session: AsyncSession, regs: list[AdmissionRegistration]) -> list[dict[str, Any]]:
    """Everything the letter step shows for each registration: the draft, the letter in force and
    the earlier ones (with their email status), whether email works and is sent automatically."""
    from app.modules.learning import certificates as certs
    from app.modules.learning import docdefs as dd
    from app.modules.learning import documents as docs
    from app.modules.learning.doc_admin import _last_emails
    from app.modules.notifications.adapters import email_integrated

    by_reg = await letters_by_registration(session, regs)
    all_docs = [d for ds in by_reg.values() for d in ds]
    emails = await _last_emails(session, [d.id for d in all_docs])
    settings = await docs.load_settings(session)
    auto_send = await certs.auto_send_enabled(session)
    connected = email_integrated()
    auto_open = await step_auto(session)
    out = []
    for reg in regs:
        ready = reg.enrolled_at is not None and reg.user_id is not None
        letters = [_letter_out(d, emails.get(d.id)) for d in by_reg.get(reg.id, [])]
        now = current(by_reg.get(reg.id, []))
        out.append(
            {
                "registration_id": str(reg.id),
                "reg_no": reg.reg_no,
                "name": reg.name,
                "phone": reg.phone,
                "course_title": reg.course_title,
                "enrolled_at": iso(reg.enrolled_at),
                "ready": ready,
                "reason": None if ready else NOT_READY,
                "draft": await draft(session, reg) if ready else None,
                "letter": next((x for x in letters if now is not None and x["id"] == str(now.id)), None),
                "letters": letters,
                "email": {"connected": connected, "auto_send": auto_send},
                "settings_problem": dd.settings_problem(settings) or None,
                "auto_open": auto_open,
            }
        )
    return out


# --------------------------------------------------------------------------- setting


async def step_auto(session: AsyncSession) -> bool:
    """Setting: after enrolling, open the letter step automatically (default on)."""
    s = await ads.get(session, AdmissionPaySettings, 1)
    return s is None or s.letter_step_auto is not False


async def set_step_auto(session: AsyncSession, actor: Actor, on: bool) -> dict[str, Any]:
    s = await ads.get(session, AdmissionPaySettings, 1)
    before = s is None or s.letter_step_auto is not False
    if s is None:
        s = AdmissionPaySettings(id=1, preferred_app="PhonePe")
        ads.add(session, s)
    s.letter_step_auto = on
    s.updated_by, s.updated_at = actor.user_id, utcnow()
    await ads.flush(session)
    await audit(
        session,
        actor.audit_actor(),
        "admissions.letter_settings.updated",
        "admission_pay_settings",
        None,
        before={"letter_step_auto": before},
        after={"letter_step_auto": on},
    )
    return {"auto_open": on}
