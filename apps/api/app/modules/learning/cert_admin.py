"""Admin certificates API (Admin > Certificates).

All routes need ``certificate.issue_manual`` @P (the existing permission of the people who
issue certificates); issuing one certificate and revoking stay on the existing
``POST /certificates`` and ``POST /certificates/{id}/revoke`` (``certificate.revoke``, step-up).

* ``GET  /admin/certificates``                 register: filters course / status / search, cursor
* ``GET  /admin/certificates/summary``         KPI counts + the auto-send setting
* ``GET  /admin/certificates/due``             enrolments without a certificate (completed / batch ended)
* ``POST /admin/certificates/due/issue``       issue the eligible due rows (all, or ``enrolment_ids``)
* ``POST /admin/certificates/due/preview``     draft PDF of one due row's certificate (nothing stored)
* ``GET  /admin/certificates/outbox``          the email approval queue (certificates + issued
  documents; each row has a normalised ``item``; ``kind`` filters)
* ``POST /admin/certificates/outbox/approve``  approve (single or bulk) -> sent
* ``POST /admin/certificates/outbox/cancel``   cancel unsent emails
* ``GET|PUT /admin/certificates/settings``     ``auto_send`` (feature flag ``certificates.auto_send``)
* ``GET  /admin/certificates/{id}``            one certificate
* ``GET  /admin/certificates/{id}/pdf``        short-lived download link (generates a missing PDF)
* ``POST /admin/certificates/{id}/regenerate`` re-render + store the PDF
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from fastapi import Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select

from app.core.audit import audit
from app.core.auth import PLATFORM_SCOPE, require_permission
from app.core.db import PrincipalDbSession
from app.core.errors import ProblemError
from app.core.idempotency import IdemResult, idempotent
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339
from app.modules.learning import certificates as certs
from app.modules.learning import fs_cert
from app.modules.learning import fs_store as fss
from app.modules.learning.cert_models import CertificateOutbox
from app.modules.learning.models import Certificate

router = authenticated_router(tags=["learning"])
NEUTRAL = {"x-td-idle": "neutral"}
PERM = "certificate.issue_manual"
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]
PDF_URL_SECONDS = 300


def _perm() -> Any:
    return Depends(require_permission(PERM, scope=PLATFORM_SCOPE))


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdsIn(Strict):
    ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class IssueDueIn(Strict):
    enrolment_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=500)
    course_id: uuid.UUID | None = None


class SettingsIn(Strict):
    auto_send: bool


class DuePreviewIn(Strict):
    enrolment_id: uuid.UUID


def _ts(v: Any) -> str | None:
    return to_rfc3339(v) if v else None


def _outbox_out(o: CertificateOutbox | None) -> dict[str, Any] | None:
    if o is None:
        return None
    return {
        "id": str(o.id),
        "status": o.status,
        "origin": o.origin,
        "attempts": o.attempts,
        "last_error": o.last_error,
        "approved_at": _ts(o.approved_at),
        "sent_at": _ts(o.sent_at),
        "cancelled_at": _ts(o.cancelled_at),
        "created_at": _ts(o.created_at),
    }


def _cert_out(
    c: Certificate,
    *,
    title: str | None,
    email: str | None,
    outbox: CertificateOutbox | None,
) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "public_code": c.public_code,
        "user_id": str(c.user_id),
        "name_on_certificate": c.name_on_certificate,
        "email": email,
        "course_id": str(c.course_id),
        "course_title": title,
        "enrolment_id": str(c.enrolment_id),
        "issue_source": c.issue_source,
        "issued_at": _ts(c.issued_at),
        "status": "revoked" if c.revoked_at else "valid",
        "revoked_at": _ts(c.revoked_at),
        "revoke_reason": c.revoke_reason,
        "pdf_available": c.pdf_s3_key is not None,
        "content_sha256": bytes(c.content_hash).hex() if c.pdf_s3_key else None,
        "template_version": c.template_version,
        "verify_url": f"/verify/{c.public_code}",
        "email_status": outbox.status if outbox else None,
        "outbox": _outbox_out(outbox),
    }


async def _emails(session: Any, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    """E-mails through ``identity.public`` (either store)."""
    if not user_ids:
        return {}
    return await fs_cert.emails(session, user_ids)


async def _outboxes(session: Any, cert_ids: list[uuid.UUID]) -> dict[uuid.UUID, CertificateOutbox]:
    if not cert_ids:
        return {}
    if fss.fs():
        return await fs_cert.outboxes_of_certificates(session, cert_ids)
    rows = (
        await session.execute(select(CertificateOutbox).where(CertificateOutbox.certificate_id.in_(cert_ids)))
    ).scalars()
    return {o.certificate_id: o for o in rows}


async def _decorate(session: Any, rows: list[Certificate]) -> list[dict[str, Any]]:
    titles = await certs.course_titles(session, {c.course_version_id for c in rows})
    emails = await _emails(session, {c.user_id for c in rows})
    boxes = await _outboxes(session, [c.id for c in rows])
    return [
        _cert_out(
            c, title=titles.get(c.course_version_id), email=emails.get(c.user_id), outbox=boxes.get(c.id)
        )
        for c in rows
    ]


def _after(cursor: str | None) -> uuid.UUID | None:
    if not cursor:
        return None
    try:
        return uuid.UUID(str(decode_cursor(cursor)["id"]))
    except (KeyError, ValueError) as e:
        raise ProblemError("invalid_cursor") from e


# --------------------------------------------------------------------------- register


@router.get("/admin/certificates", openapi_extra=NEUTRAL, operation_id="lrn_30_admin_certificates")
async def list_certificates(
    session: PrincipalDbSession,
    principal: Principal = _perm(),
    course_id: uuid.UUID | None = None,
    status: Literal["valid", "revoked"] | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    if fss.fs():
        rows = await fs_cert.certificate_page(
            session,
            course_id=course_id,
            status=status,
            term=(q or "").strip().lower(),
            after=_after(cursor),
            limit=limit,
        )
        more = len(rows) > limit
        rows = rows[:limit]
        return {
            "data": await _decorate(session, rows),
            "page": page_meta({"id": str(rows[-1].id)} if more and rows else None, limit),
        }
    qry = select(Certificate)
    if course_id is not None:
        qry = qry.where(Certificate.course_id == course_id)
    if status == "valid":
        qry = qry.where(Certificate.revoked_at.is_(None))
    elif status == "revoked":
        qry = qry.where(Certificate.revoked_at.is_not(None))
    term = (q or "").strip().lower()
    if term:
        like = f"%{term}%"
        # users whose e-mail or full name matches: identity's public API (no SQL on its tables)
        people = await fs_cert.people_matching(session, term)
        qry = qry.where(
            or_(
                func.lower(Certificate.name_on_certificate).like(like),
                func.lower(Certificate.public_code).like(like),
                Certificate.user_id.in_(people),
            )
        )
    after = _after(cursor)
    if after is not None:
        qry = qry.where(Certificate.id < after)
    rows = list((await session.execute(qry.order_by(Certificate.id.desc()).limit(limit + 1))).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    return {
        "data": await _decorate(session, rows),
        "page": page_meta({"id": str(rows[-1].id)} if more and rows else None, limit),
    }


@router.get("/admin/certificates/summary", openapi_extra=NEUTRAL, operation_id="lrn_31_admin_cert_summary")
async def summary(
    session: PrincipalDbSession,
    principal: Principal = _perm(),
    course_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    if fss.fs():
        all_certs = await fs_cert.certificates(session, course_id)
        total = len(all_certs)
        revoked = sum(1 for c in all_certs if c.revoked_at is not None)
        no_pdf = sum(1 for c in all_certs if c.revoked_at is None and c.pdf_s3_key is None)
    else:
        base = select(func.count()).select_from(Certificate)
        if course_id is not None:
            base = base.where(Certificate.course_id == course_id)
        total = int((await session.execute(base)).scalar_one())
        revoked = int((await session.execute(base.where(Certificate.revoked_at.is_not(None)))).scalar_one())
        no_pdf = int(
            (
                await session.execute(
                    base.where(Certificate.revoked_at.is_(None), Certificate.pdf_s3_key.is_(None))
                )
            ).scalar_one()
        )
    due = await certs.due_enrolments(session, course_id=course_id)
    from app.modules.learning.doc_models import IssuedDocument

    doc_counts = {"valid": 0, "revoked": 0, "superseded": 0}
    if fss.fs():
        doc_counts.update(await fs_cert.document_status_counts(session, course_id))
    else:
        dq = select(IssuedDocument.status, func.count()).group_by(IssuedDocument.status)
        if course_id is not None:
            dq = dq.where(IssuedDocument.course_id == course_id)
        doc_counts.update({s: int(n) for s, n in (await session.execute(dq)).all()})
    return {
        "documents": doc_counts,
        "issued": total,
        "valid": total - revoked,
        "revoked": revoked,
        "without_pdf": no_pdf,
        "due": len(due),
        "due_eligible": sum(1 for r in due if r["eligible"]),
        "outbox": await certs.outbox_counts(session),
        "auto_send": await certs.auto_send_enabled(session),
    }


# --------------------------------------------------------------------------- due


@router.get("/admin/certificates/due", openapi_extra=NEUTRAL, operation_id="lrn_32_admin_cert_due")
async def due(
    session: PrincipalDbSession,
    principal: Principal = _perm(),
    course_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    rows = await certs.due_enrolments(session, course_id=course_id)
    return {"data": rows, "eligible": sum(1 for r in rows if r["eligible"])}


@router.post("/admin/certificates/due/issue", operation_id="lrn_33_admin_cert_issue_due")
async def issue_due(
    request: Request,
    body: IssueDueIn,
    session: PrincipalDbSession,
    principal: Principal = _perm(),
) -> Any:
    async def op() -> IdemResult:
        out = await certs.issue_due(
            session, principal, enrolment_ids=body.enrolment_ids, course_id=body.course_id, origin="manual"
        )
        return IdemResult(out, 200)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


PREVIEW_CODE = "PREVIEW00000"


@router.post("/admin/certificates/due/preview", operation_id="lrn_33b_admin_cert_due_preview")
async def due_preview(
    body: DuePreviewIn, session: PrincipalDbSession, principal: Principal = _perm()
) -> dict[str, Any]:
    """The certificate this enrolment would get (name, course, today), drawn by the same renderer
    as the real one with a placeholder number. Nothing is stored; "issue all" stays a separate
    step (the Due tab asks for a preview first)."""
    import base64

    from app.core.ids import uuid7
    from app.core.time import utcnow
    from app.modules.learning import service as svc
    from app.modules.learning.certpdf import TEMPLATE_VERSION
    from app.modules.learning.models import Enrolment

    enr = await fss.get(session, Enrolment, body.enrolment_id)
    if enr is None:
        raise ProblemError("not_found")
    draft = Certificate(
        id=uuid7(),
        public_code=PREVIEW_CODE,
        user_id=enr.user_id,
        organization_id=enr.organization_id,
        course_id=enr.course_id,
        course_version_id=enr.course_version_id,
        enrolment_id=enr.id,
        name_on_certificate=await svc._name_for(session, enr.user_id),
        template_version=TEMPLATE_VERSION,
        content_hash=b"",
        issued_at=utcnow(),
    )
    data = await certs.render_pdf(session, draft)
    title = (await certs.course_titles(session, {enr.course_version_id})).get(enr.course_version_id)
    return {
        "pdf_base64": base64.b64encode(data).decode("ascii"),
        "name": draft.name_on_certificate,
        "course_title": title,
    }


# --------------------------------------------------------------------------- outbox


@router.get("/admin/certificates/outbox", openapi_extra=NEUTRAL, operation_id="lrn_34_admin_cert_outbox")
async def outbox(
    session: PrincipalDbSession,
    principal: Principal = _perm(),
    status: Literal["awaiting", "pending", "sent", "failed", "cancelled"] | None = None,
    course_id: uuid.UUID | None = None,
    kind: Literal["certificate", "document"] | None = None,
    cursor: str | None = None,
    limit: Limit = DEFAULT_LIMIT,
) -> dict[str, Any]:
    from app.modules.learning.doc_models import IssuedDocument

    # certificates and issued documents share the queue (learning_0006)
    if fss.fs():
        fs_rows = await fs_cert.outbox_page(
            session, status=status, course_id=course_id, kind=kind, after=_after(cursor), limit=limit
        )
        return await _outbox_page(session, fs_rows, limit)
    qry = (
        select(CertificateOutbox, Certificate, IssuedDocument)
        .outerjoin(Certificate, Certificate.id == CertificateOutbox.certificate_id)
        .outerjoin(IssuedDocument, IssuedDocument.id == CertificateOutbox.document_id)
    )
    if status:
        qry = qry.where(CertificateOutbox.status == status)
    if course_id is not None:
        qry = qry.where(or_(Certificate.course_id == course_id, IssuedDocument.course_id == course_id))
    if kind == "certificate":
        qry = qry.where(CertificateOutbox.certificate_id.is_not(None))
    elif kind == "document":
        qry = qry.where(CertificateOutbox.document_id.is_not(None))
    after = _after(cursor)
    if after is not None:
        qry = qry.where(CertificateOutbox.id < after)
    rows = (await session.execute(qry.order_by(CertificateOutbox.id.desc()).limit(limit + 1))).all()
    return await _outbox_page(session, rows, limit)


async def _outbox_page(session: Any, rows: Any, limit: int) -> dict[str, Any]:
    from app.modules.learning import docdefs as dd

    more = len(rows) > limit
    rows = rows[:limit]
    titles = await certs.course_titles(session, {c.course_version_id for _, c, _d in rows if c is not None})
    emails = await _emails(session, {c.user_id for _, c, _d in rows if c is not None})
    data = []
    for o, c, d in rows:
        cert = (
            _cert_out(c, title=titles.get(c.course_version_id), email=emails.get(c.user_id), outbox=None)
            if c is not None
            else None
        )
        if cert is not None:
            item = {
                "kind": "certificate", "id": cert["id"], "name": cert["name_on_certificate"],
                "email": cert["email"], "title": cert["course_title"], "label": "Course certificate",
                "number": cert["public_code"],
            }  # fmt: skip
        elif d is not None:
            item = {
                "kind": "document", "id": str(d.id), "name": d.recipient_name,
                "email": o.to_email or d.recipient_email,
                "title": (d.content.get("public") or {}).get("program") or d.content.get("subject"),
                "label": dd.DOC_TYPES[d.doc_type]["short"], "number": d.ref_no,
            }  # fmt: skip
        else:
            item = None
        data.append({**(_outbox_out(o) or {}), "certificate": cert, "item": item})
    return {
        "data": data,
        "counts": await certs.outbox_counts(session),
        "page": page_meta({"id": str(rows[-1][0].id)} if more and rows else None, limit),
    }


@router.post("/admin/certificates/outbox/approve", operation_id="lrn_35_admin_cert_outbox_approve")
async def outbox_approve(
    request: Request,
    body: IdsIn,
    session: PrincipalDbSession,
    principal: Principal = _perm(),
) -> Any:
    async def op() -> IdemResult:
        return IdemResult(await certs.approve(session, principal, list(dict.fromkeys(body.ids))), 200)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


@router.post("/admin/certificates/outbox/cancel", operation_id="lrn_36_admin_cert_outbox_cancel")
async def outbox_cancel(
    request: Request,
    body: IdsIn,
    session: PrincipalDbSession,
    principal: Principal = _perm(),
) -> Any:
    async def op() -> IdemResult:
        return IdemResult(await certs.cancel(session, principal, list(dict.fromkeys(body.ids))), 200)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


# --------------------------------------------------------------------------- settings


@router.get("/admin/certificates/settings", openapi_extra=NEUTRAL, operation_id="lrn_37_admin_cert_settings")
async def get_settings(session: PrincipalDbSession, principal: Principal = _perm()) -> dict[str, Any]:
    return {"auto_send": await certs.auto_send_enabled(session), "flag_key": certs.AUTO_SEND_FLAG}


@router.put("/admin/certificates/settings", operation_id="lrn_38_admin_cert_settings_put")
async def put_settings(
    body: SettingsIn, session: PrincipalDbSession, principal: Principal = _perm()
) -> dict[str, Any]:
    from app.core.firestore.backend import uses_firestore
    from app.modules.admin import public as admin_public

    key = certs.AUTO_SEND_FLAG
    before = await certs.auto_send_enabled(session)
    changes = {"is_enabled": body.auto_send, "rollout_percent": 100 if body.auto_send else 0}
    try:
        # admin's public API: either store; it invalidates the flag cache
        _prev, f = await admin_public.patch_flag(session, principal, key, changes)
    except ProblemError as e:
        if e.code != "not_found":
            raise
        detail = (
            "The certificates.auto_send flag does not exist in this environment."
            if uses_firestore("admin")
            else "Run the learning_0005 migration first (flag missing)."
        )
        raise ProblemError("not_found", detail=detail) from e
    target_id: uuid.UUID | None = getattr(f, "id", None)
    await audit(
        session,
        principal,
        "feature_flag.changed",
        "feature_flag",
        target_id if isinstance(target_id, uuid.UUID) else None,
        before={"flag_key": key, "is_enabled": before},
        after={"flag_key": key, "is_enabled": body.auto_send},
    )
    return {"auto_send": body.auto_send, "flag_key": key}


# --------------------------------------------------------------------------- one certificate


async def _cert(session: Any, certificate_id: uuid.UUID) -> Certificate:
    c = await fss.get(session, Certificate, certificate_id)
    if c is None:
        raise ProblemError("not_found")
    return c


@router.get(
    "/admin/certificates/{certificate_id}", openapi_extra=NEUTRAL, operation_id="lrn_39_admin_certificate"
)
async def get_certificate(
    certificate_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = _perm()
) -> dict[str, Any]:
    return (await _decorate(session, [await _cert(session, certificate_id)]))[0]


@router.get(
    "/admin/certificates/{certificate_id}/pdf", openapi_extra=NEUTRAL, operation_id="lrn_40_admin_cert_pdf"
)
async def certificate_pdf(
    certificate_id: uuid.UUID, session: PrincipalDbSession, principal: Principal = _perm()
) -> dict[str, Any]:
    c = await _cert(session, certificate_id)
    if c.pdf_s3_key is None:
        if c.revoked_at is not None:
            raise ProblemError("not_found", detail="The certificate is revoked and has no PDF.")
        await certs.ensure_pdf(session, c)
    assert c.pdf_s3_key is not None
    url, exp = certs._store().signed_url(
        certs._bucket(), c.pdf_s3_key, filename=f"{c.public_code}.pdf", expires_s=PDF_URL_SECONDS
    )
    return {"url": url, "expires_at": to_rfc3339(exp)}


@router.post("/admin/certificates/{certificate_id}/regenerate", operation_id="lrn_41_admin_cert_regenerate")
async def regenerate(
    request: Request,
    certificate_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = _perm(),
) -> Any:
    async def op() -> IdemResult:
        c = await _cert(session, certificate_id)
        before = bytes(c.content_hash).hex()
        await certs.ensure_pdf(session, c, force=True)
        await audit(
            session,
            principal,
            "certificate.pdf_regenerate",
            "certificate",
            c.id,
            organization_id=c.organization_id,
            subject_user_id=c.user_id,
            before={"content_sha256": before},
            after={"content_sha256": bytes(c.content_hash).hex(), "template_version": c.template_version},
        )
        return IdemResult((await _decorate(session, [c]))[0], 200, c.id)

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)
