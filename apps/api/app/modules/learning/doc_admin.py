"""Admin documents API (Admin > Certificates & documents) + the public PDF check.

Permissions: ``certificate.issue_manual`` @P for everything (the people who issue certificates);
revoke and re-issue (correction) need ``certificate.revoke`` @P plus a recent step-up, like
revoking a certificate.

* ``GET    /admin/documents/types``                    type picker: fields per type, sections, email keys
* ``GET    /admin/documents``                          register: q / doc_type / status / course, cursor
* ``POST   /admin/documents``                          issue (+ email: send | queue | none)
* ``POST   /admin/documents/preview``                  draft PDF (base64) + what still blocks issuing
* ``GET    /admin/documents/prefill?enrolment_id=``    recipient + admission fields from an enrolment
* ``GET|PUT /admin/documents/settings``                letterhead, signatory, automation
* ``PUT|DELETE /admin/documents/settings/images/{slot}``  signature / seal / logo_left / logo_right (data URL)
* ``GET    /admin/documents/settings/images/{slot}``   short-lived link to the stored image
* ``GET    /admin/documents/templates``                defaults + overrides (documents, emails)
* ``PUT|DELETE /admin/documents/templates/{kind}/{key}``  override / reset to default
* ``POST   /admin/documents/bulk/validate``            bulk: check spreadsheet rows (no writes)
* ``POST   /admin/documents/bulk/issue``               bulk: issue up to 200 rows (idempotency key)
* ``GET    /admin/documents/bulk/enrolments``          bulk: students of a batch / course to pick
* ``GET    /admin/documents/bulk/{bulk_id}``           bulk: the documents of one run
* ``POST   /admin/documents/bulk/pdfs``                bulk: up to 20 PDFs (base64) for the ZIP
* ``GET    /admin/documents/{id}``                     one document + its emails (sends log)
* ``GET    /admin/documents/{id}/pdf``                 short-lived download link
* ``POST   /admin/documents/{id}/regenerate``          re-render + store
* ``POST   /admin/documents/{id}/email``               send / queue an email (resend, edited text)
* ``POST   /admin/documents/{id}/revoke``              revoke (reason, optionally public)
* ``POST   /admin/documents/{id}/reissue``             corrected copy; the old one is superseded
* ``GET    /certificates/verify/{code}/check?sha256=`` public: does this PDF match an issued copy
"""

from __future__ import annotations

import time
import uuid
from datetime import date
from typing import Annotated, Any, Literal

from fastapi import Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from app.core.auth import PLATFORM_SCOPE, require_permission
from app.core.db import DbSession, PrincipalDbSession, system_context
from app.core.errors import ProblemError
from app.core.idempotency import IdemResult, idempotent
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router, public_router
from app.core.time import to_rfc3339
from app.modules.learning import certificates as certs
from app.modules.learning import doc_bulk, fs_docs
from app.modules.learning import docdefs as dd
from app.modules.learning import documents as docs
from app.modules.learning import fs_store as fss
from app.modules.learning.cert_models import CertificateOutbox
from app.modules.learning.doc_models import IssuedDocument

router = authenticated_router(tags=["learning"])
pub = public_router(tags=["learning"])
NEUTRAL = {"x-td-idle": "neutral"}
PERM = "certificate.issue_manual"
REVOKE_PERM = "certificate.revoke"
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
PDF_URL_SECONDS = 300
DocType = Literal[
    "offer_internship", "offer_employment", "offer_course", "cert_completion",
    "cert_internship", "cert_appreciation", "cert_participation", "lor",
]  # fmt: skip


def _perm() -> Any:
    return Depends(require_permission(PERM, scope=PLATFORM_SCOPE))


def _revoke_perm() -> Any:
    return Depends(require_permission(REVOKE_PERM, scope=PLATFORM_SCOPE))


async def _step_up(principal: Principal) -> None:
    from app.core.auth import require_step_up

    await require_step_up(300 if principal.tier == "privileged" else 600)(principal)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecipientIn(Strict):
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=254)
    college: str | None = Field(default=None, max_length=160)
    reg_no: str | None = Field(default=None, max_length=60)


class IssueIn(Strict):
    doc_type: DocType
    recipient: RecipientIn
    fields: dict[str, str] = Field(default_factory=dict)
    issue_date: date | None = None
    user_id: uuid.UUID | None = None
    enrolment_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None
    email: Literal["send", "queue", "none"] = "send"


class PreviewIn(Strict):
    doc_type: DocType
    recipient: dict[str, str] = Field(default_factory=dict)
    fields: dict[str, str] = Field(default_factory=dict)
    issue_date: date | None = None


class RevokeIn(Strict):
    reason: str = Field(min_length=5, max_length=300)
    public_reason: bool = False


class ReissueIn(Strict):
    recipient: RecipientIn | None = None
    fields: dict[str, str] | None = None
    issue_date: date | None = None
    email: Literal["send", "queue", "none"] = "queue"


class EmailIn(Strict):
    mode: Literal["send", "queue"] = "send"
    to: str | None = Field(default=None, max_length=254)
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, max_length=20000)


class SettingsIn(Strict):
    company: str | None = Field(default=None, max_length=120)
    legal_name: str | None = Field(default=None, max_length=160)
    tagline: str | None = Field(default=None, max_length=120)
    address: str | None = Field(default=None, max_length=300)
    phone: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=160)
    website: str | None = Field(default=None, max_length=120)
    reg_lines: list[str] | None = Field(default=None, max_length=4)
    signatory: str | None = Field(default=None, max_length=80)
    designation: str | None = Field(default=None, max_length=80)
    signatory_email: str | None = Field(default=None, max_length=160)
    signatory_phone: str | None = Field(default=None, max_length=40)
    signatory2: str | None = Field(default=None, max_length=80)
    designation2: str | None = Field(default=None, max_length=80)
    portal_url: str | None = Field(default=None, max_length=200)
    auto_admission_letter: bool | None = None


class ImageIn(Strict):
    data_url: str = Field(min_length=20, max_length=420_000)


# settings image slots (``docdefs.IMAGE_SLOTS``); signature2 is accepted but not printed
ImageSlot = Literal["signature", "seal", "signature2", "logo_left", "logo_right"]


class TemplateIn(Strict):
    content: dict[str, Any]


def _ts(v: Any) -> str | None:
    return to_rfc3339(v) if v else None


def _outbox_out(o: CertificateOutbox) -> dict[str, Any]:
    return {
        "id": str(o.id),
        "status": o.status,
        "origin": o.origin,
        "attempts": o.attempts,
        "last_error": o.last_error,
        "to": o.to_email,
        "subject": o.subject,
        "approved_at": _ts(o.approved_at),
        "sent_at": _ts(o.sent_at),
        "cancelled_at": _ts(o.cancelled_at),
        "created_at": _ts(o.created_at),
    }


def doc_out(d: IssuedDocument, *, last_email: CertificateOutbox | None = None) -> dict[str, Any]:
    t = dd.DOC_TYPES[d.doc_type]
    pubd = d.content.get("public") or {}
    return {
        "id": str(d.id),
        "doc_type": d.doc_type,
        "label": t["label"],
        "short": t["short"],
        "layout": t["layout"],
        "ref_no": d.ref_no,
        "recipient": {"name": d.recipient_name, "email": d.recipient_email, **(d.recipient or {})},
        "title": pubd.get("program") or None,
        "user_id": str(d.user_id) if d.user_id else None,
        "enrolment_id": str(d.enrolment_id) if d.enrolment_id else None,
        "batch_id": str(d.batch_id) if d.batch_id else None,
        "course_id": str(d.course_id) if d.course_id else None,
        "fields": d.fields,
        "subject": d.content.get("subject"),
        "issue_date": d.issue_date.isoformat(),
        "status": d.status,
        "origin": d.origin,
        "replaces_id": str(d.replaces_id) if d.replaces_id else None,
        "superseded_by_id": str(d.superseded_by_id) if d.superseded_by_id else None,
        "revoked_at": _ts(d.revoked_at),
        "revoke_reason": d.revoke_reason,
        "pdf_available": d.pdf_s3_key is not None,
        "content_sha256": bytes(d.content_hash).hex() if d.content_hash else None,
        "template_version": d.template_version,
        "verify_url": f"/verify/{d.ref_no}",
        "bulk_id": doc_bulk.bulk_tag(d).get("id"),
        "created_at": _ts(d.created_at),
        "email_status": last_email.status if last_email else None,
    }


async def _doc(session: Any, document_id: uuid.UUID) -> IssuedDocument:
    d = await fss.get(session, IssuedDocument, document_id)
    if d is None:
        raise ProblemError("not_found")
    return d


async def _last_emails(session: Any, ids: list[uuid.UUID]) -> dict[uuid.UUID, CertificateOutbox]:
    if not ids:
        return {}
    rows = (
        await fs_docs.document_outbox(session, ids)
        if fss.fs()
        else (
            await session.execute(
                select(CertificateOutbox)
                .where(CertificateOutbox.document_id.in_(ids))
                .order_by(CertificateOutbox.created_at, CertificateOutbox.id)
            )
        ).scalars()
    )
    out: dict[uuid.UUID, CertificateOutbox] = {}
    for o in rows:
        if o.document_id is not None:
            out[o.document_id] = o  # the newest wins
    return out


async def _email_after_issue(session: Any, doc: IssuedDocument, mode: str, origin: str) -> str | None:
    if mode == "none":
        return None
    row = await docs.queue_email(
        session, doc, origin=origin, status="pending" if mode == "send" else "awaiting"
    )
    if row is None:
        return None
    if mode == "send":
        return await certs.send_one(session, row)
    return row.status


def _after(cursor: str | None) -> uuid.UUID | None:
    if not cursor:
        return None
    try:
        return uuid.UUID(str(decode_cursor(cursor)["id"]))
    except (KeyError, ValueError) as e:
        raise ProblemError("invalid_cursor") from e


# --------------------------------------------------------------------------- catalogue / register


@router.get("/admin/documents/types", openapi_extra=NEUTRAL, operation_id="doc_01_types")
async def types(session: PrincipalDbSession, principal: Principal = _perm()) -> dict[str, Any]:
    st = await docs.load_settings(session)
    return {
        "types": dd.types_catalogue(),
        "emails": [
            {"key": k, "label": v["label"], "attach": v["attach"]} for k, v in dd.EMAIL_TEMPLATES.items()
        ],
        "settings_problem": dd.settings_problem(st) or None,
    }


@router.get("/admin/documents", openapi_extra=NEUTRAL, operation_id="doc_02_list")
async def list_documents(
    session: PrincipalDbSession,
    principal: Principal = _perm(),
    doc_type: DocType | None = None,
    status: Literal["valid", "revoked", "superseded"] | None = None,
    course_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    if fss.fs():
        return await _list_documents_fs(session, doc_type, status, course_id, q, cursor, limit)
    qry = select(IssuedDocument)
    if doc_type:
        qry = qry.where(IssuedDocument.doc_type == doc_type)
    if status:
        qry = qry.where(IssuedDocument.status == status)
    if course_id is not None:
        qry = qry.where(IssuedDocument.course_id == course_id)
    term = (q or "").strip().lower()
    if term:
        like = f"%{term}%"
        ref = dd.normalise_ref(term).lower()
        qry = qry.where(
            or_(
                func.lower(IssuedDocument.recipient_name).like(like),
                func.lower(IssuedDocument.recipient_email).like(like),
                func.lower(IssuedDocument.ref_no).like(f"%{ref}%"),
            )
        )
    after = _after(cursor)
    if after is not None:
        qry = qry.where(IssuedDocument.id < after)
    rows = list((await session.execute(qry.order_by(IssuedDocument.id.desc()).limit(limit + 1))).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    last = await _last_emails(session, [d.id for d in rows])
    counts = dict.fromkeys(docs.STATUSES, 0)
    counts.update(
        {
            s: int(n)
            for s, n in (
                await session.execute(
                    select(IssuedDocument.status, func.count()).group_by(IssuedDocument.status)
                )
            ).all()
        }
    )
    return {
        "data": [doc_out(d, last_email=last.get(d.id)) for d in rows],
        "counts": counts,
        "page": page_meta({"id": str(rows[-1].id)} if more and rows else None, limit),
    }


async def _list_documents_fs(
    session: Any,
    doc_type: str | None,
    status: str | None,
    course_id: uuid.UUID | None,
    q: str | None,
    cursor: str | None,
    limit: int,
) -> dict[str, Any]:
    """The register on Firestore: same filters, id-descending keyset page and counts."""
    term = (q or "").strip().lower()
    rows = await fs_docs.register_page(
        session,
        doc_type=doc_type,
        status=status,
        course_id=course_id,
        term=term,
        ref=dd.normalise_ref(term).lower() if term else "",
        after=_after(cursor),
        limit=limit,
    )
    more = len(rows) > limit
    rows = rows[:limit]
    last = await _last_emails(session, [d.id for d in rows])
    counts = dict.fromkeys(docs.STATUSES, 0)
    counts.update(await fs_docs.status_counts())
    return {
        "data": [doc_out(d, last_email=last.get(d.id)) for d in rows],
        "counts": counts,
        "page": page_meta({"id": str(rows[-1].id)} if more and rows else None, limit),
    }


@router.post("/admin/documents", operation_id="doc_03_issue")
async def issue(
    request: Request, body: IssueIn, session: PrincipalDbSession, principal: Principal = _perm()
) -> Any:
    async def op() -> IdemResult:
        doc = await docs.issue_document(
            session,
            principal,
            doc_type=body.doc_type,
            recipient=body.recipient.model_dump(),
            fields=body.fields,
            issue_date=body.issue_date,
            user_id=body.user_id,
            enrolment_id=body.enrolment_id,
            batch_id=body.batch_id,
            course_id=body.course_id,
        )
        email_status = await _email_after_issue(session, doc, body.email, "manual")
        return IdemResult({**doc_out(doc), "email_status": email_status}, 201, doc.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@router.post("/admin/documents/preview", operation_id="doc_04_preview")
async def preview(
    body: PreviewIn, session: PrincipalDbSession, principal: Principal = _perm()
) -> dict[str, Any]:
    return await docs.preview(
        session,
        doc_type=body.doc_type,
        recipient=body.recipient,
        fields=body.fields,
        issue_date=body.issue_date,
    )


@router.get("/admin/documents/prefill", openapi_extra=NEUTRAL, operation_id="doc_05_prefill")
async def prefill(
    enrolment_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = _perm()
) -> dict[str, Any]:
    return await docs.prefill_from_enrolment(session, enrolment_id)


# --------------------------------------------------------------------------- settings


@router.get("/admin/documents/settings", openapi_extra=NEUTRAL, operation_id="doc_06_settings")
async def get_settings(session: PrincipalDbSession, principal: Principal = _perm()) -> dict[str, Any]:
    out = docs.settings_out(await docs.load_settings(session))
    out["auto_send"] = await certs.auto_send_enabled(session)
    return out


@router.put("/admin/documents/settings", operation_id="doc_07_settings_put")
async def put_settings(
    body: SettingsIn, session: PrincipalDbSession, principal: Principal = _perm()
) -> dict[str, Any]:
    st = await docs.save_settings(session, principal, body.model_dump(exclude_none=True))
    out = docs.settings_out(st)
    out["auto_send"] = await certs.auto_send_enabled(session)
    return out


@router.put("/admin/documents/settings/images/{slot}", operation_id="doc_08_image_put")
async def put_image(
    slot: ImageSlot,
    body: ImageIn,
    session: PrincipalDbSession,
    principal: Principal = _perm(),
) -> dict[str, Any]:
    return docs.settings_out(await docs.store_image(session, principal, slot, body.data_url))


@router.delete("/admin/documents/settings/images/{slot}", operation_id="doc_09_image_delete")
async def delete_image(
    slot: ImageSlot,
    session: PrincipalDbSession,
    principal: Principal = _perm(),
) -> dict[str, Any]:
    return docs.settings_out(await docs.clear_image(session, principal, slot))


@router.get("/admin/documents/settings/images/{slot}", openapi_extra=NEUTRAL, operation_id="doc_10_image_get")
async def get_image(
    slot: ImageSlot,
    session: PrincipalDbSession,
    principal: Principal = _perm(),
) -> dict[str, Any]:
    st = await docs.load_settings(session)
    key = st.get(f"{slot}_key")
    if not key:
        raise ProblemError("not_found")
    url, exp = certs._store().signed_url(
        certs._bucket(), key, filename=key.rsplit("/", 1)[-1], expires_s=PDF_URL_SECONDS
    )
    return {"url": url, "expires_at": to_rfc3339(exp)}


# --------------------------------------------------------------------------- templates


@router.get("/admin/documents/templates", openapi_extra=NEUTRAL, operation_id="doc_11_templates")
async def templates(session: PrincipalDbSession, principal: Principal = _perm()) -> dict[str, Any]:
    return await docs.templates_catalogue(session)


@router.put("/admin/documents/templates/{kind}/{key}", operation_id="doc_12_template_put")
async def put_template(
    kind: Literal["document", "email"],
    key: str,
    body: TemplateIn,
    session: PrincipalDbSession,
    principal: Principal = _perm(),
) -> dict[str, Any]:
    return {
        "kind": kind,
        "key": key,
        "override": await docs.put_template(session, principal, kind, key, body.content),
    }


@router.delete("/admin/documents/templates/{kind}/{key}", operation_id="doc_13_template_reset")
async def reset_template(
    kind: Literal["document", "email"], key: str, session: PrincipalDbSession, principal: Principal = _perm()
) -> dict[str, Any]:
    await docs.reset_template(session, principal, kind, key)
    return {"kind": kind, "key": key, "override": None}


# --------------------------------------------------------------------------- bulk (doc_bulk)
# Declared before ``/admin/documents/{document_id}`` so ``bulk/...`` never reads as an id.


class BulkRowIn(Strict):
    """One spreadsheet row (or picked student). Empty / invalid values are reported by validate,
    not refused by the schema, so one bad row never rejects the whole upload."""

    row: int | None = Field(default=None, ge=1, le=100_000)
    name: str = Field(default="", max_length=300)
    email: str = Field(default="", max_length=320)
    mobile: str | None = Field(default=None, max_length=40)
    college: str | None = Field(default=None, max_length=300)
    reg_no: str | None = Field(default=None, max_length=120)
    fields: dict[str, str] = Field(default_factory=dict, max_length=40)
    user_id: uuid.UUID | None = None
    enrolment_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    course_id: uuid.UUID | None = None


class BulkValidateIn(Strict):
    doc_type: DocType
    rows: list[BulkRowIn] = Field(min_length=1, max_length=doc_bulk.MAX_VALIDATE_ROWS)
    issue_date: date | None = None


class BulkIssueIn(Strict):
    doc_type: DocType
    bulk_id: uuid.UUID
    label: str = Field(default="", max_length=120)
    rows: list[BulkRowIn] = Field(min_length=1, max_length=doc_bulk.MAX_ISSUE_ROWS)
    issue_date: date | None = None
    email: Literal["outbox", "none"] = "none"


class BulkPdfsIn(Strict):
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=doc_bulk.MAX_PDF_IDS)


@router.post("/admin/documents/bulk/validate", operation_id="doc_21_bulk_validate")
async def bulk_validate(
    body: BulkValidateIn, session: PrincipalDbSession, principal: Principal = _perm()
) -> dict[str, Any]:
    return await doc_bulk.validate(
        session,
        doc_type=body.doc_type,
        rows=[r.model_dump() for r in body.rows],
        issue_date=body.issue_date,
    )


@router.post("/admin/documents/bulk/issue", operation_id="doc_22_bulk_issue")
async def bulk_issue(
    request: Request, body: BulkIssueIn, session: PrincipalDbSession, principal: Principal = _perm()
) -> Any:
    """Issue up to 200 rows; per-row results, failures never abort the run. Rows not reached
    within the time budget come back ``deferred`` (send them again). Idempotency key required:
    a retried chunk replays its first answer instead of issuing twice."""
    started = time.monotonic()

    async def op() -> IdemResult:
        out = await doc_bulk.issue_rows(
            session,
            principal,
            doc_type=body.doc_type,
            rows=[r.model_dump() for r in body.rows],
            issue_date=body.issue_date,
            email=body.email,
            bulk_id=body.bulk_id,
            label=body.label,
            started=started,
        )
        return IdemResult(out, 200)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=True)


@router.get("/admin/documents/bulk/enrolments", openapi_extra=NEUTRAL, operation_id="doc_23_bulk_enrolments")
async def bulk_enrolments(
    session: PrincipalDbSession,
    principal: Principal = _perm(),
    batch_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    rows = await doc_bulk.enrolment_rows(session, batch_id=batch_id, course_id=course_id)
    return {"data": rows, "truncated": len(rows) >= doc_bulk.MAX_ENROLMENTS}


@router.post("/admin/documents/bulk/pdfs", operation_id="doc_24_bulk_pdfs")
async def bulk_pdfs(
    body: BulkPdfsIn, session: PrincipalDbSession, principal: Principal = _perm()
) -> dict[str, Any]:
    return await doc_bulk.pdfs(session, body.document_ids)


@router.get("/admin/documents/bulk/{bulk_id}", openapi_extra=NEUTRAL, operation_id="doc_25_bulk_run")
async def bulk_run(
    bulk_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = _perm(),
    doc_type: DocType | None = None,
) -> dict[str, Any]:
    rows = await doc_bulk.run_documents(session, bulk_id, doc_type)
    last = await _last_emails(session, [d.id for d in rows])
    data = []
    for d in rows:
        out = doc_out(d, last_email=last.get(d.id))
        out["bulk_row"] = doc_bulk.bulk_tag(d).get("row")
        data.append(out)
    counts = dict.fromkeys(docs.STATUSES, 0)
    for d in rows:
        counts[d.status] = counts.get(d.status, 0) + 1
    return {"bulk_id": str(bulk_id), "data": data, "counts": counts}


# --------------------------------------------------------------------------- one document


@router.get("/admin/documents/{document_id}", openapi_extra=NEUTRAL, operation_id="doc_14_get")
async def get_document(
    document_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = _perm()
) -> dict[str, Any]:
    d = await _doc(session, document_id)
    if fss.fs():
        sends = list(reversed(await fs_docs.document_outbox(session, [d.id])))
        related = await fs_docs.same_recipient(session, d, valid_only=False, limit=20)
    else:
        sends = list(
            (
                await session.execute(
                    select(CertificateOutbox)
                    .where(CertificateOutbox.document_id == d.id)
                    .order_by(CertificateOutbox.created_at.desc(), CertificateOutbox.id.desc())
                )
            ).scalars()
        )
        related = list(
            (
                await session.execute(
                    select(IssuedDocument)
                    .where(
                        func.lower(IssuedDocument.recipient_email) == d.recipient_email.lower(),
                        IssuedDocument.id != d.id,
                    )
                    .order_by(IssuedDocument.created_at.desc())
                    .limit(20)
                )
            ).scalars()
        )
    out = doc_out(d, last_email=sends[0] if sends else None)
    out["emails"] = [_outbox_out(o) for o in sends]
    out["paragraphs"] = d.content.get("paragraphs") or []
    out["related"] = [
        {"id": str(r.id), "ref_no": r.ref_no, "label": dd.DOC_TYPES[r.doc_type]["short"], "status": r.status}
        for r in related
    ]
    return out


@router.get("/admin/documents/{document_id}/pdf", openapi_extra=NEUTRAL, operation_id="doc_15_pdf")
async def document_pdf(
    document_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = _perm()
) -> dict[str, Any]:
    d = await _doc(session, document_id)
    if d.pdf_s3_key is None:
        if d.status != "valid":
            raise ProblemError("not_found", detail=f"The document is {d.status} and has no PDF.")
        await docs.ensure_pdf(session, d)
    assert d.pdf_s3_key is not None
    url, exp = certs._store().signed_url(
        certs._bucket(), d.pdf_s3_key, filename=f"{d.ref_no}.pdf", expires_s=PDF_URL_SECONDS
    )
    return {"url": url, "expires_at": to_rfc3339(exp)}


@router.post("/admin/documents/{document_id}/regenerate", operation_id="doc_16_regenerate")
async def regenerate(
    request: Request, document_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = _perm()
) -> Any:
    async def op() -> IdemResult:
        d = await _doc(session, document_id)
        await docs.ensure_pdf(session, d, force=True)
        return IdemResult(doc_out(d), 200, d.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@router.post("/admin/documents/{document_id}/email", operation_id="doc_17_email")
async def email(
    request: Request,
    document_id: uuid.UUID,
    body: EmailIn,
    session: PrincipalDbSession,
    principal: Principal = _perm(),
) -> Any:
    async def op() -> IdemResult:
        d = await _doc(session, document_id)
        if d.status != "valid":
            raise ProblemError("invalid_state_transition", detail=f"The document is {d.status}.")
        row = await docs.queue_email(
            session, d, origin="resend", status="pending" if body.mode == "send" else "awaiting",
            to=body.to, subject=body.subject, body=body.body,
        )  # fmt: skip
        assert row is not None
        if body.mode == "send":
            await certs.send_one(session, row)
        return IdemResult(_outbox_out(row), 200, row.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@router.post("/admin/documents/{document_id}/revoke", operation_id="doc_18_revoke")
async def revoke(
    request: Request,
    document_id: uuid.UUID,
    body: RevokeIn,
    session: PrincipalDbSession,
    principal: Principal = _revoke_perm(),
) -> Any:
    await _step_up(principal)

    async def op() -> IdemResult:
        d = await _doc(session, document_id)
        changed = await docs.revoke(session, principal, d, body.reason, public_reason=body.public_reason)
        return IdemResult({**doc_out(d), "changed": changed}, 200, d.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@router.post("/admin/documents/{document_id}/reissue", operation_id="doc_19_reissue")
async def reissue(
    request: Request,
    document_id: uuid.UUID,
    body: ReissueIn,
    session: PrincipalDbSession,
    principal: Principal = _revoke_perm(),
) -> Any:
    await _step_up(principal)

    async def op() -> IdemResult:
        old = await _doc(session, document_id)
        new = await docs.reissue(
            session, principal, old,
            recipient=body.recipient.model_dump() if body.recipient else None,
            fields=body.fields, issue_date=body.issue_date,
        )  # fmt: skip
        email_status = await _email_after_issue(session, new, body.email, "reissue")
        return IdemResult({**doc_out(new), "email_status": email_status, "replaced": old.ref_no}, 201, new.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


# --------------------------------------------------------------------------- public


@pub.get("/certificates/verify/{code}/check", operation_id="doc_20_verify_pdf_check")
async def verify_pdf_check(
    code: str,
    session: DbSession,
    sha256: Annotated[str, Query(min_length=64, max_length=64)],
) -> dict[str, Any]:
    """Public: compare the SHA-256 of a PDF (computed in the visitor's browser; the file is never
    uploaded) with the copies issued for this certificate number / document reference."""
    if len(code) > 40:
        raise ProblemError("not_found")
    await system_context(session, "learning.document_verify")
    return await docs.check_pdf(session, code, sha256)
