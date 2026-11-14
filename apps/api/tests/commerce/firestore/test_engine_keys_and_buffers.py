"""Engine fixes: composite primary keys match on ALL columns (get / update / delete), and the
request's buffered audit rows and outbox events commit in the same Firestore transaction as the
unit of work (none on a failed commit, all on a successful one)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import select

from app.core.ids import uuid7
from app.modules.commerce import datastore as ds
from app.modules.commerce.models import InvoiceSequence, Product
from tests.commerce.firestore.conftest import FakeSession


async def test_composite_key_get_update_delete(fs: Any, session: Any) -> None:
    ds.add(session, InvoiceSequence(series="TD", fiscal_year="2026-27", next_value=5))
    ds.add(session, InvoiceSequence(series="TD", fiscal_year="2027-28", next_value=9))
    ds.add(session, InvoiceSequence(series="TDCN", fiscal_year="2026-27", next_value=2))
    await session.commit()
    s = FakeSession().as_platform()
    a = await ds.get(s, InvoiceSequence, ("TD", "2027-28"))
    b = await ds.get(s, InvoiceSequence, {"series": "TDCN", "fiscal_year": "2026-27"})
    assert (a.next_value, b.next_value) == (9, 2)  # not the first row with series TD
    assert await ds.get(s, InvoiceSequence, ("TD", "2099-00")) is None
    with pytest.raises(ValueError):
        await ds.get(s, InvoiceSequence, "TD")  # a composite key needs every column
    a.next_value = 10  # update through the identity map: no duplicate row, no 409
    await s.commit()
    s2 = FakeSession().as_platform()
    from app.core.firestore.sqlstore import pk_conditions

    rows = (
        (await ds.execute(s2, select(InvoiceSequence).where(InvoiceSequence.series == "TD"))).scalars().all()
    )
    assert sorted((r.fiscal_year, r.next_value) for r in rows) == [("2026-27", 5), ("2027-28", 10)]
    victim = await ds.get(s2, InvoiceSequence, ("TD", "2026-27"))
    from app.modules.commerce.store_specs import STORE

    STORE.uow(s2).delete(victim, await STORE.scope(s2))
    await s2.commit()
    left = (await ds.execute(FakeSession().as_platform(), select(InvoiceSequence))).scalars().all()
    assert sorted((r.series, r.fiscal_year) for r in left) == [("TD", "2027-28"), ("TDCN", "2026-27")]
    assert len(pk_conditions(InvoiceSequence, ("TD", "x"))) == 2


async def _exists(client: Any, coll: str, doc_id: Any) -> bool:
    snap = await client.collection(f"lms_{coll}").document(str(doc_id)).get()
    return bool(snap.exists)


@pytest.fixture
def audit_on_firestore(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.firestore.backend import reset_store_backends

    monkeypatch.setenv("TD_STORE_AUDIT", "firestore")
    reset_store_backends()


async def _buffer_one_of_each() -> tuple[uuid.UUID, uuid.UUID]:
    from app.core.audit import AuditActor, audit
    from app.core.db import NO_POSTGRES
    from app.core.outbox import emit_event

    aid = await audit(NO_POSTGRES, AuditActor.system("test.engine"), "commerce.test_done", "product", None)
    eid = await emit_event(
        NO_POSTGRES, "commerce.test_done", {"k": [1, 2]}, aggregate_type="product", aggregate_id=uuid7()
    )
    return aid, eid


async def test_buffered_audit_and_event_commit_with_the_rows(
    fs: Any, session: Any, audit_on_firestore: Any
) -> None:
    from app.core import request_commit
    from app.core.firestore.core_store import OUTBOX as EVENTS
    from app.modules.audit.store_specs import OUTBOX as AUDIT

    async with request_commit.buffer_open():
        s = FakeSession().as_platform()
        ds.add(
            s,
            Product(
                id=uuid7(),
                sku=f"BUF-{uuid.uuid4().hex[:6]}",
                name="Buffered",
                product_kind="course",
                refund_policy_key="standard",
            ),
        )
        aid, eid = await _buffer_one_of_each()
        await s.commit()  # the engine's commit point takes the buffers into its transaction
        assert not request_commit.has_pending()
        assert await _exists(fs, AUDIT, aid) and await _exists(fs, EVENTS, eid)
        doc = (await fs.collection(f"lms_{EVENTS}").document(str(eid)).get()).to_dict()
        assert doc["payload_json"] == '{"k":[1,2]}'  # JSON text, core's event_doc layout


async def test_failed_commit_writes_no_audit_and_no_event(
    fs: Any, session: Any, audit_on_firestore: Any
) -> None:
    from app.core import request_commit
    from app.core.errors import ProblemError
    from app.core.firestore.core_store import OUTBOX as EVENTS
    from app.modules.audit.store_specs import OUTBOX as AUDIT

    sku = f"DUP-{uuid.uuid4().hex[:6]}"
    ds.add(
        session,
        Product(id=uuid7(), sku=sku, name="First", product_kind="course", refund_policy_key="standard"),
    )
    await session.commit()
    ids: tuple[uuid.UUID, uuid.UUID] | None = None
    with pytest.raises(ProblemError):
        async with request_commit.buffer_open():
            s = FakeSession().as_platform()
            ds.add(
                s,
                Product(
                    id=uuid7(),
                    sku=sku.lower(),
                    name="Dup",
                    product_kind="course",
                    refund_policy_key="standard",
                ),
            )
            ids = await _buffer_one_of_each()
            await s.commit()  # unique violation (citext sku): nothing of the transaction is written
    assert ids is not None
    assert not await _exists(fs, AUDIT, ids[0]) and not await _exists(fs, EVENTS, ids[1])
