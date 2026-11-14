"""Certificate automation on Firestore (``TD_STORE_LEARNING=firestore``), emulator only.

Postgres-only collaborators (audit, e-mail flag, users, batches, catalog titles, eligibility rule)
are monkeypatched; the outbox state machine, idempotent queueing, the sender lease, the due list,
the admin register / queue joins and the PDF backfill run against the emulator."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from tests.learning.fs_harness import firestore_emulator, fs  # noqa: F401

T0 = datetime(2026, 11, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def fs_on(monkeypatch: pytest.MonkeyPatch) -> Any:
    from app.core.firestore.backend import reset_store_backends
    from app.modules.learning import certificates as certs

    monkeypatch.setenv("TD_STORE_LEARNING", "firestore")
    reset_store_backends()

    async def no_audit(*a: Any, **k: Any) -> None:
        return None

    async def auto_send(session: Any) -> bool:
        return False

    monkeypatch.setattr(certs, "audit", no_audit)
    monkeypatch.setattr(certs, "auto_send_enabled", auto_send)
    yield
    monkeypatch.delenv("TD_STORE_LEARNING", raising=False)
    reset_store_backends()


def _s() -> Any:
    from sqlalchemy.ext.asyncio import AsyncSession

    return AsyncSession()


def _cert(**over: Any) -> Any:
    from app.modules.learning.models import Certificate

    base = dict(
        id=uuid.uuid4(), public_code=uuid.uuid4().hex[:12].upper(), user_id=uuid.uuid4(), organization_id=None,
        course_id=uuid.uuid4(), course_version_id=uuid.uuid4(), enrolment_id=uuid.uuid4(),
        name_on_certificate="Asha Rao", template_version="v1", content_hash=b"\x00", issued_at=T0,
    )  # fmt: skip
    base.update(over)
    return Certificate(**base)


async def _save(*objs: Any) -> None:
    from app.modules.learning import fs_store as fss

    s = _s()
    for o in objs:
        fss.add(s, o)
    await fss.flush(s)


async def test_queue_approve_cancel_counts(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.modules.learning import certificates as certs

    c1, c2 = _cert(), _cert()
    await _save(c1, c2)
    s = _s()
    row = await certs.queue_email(s, c1, origin="rule")
    assert row is not None and row.status == "awaiting" and row.attempts == 0
    assert await certs.queue_email(_s(), c1, origin="rule") is None  # one row per certificate
    row2 = await certs.queue_email(_s(), c2, origin="manual")
    assert row2 is not None
    assert await certs.outbox_counts(_s()) == {
        "awaiting": 2,
        "pending": 0,
        "sent": 0,
        "failed": 0,
        "cancelled": 0,
    }

    actor = SimpleNamespace(user_id=uuid.uuid4())
    missing = uuid.uuid4()
    out = await certs.approve(_s(), actor, [row.id, missing], send_now=False)
    assert out["approved"] == 1 and out["pending"] == 1
    assert out["skipped"] == [{"id": str(missing), "reason": "not_found"}]
    again = await certs.approve(_s(), actor, [row.id], send_now=False)
    assert again["approved"] == 0 and again["skipped"] == [{"id": str(row.id), "reason": "pending"}]

    res = await certs.cancel(_s(), actor, [row.id, row2.id])
    assert res == {"cancelled": 2, "skipped": []}
    res = await certs.cancel(_s(), actor, [row.id])
    assert res == {"cancelled": 0, "skipped": [{"id": str(row.id), "reason": "cancelled"}]}
    counts = await certs.outbox_counts(_s())
    assert counts["cancelled"] == 2 and counts["awaiting"] == 0


async def test_send_paths_and_sender_lease(fs: Any, fs_on: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.modules.learning import certificates as certs
    from app.modules.learning import fs_cert
    from app.modules.learning import fs_store as fss
    from app.modules.learning.cert_models import CertificateOutbox
    from app.modules.learning.models import Certificate

    async def nobody(session: Any, user_id: Any) -> None:
        return None

    monkeypatch.setattr(certs, "_recipient", nobody)
    live, gone = _cert(), _cert(revoked_at=T0)
    await _save(live, gone)
    actor = SimpleNamespace(user_id=uuid.uuid4())
    r_live = await certs.queue_email(_s(), live, origin="rule")
    assert r_live is not None
    # a revoked certificate gets no email at all
    assert await certs.queue_email(_s(), gone, origin="rule") is None
    await certs.approve(_s(), actor, [r_live.id], send_now=False)

    # another sender holds the lease: this sweep sends nothing
    assert await fs_cert.claim_sender("other")
    assert await certs.send_pending(_s()) == {"sent": 0, "failed": 0, "cancelled": 0, "retry": 0}
    await fs_cert.release_sender("other")

    out = await certs.send_pending(_s())
    assert out == {"sent": 0, "failed": 1, "cancelled": 0, "retry": 0}  # no deliverable address
    s = _s()
    row = await fss.get(s, CertificateOutbox, r_live.id)
    assert row is not None and row.status == "failed" and row.last_error == "no deliverable email address"

    # revoked after queueing: the pending row is cancelled at send time
    s2 = _s()
    c = await fss.get(s2, Certificate, live.id)
    assert c is not None
    await certs.approve(_s(), actor, [r_live.id], send_now=False)
    c.revoked_at = T0
    await fss.flush(s2)
    assert await certs.send_pending(_s()) == {"sent": 0, "failed": 0, "cancelled": 1, "retry": 0}


async def test_backfill_pdfs_stores_missing(fs: Any, fs_on: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.modules.learning import certificates as certs
    from app.modules.learning import fs_store as fss
    from app.modules.learning.models import Certificate

    stored: list[str] = []

    class Store:
        async def put(self, bucket: str, key: str, data: bytes, ctype: str) -> None:
            stored.append(key)

    async def render(session: Any, cert: Any) -> bytes:
        return b"%PDF-1.7 fake"

    monkeypatch.setattr(certs, "_store", lambda: Store())
    monkeypatch.setattr(certs, "_bucket", lambda: "b")
    monkeypatch.setattr(certs, "render_pdf", render)
    old = _cert(issued_at=T0)
    new = _cert(issued_at=T0 + timedelta(days=1))
    done = _cert(pdf_s3_key="k")
    revoked = _cert(revoked_at=T0)
    await _save(old, new, done, revoked)
    assert await certs.backfill_pdfs(_s(), limit=1) == 1
    assert stored == [certs.pdf_key(old)]  # oldest first
    got = await fss.get(_s(), Certificate, old.id)
    assert got is not None and got.pdf_s3_key == certs.pdf_key(old) and len(got.content_hash) == 32
    assert await certs.backfill_pdfs(_s()) == 1  # only ``new`` remains


async def test_due_enrolments(fs: Any, fs_on: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.modules.identity import public as identity
    from app.modules.learning import certificates as certs
    from app.modules.learning import service as svc
    from app.modules.learning.models import Enrolment
    from app.modules.orgs import public as orgs

    course = uuid.uuid4()
    ended, running = uuid.uuid4(), uuid.uuid4()
    batches = {
        ended: SimpleNamespace(name="B-ended", ends_on=date(2026, 10, 1)),
        running: SimpleNamespace(name="B-run", ends_on=date(2027, 1, 1)),
    }

    async def get_batches(session: Any, ids: Any) -> dict[Any, Any]:
        return {i: batches[i] for i in ids if i in batches}

    async def get_users(session: Any, ids: Any) -> dict[Any, Any]:
        return {i: SimpleNamespace(email=f"{i}@x.in") for i in ids}

    async def get_profiles(session: Any, ids: Any) -> dict[Any, Any]:
        return {i: SimpleNamespace(full_name="Learner") for i in ids}

    async def titles(session: Any, ids: Any) -> dict[Any, str]:
        return dict.fromkeys(ids, "Course")

    async def eligible(session: Any, enr: Any) -> dict[str, Any]:
        return {
            "eligible": enr.status == "completed",
            "reason": None if enr.status == "completed" else "rule",
        }

    monkeypatch.setattr(orgs, "get_batches", get_batches)
    monkeypatch.setattr(identity, "get_users", get_users)
    monkeypatch.setattr(identity, "get_profiles", get_profiles)
    monkeypatch.setattr(certs, "course_titles", titles)
    monkeypatch.setattr(svc, "certificate_eligibility", eligible)

    def enr(status: str, batch: Any = None, completed: datetime | None = None) -> Enrolment:
        return Enrolment(
            id=uuid.uuid4(), user_id=uuid.uuid4(), course_id=course, course_version_id=uuid.uuid4(),
            source="self", status=status, batch_id=batch, completed_at=completed,
        )  # fmt: skip

    done_old = enr("completed", completed=T0)
    done_new = enr("completed", completed=T0 + timedelta(days=2))
    batch_over = enr("active", batch=ended)
    batch_on = enr("active", batch=running)  # not due
    withdrawn = enr("withdrawn", completed=T0)  # not due
    certified = enr("completed", completed=T0)  # has a certificate
    await _save(done_old, done_new, batch_over, batch_on, withdrawn, certified)
    await _save(_cert(enrolment_id=certified.id, course_id=course))

    rows = await certs.due_enrolments(_s(), course_id=course, today=date(2026, 11, 12))
    assert {r["enrolment_id"] for r in rows} == {str(done_old.id), str(done_new.id), str(batch_over.id)}
    by = {r["enrolment_id"]: r for r in rows}
    assert by[str(batch_over.id)]["due_because"] == "batch_ended" and not by[str(batch_over.id)]["eligible"]
    assert (
        by[str(batch_over.id)]["batch_name"] == "B-ended"
        and by[str(batch_over.id)]["batch_ends_on"] == "2026-10-01"
    )
    only_batch = await certs.due_enrolments(
        _s(), course_id=course, batch_ended_only=True, today=date(2026, 11, 12)
    )
    assert [r["enrolment_id"] for r in only_batch] == [str(batch_over.id)]
    limited = await certs.due_enrolments(_s(), course_id=course, today=date(2026, 11, 12), limit=1)
    assert [r["enrolment_id"] for r in limited] == [str(done_new.id)]  # completed_at DESC first


async def test_admin_register_and_queue_joins(fs: Any, fs_on: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.modules.learning import certificates as certs
    from app.modules.learning import fs_cert
    from app.modules.learning.cert_models import CertificateOutbox
    from app.modules.learning.doc_models import IssuedDocument

    course, other = uuid.uuid4(), uuid.uuid4()
    a = _cert(course_id=course, name_on_certificate="Asha Rao")
    b = _cert(course_id=course, name_on_certificate="Vikram S", revoked_at=T0)
    c = _cert(course_id=other, name_on_certificate="Meera K")
    await _save(a, b, c)

    async def people(session: Any, term: str) -> set[uuid.UUID]:
        return {c.user_id} if term == "meera@x.in" else set()

    monkeypatch.setattr(fs_cert, "people_matching", people)
    s = _s()
    page = await fs_cert.certificate_page(s, course_id=course, status=None, term="", after=None, limit=10)
    assert [x.id for x in page] == sorted([a.id, b.id], reverse=True)
    assert [
        x.id
        for x in await fs_cert.certificate_page(
            s, course_id=None, status="revoked", term="", after=None, limit=10
        )
    ] == [b.id]
    assert [
        x.id
        for x in await fs_cert.certificate_page(
            s, course_id=None, status=None, term="asha", after=None, limit=10
        )
    ] == [a.id]
    assert [
        x.id
        for x in await fs_cert.certificate_page(
            s, course_id=None, status=None, term="meera@x.in", after=None, limit=10
        )
    ] == [c.id]
    top = max(a.id, b.id, c.id)
    rest = await fs_cert.certificate_page(s, course_id=None, status=None, term="", after=top, limit=10)
    assert top not in [x.id for x in rest] and len(rest) == 2

    doc = IssuedDocument(
        id=uuid.uuid4(), doc_type="offer_letter", ref_no="TD-OL-2026-ABCDEF", recipient_name="R",
        recipient_email="r@x.in", course_id=course, issue_date=date(2026, 11, 1), template_version="v1",
    )  # fmt: skip
    await _save(doc)
    ra = await certs.queue_email(_s(), a, origin="rule")
    rc = await certs.queue_email(_s(), c, origin="rule")
    rd = CertificateOutbox(
        id=uuid.uuid4(), document_id=doc.id, to_email="r@x.in", status="awaiting", origin="manual"
    )
    await _save(rd)
    assert ra is not None and rc is not None
    rows = await fs_cert.outbox_page(_s(), status=None, course_id=course, kind=None, after=None, limit=10)
    assert {o.id for o, _c, _d in rows} == {ra.id, rd.id}
    certs_only = await fs_cert.outbox_page(
        _s(), status="awaiting", course_id=None, kind="certificate", after=None, limit=10
    )
    assert {o.id for o, _c, _d in certs_only} == {ra.id, rc.id}
    one = await fs_cert.outbox_page(_s(), status=None, course_id=None, kind=None, after=None, limit=1)
    assert len(one) == 2  # limit + 1 -> the caller sees "more"
    boxes = await fs_cert.outboxes_of_certificates(_s(), [a.id, b.id])
    assert set(boxes) == {a.id}
    assert await fs_cert.document_status_counts(_s(), course) == {"valid": 1}
