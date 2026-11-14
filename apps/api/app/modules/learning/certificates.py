"""Certificate issuance automation: PDF generation + storage, the email outbox with an approval
step, and the "due" list (completed enrolments / ended batches without a certificate).

Flow (end to end):

1. A certificate is issued (``service.issue_certificate``: progress rule, manual issue, or the
   due list / daily batch-end job here). It emits ``learning.certificate_issued``.
2. The outbox relay runs ``on_certificate_issued`` (``learning.tasks``): renders the PDF
   (``certpdf``), stores it in ``S3_BUCKET_CERTIFICATES`` (``pdf_s3_key``; ``content_hash`` =
   SHA-256 of the PDF) and queues one ``certificate_outbox`` row: ``pending`` when the feature
   flag ``certificates.auto_send`` is on, else ``awaiting`` (admin approval).
3. Admins approve (single / bulk) in Admin > Certificates: ``awaiting -> pending``; approved rows
   are sent at once (capped) and the beat job ``learning.certificate_outbox_send`` sends the rest.
   The email carries the PDF as an attachment (``OutboundEmail.attachments``) and an in-app
   notification (``learning.certificate_issued``) is written when it is sent.
4. ``learning.certificates_batch_end`` (daily beat) issues certificates for enrolments whose
   batch ended (``batches.ends_on`` < today, IST) and whose course rule is met. Idempotent: one
   certificate per enrolment (unique), one outbox row per certificate (unique).
   Batch attendance gate: when the batch plan sets ``min_attendance_percent`` (orgs_0005,
   default off) a learner below it is listed as not eligible with the reason (``due_enrolments``).

Every function takes the caller's session/RLS context (platform staff or ``system_context``).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import date
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal
from app.core.time import ist_date, utcnow
from app.modules.catalog import public as catalog_api
from app.modules.learning import fs_cert
from app.modules.learning import fs_store as fss
from app.modules.learning import service as svc
from app.modules.learning.cert_models import CertificateOutbox
from app.modules.learning.certpdf import TEMPLATE_VERSION, CertificateArt, pdf_sha256, render_certificate_pdf
from app.modules.learning.models import Certificate, Enrolment

log = structlog.get_logger("app.learning.certificates")

AUTO_SEND_FLAG = "certificates.auto_send"
OUTBOX_STATUSES = ("awaiting", "pending", "sent", "failed", "cancelled")
# action -> (allowed current statuses, next status)
OUTBOX_TRANSITIONS: dict[str, tuple[frozenset[str], str]] = {
    "approve": (frozenset({"awaiting", "failed"}), "pending"),
    "cancel": (frozenset({"awaiting", "pending", "failed"}), "cancelled"),
    "sent": (frozenset({"pending"}), "sent"),
    "fail": (frozenset({"pending"}), "failed"),
}
MAX_SEND_ATTEMPTS = 3
INLINE_SEND_CAP = 25  # approve sends this many at once; the beat job sends the rest
EMAIL_TEMPLATE_KEY = "learning.certificate_issued"


def next_status(current: str, action: str) -> str:
    """The outbox state machine; raises ``invalid_state_transition`` for a move it forbids."""
    rule = OUTBOX_TRANSITIONS.get(action)
    if rule is None:
        raise ValueError(f"unknown outbox action {action!r}")
    allowed, target = rule
    if current not in allowed:
        raise ProblemError(
            "invalid_state_transition", detail=f"A certificate email that is {current} cannot be {action}d."
        )
    return target


# --------------------------------------------------------------------------- PDF


def verify_url(public_code: str) -> str:
    from app.modules.identity.public import web_base_url

    return f"{web_base_url()}/verify/{public_code}"


def pdf_key(cert: Certificate) -> str:
    return f"certificates/{cert.user_id}/{cert.id}/{cert.public_code}.pdf"


def _bucket() -> str:
    from app.modules.media.public import storage_settings

    return storage_settings().S3_BUCKET_CERTIFICATES


def _store() -> Any:
    # The commerce document store (S3 put_object / memory fake) is the generic "store a generated
    # document" adapter; certificates use it with their own bucket.
    from app.modules.commerce.public import get_document_store

    return get_document_store()


async def course_titles(session: AsyncSession, version_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    versions = await catalog_api.get_versions(session, version_ids)
    return {k: v.title for k, v in versions.items()}


async def art_for(session: AsyncSession, cert: Certificate) -> CertificateArt:
    title = (await course_titles(session, {cert.course_version_id})).get(cert.course_version_id) or "Course"
    # organisation, tagline, signatory, signature and logo slots: Documents -> Settings (shared
    # with the issued documents, so every certificate looks the same)
    from app.modules.learning import documents as docs

    try:
        st = await docs.load_settings(session)
    except Exception as e:  # settings unreadable: the certificate still renders (defaults)
        log.warning("certificate_settings_unreadable", error=type(e).__name__)
        st = {}

    async def image(slot: str) -> bytes | None:
        key = st.get(f"{slot}_key")
        return await docs._read_object(key) if key else None

    return CertificateArt(
        name=cert.name_on_certificate,
        course_title=title,
        public_code=cert.public_code,
        issued_on=ist_date(cert.issued_at),
        verify_url=verify_url(cert.public_code),
        citation="has successfully completed the course",
        issuer=st.get("legal_name") or st.get("company") or "Tech Drona",
        signatory=st.get("signatory") or "",
        signatory_title=st.get("designation") or "",
        tagline=st.get("tagline") or "",
        signature_image=await image("signature"),
        logo_left=await image("logo_left"),
        logo_right=await image("logo_right"),
    )


async def render_pdf(session: AsyncSession, cert: Certificate) -> bytes:
    art = await art_for(session, cert)
    return await asyncio.to_thread(render_certificate_pdf, art)


async def store_pdf(session: AsyncSession, cert: Certificate, data: bytes) -> None:
    key = pdf_key(cert)
    await _store().put(_bucket(), key, data, "application/pdf")
    cert.pdf_s3_key = key
    cert.content_hash = pdf_sha256(data)
    cert.template_version = TEMPLATE_VERSION
    await fss.flush(session)


async def ensure_pdf(session: AsyncSession, cert: Certificate, *, force: bool = False) -> bytes | None:
    """Render + store the PDF when it is missing (or ``force``). Returns the bytes it stored,
    ``None`` when nothing had to be done. Revoked certificates are never (re)generated."""
    if cert.revoked_at is not None:
        if force:
            raise ProblemError("invalid_state_transition", detail="The certificate is revoked.")
        return None
    if cert.pdf_s3_key and not force:
        return None
    data = await render_pdf(session, cert)
    await store_pdf(session, cert, data)
    return data


async def pdf_for_email(session: AsyncSession, cert: Certificate) -> bytes:
    """The PDF to attach. Rendering is deterministic, so a re-render matches the stored file;
    when it does not (missing PDF, new template or base URL) the new file is stored."""
    data = await render_pdf(session, cert)
    if cert.pdf_s3_key is None or pdf_sha256(data) != bytes(cert.content_hash):
        await store_pdf(session, cert, data)
    return data


async def backfill_pdfs(session: AsyncSession, *, limit: int = 200) -> int:
    """Generate the PDF of live certificates that have none (oldest first). Returns the count."""
    if fss.fs():
        return await _backfill(session, await fs_cert.certs_without_pdf(session, limit))
    certs = list(
        (
            await session.execute(
                select(Certificate)
                .where(Certificate.pdf_s3_key.is_(None), Certificate.revoked_at.is_(None))
                .order_by(Certificate.issued_at, Certificate.id)
                .limit(limit)
            )
        ).scalars()
    )
    return await _backfill(session, certs)


async def _backfill(session: AsyncSession, certs: list[Certificate]) -> int:
    n = 0
    for cert in certs:
        try:
            await ensure_pdf(session, cert)
            n += 1
        except Exception as e:  # one bad row never blocks the rest
            log.warning(
                "certificate_pdf_backfill_failed", certificate_id=str(cert.id), error=type(e).__name__
            )
    return n


# --------------------------------------------------------------------------- outbox


async def auto_send_enabled(session: AsyncSession) -> bool:
    from app.modules.admin import public as admin_flags

    try:
        return await admin_flags.flag_enabled(session, AUTO_SEND_FLAG)
    except Exception as e:  # flag store unreachable: fail safe (wait for approval)
        log.warning("certificate_auto_send_flag_unreadable", error=type(e).__name__)
        return False


async def queue_email(session: AsyncSession, cert: Certificate, *, origin: str) -> CertificateOutbox | None:
    """Queue the certificate email once (idempotent per certificate). Returns the new row or None."""
    if cert.revoked_at is not None:
        return None
    status = "pending" if await auto_send_enabled(session) else "awaiting"
    if fss.fs():
        return await fs_cert.queue_certificate_email(
            session,
            CertificateOutbox(
                id=uuid7(),
                certificate_id=cert.id,
                user_id=cert.user_id,
                organization_id=cert.organization_id,
                status=status,
                origin=origin,
            ),
        )
    new_id = (
        await session.execute(
            pg_insert(CertificateOutbox)
            .values(
                id=uuid7(),
                certificate_id=cert.id,
                user_id=cert.user_id,
                organization_id=cert.organization_id,
                status=status,
                origin=origin,
            )
            .on_conflict_do_nothing(index_elements=[CertificateOutbox.certificate_id])
            .returning(CertificateOutbox.id)
        )
    ).scalar_one_or_none()
    return await session.get(CertificateOutbox, new_id) if new_id else None


def email_content(*, name: str, course_title: str, public_code: str, url: str) -> tuple[str, str]:
    """Subject + text of the certificate email (website template ``cert_completion``)."""
    first = (name.split() or ["there"])[0]
    subject = f"Your certificate of completion: {course_title}"
    text = (
        f"Dear {first},\n\n"
        f"Congratulations on completing {course_title}! Your certificate is attached.\n\n"
        f"Certificate number: {public_code}\n"
        f"Anyone can verify it at {url}\n\n"
        "You can also download it any time from Certificates in your Tech Drona account.\n\n"
        "We wish you every success.\nTech Drona\n"
    )
    return subject, text


async def _recipient(session: AsyncSession, user_id: uuid.UUID) -> str | None:
    from app.modules.identity import public as identity

    u = await identity.get_user(session, user_id)
    if u is None or u.status in ("deleted", "deactivated") or not u.email:
        return None
    return u.email


async def send_one(session: AsyncSession, row: CertificateOutbox) -> str:
    """Deliver one ``pending`` row; returns the resulting status. Never raises for delivery errors.

    Firestore: the Postgres row lock held while sending (``FOR UPDATE`` / ``SKIP LOCKED``) is a
    per-row lease; a row another sender is working on is skipped, and the status is re-read
    after the lease is taken, so the same email is never sent twice."""
    if not fss.fs():
        return await _send_one(session, row)
    if row.status != "pending":
        return row.status
    holder = await fss.lease(f"outbox.{row.id}")
    if holder is None:
        return row.status  # another sender holds the row (SKIP LOCKED)
    try:
        _, fresh = await fss.locked(session, CertificateOutbox, [row.id], lambda rows: None)
        cur = fresh.get(row.id)
        if cur is None:
            return row.status
        # work on the instance this session tracks (its changes are what ``flush`` writes)
        result = await _send_one(session, cur)
        fss.copy_into(row, cur)
        return result
    finally:
        await fss.release(f"outbox.{row.id}", holder)


async def _send_one(session: AsyncSession, row: CertificateOutbox) -> str:
    from app.modules.notifications.public import EmailAttachment, OutboundEmail, get_email_adapter

    if row.status != "pending":
        return row.status
    if row.document_id is not None:  # issued documents share this outbox (learning_0006)
        from app.modules.learning.documents import send_document_row

        return await send_document_row(session, row)
    cert = await fss.get(session, Certificate, row.certificate_id)
    if cert is None or cert.revoked_at is not None:
        row.status = next_status(row.status, "cancel")
        row.cancelled_at = utcnow()
        row.last_error = "certificate revoked"
        await fss.flush(session)
        return row.status
    to = await _recipient(session, row.user_id) if row.user_id else None
    if to is None:
        row.status = next_status(row.status, "fail")
        row.last_error = "no deliverable email address"
        await fss.flush(session)
        return row.status
    try:
        data = await pdf_for_email(session, cert)
        art = await art_for(session, cert)
        subject, text = email_content(
            name=cert.name_on_certificate,
            course_title=art.course_title,
            public_code=cert.public_code,
            url=art.verify_url,
        )
        mid = await get_email_adapter().send(
            OutboundEmail(
                to=to,
                subject=subject,
                text=text,
                category="learning",
                template_key=EMAIL_TEMPLATE_KEY,
                attachments=(EmailAttachment(f"{cert.public_code}.pdf", "application/pdf", data),),
            )
        )
    except Exception as e:  # provider/storage failure: retry up to MAX_SEND_ATTEMPTS
        row.attempts += 1
        row.last_error = f"{type(e).__name__}"[:500]
        if row.attempts >= MAX_SEND_ATTEMPTS:
            row.status = next_status(row.status, "fail")
        await fss.flush(session)
        log.warning(
            "certificate_email_failed", outbox_id=str(row.id), attempts=row.attempts, error=type(e).__name__
        )
        return row.status
    row.status = next_status(row.status, "sent")
    row.sent_at = utcnow()
    row.attempts += 1
    row.last_error = None
    row.provider_message_id = str(mid or "")[:200] or None
    await fss.flush(session)
    await _notify_in_app(session, cert, art.course_title)
    return row.status


def savepoint(session: AsyncSession) -> Any:
    """``session.begin_nested()`` on a SQL session; no savepoint on the no-Postgres placeholder
    (``NO_POSTGRES``/``None``, the Firebase stack's request session), where ``begin_nested`` raised
    ``PostgresDisabledError``: LRN-33 answered 500 and the in-app certificate notice was silently
    dropped. Firestore writes here are their own transactions (nothing partial to roll back), as
    in ``core_store.idempotent_firestore`` (R10)."""
    from app.core.db import no_sql_session

    return contextlib.nullcontext() if no_sql_session(session) else session.begin_nested()


async def _notify_in_app(session: AsyncSession, cert: Certificate, course_title: str) -> None:
    from app.modules.notifications.public import notify

    try:
        async with savepoint(session):
            await notify(
                session,
                cert.user_id,
                EMAIL_TEMPLATE_KEY,
                category="learning",
                data={
                    "certificate_id": str(cert.id),
                    "public_code": cert.public_code,
                    "course_title": course_title,
                },
                channels=("in_app",),
                dedupe_key=f"certificate:{cert.id}",
            )
    except Exception as e:  # the email went out; the inbox row is a nicety
        log.warning("certificate_inapp_notify_failed", certificate_id=str(cert.id), error=type(e).__name__)


async def send_pending(session: AsyncSession, *, limit: int = 50) -> dict[str, int]:
    """Send up to ``limit`` pending rows (oldest first; rows locked by another sender are skipped)."""
    if fss.fs():
        # FOR UPDATE SKIP LOCKED -> one sender at a time (a lease); a concurrent sweep sends nothing.
        holder = str(uuid7())
        if not await fs_cert.claim_sender(holder):
            return {"sent": 0, "failed": 0, "cancelled": 0, "retry": 0}
        try:
            return await _send_rows(session, await fs_cert.pending_rows(session, limit))
        finally:
            await fs_cert.release_sender(holder)
    rows = list(
        (
            await session.execute(
                select(CertificateOutbox)
                .where(CertificateOutbox.status == "pending")
                .order_by(CertificateOutbox.created_at, CertificateOutbox.id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars()
    )
    return await _send_rows(session, rows)


async def _send_rows(session: AsyncSession, rows: list[CertificateOutbox]) -> dict[str, int]:
    out = {"sent": 0, "failed": 0, "cancelled": 0, "retry": 0}
    for row in rows:
        st = await send_one(session, row)
        out[st if st in out else "retry"] += 1
    return out


async def approve(
    session: AsyncSession, actor: Principal | AuditActor, ids: list[uuid.UUID], *, send_now: bool = True
) -> dict[str, Any]:
    """``awaiting|failed -> pending`` for each id (rows in other states are reported, not changed),
    then send up to ``INLINE_SEND_CAP`` of them at once."""
    if fss.fs():
        return await _approve_fs(session, actor, ids, send_now=send_now)
    rows = list(
        (
            await session.execute(
                select(CertificateOutbox)
                .where(CertificateOutbox.id.in_(ids))
                .order_by(CertificateOutbox.created_at, CertificateOutbox.id)
                .with_for_update()
            )
        ).scalars()
    )
    found = {r.id for r in rows}
    approved: list[CertificateOutbox] = []
    skipped = [{"id": str(i), "reason": "not_found"} for i in ids if i not in found]
    now = utcnow()
    for r in rows:
        if r.status not in OUTBOX_TRANSITIONS["approve"][0]:
            skipped.append({"id": str(r.id), "reason": r.status})
            continue
        r.status = next_status(r.status, "approve")
        r.attempts = 0
        r.last_error = None
        r.approved_by = getattr(actor, "user_id", None)
        r.approved_at = now
        approved.append(r)
    await fss.flush(session)
    for r in approved:
        await audit(
            session,
            actor,
            "certificate.email_approve",
            "certificate_outbox",
            r.id,
            organization_id=r.organization_id,
            subject_user_id=r.user_id,
            after={"certificate_id": r.certificate_id, "status": r.status},
        )
    results: dict[str, int] = {"sent": 0, "failed": 0, "cancelled": 0, "pending": 0}
    for i, r in enumerate(approved):
        if send_now and i < INLINE_SEND_CAP:
            st = await send_one(session, r)
        else:
            st = r.status
        results[st] = results.get(st, 0) + 1
    return {"approved": len(approved), "skipped": skipped, **results}


async def _approve_fs(
    session: AsyncSession, actor: Principal | AuditActor, ids: list[uuid.UUID], *, send_now: bool
) -> dict[str, Any]:
    """Firestore ``approve``: the state change is one transaction over the rows (the Postgres
    ``SELECT ... FOR UPDATE``), re-run on contention, so a concurrent cancel/approve/send cannot
    be overwritten; sending happens after the commit."""
    now = utcnow()
    by = getattr(actor, "user_id", None)

    def step(rows: dict[uuid.UUID, CertificateOutbox]) -> tuple[list[uuid.UUID], list[dict[str, str]]]:
        ok: list[uuid.UUID] = []
        skipped = [{"id": str(i), "reason": "not_found"} for i in ids if i not in rows]
        for r in sorted(rows.values(), key=lambda x: (x.created_at, str(x.id))):
            if r.status not in OUTBOX_TRANSITIONS["approve"][0]:
                skipped.append({"id": str(r.id), "reason": r.status})
                continue
            r.status = next_status(r.status, "approve")
            r.attempts = 0
            r.last_error = None
            r.approved_by = by
            r.approved_at = now
            ok.append(r.id)
        return ok, skipped

    # a row being sent holds its send lease (the Postgres row lock): wait for it, then decide
    leases = [f"outbox.{i}" for i in ids]
    (ok, skipped), rows = await fss.locked(session, CertificateOutbox, ids, step, respect_leases=leases)
    approved = [rows[i] for i in ok]
    for r in approved:
        await audit(
            session,
            actor,
            "certificate.email_approve",
            "certificate_outbox",
            r.id,
            organization_id=r.organization_id,
            subject_user_id=r.user_id,
            after={"certificate_id": r.certificate_id, "status": r.status},
        )
    results: dict[str, int] = {"sent": 0, "failed": 0, "cancelled": 0, "pending": 0}
    for i, r in enumerate(approved):
        st = await send_one(session, r) if send_now and i < INLINE_SEND_CAP else r.status
        results[st] = results.get(st, 0) + 1
    return {"approved": len(approved), "skipped": skipped, **results}


async def _cancel_fs(
    session: AsyncSession, actor: Principal | AuditActor, ids: list[uuid.UUID]
) -> dict[str, Any]:
    """Firestore ``cancel``: one transaction over the rows (``SELECT ... FOR UPDATE``)."""
    now = utcnow()
    by = getattr(actor, "user_id", None)

    def step(rows: dict[uuid.UUID, CertificateOutbox]) -> tuple[list[uuid.UUID], list[dict[str, str]]]:
        done: list[uuid.UUID] = []
        skipped = [{"id": str(i), "reason": "not_found"} for i in ids if i not in rows]
        for i in ids:
            r = rows.get(i)
            if r is None:
                continue
            if r.status not in OUTBOX_TRANSITIONS["cancel"][0]:
                skipped.append({"id": str(r.id), "reason": r.status})
                continue
            r.status = next_status(r.status, "cancel")
            r.cancelled_by = by
            r.cancelled_at = now
            done.append(r.id)
        return done, skipped

    # wait for an in-flight send (its lease = the Postgres row lock); a row that ends "sent" is
    # then skipped with reason "sent", exactly as on Postgres
    leases = [f"outbox.{i}" for i in ids]
    (done, skipped), rows = await fss.locked(session, CertificateOutbox, ids, step, respect_leases=leases)
    for i in done:
        r = rows[i]
        await audit(
            session,
            actor,
            "certificate.email_cancel",
            "certificate_outbox",
            r.id,
            organization_id=r.organization_id,
            subject_user_id=r.user_id,
        )
    return {"cancelled": len(done), "skipped": skipped}


async def cancel(
    session: AsyncSession, actor: Principal | AuditActor, ids: list[uuid.UUID]
) -> dict[str, Any]:
    if fss.fs():
        return await _cancel_fs(session, actor, ids)
    rows = list(
        (
            await session.execute(
                select(CertificateOutbox).where(CertificateOutbox.id.in_(ids)).with_for_update()
            )
        ).scalars()
    )
    found = {r.id for r in rows}
    skipped = [{"id": str(i), "reason": "not_found"} for i in ids if i not in found]
    n = 0
    now = utcnow()
    for r in rows:
        if r.status not in OUTBOX_TRANSITIONS["cancel"][0]:
            skipped.append({"id": str(r.id), "reason": r.status})
            continue
        r.status = next_status(r.status, "cancel")
        r.cancelled_by = getattr(actor, "user_id", None)
        r.cancelled_at = now
        n += 1
        await audit(
            session,
            actor,
            "certificate.email_cancel",
            "certificate_outbox",
            r.id,
            organization_id=r.organization_id,
            subject_user_id=r.user_id,
        )
    await fss.flush(session)
    return {"cancelled": n, "skipped": skipped}


# --------------------------------------------------------------------------- relay handler


async def on_certificate_issued(session: AsyncSession, certificate_id: uuid.UUID, issue_source: str) -> None:
    """Outbox consumer body: PDF + queued email (both idempotent)."""
    cert = await fss.get(session, Certificate, certificate_id)
    if cert is None or cert.revoked_at is not None:
        return
    try:
        await ensure_pdf(session, cert)
    except Exception as e:  # storage down: the email path re-renders and stores; backfill too
        log.warning("certificate_pdf_failed", certificate_id=str(cert.id), error=type(e).__name__)
    await queue_email(session, cert, origin="manual" if issue_source == "manual" else "rule")


# --------------------------------------------------------------------------- due list


async def due_enrolments(
    session: AsyncSession,
    *,
    course_id: uuid.UUID | None = None,
    batch_ended_only: bool = False,
    today: date | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Enrolments without a certificate that are completed, or whose batch has ended
    (``ends_on`` before ``today`` IST). Each row carries the course rule's verdict
    (``eligible`` + ``reason``) so the UI can say why a row cannot be issued yet."""
    today = today or ist_date(utcnow())
    # both stores: learning's tables are read by fs_cert.due_rows (SQL on Postgres), batches and
    # users come from orgs.public / identity.public (no join into their tables)
    rows: Any = await fs_cert.due_rows(
        session, course_id=course_id, batch_ended_only=batch_ended_only, today=today, limit=limit
    )
    return await _due_out(session, rows)


async def _due_out(session: AsyncSession, rows: Any) -> list[dict[str, Any]]:
    titles = await course_titles(session, {r[0].course_version_id for r in rows})
    out = []
    for enr, bname, ends_on, email, full_name in rows:
        el = await svc.certificate_eligibility(session, enr)
        # orgs_0005 attendance gate (additive hook, orgs-owned rule): only when the batch plan
        # sets ``min_attendance_percent`` (default off); see orgs.public.attendance_certificate_block.
        if el["eligible"] and enr.batch_id is not None:
            from app.modules.orgs.public import attendance_certificate_block

            blocked = await attendance_certificate_block(session, enr.batch_id, enr.user_id)
            if blocked:
                el = {**el, "eligible": False, "reason": blocked}
        out.append(
            {
                "enrolment_id": str(enr.id),
                "user_id": str(enr.user_id),
                "name": (full_name or "").strip() or None,
                "email": email,
                "course_id": str(enr.course_id),
                "course_title": titles.get(enr.course_version_id),
                "batch_id": str(enr.batch_id) if enr.batch_id else None,
                "batch_name": bname,
                "batch_ends_on": ends_on.isoformat() if ends_on else None,
                "enrolment_status": enr.status,
                "progress_pct": float(enr.progress_pct),
                "completed_at": enr.completed_at.isoformat() if enr.completed_at else None,
                "due_because": "completed" if enr.status == "completed" else "batch_ended",
                "eligible": bool(el["eligible"]),
                "reason": el.get("reason"),
            }
        )
    out.sort(key=lambda r: (not r["eligible"], r["course_title"] or "", r["name"] or ""))
    return out


async def issue_due(
    session: AsyncSession,
    actor: Principal | AuditActor,
    *,
    enrolment_ids: list[uuid.UUID] | None = None,
    course_id: uuid.UUID | None = None,
    batch_ended_only: bool = False,
    origin: str = "batch_end",
    limit: int = 500,
) -> dict[str, Any]:
    """Issue certificates for due enrolments whose course rule is met (``issue_source='rule'``)
    and queue their emails. Rows that are not eligible are skipped with their reason."""
    rows = await due_enrolments(session, course_id=course_id, batch_ended_only=batch_ended_only, limit=limit)
    if enrolment_ids is not None:
        want = {str(i) for i in enrolment_ids}
        rows = [r for r in rows if r["enrolment_id"] in want]
    issued: list[str] = []
    skipped: list[dict[str, Any]] = []
    for r in rows:
        if not r["eligible"]:
            skipped.append({"enrolment_id": r["enrolment_id"], "reason": r["reason"]})
            continue
        enr = await fss.get(session, Enrolment, uuid.UUID(r["enrolment_id"]))
        if enr is None:
            continue
        try:
            async with savepoint(session):
                cert = await svc.maybe_issue_certificate(session, enr)
        except ProblemError as e:  # concurrent issue of the same enrolment
            skipped.append({"enrolment_id": r["enrolment_id"], "reason": e.code})
            continue
        if cert is None:
            skipped.append({"enrolment_id": r["enrolment_id"], "reason": "not_eligible"})
            continue
        await queue_email(session, cert, origin=origin)
        await audit(
            session,
            actor,
            "certificate.issue_due",
            "certificate",
            cert.id,
            organization_id=cert.organization_id,
            subject_user_id=cert.user_id,
            after={"public_code": cert.public_code, "enrolment_id": enr.id, "origin": origin},
        )
        issued.append(str(cert.id))
    return {"issued": len(issued), "certificate_ids": issued, "skipped": skipped}


# --------------------------------------------------------------------------- register


async def outbox_counts(session: AsyncSession) -> dict[str, int]:
    if fss.fs():
        return await fs_cert.outbox_counts(OUTBOX_STATUSES)
    rows = (
        await session.execute(
            select(CertificateOutbox.status, func.count()).group_by(CertificateOutbox.status)
        )
    ).all()
    out = dict.fromkeys(OUTBOX_STATUSES, 0)
    out.update({s: int(n) for s, n in rows})
    return out
