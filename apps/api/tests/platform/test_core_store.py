"""Firestore ``core`` repositories (emulator): outbox emit + relay, Idempotency-Key records."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from starlette.requests import Request

from app.core import outbox
from app.core.errors import ProblemError
from app.core.firestore.collections import physical_name
from app.core.firestore.core_store import (
    IDEMPOTENCY,
    OUTBOX,
    emit_event_tx,
    idempotent_firestore,
    relay_pending_firestore,
)
from app.core.firestore.store import ScopedStore
from app.core.idempotency import IdemResult

EVENT = "platformtest.thing_happened"


@pytest.fixture
def handlers() -> Any:
    registered: list[Any] = []

    def reg(fn: Any) -> None:
        outbox.register_handler(EVENT, fn)
        registered.append(fn)

    yield reg
    for fn in registered:
        outbox.unregister_handler(EVENT, fn)


async def _emit(store: ScopedStore, n: int = 1) -> list[uuid.UUID]:
    ids = []
    for i in range(n):
        ids.append(await store.run_transaction(lambda tx, i=i: _do_emit(tx, i)))
    return ids


async def _do_emit(tx: Any, i: int) -> uuid.UUID:
    return emit_event_tx(tx, EVENT, {"n": i}, aggregate_type="thing", aggregate_id=uuid.uuid4())


async def _raw(fs_client: Any, coll: str, doc_id: str) -> dict[str, Any]:
    snap = await fs_client.collection(physical_name(coll)).document(doc_id).get()
    return snap.to_dict() or {}


async def test_emit_and_relay_dispatches_in_order(fs_client: Any, handlers: Any) -> None:
    store = ScopedStore.system("core.outbox_relay", client=fs_client)
    seen: list[tuple[Any, int]] = []

    async def h(session: Any, msg: outbox.OutboxMessage) -> None:
        seen.append((session, msg.payload["n"]))
        assert msg.attempt == 1 and msg.event_type == EVENT

    handlers(h)
    ids = await _emit(store, 3)
    r = await relay_pending_firestore(store=store)
    assert (r.dispatched, r.failed) == (3, 0)
    assert [n for _s, n in seen] == [0, 1, 2]
    assert all(s is None for s, _n in seen)
    doc = await _raw(fs_client, OUTBOX, str(ids[0]))
    assert doc["dispatched_at"] is not None and "pending_at" not in doc and doc["attempts"] == 1
    again = await relay_pending_firestore(store=store)
    assert (again.dispatched, again.failed, again.skipped_no_handler) == (0, 0, 0)


async def test_failure_retries_then_dead_letters(fs_client: Any, handlers: Any) -> None:
    store = ScopedStore.system("core.outbox_relay", client=fs_client)

    async def boom(session: Any, msg: outbox.OutboxMessage) -> None:
        raise RuntimeError("nope")

    handlers(boom)
    (eid,) = await _emit(store)
    for attempt in (1, 2):
        r = await relay_pending_firestore(store=store, max_attempts=2)
        assert r.failed == 1
        doc = await _raw(fs_client, OUTBOX, str(eid))
        assert doc["attempts"] == attempt and doc["last_error"].startswith("RuntimeError")
    assert "pending_at" not in doc and doc.get("dead_at") is not None and doc["dispatched_at"] is None
    r = await relay_pending_firestore(store=store, max_attempts=2)
    assert r.failed == 0  # dead letter is not picked up again


async def test_no_handler_marks_dispatched_and_session_scope_is_used(fs_client: Any, handlers: Any) -> None:
    store = ScopedStore.system("core.outbox_relay", client=fs_client)
    (eid,) = await _emit(store)
    r = await relay_pending_firestore(store=store)
    assert r.skipped_no_handler == 1
    assert (await _raw(fs_client, OUTBOX, str(eid)))["dispatched_at"] is not None

    from contextlib import asynccontextmanager

    sessions: list[str] = []

    @asynccontextmanager
    async def scope() -> Any:
        sessions.append("open")
        yield "pg-session"

    got: list[Any] = []

    async def h(session: Any, msg: outbox.OutboxMessage) -> None:
        got.append(session)

    handlers(h)
    await _emit(store)
    await relay_pending_firestore(store=store, session_scope=scope)
    assert got == ["pg-session"] and sessions == ["open"]


async def test_lease_blocks_a_second_relay(fs_client: Any, handlers: Any) -> None:
    from app.core.firestore.core_store import _claim

    store = ScopedStore.system("core.outbox_relay", client=fs_client)
    calls: list[int] = []

    async def h(session: Any, msg: outbox.OutboxMessage) -> None:
        calls.append(1)

    handlers(h)
    (eid,) = await _emit(store)
    claimed = await store.run_transaction(lambda tx: _claim(tx, str(eid), "other-relay", 10))
    assert claimed is not None
    r = await relay_pending_firestore(store=store, holder="me")
    assert r.dispatched == 0 and calls == []  # SKIP LOCKED equivalent


def _request(body: dict[str, Any], key: str | None, path: str = "/api/v1/things") -> Request:
    raw = json.dumps(body).encode()
    headers = [(b"content-type", b"application/json")]
    if key:
        headers.append((b"idempotency-key", key.encode()))
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": headers,
        "query_string": b"",
        "path_params": {},
    }
    return Request(scope, receive)


async def test_idempotency_replay_reuse_and_problem(fs_client: Any) -> None:
    store = ScopedStore.system("core.idempotency", client=fs_client)
    user = uuid.uuid4()
    calls: list[int] = []

    async def op() -> IdemResult:
        calls.append(1)
        return IdemResult(body={"id": "x1", "n": len(calls)}, status=201)

    r1 = await idempotent_firestore(
        _request({"a": 1}, "key-00000001"), None, user_id=user, operation=op, store=store
    )
    assert r1.status_code == 201 and json.loads(r1.body) == {"id": "x1", "n": 1}
    r2 = await idempotent_firestore(
        _request({"a": 1}, "key-00000001"), None, user_id=user, operation=op, store=store
    )
    assert r2.status_code == 201 and json.loads(r2.body) == {"id": "x1", "n": 1}
    assert r2.headers["Idempotency-Replayed"] == "true" and calls == [1]
    with pytest.raises(ProblemError) as ei:
        await idempotent_firestore(
            _request({"a": 2}, "key-00000001"), None, user_id=user, operation=op, store=store
        )
    assert ei.value.code == "idempotency_key_reuse"
    # another user may use the same key
    r3 = await idempotent_firestore(
        _request({"a": 1}, "key-00000001"), None, user_id=uuid.uuid4(), operation=op, store=store
    )
    assert json.loads(r3.body)["n"] == 2

    async def bad() -> IdemResult:
        raise ProblemError("validation_failed", errors=[])

    p1 = await idempotent_firestore(
        _request({}, "key-00000002"), None, user_id=user, operation=bad, store=store
    )
    assert p1.status_code == 422 or p1.status_code == 400
    p2 = await idempotent_firestore(
        _request({}, "key-00000002"), None, user_id=user, operation=bad, store=store
    )
    assert p2.status_code == p1.status_code and p2.headers["Idempotency-Replayed"] == "true"
    assert p2.media_type == "application/problem+json"


async def test_idempotency_5xx_not_stored_and_missing_key(fs_client: Any) -> None:
    store = ScopedStore.system("core.idempotency", client=fs_client)

    async def fail() -> IdemResult:
        raise RuntimeError("db down")

    with pytest.raises(RuntimeError):
        await idempotent_firestore(
            _request({}, "key-00000003"), None, user_id=None, operation=fail, store=store
        )

    async def ok() -> IdemResult:
        return IdemResult(body={"ok": True})

    r = await idempotent_firestore(
        _request({}, "key-00000003"), None, user_id=None, operation=ok, store=store
    )
    assert r.status_code == 200 and "Idempotency-Replayed" not in r.headers
    with pytest.raises(ProblemError) as ei:
        await idempotent_firestore(_request({}, None), None, user_id=None, operation=ok, store=store)
    assert ei.value.code == "idempotency_key_required"
    snaps = [s async for s in fs_client.collection(physical_name(IDEMPOTENCY)).stream()]
    assert len(snaps) == 1 and snaps[0].to_dict()["status"] == "completed"


async def test_in_progress_duplicate_answers_409(fs_client: Any) -> None:
    store = ScopedStore.system("core.idempotency", client=fs_client)
    inner: list[Any] = []

    async def slow() -> IdemResult:
        with pytest.raises(ProblemError) as ei:
            await idempotent_firestore(
                _request({}, "key-00000004"), None, user_id=None, operation=slow, store=store
            )
        inner.append(ei.value.code)
        return IdemResult(body={})

    await idempotent_firestore(_request({}, "key-00000004"), None, user_id=None, operation=slow, store=store)
    assert inner == ["idempotency_in_progress"]


async def test_idempotency_with_the_no_postgres_placeholder(fs_client: Any) -> None:
    """R10: the request session on the Firebase stack is db.NO_POSTGRES (falsy): no savepoint."""
    from app.core.db import NO_POSTGRES

    store = ScopedStore.system("core.idempotency", client=fs_client)

    async def ok() -> IdemResult:
        return IdemResult(body={"ok": 1}, status=201)

    async def bad() -> IdemResult:
        raise ProblemError("validation_failed", errors=[])

    r = await idempotent_firestore(
        _request({}, "key-00000005"), NO_POSTGRES, user_id=None, operation=ok, store=store
    )
    assert r.status_code == 201
    p = await idempotent_firestore(
        _request({}, "key-00000006"), NO_POSTGRES, user_id=None, operation=bad, store=store
    )
    assert p.status_code in (400, 422)


async def test_relay_message_matches_the_postgres_relay(fs_client: Any, handlers: Any) -> None:
    """A3: same OutboxMessage fields/types as the Postgres relay; payload round-trips like JSONB
    (incl. nested arrays Firestore maps refuse); ties on occurred_at are ordered by id."""
    from datetime import UTC, datetime

    from app.core.firestore.core_store import event_doc

    store = ScopedStore.system("core.outbox_relay", client=fs_client)
    got: list[outbox.OutboxMessage] = []

    async def h(session: Any, msg: outbox.OutboxMessage) -> None:
        got.append(msg)
        if msg.payload.get("fail_once") and msg.attempt == 1:
            raise RuntimeError("transient")

    handlers(h)
    org, agg = uuid.uuid4(), uuid.uuid4()
    same_time = datetime(2026, 11, 12, 10, 0, 0, 123456, tzinfo=UTC)
    payload = {"grid": [[1, 2], [3]], "n": 1.5, "s": "x", "none": None, "fail_once": True}
    ids = sorted(uuid.UUID(int=(0x0189 << 112) | i) for i in (3, 1, 2))  # uuid-ordered ids

    async def put(tx: Any) -> None:
        for i, eid in enumerate(reversed(ids)):  # inserted out of order
            tx.raw_create(
                OUTBOX, str(eid), event_doc(eid, EVENT, {**payload, "i": i}, "thing", agg, org, same_time)
            )

    await store.run_transaction(put)
    r1 = await relay_pending_firestore(store=store)
    assert (r1.dispatched, r1.failed) == (0, 3)
    assert [m.id for m in got] == ids  # occurred_at tie -> id order (Postgres ORDER BY occurred_at, id)
    m = got[0]
    assert isinstance(m.id, uuid.UUID) and m.aggregate_id == agg and m.organization_id == org
    assert m.event_type == EVENT and m.aggregate_type == "thing" and m.attempt == 1
    assert m.occurred_at == same_time and type(m.occurred_at) is datetime and m.occurred_at.tzinfo is not None
    assert m.payload["grid"] == [[1, 2], [3]] and m.payload["n"] == 1.5 and m.payload["none"] is None
    got.clear()
    r2 = await relay_pending_firestore(store=store)  # at-least-once: redelivered, attempt 2
    assert (r2.dispatched, r2.failed) == (3, 0) and {m.attempt for m in got} == {2}
    doc = await _raw(fs_client, OUTBOX, str(ids[0]))
    assert doc["attempts"] == 2 and doc["last_error"] is None and doc["dispatched_at"] is not None


async def test_relay_reads_map_payloads_written_by_the_sql_engine(fs_client: Any, handlers: Any) -> None:
    store = ScopedStore.system("core.outbox_relay", client=fs_client)
    got: list[outbox.OutboxMessage] = []

    async def h(session: Any, msg: outbox.OutboxMessage) -> None:
        got.append(msg)

    handlers(h)
    eid = uuid.uuid4()

    async def put(tx: Any) -> None:
        from app.core.time import utcnow

        now = utcnow()
        tx.raw_create(
            OUTBOX,
            str(eid),
            {
                "id": str(eid),
                "event_type": EVENT,
                "aggregate_type": "t",
                "aggregate_id": str(uuid.uuid4()),
                "payload": {"a": 1},
                "organization_id": None,
                "attempts": 0,
                "dispatched_at": None,
                "last_error": None,
                "lease_until": None,
                "occurred_at": now,
                "pending_at": now,
            },
        )

    await store.run_transaction(put)
    await relay_pending_firestore(store=store)
    assert got[0].payload == {"a": 1} and got[0].organization_id is None


async def test_raising_max_attempts_repicks_dead_letters(fs_client: Any, handlers: Any) -> None:
    """Postgres selects ``attempts < :max``: a later, higher TD_OUTBOX_MAX_ATTEMPTS re-picks dead
    letters. Same here (no stored dead verdict)."""
    store = ScopedStore.system("core.outbox_relay", client=fs_client)
    healthy = {"ok": False}
    seen: list[int] = []

    async def h(session: Any, msg: outbox.OutboxMessage) -> None:
        seen.append(msg.attempt)
        if not healthy["ok"]:
            raise RuntimeError("down")

    handlers(h)
    (eid,) = await _emit(store)
    for _ in range(3):
        await relay_pending_firestore(store=store, max_attempts=2)
    doc = await _raw(fs_client, OUTBOX, str(eid))
    assert doc["attempts"] == 2 and doc.get("dead_at") is not None and seen == [1, 2]
    r = await relay_pending_firestore(store=store, max_attempts=3)  # raised max: re-picked, fails again
    assert r.failed == 1 and seen == [1, 2, 3]
    doc = await _raw(fs_client, OUTBOX, str(eid))
    assert doc["attempts"] == 3 and doc.get("dead_at") is not None  # dead again at the new max
    healthy["ok"] = True
    r = await relay_pending_firestore(store=store, max_attempts=5)
    assert r.dispatched == 1 and seen[-1] == 4
    doc = await _raw(fs_client, OUTBOX, str(eid))
    assert doc["dispatched_at"] is not None and "dead_at" not in doc and "pending_at" not in doc


async def test_idempotency_fresh_key_needs_no_transaction_and_expired_keys_restart(
    fs_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cost: a new key is claimed with one ``create`` and finished with one field update (no
    read). An existing key (replay / expired previous use) still goes through the transaction."""
    from datetime import timedelta

    from app.core.time import utcnow

    store = ScopedStore.system("core.idempotency", client=fs_client)
    txs: list[int] = []
    real_tx = store.run_transaction

    async def counting(fn: Any, **kw: Any) -> Any:
        txs.append(1)
        return await real_tx(fn, **kw)

    monkeypatch.setattr(store, "run_transaction", counting)
    n: list[int] = []

    async def op() -> IdemResult:
        n.append(1)
        return IdemResult(body={"n": len(n)}, status=201)

    r = await idempotent_firestore(_request({"a": 1}, "key-00000101"), None, user_id=None, operation=op, store=store)
    assert r.status_code == 201 and txs == []
    snaps = [s async for s in fs_client.collection(physical_name(IDEMPOTENCY)).stream()]
    assert len(snaps) == 1
    rec = snaps[0].to_dict()
    assert rec["status"] == "completed" and rec["response_status"] == 201 and rec["route_key"]
    assert json.loads(rec["response_json"]) == {"n": 1} and rec["expire_at"] == rec["expires_at"]

    # replay: answered from the record through the transaction
    r2 = await idempotent_firestore(_request({"a": 1}, "key-00000101"), None, user_id=None, operation=op, store=store)
    assert r2.headers["Idempotency-Replayed"] == "true" and n == [1] and txs == [1]

    # an expired previous use of the key starts over (transaction path, as before)
    await snaps[0].reference.update({"expires_at": utcnow() - timedelta(seconds=1)})
    r3 = await idempotent_firestore(_request({"a": 1}, "key-00000101"), None, user_id=None, operation=op, store=store)
    assert r3.status_code == 201 and json.loads(r3.body) == {"n": 2} and "Idempotency-Replayed" not in r3.headers


async def test_idempotency_record_removed_meanwhile_stays_absent(fs_client: Any) -> None:
    """``_set`` on a record that disappeared (e.g. dropped by retention) does not recreate it."""
    store = ScopedStore.system("core.idempotency", client=fs_client)

    async def op() -> IdemResult:
        async for s in fs_client.collection(physical_name(IDEMPOTENCY)).stream():
            await s.reference.delete()
        return IdemResult(body={"ok": True})

    r = await idempotent_firestore(_request({}, "key-00000102"), None, user_id=None, operation=op, store=store)
    assert r.status_code == 200
    assert [s async for s in fs_client.collection(physical_name(IDEMPOTENCY)).stream()] == []
