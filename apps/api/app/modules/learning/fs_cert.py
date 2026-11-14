"""Firestore branches of the certificate automation (``certificates.py`` / ``cert_admin.py``).

Only used when ``TD_STORE_LEARNING=firestore``; the Postgres paths keep their SQL. Rows come back
as tracked transient ORM instances (``fs_store``), so callers mutate them and call
``fss.flush(session)`` exactly as on Postgres.

Joins into other modules go through their public APIs: users/profiles via
``identity.public`` (``get_users`` / ``get_profiles`` / ``list_users``), batches via
``orgs.public.get_batches``, course titles via ``catalog.api``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.learning import fs_store as fss
from app.modules.learning import store_specs as ss
from app.modules.learning.cert_models import CertificateOutbox
from app.modules.learning.doc_models import IssuedDocument
from app.modules.learning.models import Certificate, Enrolment

SEND_LEASE = "learning.certificate_outbox_send"
SEND_LEASE_TTL = timedelta(minutes=5)


def _chunks(ids: list[Any], n: int = 30) -> Iterable[list[Any]]:
    for i in range(0, len(ids), n):
        yield ids[i : i + n]


def _cert_order(c: Certificate) -> tuple[Any, str]:
    return (c.issued_at, str(c.id))


def _box_order(o: CertificateOutbox) -> tuple[Any, str]:
    return (o.created_at, str(o.id))


# --------------------------------------------------------------------------- certificates


async def certs_without_pdf(session: AsyncSession, limit: int) -> list[Certificate]:
    """Live certificates with no PDF, oldest first (``issued_at, id``)."""
    rows = await fss.find(session, Certificate, where=lambda c: c.pdf_s3_key is None and c.revoked_at is None)
    return sorted(rows, key=_cert_order)[:limit]


async def certificates(session: AsyncSession, course_id: uuid.UUID | None) -> list[Certificate]:
    filters = (("course_id", "==", course_id),) if course_id is not None else ()
    return await fss.find(session, Certificate, filters=filters)


async def certificate_page(
    session: AsyncSession,
    *,
    course_id: uuid.UUID | None,
    status: str | None,
    term: str,
    after: uuid.UUID | None,
    limit: int,
) -> list[Certificate]:
    """Admin register: newest id first, ``limit + 1`` rows (the caller detects ``more``)."""
    people = await people_matching(session, term) if term else set()

    def keep(c: Certificate) -> bool:
        if status == "valid" and c.revoked_at is not None:
            return False
        if status == "revoked" and c.revoked_at is None:
            return False
        like = f"%{term}%"
        if term and not (
            fss.like(
                (c.name_on_certificate or "").lower() if c.name_on_certificate is not None else None, like
            )
            or fss.like((c.public_code or "").lower(), like)
            or c.user_id in people
        ):
            return False
        return after is None or c.id < after

    rows = [c for c in await certificates(session, course_id) if keep(c)]
    rows.sort(key=lambda c: c.id, reverse=True)
    return rows[: limit + 1]


async def people_matching(session: AsyncSession, term: str) -> set[uuid.UUID]:
    """Users whose e-mail or full name contains ``term`` (lower-case), as the SQL subquery."""
    from app.modules.identity import public as identity

    users = await identity.list_users(session)
    profs = await identity.get_profiles(session, [u.id for u in users])
    out: set[uuid.UUID] = set()
    like = f"%{term}%"
    for u in users:
        p = profs.get(u.id)
        email = u.email.lower() if u.email is not None else None
        name = p.full_name.lower() if p is not None and p.full_name is not None else None
        if fss.like(email, like) or fss.like(name, like):
            out.add(u.id)
    return out


async def emails(session: AsyncSession, user_ids: set[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    from app.modules.identity import public as identity

    return {uid: u.email for uid, u in (await identity.get_users(session, user_ids)).items()}


# --------------------------------------------------------------------------- outbox


async def outbox_for_certificate(certificate_id: uuid.UUID) -> uuid.UUID | None:
    target = await fss.key_target(ss.CERT_OUTBOX_KEYS, ss.outbox_cert_key(certificate_id))
    return uuid.UUID(target) if target else None


async def queue_certificate_email(session: AsyncSession, row: CertificateOutbox) -> CertificateOutbox | None:
    """Insert ``row`` unless the certificate already has one (``ON CONFLICT DO NOTHING``)."""
    if row.certificate_id is not None and await outbox_for_certificate(row.certificate_id) is not None:
        return None
    fss.add(session, row)
    try:
        await fss.flush(session, raise_unique=True)
    except fss.UniqueConflict:  # a concurrent queue of the same certificate won
        return None
    return row


async def outboxes_of_certificates(
    session: AsyncSession, cert_ids: list[uuid.UUID]
) -> dict[uuid.UUID, CertificateOutbox]:
    out: dict[uuid.UUID, CertificateOutbox] = {}
    for part in _chunks(list(dict.fromkeys(cert_ids))):
        for o in await fss.find(session, CertificateOutbox, filters=(("certificate_id", "in", part),)):
            if o.certificate_id is not None:
                out[o.certificate_id] = o
    return out


async def outbox_rows(session: AsyncSession, ids: list[uuid.UUID]) -> list[CertificateOutbox]:
    """Rows by id, ordered ``created_at, id`` (the approve/cancel ``SELECT ... FOR UPDATE``)."""
    rows = list((await fss.get_many(session, CertificateOutbox, ids)).values())
    return sorted(rows, key=_box_order)


async def pending_rows(session: AsyncSession, limit: int) -> list[CertificateOutbox]:
    rows = await fss.find(session, CertificateOutbox, filters=(("status", "==", "pending"),))
    return sorted(rows, key=_box_order)[:limit]


async def claim_sender(holder: str) -> bool:
    """Replaces ``FOR UPDATE SKIP LOCKED``: one sender at a time (a lease, auto-expiring)."""
    return bool(await fss.store("learning.cert_send").claim_lease(SEND_LEASE, holder, SEND_LEASE_TTL))


async def release_sender(holder: str) -> None:
    await fss.store("learning.cert_send").release_lease(SEND_LEASE, holder)


async def outbox_counts(statuses: Iterable[str]) -> dict[str, int]:
    return {s: await fss.count(CertificateOutbox, (("status", "==", s),)) for s in statuses}


async def outbox_page(
    session: AsyncSession,
    *,
    status: str | None,
    course_id: uuid.UUID | None,
    kind: str | None,
    after: uuid.UUID | None,
    limit: int,
) -> list[tuple[CertificateOutbox, Certificate | None, IssuedDocument | None]]:
    """The approval queue joined with its certificate / issued document; newest id first,
    ``limit + 1`` rows."""
    filters = (("status", "==", status),) if status else ()
    rows = await fss.find(session, CertificateOutbox, filters=filters)
    if kind == "certificate":
        rows = [o for o in rows if o.certificate_id is not None]
    elif kind == "document":
        rows = [o for o in rows if o.document_id is not None]
    if after is not None:
        rows = [o for o in rows if o.id < after]
    rows.sort(key=lambda o: o.id, reverse=True)
    out: list[tuple[CertificateOutbox, Certificate | None, IssuedDocument | None]] = []
    # join lazily, page by page, so the course filter can drop rows before the limit
    for i in range(0, len(rows), 100):
        part = rows[i : i + 100]
        certs = await fss.get_many(session, Certificate, [o.certificate_id for o in part if o.certificate_id])
        docs = await fss.get_many(session, IssuedDocument, [o.document_id for o in part if o.document_id])
        for o in part:
            c = certs.get(o.certificate_id) if o.certificate_id else None
            d = docs.get(o.document_id) if o.document_id else None
            if course_id is not None and not (
                (c is not None and c.course_id == course_id) or (d is not None and d.course_id == course_id)
            ):
                continue
            out.append((o, c, d))
            if len(out) > limit:
                return out
    return out


async def document_status_counts(session: AsyncSession, course_id: uuid.UUID | None) -> dict[str, int]:
    filters = (("course_id", "==", course_id),) if course_id is not None else ()
    out: dict[str, int] = {}
    for d in await fss.find(session, IssuedDocument, filters=filters):
        out[d.status] = out.get(d.status, 0) + 1
    return out


# --------------------------------------------------------------------------- due list


async def due_rows(
    session: AsyncSession,
    *,
    course_id: uuid.UUID | None,
    batch_ended_only: bool,
    today: date,
    limit: int,
) -> list[tuple[Enrolment, str | None, date | None, str | None, str | None]]:
    """Both stores. ``(enrolment, batch name, batch ends_on, email, full name)`` of active/completed
    enrolments without a certificate that are completed or whose batch ended before ``today``;
    ordered ``completed_at DESC NULLS LAST, id DESC``; at most ``limit``."""
    from app.modules.identity import public as identity
    from app.modules.orgs import public as orgs

    if fss.fs():
        filters: list[Any] = [("status", "in", ["active", "completed"])]
        if course_id is not None:
            filters.append(("course_id", "==", course_id))
        enrs = await fss.find(session, Enrolment, filters=filters)
        if not enrs:
            return []
        certified: set[str] = set()
        st = fss.store()
        ids = [str(e.id) for e in enrs]
        for i in range(0, len(ids), 100):
            certified |= set((await st.get_many(ss.CERT_BY_ENROLMENT, ids[i : i + 100])).keys())
        enrs = [e for e in enrs if str(e.id) not in certified]
    else:  # Postgres: learning's own tables in SQL; batches and users through their public APIs
        from sqlalchemy import select

        q = (
            select(Enrolment)
            .outerjoin(Certificate, Certificate.enrolment_id == Enrolment.id)
            .where(Certificate.id.is_(None), Enrolment.status.in_(("active", "completed")))
        )
        if course_id is not None:
            q = q.where(Enrolment.course_id == course_id)
        enrs = list((await session.execute(q)).scalars())
    batches = await orgs.get_batches(session, {e.batch_id for e in enrs if e.batch_id})

    def ended(e: Enrolment) -> bool:
        b = batches.get(e.batch_id) if e.batch_id else None
        return b is not None and b.ends_on is not None and b.ends_on < today

    enrs = [e for e in enrs if (ended(e) if batch_ended_only else (e.status == "completed" or ended(e)))]
    enrs.sort(key=lambda e: str(e.id), reverse=True)
    enrs.sort(key=lambda e: (e.completed_at is None, -(e.completed_at.timestamp()) if e.completed_at else 0))
    enrs = enrs[:limit]
    users = await identity.get_users(session, {e.user_id for e in enrs})
    profs = await identity.get_profiles(session, {e.user_id for e in enrs})
    out = []
    for e in enrs:
        b = batches.get(e.batch_id) if e.batch_id else None
        u = users.get(e.user_id)
        p = profs.get(e.user_id)
        out.append(
            (
                e,
                b.name if b else None,
                b.ends_on if b else None,
                u.email if u else None,
                p.full_name if p else None,
            )
        )
    return out
