"""Issued documents on Firestore (``TD_STORE_LEARNING=firestore``): the reads ``documents.py`` and
``doc_admin.py`` need, built on ``fs_store`` (fss). The Postgres queries stay in those files.

Data model (``store_specs``): ``issued_documents/{id}``, ``issued_document_keys/{ref:..|replaces:..|
enrolment_auto:..}``, ``document_templates/{kind:key}``, ``document_settings/platform``,
``certificate_outbox/{id}``.

Costs (no SQL ``lower()``/``LIKE`` on Firestore):

* ``related_*`` (same recipient email, case-insensitive) and the register search ``q`` scan the
  matching ``issued_documents`` (``status == valid`` for the public verify page, the whole register
  for the admin search) and filter in memory. Fine for a company register (thousands); revisit
  with a lowercased ``recipient_email_lc`` shadow field + index if it grows.
* The register is ordered by id (uuid7, i.e. issue order) and keyset-paged by id, as on Postgres.
"""

from __future__ import annotations

import uuid
from collections import Counter

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.learning import fs_store as fss
from app.modules.learning import store_specs as ss
from app.modules.learning.cert_models import CertificateOutbox
from app.modules.learning.doc_models import DocumentSettings, DocumentTemplate, IssuedDocument
from app.modules.learning.models import Certificate

JOB = "learning.documents"


# --------------------------------------------------------------------------- settings / templates
# (both stores: the Postgres branch is the original ``session.get``)


async def settings_row(session: AsyncSession) -> DocumentSettings | None:
    if not fss.fs():
        return await session.get(DocumentSettings, 1)
    return await fss.get(session, DocumentSettings, ss.DOC_SETTINGS_ID, job=JOB)


async def template_row(session: AsyncSession, kind: str, key: str) -> DocumentTemplate | None:
    if not fss.fs():
        return await session.get(DocumentTemplate, (kind, key))
    return await fss.get(session, DocumentTemplate, ss.template_id(kind, key), job=JOB)


async def all_templates(session: AsyncSession) -> list[DocumentTemplate]:
    """Firestore only (the catalogue's Postgres branch keeps its ``select``)."""
    return await fss.find(session, DocumentTemplate, job=JOB)


# --------------------------------------------------------------------------- documents


async def document(session: AsyncSession | None, document_id: uuid.UUID) -> IssuedDocument | None:
    return await fss.get(session, IssuedDocument, document_id, job=JOB)


async def document_by_ref(session: AsyncSession | None, ref_no: str) -> IssuedDocument | None:
    """``WHERE ref_no = :ref`` through the unique ref key document."""
    target = await fss.key_target(ss.DOCUMENT_KEYS, ss.doc_ref_key(ref_no), job=JOB)
    return await document(session, uuid.UUID(target)) if target else None


async def ref_taken(ref_no: str) -> bool:
    return (await fss.key_target(ss.DOCUMENT_KEYS, ss.doc_ref_key(ref_no), job=JOB)) is not None


async def enrolment_letter_exists(enrolment_id: uuid.UUID, doc_type: str) -> bool:
    """Any document of ``doc_type`` for the enrolment (whatever its origin, as the SQL)."""
    rows = await fss.find(
        None,
        IssuedDocument,
        filters=(("enrolment_id", "==", enrolment_id), ("doc_type", "==", doc_type)),
        limit=1,
        job=JOB,
    )
    return bool(rows)


async def same_recipient(
    session: AsyncSession | None, doc: IssuedDocument, *, valid_only: bool, limit: int
) -> list[IssuedDocument]:
    """Other documents of the recipient (``lower(recipient_email)`` equality), newest first."""
    email = (doc.recipient_email or "").lower()
    filters: tuple[fss.Filter, ...] = (("status", "==", "valid"),) if valid_only else ()
    rows = await fss.find(
        session,
        IssuedDocument,
        filters=filters,
        where=lambda d: d.id != doc.id and (d.recipient_email or "").lower() == email,
        job=JOB,
    )
    rows.sort(key=lambda d: d.created_at, reverse=True)
    return rows[:limit]


def _lower(v: str | None) -> str | None:
    return v.lower() if v is not None else None


def _matches(d: IssuedDocument, term: str, ref: str) -> bool:
    """``lower(col) LIKE '%term%'`` (unescaped, as the SQL): wildcards in the term apply."""
    return (
        fss.like(_lower(d.recipient_name), f"%{term}%")
        or fss.like(_lower(d.recipient_email), f"%{term}%")
        or fss.like(_lower(d.ref_no), f"%{ref}%")
    )


async def register_page(
    session: AsyncSession,
    *,
    doc_type: str | None,
    status: str | None,
    course_id: uuid.UUID | None,
    term: str,
    ref: str,
    after: uuid.UUID | None,
    limit: int,
) -> list[IssuedDocument]:
    """``limit + 1`` rows, id descending, after the cursor id (the admin register)."""
    filters: list[fss.Filter] = []
    if doc_type:
        filters.append(("doc_type", "==", doc_type))
    if status:
        filters.append(("status", "==", status))
    if course_id is not None:
        filters.append(("course_id", "==", course_id))
    rows = await fss.find(
        session,
        IssuedDocument,
        filters=filters,
        where=lambda d: (after is None or d.id < after) and (not term or _matches(d, term, ref)),
        job=JOB,
    )
    rows.sort(key=lambda d: d.id, reverse=True)
    return rows[: limit + 1]


async def status_counts() -> dict[str, int]:
    out: Counter[str] = Counter()
    for s in ("valid", "revoked", "superseded"):
        n = await fss.count(IssuedDocument, (("status", "==", s),), job=JOB)
        if n:
            out[s] = n
    return dict(out)


# --------------------------------------------------------------------------- outbox rows of documents


async def document_outbox(
    session: AsyncSession | None,
    document_ids: list[uuid.UUID],
    *,
    statuses: tuple[str, ...] | None = None,
    origin: str | None = None,
) -> list[CertificateOutbox]:
    """Outbox rows of these documents, ordered (created_at, id) ascending."""
    out: list[CertificateOutbox] = []
    for i in range(0, len(document_ids), 30):
        chunk = document_ids[i : i + 30]
        filters: list[fss.Filter] = [("document_id", "in", chunk)]
        if origin is not None:
            filters.append(("origin", "==", origin))
        out += await fss.find(
            session,
            CertificateOutbox,
            filters=filters,
            where=lambda o: statuses is None or o.status in statuses,
            job=JOB,
        )
    out.sort(key=lambda o: (o.created_at, str(o.id)))
    return out


# --------------------------------------------------------------------------- certificates (PDF check)


async def certificate_by_code(code: str) -> Certificate | None:
    target = await fss.key_target(ss.CERT_CODES, code, job=JOB)
    return await fss.get(None, Certificate, uuid.UUID(target), job=JOB) if target else None
