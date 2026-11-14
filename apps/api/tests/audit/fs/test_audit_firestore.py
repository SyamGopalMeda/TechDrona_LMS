"""Audit on Firestore (``TD_STORE_AUDIT=firestore``): outbox -> sealed hash chain, reads, guards.

Runs on the emulator without Postgres (see ``conftest.py``)."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.audit import AuditActor
from app.core.firestore.errors import StoreAccessDeniedError
from app.core.firestore.repository import assert_repository_scoped
from app.core.firestore.store import ScopedStore, ScopedTransaction
from app.core.ids import uuid7
from app.modules.audit import repo_firestore as rf
from app.modules.audit.chain import GENESIS_HASH, verify_rows
from app.modules.audit.store_specs import LOG, OUTBOX, head_doc, log_doc, log_id

FS_MODULES = ("audit",)
pytestmark = pytest.mark.usefixtures("fs_env")


def _actor() -> AuditActor:
    return AuditActor("user", user_id=uuid7(), session_id=uuid7(), roles=("super_admin",))


async def _write(n: int, action: str = "test.sealed.fs", **kw: Any) -> list[uuid.UUID]:
    store = ScopedStore.system("test.writer")
    ids: list[uuid.UUID] = []

    async def fn(tx: ScopedTransaction) -> None:
        for i in range(n):
            ids.append(
                await rf.enqueue(
                    tx,
                    _actor(),
                    action,
                    "probe",
                    uuid7(),
                    after={"i": i, "nested": {"b": 2, "a": 1}, "grid": [[1, 2], [3]], "f": 5.0},
                    ip="203.0.113.7",
                    request_id=f"req-{i}",
                    **kw,
                )
            )

    await store.run_transaction(fn)
    return ids


async def _seal_all() -> int:
    repo = rf.sealer_repo()
    total = 0
    while n := await repo.seal_pending(50):
        total += n
    return total


def test_repository_scope_lint() -> None:
    assert_repository_scoped(rf.AuditFsRepo)


async def test_enqueue_seal_chain_verify() -> None:
    await _write(4)
    assert await _seal_all() == 4
    repo = rf.chain_repo()
    rows = await repo.chain_rows()
    assert [r["seq"] for r in rows] == [1, 2, 3, 4]
    assert rows[0]["after_state"] == {"i": 0, "nested": {"a": 1, "b": 2}, "grid": [[1, 2], [3]], "f": 5.0}
    assert isinstance(rows[0]["after_state"]["f"], float)
    assert rows[0]["ip"] == "203.0.113.7" and rows[0]["prev_hash"] == GENESIS_HASH
    res = await repo.verify_chain()
    assert res.ok and res.checked == 4 and res.last_seq == 4
    assert (await repo.verify_chain(3)).ok
    assert await ScopedStore.system("t").scan(OUTBOX) == []
    seq, h = await rf.sealer_repo().head()
    assert seq == 4 and h == rows[-1]["row_hash"]


async def test_invalid_action_rejected() -> None:
    with pytest.raises(ValueError):
        rf.build_record(_actor(), "Bad Action", "probe")


async def test_concurrent_sealers_gap_free() -> None:
    await _write(30)
    repo = rf.sealer_repo()

    async def worker() -> int:
        n = 0
        for _ in range(20):
            got = await rf.AuditFsRepo(ScopedStore.system("audit.sealer")).append(
                outbox_ids=await repo.pending_ids(7)
            )
            n += got
        return n

    counts = await asyncio.gather(*(worker() for _ in range(3)))
    assert sum(counts) == 30
    rows = await rf.chain_repo().chain_rows()
    assert [r["seq"] for r in rows] == list(range(1, 31))
    assert len({r["id"] for r in rows}) == 30
    assert (await rf.chain_repo().verify_chain()).ok


async def test_tamper_detected(fs_env: Any) -> None:
    await _write(3)
    await _seal_all()
    ref = fs_env.collection("lms_audit_log").document(log_id(2))
    await ref.update({"target_type": "something_else"})
    res = await rf.chain_repo().verify_chain()
    assert not res.ok and res.first_bad_seq == 2 and "altered" in (res.reason or "")


async def test_store_guards(make_principal: Any, auth: Any) -> None:
    await _write(1)
    await _seal_all()
    nobody = make_principal()
    with pytest.raises(StoreAccessDeniedError):
        await rf.reader_repo(nobody).get_event(1)
    reader = make_principal(roles=("super_admin",))
    auth.grant(reader, "audit.read")
    assert (await rf.reader_repo(reader).get_event(1)) is not None
    st = ScopedStore(reader)
    with pytest.raises(StoreAccessDeniedError):  # append-only, no principal writes
        await st.update(LOG, log_id(1), {"reason": "x"})
    with pytest.raises(StoreAccessDeniedError):
        await st.query(OUTBOX)
    with pytest.raises(StoreAccessDeniedError):  # sealer methods are system-only
        await rf.reader_repo(reader).seal_pending()


async def test_postgres_batch_redelivery_is_not_sealed_twice() -> None:
    now = datetime.now(UTC)
    recs = [
        (uuid7(), now + timedelta(microseconds=i), rf.build_record(_actor(), "test.pg.batch", "probe"))
        for i in range(3)
    ]
    repo = rf.sealer_repo()
    ids = [str(r[0]) for r in recs]
    assert await repo.append(recs, pg_batch_ids=ids) == 3
    # the Postgres delete "failed": the same batch comes back on the next round
    assert await repo.append(recs, pg_batch_ids=ids) == 0
    rows = await rf.chain_repo().chain_rows()
    assert [r["seq"] for r in rows] == [1, 2, 3]
    assert (await rf.chain_repo().verify_chain()).ok


async def test_backfill_mapping_continues_postgres_chain() -> None:
    """Rows shaped as asyncpg returns them -> documents -> the chain verifies and continues."""
    import ipaddress

    from app.modules.audit.sealer import _row

    prev, pg_rows = GENESIS_HASH, []
    t0 = datetime(2026, 11, 1, 10, 0, 0, 123456, tzinfo=UTC)
    for seq in (1, 2):
        rec = rf.build_record(
            _actor(), "test.backfill", "probe", after={"k": [1, {"z": None}]}, ip="10.1.2.3"
        )
        row = _row(seq, prev, uuid7(), t0 + timedelta(seconds=seq), rec)
        row["ip"] = ipaddress.ip_address("10.1.2.3")
        pg_rows.append(row)
        prev = row["row_hash"]
    st = ScopedStore.system("firestore.backfill")
    await st.import_documents(LOG, [(log_id(r["seq"]), log_doc(r)) for r in pg_rows])
    await st.import_documents("audit_meta", [("head", head_doc(pg_rows[-1]))])
    await _write(2)
    assert await _seal_all() == 2
    rows = await rf.chain_repo().chain_rows()
    assert [r["seq"] for r in rows] == [1, 2, 3, 4]
    assert verify_rows(rows).ok
    assert rows[0]["occurred_at"] == pg_rows[0]["occurred_at"]


async def test_router_list_get_filters_and_cursor(make_principal: Any, auth: Any) -> None:
    from app.core.pagination import encode_cursor
    from app.modules.audit import router as r

    await _write(3, action="test.list.a")
    await _write(2, action="test.list.b", reason_code="rc1")
    await _seal_all()
    reader = make_principal(roles=("super_admin",))
    auth.grant(reader, "audit.read")
    eq = dict.fromkeys(
        (
            "action",
            "actor_user_id",
            "subject_user_id",
            "target_type",
            "target_id",
            "organization_id",
            "reason_code",
        )
    )
    rows, more = await r._list_events_fs(reader, None, eq, None, None, None, 2)
    assert [x.seq for x in rows] == [5, 4] and more
    rows, more = await r._list_events_fs(reader, None, eq, None, None, encode_cursor({"seq": 4}), 10)
    assert [x.seq for x in rows] == [3, 2, 1] and not more
    rows, _ = await r._list_events_fs(reader, None, {**eq, "action": "test.list.a"}, None, None, None, 10)
    assert [x.seq for x in rows] == [3, 2, 1]
    rows, _ = await r._list_events_fs(reader, None, {**eq, "reason_code": "rc1"}, None, None, None, 10)
    assert [x.seq for x in rows] == [5, 4]
    future = datetime.now(UTC) + timedelta(days=1)
    rows, _ = await r._list_events_fs(reader, None, eq, future, None, None, 10)
    assert rows == []
    rows, _ = await r._list_events_fs(reader, None, eq, None, future.replace(tzinfo=None), None, 10)
    assert len(rows) == 5  # zone-less "to" is read as UTC, as Postgres does
    rows, more = await r._list_events_fs(reader, set(), eq, None, None, None, 10)
    assert rows == [] and not more  # a reader with no event family sees nothing
    sec = r._family_match({"security"})
    one = rows_all = (await r._list_events_fs(reader, None, eq, None, None, None, 10))[0]
    assert not any(sec(x) for x in rows_all) and one
    from app.core.errors import ProblemError

    with pytest.raises(ProblemError):
        await r._list_events_fs(reader, None, eq, None, None, encode_cursor({"x": 1}), 10)
    # schema output is the same model the Postgres path serialises
    from app.modules.audit.schemas import AuditEventDetailOut, AuditEventOut

    ev = await rf.reader_repo(reader).get_event(1)
    assert ev is not None
    out = AuditEventDetailOut.from_row(ev)
    assert out.ip == "203.0.113.7" and out.after_state["nested"] == {"a": 1, "b": 2}
    assert AuditEventOut.from_row(ev).row_hash == ev.row_hash.hex()
    assert await rf.reader_repo(reader).get_event(999) is None


def test_index_fragment_declares_list_indexes() -> None:
    p = Path(rf.__file__).with_name("firestore.indexes.fragment.json")
    data = json.loads(p.read_text())
    declared = {tuple(f["fieldPath"] for f in i["fields"]) for i in data["indexes"]}
    for f in (
        "action",
        "actor_user_id",
        "subject_user_id",
        "target_type",
        "target_id",
        "organization_id",
        "reason_code",
    ):
        assert (f, "seq") in declared


async def test_core_audit_inside_firestore_transaction_is_atomic() -> None:
    """Platform finding: ``core.audit.audit(tx, ...)`` writes the outbox in the caller's Firestore
    transaction -- committed with the business write, discarded when it rolls back."""
    from app.core.audit import audit as core_audit

    store = ScopedStore.system("test.business")

    async def ok(tx: ScopedTransaction) -> None:
        await core_audit(tx, _actor(), "test.core.tx", "probe", uuid7(), after={"k": [[1]]}, reason_code="r1")

    await store.run_transaction(ok)

    class Boom(Exception):
        pass

    async def fails(tx: ScopedTransaction) -> None:
        await core_audit(tx, _actor(), "test.core.tx", "probe", uuid7())
        raise Boom

    with pytest.raises(Boom):
        await store.run_transaction(fails)
    assert await _seal_all() == 1
    rows = await rf.chain_repo().chain_rows()
    assert rows[0]["action"] == "test.core.tx" and rows[0]["reason_code"] == "r1"
    assert rows[0]["after_state"] == {"k": [[1]]} and (await rf.chain_repo().verify_chain()).ok
