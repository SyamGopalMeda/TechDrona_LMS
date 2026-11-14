"""Request-scoped read memo (``app.core.firestore.request_memo``) on the Firestore emulator.

A second read of the same document inside ONE request is served from the memo; every write staged
through the store, a lease/lock, the end of the request and transactions bypass/forget it, and
nothing is memoised outside a request.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any

import pytest

from app.core.firestore import request_memo
from app.core.firestore.collections import CollectionSpec, register_collection, unregister_collection
from app.core.firestore.errors import StoreAccessDeniedError
from app.core.firestore.store import ScopedStore, ScopedTransaction
from app.core.request_context import bind_request_state, reset_request_state

DOCS = CollectionSpec("t_memo_docs", "shared", write_permission="memo.write")
LEDGER = CollectionSpec("t_memo_ledger", "owned")
OTHER = CollectionSpec("t_memo_other", "shared", write_permission="memo.write")


@pytest.fixture(autouse=True)
def _specs(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for s in (DOCS, LEDGER, OTHER):
        register_collection(s)
    monkeypatch.setattr(request_memo, "DOC_COLLECTIONS", frozenset({"lms_t_memo_docs"}))
    monkeypatch.setattr(request_memo, "QUERY_COLLECTIONS", frozenset({"lms_t_memo_ledger"}))
    yield
    for s in (DOCS, LEDGER, OTHER):
        unregister_collection(s.name)


@pytest.fixture
def in_request() -> Iterator[dict[str, Any]]:
    """What RequestContextMiddleware does for one HTTP request."""
    state: dict[str, Any] = {request_memo.STATE_KEY: request_memo.begin()}
    token = bind_request_state(state)
    yield state
    state.pop(request_memo.STATE_KEY, None)
    reset_request_state(token)


def _sys(client: Any) -> Any:
    return ScopedStore.system("tests.memo", client=client)


async def _behind_the_back(client: Any, coll: str, doc_id: str, data: dict[str, Any]) -> None:
    """Another request/instance changes the document (not through this request's store)."""
    await client.collection(f"lms_{coll}").document(doc_id).set(data, merge=True)


async def test_second_read_in_a_request_is_memoised(fs_client: Any, in_request: dict[str, Any]) -> None:
    s = _sys(fs_client)
    await s.create("t_memo_docs", {"v": 1}, doc_id="d1")
    assert (await s.get("t_memo_docs", "d1"))["v"] == 1
    await _behind_the_back(fs_client, "t_memo_docs", "d1", {"v": 2})
    assert (await s.get("t_memo_docs", "d1"))["v"] == 1  # same request: the first read's answer
    assert (await s.get_many("t_memo_docs", ["d1"]))["d1"]["v"] == 1
    # missing documents are memoised as missing too
    assert await s.get("t_memo_docs", "nope") is None
    await _behind_the_back(fs_client, "t_memo_docs", "nope", {"v": 9})
    assert await s.get("t_memo_docs", "nope") is None


async def test_returned_data_is_a_copy(fs_client: Any, in_request: dict[str, Any]) -> None:
    s = _sys(fs_client)
    await s.create("t_memo_docs", {"v": 1, "tags": ["a"]}, doc_id="d1")
    first = await s.get("t_memo_docs", "d1")
    first.data["tags"].append("mutated")
    first.data["v"] = 99
    again = await s.get("t_memo_docs", "d1")
    assert again["v"] == 1 and again["tags"] == ["a"]


async def test_store_writes_forget_the_document(fs_client: Any, in_request: dict[str, Any]) -> None:
    s = _sys(fs_client)
    await s.create("t_memo_docs", {"v": 1}, doc_id="d1")
    assert (await s.get("t_memo_docs", "d1"))["v"] == 1
    await s.update("t_memo_docs", "d1", {"v": 2})  # transaction update
    assert (await s.get("t_memo_docs", "d1"))["v"] == 2

    async def put(tx: ScopedTransaction) -> None:
        await tx.put("t_memo_docs", "d1", {"v": 3})

    await s.run_transaction(put)
    assert (await s.get("t_memo_docs", "d1"))["v"] == 3

    async def raw(tx: ScopedTransaction) -> None:
        tx.raw_set("t_memo_docs", "d1", {"v": 4})

    await s.run_transaction(raw)
    assert (await s.get("t_memo_docs", "d1"))["v"] == 4
    await s.delete("t_memo_docs", "d1")
    assert await s.get("t_memo_docs", "d1") is None
    await s.create("t_memo_docs", {"v": 5}, doc_id="d1")
    assert (await s.get("t_memo_docs", "d1"))["v"] == 5


async def test_a_lease_clears_the_memo(fs_client: Any, in_request: dict[str, Any]) -> None:
    s = _sys(fs_client)
    await s.create("t_memo_docs", {"v": 1}, doc_id="d1")
    assert (await s.get("t_memo_docs", "d1"))["v"] == 1
    await _behind_the_back(fs_client, "t_memo_docs", "d1", {"v": 2})
    assert await s.claim_lease("memo:test", "holder", timedelta(seconds=30))
    assert (await s.get("t_memo_docs", "d1"))["v"] == 2  # serialised: re-read after the lock


async def test_transactions_never_use_the_memo(fs_client: Any, in_request: dict[str, Any]) -> None:
    s = _sys(fs_client)
    await s.create("t_memo_docs", {"v": 1}, doc_id="d1")
    assert (await s.get("t_memo_docs", "d1"))["v"] == 1
    await _behind_the_back(fs_client, "t_memo_docs", "d1", {"v": 2})

    async def read(tx: Any) -> Any:
        return (await tx.get("t_memo_docs", "d1"))["v"]

    assert await s.run_transaction(read) == 2


async def test_no_memo_outside_a_request_or_after_it(fs_client: Any) -> None:
    s = _sys(fs_client)
    await s.create("t_memo_docs", {"v": 1}, doc_id="d1")
    assert (await s.get("t_memo_docs", "d1"))["v"] == 1
    await _behind_the_back(fs_client, "t_memo_docs", "d1", {"v": 2})
    assert (await s.get("t_memo_docs", "d1"))["v"] == 2  # no request: always a fresh read

    state: dict[str, Any] = {request_memo.STATE_KEY: request_memo.begin()}
    token = bind_request_state(state)
    try:
        assert (await s.get("t_memo_docs", "d1"))["v"] == 2
        state.pop(request_memo.STATE_KEY)  # the middleware drops it when the request ends
        await _behind_the_back(fs_client, "t_memo_docs", "d1", {"v": 3})
        assert (await s.get("t_memo_docs", "d1"))["v"] == 3
    finally:
        reset_request_state(token)


async def test_only_listed_collections_are_memoised(fs_client: Any, in_request: dict[str, Any]) -> None:
    s = _sys(fs_client)
    await s.create("t_memo_other", {"v": 1}, doc_id="o1")
    assert (await s.get("t_memo_other", "o1"))["v"] == 1
    await _behind_the_back(fs_client, "t_memo_other", "o1", {"v": 2})
    assert (await s.get("t_memo_other", "o1"))["v"] == 2


async def test_query_memo_and_collection_invalidation(
    fs_client: Any, in_request: dict[str, Any], make_principal: Any
) -> None:
    s = _sys(fs_client)
    alice = make_principal()
    await s.create("t_memo_ledger", {"user_id": alice.user_id, "n": 1}, doc_id="l1")
    first = await s.query("t_memo_ledger", user_id=alice.user_id, order_by=())
    assert [d["n"] for d in first.items] == [1]
    await _behind_the_back(fs_client, "t_memo_ledger", "l2", {"user_id": str(alice.user_id), "n": 2})
    again = await s.query("t_memo_ledger", user_id=alice.user_id, order_by=())
    assert [d["n"] for d in again.items] == [1]  # same query, same request
    # a write anywhere in the collection forgets its queries
    await s.create("t_memo_ledger", {"user_id": alice.user_id, "n": 3}, doc_id="l3")
    fresh = await s.query("t_memo_ledger", user_id=alice.user_id, order_by=())
    assert sorted(d["n"] for d in fresh.items) == [1, 2, 3]
    # read rights are re-checked on memoised rows: another principal's store sees nothing
    bob = make_principal()
    with pytest.raises(StoreAccessDeniedError):  # owned rows of Alice: Bob may not query them
        await ScopedStore(bob, client=fs_client).query("t_memo_ledger", user_id=alice.user_id, order_by=())


async def test_middleware_creates_and_drops_the_memo() -> None:
    from app.core.middleware import RequestContextMiddleware

    seen: dict[str, Any] = {}

    async def app(scope: Any, receive: Any, send: Any) -> None:
        seen["memo"] = request_memo._memo()
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def receive() -> Any:
        return {"type": "http.request", "body": b""}

    async def send(_m: Any) -> None:
        return None

    scope: dict[str, Any] = {"type": "http", "method": "GET", "path": "/x", "headers": []}
    await RequestContextMiddleware(app)(scope, receive, send)
    assert seen["memo"] == {"docs": {}, "queries": {}}
    assert request_memo.STATE_KEY not in scope["state"]
    assert request_memo._memo() is None
