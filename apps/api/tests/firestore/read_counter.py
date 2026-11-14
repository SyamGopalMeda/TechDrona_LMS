"""Billed Firestore reads / RPCs of a block of code (emulator tests of request cost).

    async with count_reads() as c:
        await client.get("/api/v1/me")
    assert c.reads <= 8 and c.rpcs <= 9

Counts at the GAPIC level as Firestore bills: a query = one read per returned document (one for
an empty result), an aggregation = one read, a batch get = one read per requested document.
``c.by_collection`` splits the reads per physical collection. ``c.rounds`` is the number of
sequential waits on Firestore: RPCs started while another one is still in flight share a round
(so concurrent reads count once) -- the latency a request pays is ``rounds x`` the round trip.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ReadCount:
    reads: int = 0
    rpcs: int = 0
    rounds: int = 0
    by_collection: Counter[str] = field(default_factory=Counter)
    _in_flight: int = 0

    def _start(self) -> None:
        self.rpcs += 1
        if self._in_flight == 0:
            self.rounds += 1
        self._in_flight += 1

    def _end(self) -> None:
        self._in_flight -= 1


def _collection(req: Any) -> str:
    try:
        parent = getattr(req, "parent", "") or ""
        sq = getattr(req, "structured_query", None)
        if sq is not None and sq.from_:
            return str(sq.from_[0].collection_id)
        docs = list(getattr(req, "documents", []) or [])
        if docs:
            return str(docs[0]).split("/documents/", 1)[-1].split("/")[0]
        return str(parent).rsplit("/", 1)[-1]
    except Exception:  # noqa: BLE001 - a label only
        return "?"


class _Stream:
    def __init__(self, inner: Any, c: ReadCount, kind: str, coll: str) -> None:
        self._inner, self._c, self._kind, self._coll = inner, c, kind, coll
        self._it: Any = None
        self._docs = 0
        self._done = False

    def __aiter__(self) -> _Stream:
        return self

    async def __anext__(self) -> Any:
        if self._it is None:
            self._it = self._inner.__aiter__()
        try:
            resp = await self._it.__anext__()
        except StopAsyncIteration:
            if not self._done:
                self._done = True
                if self._kind == "query" and self._docs == 0:
                    self._c.reads += 1
                    self._c.by_collection[self._coll] += 1
                self._c._end()
            raise
        pb = getattr(resp, "_pb", resp)
        if self._kind == "query" and pb.HasField("document"):
            self._docs += 1
            self._c.reads += 1
            self._c.by_collection[self._coll] += 1
        elif self._kind == "batch_get" and (pb.HasField("found") or pb.WhichOneof("result") == "missing"):
            self._c.reads += 1
            self._c.by_collection[self._coll] += 1
        return resp

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@asynccontextmanager
async def count_reads() -> AsyncIterator[ReadCount]:
    from google.cloud.firestore_v1.services.firestore.async_client import FirestoreAsyncClient as C

    c = ReadCount()
    saved = {n: getattr(C, n) for n in ("run_query", "run_aggregation_query", "batch_get_documents", "commit")}
    saved["begin_transaction"] = C.begin_transaction

    def _req(a: tuple[Any, ...], kw: dict[str, Any]) -> Any:
        return kw.get("request") if kw.get("request") is not None else (a[0] if a else None)

    async def run_query(self: Any, *a: Any, **kw: Any) -> Any:
        c._start()
        try:
            inner = await saved["run_query"](self, *a, **kw)
        except BaseException:
            c._end()
            raise
        return _Stream(inner, c, "query", _collection(_req(a, kw)))

    async def batch_get_documents(self: Any, *a: Any, **kw: Any) -> Any:
        c._start()
        try:
            inner = await saved["batch_get_documents"](self, *a, **kw)
        except BaseException:
            c._end()
            raise
        return _Stream(inner, c, "batch_get", _collection(_req(a, kw)))

    def _unary(name: str, reads: int) -> Any:
        async def call(self: Any, *a: Any, **kw: Any) -> Any:
            c._start()
            try:
                if reads:
                    c.reads += reads
                    c.by_collection[_collection(_req(a, kw))] += reads
                return await saved[name](self, *a, **kw)
            finally:
                c._end()

        return call

    C.run_query = run_query  # type: ignore[method-assign]
    C.batch_get_documents = batch_get_documents  # type: ignore[method-assign]
    C.run_aggregation_query = _unary("run_aggregation_query", 1)  # type: ignore[method-assign]
    C.commit = _unary("commit", 0)  # type: ignore[method-assign]
    C.begin_transaction = _unary("begin_transaction", 0)  # type: ignore[method-assign]
    try:
        yield c
    finally:
        for n, f in saved.items():
            setattr(C, n, f)
