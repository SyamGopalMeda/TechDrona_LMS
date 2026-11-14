"""Issued documents: letters (offers, admission, recommendation) and the extra certificate types,
moved here from the company website (``tech drona/src/lib/docs.js``).

* Settings (``document_settings``, singleton): letterhead, signatory, signature / seal images
  (stored in ``S3_BUCKET_CERTIFICATES`` under ``documents/settings/``), automation switch.
  Emails follow the same ``certificates.auto_send`` flag as course certificates.
* Templates (``document_templates``): paragraph / section / email overrides; defaults in
  ``docdefs``.
* Issue: refuses while settings or required details are missing, or while template text would
  be left in the document. The filled wording is frozen in ``content`` so a re-render (download,
  email, regenerate) is byte-identical; ``content_hash`` = SHA-256 of the stored PDF and every
  copy handed out is noted in ``file_hashes`` (public "check a PDF").
* Revoke: ``valid -> revoked``. Re-issue: a corrected document of the same type
  (``valid -> superseded``, the new one ``replaces`` it).
* Email: ``certificate_outbox`` rows with ``document_id`` (one queue + approval for certificates
  and documents). Manual "issue & send" sends at once; automatic letters wait for approval
  unless auto-send is on.
* Automation: ``learning.enrolled`` -> admission letter (``offer_course``) for paid / manual /
  batch enrolments, queued for approval. Course completions keep the certificate flow.
* Public verify: ``verify_public`` / ``check_pdf`` (refs ``TD-XX-YYYY-XXXXXX``).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import re
import uuid
from datetime import date
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import ist_date, utcnow
from app.modules.learning import certificates as certs
from app.modules.learning import docdefs as dd
from app.modules.learning import docpdf, fs_docs
from app.modules.learning import fs_store as fss
from app.modules.learning.cert_models import CertificateOutbox
from app.modules.learning.certpdf import pdf_sha256
from app.modules.learning.doc_models import DocumentSettings, DocumentTemplate, IssuedDocument

log = structlog.get_logger("app.learning.documents")

Actor = Principal | AuditActor
EMAIL_TEMPLATE_KEY = "learning.document_issued"
IMAGE_MAX_BYTES = 300_000
MAX_FILE_HASHES = 20
STATUSES = ("valid", "revoked", "superseded")
_DATA_URL = re.compile(r"^data:image/(png|jpeg);base64,([A-Za-z0-9+/=\s]+)$")


def _uid(actor: Actor) -> uuid.UUID | None:
    return getattr(actor, "user_id", None)


def _site_url() -> str:
    from app.modules.identity.public import web_base_url

    return web_base_url().rstrip("/")


def verify_url(ref_no: str, site_url: str | None = None) -> str:
    return f"{(site_url or _site_url()).rstrip('/')}/verify/{ref_no}"


# --------------------------------------------------------------------------- pure rules


def check_revocable(status: str) -> bool:
    """True when the document can be revoked now; False when it already is (idempotent)."""
    if status == "revoked":
        return False
    if status == "superseded":
        raise ProblemError(
            "invalid_state_transition",
            detail="This document was already replaced by a corrected one; revoke the new one instead.",
        )
    return True


def check_supersedable(old_status: str, old_type: str, new_type: str) -> None:
    if old_type != new_type:
        raise ProblemError(
            "validation_failed",
            detail="A corrected document must be the same kind of document as the one it replaces.",
        )
    if old_status != "valid":
        raise ProblemError(
            "invalid_state_transition",
            detail=f"The document to replace is {old_status}; only a valid document can be replaced.",
        )


def validate_cert_completion_target(doc_type: str, enrolment_id: uuid.UUID | None) -> None:
    """Completion certificates of LMS enrolments live in ``certificates`` (one per enrolment,
    course rule): never duplicate them as issued documents."""
    if doc_type == "cert_completion" and enrolment_id is not None:
        raise ProblemError(
            "validation_failed",
            detail="Course completion certificates for LMS enrolments are issued from the Due tab "
            "(Certificates). Use this type only for programmes run outside an LMS enrolment.",
        )


# --------------------------------------------------------------------------- settings


async def load_settings(session: AsyncSession) -> dict[str, Any]:
    row = await fs_docs.settings_row(session)
    return dd.clean_settings(row.data if row else {})


async def _settings_row(session: AsyncSession) -> DocumentSettings:
    row = await fs_docs.settings_row(session)
    if row is None:
        row = DocumentSettings(id=1, data={})
        fss.add(session, row)
        await fss.flush(session)
    return row


async def save_settings(session: AsyncSession, actor: Actor, body: dict[str, Any]) -> dict[str, Any]:
    row = await _settings_row(session)
    before = dd.clean_settings(row.data)
    merged = {**before, **{k: v for k, v in body.items() if k in dd.SETTINGS_TEXT_LIMITS}}
    if "reg_lines" in body:
        merged["reg_lines"] = body["reg_lines"]
    for flag in ("auto_admission_letter", "watermark"):
        if flag in body:
            merged[flag] = bool(body[flag])
    for k in ("email", "signatory_email"):
        if merged.get(k) and not dd.EMAIL_RE.match(str(merged[k]).strip()):
            raise ProblemError(
                "validation_failed",
                errors=[{"field": k, "code": "invalid_email", "message": "Enter a valid email."}],
            )
    after = dd.clean_settings(merged)
    row.data = after
    row.updated_by = _uid(actor)
    await fss.flush(session)
    await audit(
        session,
        actor,
        "documents.settings_change",
        "document_settings",
        None,
        before={k: before.get(k) for k in (*dd.SETTINGS_TEXT_LIMITS, "watermark")},
        after={k: after.get(k) for k in (*dd.SETTINGS_TEXT_LIMITS, "watermark")},
    )
    return after


def decode_image(data_url: str) -> tuple[bytes, str]:
    """``data:image/png|jpeg;base64,...`` -> (bytes, content type); PNG/JPEG magic checked."""
    m = _DATA_URL.match((data_url or "").strip())
    if not m:
        raise ProblemError("unsupported_media_type", detail="Upload a PNG or JPEG image.")
    try:
        data = base64.b64decode(re.sub(r"\s+", "", m.group(2)), validate=True)
    except ValueError as e:
        raise ProblemError("validation_failed", detail="The image could not be read.") from e
    if len(data) > IMAGE_MAX_BYTES:
        raise ProblemError("payload_too_large", detail="Images must be under 300 KB.")
    kind = m.group(1)
    if (kind == "png" and not data.startswith(b"\x89PNG\r\n\x1a\n")) or (
        kind == "jpeg" and not data.startswith(b"\xff\xd8")
    ):
        raise ProblemError("unsupported_media_type", detail="The file is not a PNG or JPEG image.")
    return data, f"image/{kind}"


_image_cache: dict[str, bytes] = {}


async def _read_object(key: str) -> bytes | None:
    """Read a stored object (images are immutable: the key carries their hash)."""
    if key in _image_cache:
        return _image_cache[key]
    store = certs._store()
    bucket = certs._bucket()
    data: bytes | None = None
    objects = getattr(store, "objects", None)
    if isinstance(objects, dict):  # MemoryDocumentStore (tests / dev)
        hit = objects.get((bucket, key))
        data = hit[0] if hit else None
    elif hasattr(store, "_client"):  # S3DocumentStore
        try:
            obj = await asyncio.to_thread(store._client().get_object, Bucket=bucket, Key=key)
            data = await asyncio.to_thread(obj["Body"].read)
        except Exception as e:  # missing image: documents still render (drawn signature)
            log.warning("document_image_unreadable", key=key, error=type(e).__name__)
            data = None
    if data is not None and len(_image_cache) < 32:
        _image_cache[key] = data
    return data


async def store_image(session: AsyncSession, actor: Actor, slot: str, data_url: str) -> dict[str, Any]:
    if slot not in dd.IMAGE_SLOTS:
        raise ProblemError("not_found")
    data, ctype = decode_image(data_url)
    sha = hashlib.sha256(data).hexdigest()
    key = f"documents/settings/{slot}-{sha[:16]}.{'png' if ctype == 'image/png' else 'jpg'}"
    await certs._store().put(certs._bucket(), key, data, ctype)
    _image_cache[key] = data
    row = await _settings_row(session)
    st = dd.clean_settings(row.data)
    st[f"{slot}_key"], st[f"{slot}_sha256"] = key, sha
    row.data = st
    row.updated_by = _uid(actor)
    await fss.flush(session)
    await audit(
        session, actor, "documents.image_set", "document_settings", None, after={"slot": slot, "sha256": sha}
    )
    return st


async def clear_image(session: AsyncSession, actor: Actor, slot: str) -> dict[str, Any]:
    if slot not in dd.IMAGE_SLOTS:
        raise ProblemError("not_found")
    row = await _settings_row(session)
    st = dd.clean_settings(row.data)
    st[f"{slot}_key"], st[f"{slot}_sha256"] = None, None
    row.data = st
    row.updated_by = _uid(actor)
    await fss.flush(session)
    await audit(session, actor, "documents.image_clear", "document_settings", None, after={"slot": slot})
    return st


def settings_out(st: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in st.items() if not k.endswith("_key") and not k.endswith("_sha256")}
    out["images"] = {s: bool(st.get(f"{s}_key")) for s in dd.IMAGE_SLOTS}
    out["problem"] = dd.settings_problem(st) or None
    return out


# --------------------------------------------------------------------------- templates


async def template_override(session: AsyncSession, kind: str, key: str) -> dict[str, Any] | None:
    row = await fs_docs.template_row(session, kind, key)
    return dict(row.content) if row else None


def _str_list(v: Any, field: str, max_items: int, max_len: int) -> list[str]:
    if not isinstance(v, list) or len(v) > max_items or not all(isinstance(x, str) for x in v):
        raise ProblemError(
            "validation_failed",
            errors=[{"field": field, "code": "invalid", "message": f"Up to {max_items} lines of text."}],
        )
    out = [x.strip()[:max_len] for x in v]
    return [x for x in out if x]


def validate_template(kind: str, key: str, content: dict[str, Any]) -> dict[str, Any]:
    if kind == "document":
        if key not in dd.DOC_TYPES:
            raise ProblemError("not_found")
        out: dict[str, Any] = {}
        if "paragraphs" in content:
            paras = _str_list(content["paragraphs"], "paragraphs", 30, 3000)
            if not paras:
                raise ProblemError("validation_failed", detail="A document needs at least one paragraph.")
            out["paragraphs"] = paras
        if "sections" in content:
            if key not in dd.LETTER_SECTIONS:
                raise ProblemError("validation_failed", detail="This document type has no letter sections.")
            s = content["sections"] or {}
            if not isinstance(s, dict):
                raise ProblemError("validation_failed", detail="sections must be an object.")
            sec: dict[str, Any] = {}
            if "hero" in s:
                sec["hero"] = str(s["hero"] or "").strip()[:400]
            for k in ("benefits", "terms", "next"):
                if k in s:
                    sec[k] = _str_list(s[k], f"sections.{k}", 20, 1200)
            if "accept" in s:
                sec["accept"] = bool(s["accept"])
            out["sections"] = sec
        if not out:
            raise ProblemError("validation_failed", detail="Nothing to save.")
        return out
    if kind == "email":
        if key not in dd.EMAIL_TEMPLATES:
            raise ProblemError("not_found")
        subject = str(content.get("subject") or "").strip()[:300]
        body = str(content.get("body") or "").strip()[:8000]
        if not subject or not body:
            raise ProblemError("validation_failed", detail="An email needs a subject and a body.")
        return {"subject": subject, "body": body}
    raise ProblemError("not_found")


async def put_template(
    session: AsyncSession, actor: Actor, kind: str, key: str, content: dict[str, Any]
) -> dict[str, Any]:
    clean = validate_template(kind, key, content)
    row = await fs_docs.template_row(session, kind, key)
    before = dict(row.content) if row else None
    if row is None:
        row = DocumentTemplate(kind=kind, template_key=key, content=clean, updated_by=_uid(actor))
        fss.add(session, row)
    else:
        row.content = clean
        row.updated_by = _uid(actor)
    await fss.flush(session)
    await audit(
        session, actor, "documents.template_change", "document_template", None,
        before={"kind": kind, "key": key, "content": before},
        after={"kind": kind, "key": key, "content": clean},
    )  # fmt: skip
    return clean


async def reset_template(session: AsyncSession, actor: Actor, kind: str, key: str) -> None:
    row = await fs_docs.template_row(session, kind, key)
    if row is None:
        return
    await fss.delete(session, row)
    await fss.flush(session)
    await audit(
        session,
        actor,
        "documents.template_reset",
        "document_template",
        None,
        after={"kind": kind, "key": key},
    )


async def templates_catalogue(session: AsyncSession) -> dict[str, Any]:
    found = (
        await fs_docs.all_templates(session)
        if fss.fs()
        else (await session.execute(select(DocumentTemplate))).scalars()
    )
    rows = {(r.kind, r.template_key): dict(r.content) for r in found}
    documents = {
        k: {
            "label": t["label"],
            "default": {"paragraphs": t["paragraphs"], "sections": dd.LETTER_SECTIONS.get(k)},
            "override": rows.get(("document", k)),
        }
        for k, t in dd.DOC_TYPES.items()
    }
    emails = {
        k: {
            "label": t["label"],
            "attach": t["attach"],
            "default": {"subject": t["subject"], "body": t["body"]},
            "override": rows.get(("email", k)),
        }
        for k, t in dd.EMAIL_TEMPLATES.items()
    }
    return {"documents": documents, "emails": emails}


# --------------------------------------------------------------------------- composing

_SNAPSHOT_KEYS = (
    "company", "legal_name", "address", "phone", "email", "website", "reg_lines", "signatory",
    "designation", "signatory_email", "signatory_phone", "signature_key", "seal_key",
    "tagline", "logo_left_key", "logo_right_key", "watermark",
)  # fmt: skip


def clean_recipient(r: dict[str, Any] | None) -> dict[str, str]:
    r = r or {}
    out = {
        "name": " ".join(str(r.get("name") or "").split())[:160],
        "email": str(r.get("email") or "").strip().lower()[:254],
        "college": " ".join(str(r.get("college") or "").split())[:160],
        "reg_no": " ".join(str(r.get("reg_no") or "").split())[:60],
    }
    return out


async def compose(
    session: AsyncSession,
    *,
    doc_type: str,
    recipient: dict[str, str],
    fields: dict[str, str],
    issue_date: date,
    ref_no: str,
    settings: dict[str, Any],
    site_url: str,
    strict: bool = True,
) -> dict[str, Any]:
    """The frozen ``content`` of a document. ``strict`` refuses leftover template text."""
    cert = dd.is_certificate(doc_type)
    values = dd.placeholder_values(
        doc_type=doc_type, recipient=recipient, fields=fields, settings=settings, ref_no=ref_no,
        cert_no=ref_no if cert else "", issue_date=issue_date, site_url=site_url,
    )  # fmt: skip
    override = await template_override(session, "document", doc_type)
    paragraphs = dd.doc_paragraphs(doc_type, values, override)
    sections = dd.letter_sections(doc_type, values, override)
    subject = dd.fill(dd.DOC_TYPES[doc_type]["subject"], values)
    extras = dd.render_extras(doc_type, fields, recipient)
    if strict:
        left = dd.leftover_tokens(paragraphs, subject, sections, extras, recipient.get("name"))
        if left:
            raise ProblemError(
                "validation_failed",
                detail=f"This document still contains template text: {', '.join(left[:4])}. "
                "Fix the wording or fill in the details before issuing it.",
                leftovers=left[:10],
            )
    snap = {k: settings.get(k) for k in _SNAPSHOT_KEYS}
    return {
        "label": dd.DOC_TYPES[doc_type]["label"],
        "subject": subject,
        "paragraphs": paragraphs,
        "sections": sections,
        "extras": extras,
        "letterhead": snap,
        "site_url": site_url,
        "public": dd.public_details(doc_type, fields),
    }


async def _art(
    doc_type: str,
    ref_no: str,
    issued_on: date,
    recipient: dict[str, Any],
    content: dict[str, Any],
    *,
    preview: bool = False,
) -> Any:
    lh = content.get("letterhead") or {}
    watermark = lh.get("watermark") is not False  # documents issued before the setting: on
    url = verify_url(ref_no, content.get("site_url"))
    sig = await _read_object(lh["signature_key"]) if lh.get("signature_key") else None
    logo_l = await _read_object(lh["logo_left_key"]) if lh.get("logo_left_key") else None
    logo_r = await _read_object(lh["logo_right_key"]) if lh.get("logo_right_key") else None
    extras = content.get("extras") or {}
    if dd.is_certificate(doc_type):
        return docpdf.certificate_art(
            doc_type=doc_type, name=recipient.get("name") or "", ref_no=ref_no, issued_on=issued_on,
            verify_url=url, extras=extras, settings=lh, signature_image=sig, logo_left=logo_l,
            logo_right=logo_r, lead=(content.get("paragraphs") or [""])[0], watermark=watermark,
            preview=preview,
        )  # fmt: skip
    seal = await _read_object(lh["seal_key"]) if lh.get("seal_key") else None
    sections = content.get("sections") or {}
    lines = list(extras.get("to_lines") or [])
    if recipient.get("college"):
        lines.append(recipient["college"])
    contact = " · ".join(x for x in (lh.get("phone"), lh.get("email"), lh.get("website")) if x)
    sig_contact = ""
    if doc_type == "lor":
        sig_contact = " · ".join(
            x
            for x in (
                lh.get("signatory_email") or lh.get("email"),
                lh.get("signatory_phone") or lh.get("phone"),
            )
            if x
        )
    return docpdf.LetterArt(
        heading=dd.DOC_TYPES[doc_type]["heading"],
        ref_no=ref_no,
        issued_on=issued_on,
        verify_url=url,
        recipient_name=recipient.get("name") or "",
        recipient_lines=tuple(lines),
        paragraphs=tuple(content.get("paragraphs") or ()),
        hero=sections.get("hero") or "",
        highlights=tuple((h["label"], h["value"]) for h in extras.get("highlights") or ()),
        lists=tuple((t, tuple(items)) for t, items in extras.get("lists") or ()),
        benefits=tuple(sections.get("benefits") or ()),
        terms=tuple(sections.get("terms") or ()),
        next_steps=tuple(sections.get("next") or ()),
        accept=bool(sections.get("accept")),
        guardian=bool(extras.get("guardian")),
        company=lh.get("company") or "Tech Drona",
        legal_name=lh.get("legal_name") or "",
        address=lh.get("address") or "",
        contact_line=contact,
        reg_lines=tuple(lh.get("reg_lines") or ()),
        signatory=lh.get("signatory") or "",
        designation=lh.get("designation") or "",
        signatory_contact=sig_contact,
        signature_image=sig,
        seal_image=seal,
        tagline=lh.get("tagline") or dd.DEFAULT_TAGLINE,
        logo_left=logo_l,
        logo_right=logo_r,
        watermark=watermark,
        preview=preview,
    )


async def render_content(
    doc_type: str,
    ref_no: str,
    issued_on: date,
    recipient: dict[str, Any],
    content: dict[str, Any],
    *,
    preview: bool = False,
) -> bytes:
    """``preview``: a draft that is never stored ("DRAFT" reference, no QR / verify link, a
    "PREVIEW · NOT VALID" watermark). Issued documents always render with ``preview=False``."""
    art = await _art(doc_type, ref_no, issued_on, recipient, content, preview=preview)
    if dd.is_certificate(doc_type):
        return await asyncio.to_thread(docpdf.render_document_certificate, art)
    return await asyncio.to_thread(docpdf.render_letter_pdf, art)


def template_version(doc_type: str) -> str:
    return docpdf.CERT_TEMPLATE_VERSION if dd.is_certificate(doc_type) else docpdf.LETTER_TEMPLATE_VERSION


def recipient_of(doc: IssuedDocument) -> dict[str, Any]:
    return {"name": doc.recipient_name, "email": doc.recipient_email, **(doc.recipient or {})}


async def render(doc: IssuedDocument) -> bytes:
    return await render_content(doc.doc_type, doc.ref_no, doc.issue_date, recipient_of(doc), doc.content)


def pdf_key(doc: IssuedDocument) -> str:
    return f"documents/{doc.issue_date.year}/{doc.id}/{doc.ref_no}.pdf"


async def store_pdf(session: AsyncSession, doc: IssuedDocument, data: bytes) -> None:
    key = pdf_key(doc)
    await certs._store().put(certs._bucket(), key, data, "application/pdf")
    doc.pdf_s3_key = key
    doc.content_hash = pdf_sha256(data)
    doc.template_version = template_version(doc.doc_type)
    note_handed_out(doc, data)
    await fss.flush(session)


def note_handed_out(doc: IssuedDocument, data: bytes) -> None:
    """Record the fingerprint of a copy handed out (bounded; renders are deterministic so this
    normally stays one hash per document / template version)."""
    h = hashlib.sha256(data).hexdigest()
    have = list(doc.file_hashes or [])
    if h not in have and len(have) < MAX_FILE_HASHES:
        doc.file_hashes = [*have, h]


async def ensure_pdf(session: AsyncSession, doc: IssuedDocument, *, force: bool = False) -> bytes | None:
    if doc.status != "valid":
        if force:
            raise ProblemError("invalid_state_transition", detail=f"The document is {doc.status}.")
        return None
    if doc.pdf_s3_key and not force:
        return None
    data = await render(doc)
    await store_pdf(session, doc, data)
    return data


async def pdf_for_handout(session: AsyncSession, doc: IssuedDocument) -> bytes:
    data = await render(doc)
    if doc.pdf_s3_key is None or doc.content_hash is None or pdf_sha256(data) != bytes(doc.content_hash):
        await store_pdf(session, doc, data)
    else:
        note_handed_out(doc, data)
        await fss.flush(session)
    return data


# --------------------------------------------------------------------------- issue


async def _new_ref(session: AsyncSession, doc_type: str, year: int) -> str:
    for _ in range(8):
        ref = dd.new_ref_no(doc_type, year)
        if fss.fs():
            if not await fs_docs.ref_taken(ref):
                return ref
            continue
        hit = (await session.execute(select(IssuedDocument.id).where(IssuedDocument.ref_no == ref))).first()
        if hit is None:
            return ref
    raise ProblemError("conflict", detail="Could not allocate a reference number; try again.")


async def issue_document(
    session: AsyncSession,
    actor: Actor,
    *,
    doc_type: str,
    recipient: dict[str, Any],
    fields: dict[str, Any] | None = None,
    issue_date: date | None = None,
    user_id: uuid.UUID | None = None,
    enrolment_id: uuid.UUID | None = None,
    batch_id: uuid.UUID | None = None,
    course_id: uuid.UUID | None = None,
    organization_id: uuid.UUID | None = None,
    replaces: IssuedDocument | None = None,
    origin: str = "manual",
    bulk: dict[str, Any] | None = None,
) -> IssuedDocument:
    """``bulk``: the bulk run tag (``doc_bulk``), kept in ``content["bulk"]`` (never printed)."""
    if doc_type not in dd.DOC_TYPES:
        raise ProblemError("validation_failed", detail="Unknown document type.")
    validate_cert_completion_target(doc_type, enrolment_id)
    if replaces is not None:
        check_supersedable(replaces.status, replaces.doc_type, doc_type)
    st = await load_settings(session)
    problem = dd.settings_problem(st)
    if problem:
        raise ProblemError("invalid_state_transition", detail=problem, reason="settings")
    rcp = clean_recipient(recipient)
    try:
        f = dd.clean_fields(doc_type, fields)
    except ValueError as e:
        raise ProblemError("validation_failed", detail=str(e)) from e
    if rcp["email"] and not dd.EMAIL_RE.match(rcp["email"]):
        # A typo is not a missing field: point at the field itself.
        msg = "Enter a valid email address"
        raise ProblemError(
            "validation_failed",
            422,
            detail=f"{msg}.",
            errors=[{"field": "recipient.email", "code": "invalid_email", "message": msg}],
        )
    missing = dd.missing_fields(doc_type, f, rcp)
    if missing:
        raise ProblemError("validation_failed", detail=f"Fill in: {', '.join(missing)}.", missing=missing)
    day = issue_date or ist_date(utcnow())
    site = _site_url()
    ref = await _new_ref(session, doc_type, day.year)
    content = await compose(
        session,
        doc_type=doc_type,
        recipient=rcp,
        fields=f,
        issue_date=day,
        ref_no=ref,
        settings=st,
        site_url=site,
    )
    if bulk:
        content["bulk"] = dict(bulk)
    doc = IssuedDocument(
        id=uuid7(),
        doc_type=doc_type,
        ref_no=ref,
        recipient_name=rcp["name"],
        recipient_email=rcp["email"],
        recipient={k: rcp[k] for k in ("college", "reg_no") if rcp[k]},
        user_id=user_id,
        organization_id=organization_id,
        enrolment_id=enrolment_id,
        batch_id=batch_id,
        course_id=course_id,
        fields=f,
        content=content,
        issue_date=day,
        status="valid",
        origin=origin,
        replaces_id=replaces.id if replaces is not None else None,
        template_version=template_version(doc_type),
        file_hashes=[],
        issued_by=_uid(actor),
    )
    if fss.fs():
        fss.add(session, doc)
        try:
            await fss.flush(session, raise_unique=True)
        except fss.UniqueConflict as e:  # concurrent auto letter / 2nd correction / ref race
            raise ProblemError("conflict", detail="This document was already issued.") from e
    else:
        try:
            async with session.begin_nested():
                session.add(doc)
                await session.flush()
        except IntegrityError as e:  # concurrent auto letter for the same enrolment, or a 2nd correction
            raise ProblemError("conflict", detail="This document was already issued.") from e
    if replaces is not None:
        replaces.status = "superseded"
        replaces.superseded_by_id = doc.id
        replaces.superseded_at = utcnow()
        await fss.flush(session)
        await audit(
            session, actor, "documents.reissue", "issued_document", replaces.id,
            subject_user_id=replaces.user_id,
            before={"ref_no": replaces.ref_no, "status": "valid"},
            after={"status": "superseded", "superseded_by": doc.ref_no},
        )  # fmt: skip
    try:
        await ensure_pdf(session, doc)
    except Exception as e:  # storage down: download / email re-render and store later
        log.warning("document_pdf_failed", document_id=str(doc.id), error=type(e).__name__)
    await audit(
        session, actor, "documents.issue", "issued_document", doc.id,
        organization_id=organization_id, subject_user_id=user_id,
        after={"ref_no": ref, "doc_type": doc_type, "origin": origin, "recipient": rcp["name"]},
    )  # fmt: skip
    return doc


async def preview(
    session: AsyncSession,
    *,
    doc_type: str,
    recipient: dict[str, Any],
    fields: dict[str, Any] | None,
    issue_date: date | None = None,
) -> dict[str, Any]:
    """Draft PDF (nothing stored; reference ``TD-XX-YYYY-DRAFT``, printed as "DRAFT", no QR /
    verify link, "PREVIEW · NOT VALID" watermark) + what still blocks issuing."""
    if doc_type not in dd.DOC_TYPES:
        raise ProblemError("validation_failed", detail="Unknown document type.")
    st = await load_settings(session)
    rcp = clean_recipient(recipient)
    try:
        f = dd.clean_fields(doc_type, fields)
    except ValueError as e:
        raise ProblemError("validation_failed", detail=str(e)) from e
    day = issue_date or ist_date(utcnow())
    ref = dd.preview_ref(doc_type, day.year)
    content = await compose(
        session, doc_type=doc_type, recipient=rcp, fields=f, issue_date=day, ref_no=ref, settings=st,
        site_url=_site_url(), strict=False,
    )  # fmt: skip
    data = await render_content(doc_type, ref, day, rcp, content, preview=True)
    left = dd.leftover_tokens(
        content["paragraphs"], content["subject"], content["sections"], content["extras"]
    )
    return {
        "pdf_base64": base64.b64encode(data).decode("ascii"),
        "missing": dd.missing_fields(doc_type, f, rcp),
        "leftovers": left,
        "settings_problem": dd.settings_problem(st) or None,
        "subject": content["subject"],
    }


async def revoke(
    session: AsyncSession, actor: Actor, doc: IssuedDocument, reason: str, *, public_reason: bool = False
) -> bool:
    """``valid -> revoked``; returns False when it already was. Unsent emails are cancelled."""
    if not check_revocable(doc.status):
        return False
    why = " ".join((reason or "").split())[:300]
    doc.status = "revoked"
    doc.revoked_at = utcnow()
    doc.revoked_by = _uid(actor)
    doc.revoke_reason = why or None
    doc.revoke_reason_public = bool(public_reason and why)
    open_states = ("awaiting", "pending", "failed")
    rows = (
        await fs_docs.document_outbox(session, [doc.id], statuses=open_states)
        if fss.fs()
        else (
            await session.execute(
                select(CertificateOutbox).where(
                    CertificateOutbox.document_id == doc.id,
                    CertificateOutbox.status.in_(open_states),
                )
            )
        ).scalars()
    )
    for r in rows:
        r.status = certs.next_status(r.status, "cancel")
        r.cancelled_at = utcnow()
        r.cancelled_by = _uid(actor)
        r.last_error = "document revoked"
    await fss.flush(session)
    await audit(
        session, actor, "documents.revoke", "issued_document", doc.id, subject_user_id=doc.user_id,
        before={"status": "valid"}, after={"status": "revoked", "ref_no": doc.ref_no, "reason": why},
    )  # fmt: skip
    return True


async def reissue(
    session: AsyncSession,
    actor: Actor,
    old: IssuedDocument,
    *,
    recipient: dict[str, Any] | None = None,
    fields: dict[str, Any] | None = None,
    issue_date: date | None = None,
) -> IssuedDocument:
    """A corrected document of the same type; the old one becomes ``superseded``."""
    check_supersedable(old.status, old.doc_type, old.doc_type)
    return await issue_document(
        session,
        actor,
        doc_type=old.doc_type,
        recipient=recipient or recipient_of(old),
        fields={**(old.fields or {}), **(fields or {})} if fields is not None else old.fields,
        issue_date=issue_date,
        user_id=old.user_id,
        enrolment_id=old.enrolment_id,
        batch_id=old.batch_id,
        course_id=old.course_id,
        organization_id=old.organization_id,
        replaces=old,
        origin="reissue",
    )


# --------------------------------------------------------------------------- email


def email_text(paragraphs: list[str], company: str) -> str:
    return "\n\n".join(paragraphs) + f"\n\nRegards,\n{company}\n"


async def email_content(session: AsyncSession, doc: IssuedDocument) -> tuple[str, str]:
    """Subject + text from the email template (override or default) for this document."""
    lh = doc.content.get("letterhead") or {}
    values = dd.placeholder_values(
        doc_type=doc.doc_type, recipient=recipient_of(doc), fields=doc.fields or {}, settings=lh,
        ref_no=doc.ref_no, cert_no=doc.ref_no if dd.is_certificate(doc.doc_type) else "",
        issue_date=doc.issue_date, site_url=doc.content.get("site_url") or _site_url(),
    )  # fmt: skip
    parts = dd.email_parts(doc.doc_type, values, await template_override(session, "email", doc.doc_type))
    return parts["subject"], email_text(parts["paragraphs"], lh.get("company") or "Tech Drona")


async def queue_email(
    session: AsyncSession,
    doc: IssuedDocument,
    *,
    origin: str,
    status: str | None = None,
    to: str | None = None,
    subject: str | None = None,
    body: str | None = None,
) -> CertificateOutbox | None:
    """Queue one email with the document attached. ``status`` None = follow auto-send (pending
    when on, else awaiting approval). Automatic (``enrolment``) emails are queued once."""
    if doc.status != "valid":
        return None
    if origin == "enrolment":
        if fss.fs():
            hit: Any = (await fs_docs.document_outbox(session, [doc.id], origin="enrolment")) or None
        else:
            hit = (
                await session.execute(
                    select(CertificateOutbox.id).where(
                        CertificateOutbox.document_id == doc.id, CertificateOutbox.origin == "enrolment"
                    )
                )
            ).first()
        if hit is not None:
            return None
    if to is not None and not dd.EMAIL_RE.match(to.strip()):
        raise ProblemError("validation_failed", detail="Enter a valid email address.")
    st = status or ("pending" if await certs.auto_send_enabled(session) else "awaiting")
    row = CertificateOutbox(
        id=uuid7(),
        certificate_id=None,
        document_id=doc.id,
        user_id=doc.user_id,
        organization_id=doc.organization_id,
        status=st,
        origin=origin,
        attempts=0,
        to_email=(to or "").strip().lower() or None,
        subject=(subject or "").strip()[:300] or None,
        body=(body or "").strip()[:20000] or None,
    )
    fss.add(session, row)
    await fss.flush(session)
    return row


async def send_document_row(session: AsyncSession, row: CertificateOutbox) -> str:
    """Deliver one ``pending`` document row (called by ``certificates.send_one``)."""
    from app.modules.notifications.public import EmailAttachment, OutboundEmail, get_email_adapter

    doc = await fss.get(session, IssuedDocument, row.document_id) if row.document_id else None
    if doc is None or doc.status != "valid":
        row.status = certs.next_status(row.status, "cancel")
        row.cancelled_at = utcnow()
        row.last_error = f"document {doc.status if doc else 'missing'}"
        await fss.flush(session)
        return row.status
    to = row.to_email or doc.recipient_email
    if not to or not dd.EMAIL_RE.match(to):
        row.status = certs.next_status(row.status, "fail")
        row.last_error = "no deliverable email address"
        await fss.flush(session)
        return row.status
    try:
        data = await pdf_for_handout(session, doc)
        subject, text = await email_content(session, doc)
        mid = await get_email_adapter().send(
            OutboundEmail(
                to=to,
                subject=row.subject or subject,
                text=row.body or text,
                category="learning",
                template_key=EMAIL_TEMPLATE_KEY,
                attachments=(EmailAttachment(f"{doc.ref_no}.pdf", "application/pdf", data),),
            )
        )
    except Exception as e:  # provider / storage failure: retried up to MAX_SEND_ATTEMPTS
        row.attempts += 1
        row.last_error = type(e).__name__[:500]
        if row.attempts >= certs.MAX_SEND_ATTEMPTS:
            row.status = certs.next_status(row.status, "fail")
        await fss.flush(session)
        log.warning("document_email_failed", outbox_id=str(row.id), error=type(e).__name__)
        return row.status
    row.status = certs.next_status(row.status, "sent")
    row.sent_at = utcnow()
    row.attempts += 1
    row.last_error = None
    row.provider_message_id = str(mid or "")[:200] or None
    await fss.flush(session)
    return row.status


async def send_now(session: AsyncSession, row: CertificateOutbox) -> str:
    return await certs.send_one(session, row)


# --------------------------------------------------------------------------- enrolment automation


async def prefill_from_enrolment(session: AsyncSession, enrolment_id: uuid.UUID) -> dict[str, Any]:
    """Recipient + admission-letter fields from an enrolment (course title, batch dates)."""
    from app.modules.identity import public as identity_public
    from app.modules.learning.models import Enrolment
    from app.modules.orgs import public as orgs_public

    enr = await fss.get(session, Enrolment, enrolment_id)
    if enr is None:
        raise ProblemError("not_found")
    user = await identity_public.get_user(session, enr.user_id)
    prof = await identity_public.get_profile(session, enr.user_id)
    title = (await certs.course_titles(session, {enr.course_version_id})).get(enr.course_version_id) or ""
    batch = await orgs_public.get_batch(session, enr.batch_id) if enr.batch_id else None
    start = (batch.starts_on if batch and batch.starts_on else None) or ist_date(enr.enrolled_at or utcnow())
    duration = "self-paced"
    if batch and batch.starts_on and batch.ends_on and batch.ends_on > batch.starts_on:
        days = (batch.ends_on - batch.starts_on).days + 1
        duration = f"{round(days / 7)} weeks" if days >= 14 else f"{days} days"
    email = (getattr(user, "email", None) or "").lower()
    name = " ".join(str(getattr(prof, "full_name", "") or "").split()) or email.split("@")[0]
    return {
        "recipient": {"name": name, "email": email, "college": "", "reg_no": ""},
        "fields": {
            "program": title,
            "batch_start": start.isoformat(),
            "duration": duration,
            "mode": "Online",
        },
        "user_id": str(enr.user_id),
        "enrolment_id": str(enr.id),
        "batch_id": str(enr.batch_id) if enr.batch_id else None,
        "course_id": str(enr.course_id),
        "organization_id": str(enr.organization_id) if enr.organization_id else None,
    }


AUTO_LETTER_SKIP_SOURCES = frozenset({"free"})


async def on_enrolled(session: AsyncSession, enrolment_id: uuid.UUID, source: str) -> IssuedDocument | None:
    """Outbox consumer body (``learning.enrolled``): issue the admission letter once and queue
    its email (awaiting approval unless auto-send is on). Never raises for business reasons."""
    if source in AUTO_LETTER_SKIP_SOURCES:
        return None
    st = await load_settings(session)
    if not st.get("auto_admission_letter") or dd.settings_problem(st):
        return None
    if fss.fs():
        if await fs_docs.enrolment_letter_exists(enrolment_id, "offer_course"):
            return None
    else:
        existing = (
            await session.execute(
                select(IssuedDocument.id).where(
                    IssuedDocument.enrolment_id == enrolment_id, IssuedDocument.doc_type == "offer_course"
                )
            )
        ).first()
        if existing is not None:
            return None
    try:
        pre = await prefill_from_enrolment(session, enrolment_id)
    except ProblemError:
        return None
    if not pre["recipient"]["email"] or not pre["fields"]["program"]:
        return None
    try:
        async with certs.savepoint(session):
            doc = await issue_document(
                session,
                AuditActor.system("learning.admission_letter"),
                doc_type="offer_course",
                recipient=pre["recipient"],
                fields=pre["fields"],
                user_id=uuid.UUID(pre["user_id"]),
                enrolment_id=enrolment_id,
                batch_id=uuid.UUID(pre["batch_id"]) if pre["batch_id"] else None,
                course_id=uuid.UUID(pre["course_id"]),
                organization_id=uuid.UUID(pre["organization_id"]) if pre["organization_id"] else None,
                origin="enrolment",
            )
            await queue_email(session, doc, origin="enrolment")
    except ProblemError as e:
        log.info("admission_letter_skipped", enrolment_id=str(enrolment_id), reason=e.code)
        return None
    return doc


# --------------------------------------------------------------------------- public verify


async def _related(session: AsyncSession, doc: IssuedDocument) -> list[dict[str, str]]:
    if fss.fs():
        same = await fs_docs.same_recipient(session, doc, valid_only=True, limit=10)
        return [{"ref_no": d.ref_no, "label": dd.DOC_TYPES[d.doc_type]["label"]} for d in same]
    rows = (
        await session.execute(
            select(IssuedDocument.ref_no, IssuedDocument.doc_type)
            .where(
                func.lower(IssuedDocument.recipient_email) == doc.recipient_email.lower(),
                IssuedDocument.status == "valid",
                IssuedDocument.id != doc.id,
            )
            .order_by(IssuedDocument.created_at.desc())
            .limit(10)
        )
    ).all()
    return [{"ref_no": r, "label": dd.DOC_TYPES[t]["label"]} for r, t in rows]


async def verify_public(session: AsyncSession, code: str) -> dict[str, Any]:
    """Public result for a document reference: status, type, holder, dates, program, summary and
    signatory. Never a letter's text, contact details or fees. Uniform 404 when unknown."""
    ref = dd.normalise_ref(code)
    if not dd.REF_RE.match(ref):
        raise ProblemError("not_found")
    if fss.fs():
        doc = await fs_docs.document_by_ref(session, ref)
    else:
        doc = (
            await session.execute(select(IssuedDocument).where(IssuedDocument.ref_no == ref))
        ).scalar_one_or_none()
    if doc is None:
        raise ProblemError("not_found")
    t = dd.DOC_TYPES[doc.doc_type]
    lh = doc.content.get("letterhead") or {}
    pub = doc.content.get("public") or {}
    out: dict[str, Any] = {
        "kind": "document",
        "public_code": doc.ref_no,
        "ref_no": doc.ref_no,
        "doc_type": doc.doc_type,
        "label": t["label"],
        "layout": t["layout"],
        "status": doc.status,
        "recipient": doc.recipient_name,
        "name_on_certificate": doc.recipient_name,
        "issued_at": doc.issue_date.isoformat(),
        "issuer": lh.get("company") or "Tech Drona",
    }
    if doc.status == "revoked":
        out["revoked_on"] = ist_date(doc.revoked_at).isoformat() if doc.revoked_at else None
        out["revoked_reason"] = doc.revoke_reason if doc.revoke_reason_public else None
        return out
    if doc.status == "superseded":
        new = await fss.get(session, IssuedDocument, doc.superseded_by_id) if doc.superseded_by_id else None
        out["superseded_by"] = new.ref_no if new else None
        out["superseded_on"] = ist_date(doc.superseded_at).isoformat() if doc.superseded_at else None
        return out
    signatory = ", ".join(x for x in (lh.get("signatory"), lh.get("designation")) if x)
    out["signatory"] = signatory or None
    if doc.doc_type != "lor":
        out["program"] = pub.get("program") or None
        out["course_title"] = pub.get("program") or None
        out["start_date"] = pub.get("start_date") or None
        out["end_date"] = pub.get("end_date") or None
        out["details"] = {k: v for k, v in pub.items() if k not in ("program", "start_date", "end_date")}
    if doc.replaces_id:
        old = await fss.get(session, IssuedDocument, doc.replaces_id)
        out["replaces"] = old.ref_no if old else None
    out["related"] = await _related(session, doc)
    out["pdf_check"] = bool(doc.content_hash or doc.file_hashes)
    return out


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def hash_matches(sha_hex: str, content_hash: bytes | None, file_hashes: list[str] | None) -> bool:
    h = (sha_hex or "").strip().lower()
    if not _HEX64.match(h):
        return False
    if content_hash is not None and bytes(content_hash).hex() == h:
        return True
    return h in (file_hashes or [])


async def check_pdf(session: AsyncSession, code: str, sha_hex: str) -> dict[str, Any]:
    """Does a PDF (hashed in the visitor's browser) match a copy we issued? Certificates compare
    with their stored PDF; documents with every copy handed out."""
    from app.modules.learning.models import Certificate

    if not _HEX64.match((sha_hex or "").strip().lower()):
        raise ProblemError("validation_failed", detail="sha256 must be 64 hex characters.")
    if dd.is_doc_ref(code):
        if fss.fs():
            doc = await fs_docs.document_by_ref(session, dd.normalise_ref(code))
        else:
            doc = (
                await session.execute(
                    select(IssuedDocument).where(IssuedDocument.ref_no == dd.normalise_ref(code))
                )
            ).scalar_one_or_none()
        if doc is None:
            raise ProblemError("not_found")
        return {"match": hash_matches(sha_hex, doc.content_hash, doc.file_hashes), "status": doc.status}
    if fss.fs():
        cert = await fs_docs.certificate_by_code(code.strip().upper())
    else:
        cert = (
            await session.execute(select(Certificate).where(Certificate.public_code == code.strip().upper()))
        ).scalar_one_or_none()
    if cert is None:
        raise ProblemError("not_found")
    stored = bytes(cert.content_hash) if cert.pdf_s3_key else None
    return {
        "match": hash_matches(sha_hex, stored, None),
        "status": "revoked" if cert.revoked_at else "valid",
    }
