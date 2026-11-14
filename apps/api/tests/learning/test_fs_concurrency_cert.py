"""Row-lock parity on Firestore (certificates): Postgres ``FOR UPDATE`` sites must not lose
updates. Emulator only; each case runs the operation concurrently and checks exactly one winner.

Classes covered here: locked state transition (outbox approve/cancel, certificate revoke, bulk
revoke skipping rows revoked meanwhile) and lease-held work (``send_one``: one delivery)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from tests.learning.fs_harness import firestore_emulator, fs  # noqa: F401
from tests.learning.test_fs_cert import _cert, _s, _save, fs_on  # noqa: F401


async def _outbox(cert: Any, status: str = "awaiting") -> Any:
    from app.modules.learning.cert_models import CertificateOutbox

    row = CertificateOutbox(
        id=uuid.uuid4(), certificate_id=cert.id, user_id=cert.user_id, status=status, origin="rule"
    )
    await _save(row)
    return row


async def test_concurrent_cancels_one_winner(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.core.audit import AuditActor
    from app.modules.learning import certificates as certs

    c = _cert()
    await _save(c)
    row = await _outbox(c)
    actor = AuditActor.system("tests.concurrency")
    out = await asyncio.gather(*(certs.cancel(_s(), actor, [row.id]) for _ in range(4)))
    assert sum(o["cancelled"] for o in out) == 1
    assert sorted(s["reason"] for o in out for s in o["skipped"]) == ["cancelled"] * 3


async def test_concurrent_approve_and_cancel_serialise(fs: Any, fs_on: Any) -> None:  # noqa: F811
    from app.core.audit import AuditActor
    from app.modules.learning import certificates as certs
    from app.modules.learning import fs_store as fss
    from app.modules.learning.cert_models import CertificateOutbox

    c = _cert()
    await _save(c)
    row = await _outbox(c)
    actor = AuditActor.system("tests.concurrency")
    approved, cancelled = await asyncio.gather(
        certs.approve(_s(), actor, [row.id], send_now=False), certs.cancel(_s(), actor, [row.id])
    )
    final = await fss.get(_s(), CertificateOutbox, row.id)
    assert final is not None
    # cancel accepts awaiting and pending: whatever the order, cancel wins and is reported once
    assert final.status == "cancelled" and cancelled["cancelled"] == 1
    if approved["approved"] == 1:
        assert final.approved_at is not None  # approve ran first and was not overwritten
    else:
        assert approved["skipped"] == [{"id": str(row.id), "reason": "cancelled"}]


async def test_concurrent_revokes_one_winner(fs: Any, fs_on: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.core.audit import AuditActor
    from app.core.errors import ProblemError
    from app.modules.learning import fs_store as fss
    from app.modules.learning import service as svc
    from app.modules.learning.models import Certificate

    async def quiet(*a: Any, **k: Any) -> None:
        return None

    monkeypatch.setattr(svc, "audit", quiet)
    monkeypatch.setattr(svc, "emit_event", quiet)
    c = _cert()
    await _save(c)
    actor = AuditActor.system("tests.concurrency")

    async def revoke(reason: str) -> str:
        cert = await fss.get(_s(), Certificate, c.id)
        try:
            await svc.revoke_certificate(_s(), actor, cert, reason)
            return reason
        except ProblemError as e:
            return e.code

    out = await asyncio.gather(*(revoke(f"r{i}") for i in range(3)))
    winners = [o for o in out if o.startswith("r")]
    assert len(winners) == 1 and out.count("invalid_state_transition") == 2
    stored = await fss.get(_s(), Certificate, c.id)
    assert stored is not None and stored.revoke_reason == winners[0]  # the winner's reason is kept

    # bulk revoke: two refunds racing on the same courses revoke each certificate once
    c2, c3 = _cert(user_id=c.user_id), _cert(user_id=c.user_id)
    await _save(c2, c3)
    a, b = await asyncio.gather(
        svc.revoke_certificates_for_courses(_s(), actor, c.user_id, [c2.course_id, c3.course_id]),
        svc.revoke_certificates_for_courses(_s(), actor, c.user_id, [c2.course_id, c3.course_id]),
    )
    assert sorted(a + b) == sorted([c2.id, c3.id])


async def test_send_one_lease_delivers_once(fs: Any, fs_on: Any, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from app.modules.learning import certificates as certs
    from app.modules.learning import fs_store as fss
    from app.modules.learning.cert_models import CertificateOutbox

    c = _cert()
    await _save(c)
    row = await _outbox(c, status="pending")
    sent: list[uuid.UUID] = []

    async def deliver(session: Any, r: Any) -> str:
        await asyncio.sleep(0.2)  # the provider call: the row is "locked" meanwhile
        sent.append(r.id)
        r.status = "sent"
        await fss.flush(session)
        return "sent"

    monkeypatch.setattr(certs, "_send_one", deliver)

    async def one() -> str:
        r = await fss.get(_s(), CertificateOutbox, row.id)
        return await certs.send_one(_s(), r)

    out = await asyncio.gather(*(one() for _ in range(4)))
    assert sent == [row.id]  # one delivery
    assert out.count("sent") == 1 and out.count("pending") == 3  # the others skipped the locked row
    again = await certs.send_one(_s(), await fss.get(_s(), CertificateOutbox, row.id))
    assert again == "sent" and sent == [row.id]  # after the lease: re-read status, nothing re-sent


async def test_cancel_waits_for_in_flight_send_like_postgres(
    fs: Any,  # noqa: F811
    fs_on: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Postgres: the cancel waits on the row lock the sender holds, then sees "sent" and skips the
    row (``reason: "sent"``). Firestore: the cancel waits for the send lease, then the same."""
    from app.core.audit import AuditActor
    from app.modules.learning import certificates as certs
    from app.modules.learning import fs_store as fss
    from app.modules.learning.cert_models import CertificateOutbox

    c = _cert()
    await _save(c)
    row = await _outbox(c, status="pending")
    sending = asyncio.Event()

    async def deliver(session: Any, r: Any) -> str:
        sending.set()
        await asyncio.sleep(0.5)  # the provider call, lease held
        r.status = "sent"
        await fss.flush(session)
        return "sent"

    monkeypatch.setattr(certs, "_send_one", deliver)
    actor = AuditActor.system("tests.concurrency")

    async def send() -> str:
        return await certs.send_one(_s(), await fss.get(_s(), CertificateOutbox, row.id))

    async def cancel_mid_send() -> dict[str, Any]:
        await sending.wait()
        return await certs.cancel(_s(), actor, [row.id])

    sent, cancelled = await asyncio.gather(send(), cancel_mid_send())
    assert sent == "sent"
    assert cancelled == {"cancelled": 0, "skipped": [{"id": str(row.id), "reason": "sent"}]}
    final = await fss.get(_s(), CertificateOutbox, row.id)
    assert final is not None and final.status == "sent" and final.cancelled_at is None

    # and approve also waits, then reports the final state
    c2 = _cert()
    await _save(c2)
    row2 = await _outbox(c2, status="pending")
    sending.clear()

    async def send2() -> str:
        return await certs.send_one(_s(), await fss.get(_s(), CertificateOutbox, row2.id))

    async def approve_mid_send() -> dict[str, Any]:
        await sending.wait()
        return await certs.approve(_s(), actor, [row2.id], send_now=False)

    _, approved = await asyncio.gather(send2(), approve_mid_send())
    assert approved["approved"] == 0 and approved["skipped"] == [{"id": str(row2.id), "reason": "sent"}]


async def test_cancel_before_send_wins_and_nothing_is_sent(
    fs: Any,  # noqa: F811
    fs_on: Any,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other order: a cancel committed first means the sender re-reads "cancelled" and sends
    nothing (no row ends "sent" after a successful cancel)."""
    from app.core.audit import AuditActor
    from app.modules.learning import certificates as certs
    from app.modules.learning import fs_store as fss
    from app.modules.learning.cert_models import CertificateOutbox

    c = _cert()
    await _save(c)
    row = await _outbox(c, status="pending")
    sent: list[Any] = []

    async def deliver(session: Any, r: Any) -> str:  # the real _send_one starts with this check
        if r.status != "pending":
            return str(r.status)
        sent.append(r.id)
        r.status = "sent"
        await fss.flush(session)
        return "sent"

    monkeypatch.setattr(certs, "_send_one", deliver)
    stale = await fss.get(_s(), CertificateOutbox, row.id)  # the sender's earlier read: "pending"
    out = await certs.cancel(_s(), AuditActor.system("tests.concurrency"), [row.id])
    assert out["cancelled"] == 1
    assert await certs.send_one(_s(), stale) == "cancelled" and sent == []
    # race many of each: never a row reported cancelled that ends sent
    for _ in range(3):
        c3 = _cert()
        await _save(c3)
        r3 = await _outbox(c3, status="pending")
        results = await asyncio.gather(
            certs.send_one(_s(), await fss.get(_s(), CertificateOutbox, r3.id)),
            certs.cancel(_s(), AuditActor.system("tests.concurrency"), [r3.id]),
        )
        final = await fss.get(_s(), CertificateOutbox, r3.id)
        assert final is not None
        if results[1]["cancelled"] == 1:
            assert final.status == "cancelled"
        else:
            assert final.status == "sent" and results[1]["skipped"][0]["reason"] == "sent"
