"""Firestore replacement for the Redis *cache* cluster (``TD_CACHE_BACKEND=firestore``).

``FirestoreRedis`` implements the small subset of ``redis.asyncio.Redis`` the API uses, with the
same return types (values come back as ``bytes``, like a Redis client without
``decode_responses``), so callers (``app.core.redis.get_cache_redis()`` users: rate limits,
the entitlement decision cache, the readiness probe) work unchanged:

``get``, ``set(ex=, px=, nx=, xx=)``, ``incr``, ``incrby``, ``expire``, ``ttl``, ``delete``,
``exists``, ``mget``, ``ping``, ``pipeline()`` (queued commands, ``execute()`` returns the list of
results in order), ``aclose``.

Storage: collection ``lms_kv``; document id = SHA-256 of the key (Redis keys contain ``:`` and
user ids); fields ``k`` (the key, for debugging), ``v`` (bytes) and ``expire_at`` (UTC timestamp
or absent). Expired documents are invisible (checked on every read) and are removed by the
Firestore TTL policy on ``expire_at`` (deploy step in docs/firebase/agents/platform.md).

Read-modify-write commands (``incr``, ``set nx``, ``expire``, ...) run in a Firestore transaction
through ``ScopedStore.system(...).run_transaction`` (jittered backoff on contention), so counts
are exact like Redis ``INCR``.

``FirestoreRateLimitBackend`` is the ``app.core.ratelimit.Backend`` on the same collection: the
fixed-window keys of ``app.core.ratelimit`` take one batch of server-side increments per request
(field ``n``; 1 write per key, no read); any other key (e.g. the Google token replay guard) one
transaction for all keys (``INCR`` + ``EXPIRE`` per key).
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.firestore import client as client_mod
from app.core.firestore.collections import physical_name

KV = "kv"
# app.core.ratelimit._windows: "rl:<key>:<window_s>:<window index>"
_WINDOW_KEY = re.compile(r"^rl:.+:(\d+):(\d+)$")
_JOB = "platform.kv"


def kv_doc_id(key: str | bytes) -> str:
    raw = key if isinstance(key, bytes) else key.encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _now() -> datetime:
    return datetime.fromtimestamp(time.time(), tz=UTC)


def _to_bytes(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bool):  # redis-py refuses bools; mirror that
        raise TypeError("Invalid input of type: 'bool'. Convert to a bytes, string, int or float first.")
    if isinstance(value, int | float):
        return repr(value).encode() if isinstance(value, float) else str(value).encode()
    if isinstance(value, str):
        return value.encode("utf-8")
    raise TypeError(f"Invalid input of type: {type(value).__name__!r}")


def _live(data: dict[str, Any] | None, now: datetime) -> dict[str, Any] | None:
    if data is None:
        return None
    exp = data.get("expire_at")
    if exp is not None and exp <= now:
        return None
    return data


def _store() -> Any:
    from app.core.firestore.store import ScopedStore

    return ScopedStore.system(_JOB)


class _Pipeline:
    """Queued commands; ``await execute()`` runs them in order and returns their results."""

    def __init__(self, kv: FirestoreRedis) -> None:
        self._kv = kv
        self._ops: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_") or not hasattr(FirestoreRedis, name) or name in {"pipeline", "aclose"}:
            raise AttributeError(name)

        def queue(*args: Any, **kwargs: Any) -> _Pipeline:
            self._ops.append((name, args, kwargs))
            return self

        return queue

    async def execute(self, raise_on_error: bool = True) -> list[Any]:
        out: list[Any] = []
        for name, args, kwargs in self._ops:
            try:
                out.append(await getattr(self._kv, name)(*args, **kwargs))
            except Exception as e:
                if raise_on_error:
                    raise
                out.append(e)
        self._ops.clear()
        return out

    async def __aenter__(self) -> _Pipeline:
        return self

    async def __aexit__(self, *exc: object) -> None:
        self._ops.clear()


class FirestoreRedis:
    """Redis-compatible facade over ``lms_kv`` (cache semantics; see module docstring)."""

    def __init__(self, client: Any | None = None) -> None:
        self._client = client

    @property
    def client(self) -> Any:
        return self._client if self._client is not None else client_mod.get_client()

    def _ref(self, key: str | bytes) -> Any:
        return self.client.collection(physical_name(KV)).document(kv_doc_id(key))

    async def _read(self, key: str | bytes) -> dict[str, Any] | None:
        snap = await self._ref(key).get()
        return _live(snap.to_dict() if snap.exists else None, _now())

    async def _tx(self, fn: Any) -> Any:
        from app.core.firestore.store import ScopedStore

        return await ScopedStore.system(_JOB, client=self.client).run_transaction(fn)

    # ------------------------------------------------------------------ reads

    async def ping(self) -> bool:
        await self._ref("__td_ping__").get()
        return True

    async def get(self, key: str | bytes) -> bytes | None:
        data = await self._read(key)
        return None if data is None else bytes(data.get("v", b""))

    async def mget(self, keys: Iterable[str | bytes], *more: str | bytes) -> list[bytes | None]:
        ks = [keys, *more] if isinstance(keys, str | bytes) else [*keys, *more]
        if not ks:
            return []
        refs = [self._ref(k) for k in ks]
        now = _now()
        by_id: dict[str, bytes | None] = {}
        async for snap in self.client.get_all(refs):
            data = _live(snap.to_dict() if snap.exists else None, now)
            by_id[snap.id] = None if data is None else bytes(data.get("v", b""))
        return [by_id.get(kv_doc_id(k)) for k in ks]

    async def exists(self, *keys: str | bytes) -> int:
        return sum(1 for v in await self.mget(list(keys)) if v is not None)

    async def ttl(self, key: str | bytes) -> int:
        data = await self._read(key)
        if data is None:
            return -2
        exp = data.get("expire_at")
        if exp is None:
            return -1
        return max(0, int((exp - _now()).total_seconds()))

    # ------------------------------------------------------------------ writes

    async def set(
        self,
        key: str | bytes,
        value: Any,
        ex: int | timedelta | None = None,
        px: int | timedelta | None = None,
        nx: bool = False,
        xx: bool = False,
        keepttl: bool = False,
    ) -> bool | None:
        raw = _to_bytes(value)
        ttl_s: float | None = None
        if isinstance(ex, timedelta):
            ttl_s = ex.total_seconds()
        elif ex is not None:
            ttl_s = float(ex)
        if isinstance(px, timedelta):
            ttl_s = px.total_seconds()
        elif px is not None:
            ttl_s = px / 1000.0
        doc_id = kv_doc_id(key)
        k = key.decode() if isinstance(key, bytes) else key

        async def _fn(tx: Any) -> bool | None:
            now = _now()
            cur = _live(await tx.raw_get(KV, doc_id), now)
            if (nx and cur is not None) or (xx and cur is None):
                return None
            doc: dict[str, Any] = {"k": k, "v": raw}
            if ttl_s is not None:
                doc["expire_at"] = now + timedelta(seconds=ttl_s)
            elif keepttl and cur is not None and cur.get("expire_at") is not None:
                doc["expire_at"] = cur["expire_at"]
            tx.raw_set(KV, doc_id, doc)
            return True

        if not (nx or xx or keepttl):  # plain SET: no read needed
            now = _now()
            doc: dict[str, Any] = {"k": k, "v": raw}
            if ttl_s is not None:
                doc["expire_at"] = now + timedelta(seconds=ttl_s)
            await self._ref(key).set(doc)
            return True
        return await self._tx(_fn)

    async def incrby(self, key: str | bytes, amount: int = 1) -> int:
        doc_id = kv_doc_id(key)
        k = key.decode() if isinstance(key, bytes) else key

        async def _fn(tx: Any) -> int:
            now = _now()
            cur = _live(await tx.raw_get(KV, doc_id), now)
            try:
                n = (int(bytes(cur.get("v", b"0"))) if cur is not None else 0) + int(amount)
            except ValueError:
                raise ValueError("value is not an integer or out of range") from None
            doc: dict[str, Any] = {"k": k, "v": str(n).encode()}
            if cur is not None and cur.get("expire_at") is not None:  # INCR keeps the TTL
                doc["expire_at"] = cur["expire_at"]
            tx.raw_set(KV, doc_id, doc)
            return n

        return int(await self._tx(_fn))

    async def incr(self, key: str | bytes, amount: int = 1) -> int:
        return await self.incrby(key, amount)

    async def expire(self, key: str | bytes, time: int | timedelta) -> bool:
        seconds = time.total_seconds() if isinstance(time, timedelta) else float(time)
        doc_id = kv_doc_id(key)

        async def _fn(tx: Any) -> bool:
            now = _now()
            cur = _live(await tx.raw_get(KV, doc_id), now)
            if cur is None:
                return False
            if seconds <= 0:
                tx.raw_delete(KV, doc_id)
            else:
                tx.raw_set(KV, doc_id, {**cur, "expire_at": now + timedelta(seconds=seconds)})
            return True

        return bool(await self._tx(_fn))

    async def delete(self, *keys: str | bytes) -> int:
        if not keys:
            return 0
        ids = [kv_doc_id(k) for k in keys]

        async def _fn(tx: Any) -> int:
            now = _now()
            n = 0
            current = [await tx.raw_get(KV, i) for i in ids]
            for i, cur in zip(ids, current, strict=True):
                if cur is not None:
                    if _live(cur, now) is not None:
                        n += 1
                    tx.raw_delete(KV, i)
            return n

        return int(await self._tx(_fn))

    def pipeline(self, transaction: bool = True) -> _Pipeline:
        return _Pipeline(self)

    async def aclose(self) -> None:
        """The Firestore client is process-wide (``app.core.firestore.lifecycle.close``)."""
        return None


class FirestoreRateLimitBackend:
    """``app.core.ratelimit.Backend`` on ``lms_kv``: exact fixed-window counters."""

    def __init__(self, client: Any | None = None) -> None:
        self._kv = FirestoreRedis(client)

    async def incr(self, keys: list[tuple[str, int]]) -> list[int]:
        if keys and all(_WINDOW_KEY.match(k) for k, _ttl in keys):
            return await self._incr_windows(keys)
        ids = [(kv_doc_id(k), k, ttl) for k, ttl in keys]

        async def _fn(tx: Any) -> list[int]:
            now = _now()
            current = [_live(await tx.raw_get(KV, i), now) for i, _k, _t in ids]
            out: list[int] = []
            for (i, k, ttl), cur in zip(ids, current, strict=True):
                n = (int(bytes(cur.get("v", b"0"))) if cur is not None else 0) + 1
                # Same as the Redis pipeline: INCR then EXPIRE ttl+1 (the TTL restarts on each hit).
                tx.raw_set(
                    KV, i, {"k": k, "v": str(n).encode(), "expire_at": now + timedelta(seconds=ttl + 1)}
                )
                out.append(n)
            return out

        return list(await self._kv._tx(_fn))

    async def _incr_windows(self, keys: list[tuple[str, int]]) -> list[int]:
        """Fixed-window keys of ``app.core.ratelimit`` (``rl:<key>:<window_s>:<index>``): one
        atomic batch of server-side ``Increment(1)`` writes, the new counts come back in the commit
        response -- 1 billed write per key and no read (the transaction above costs a read + a
        write per key). Exactly the same counts: a window key is only ever used inside its own
        window and its ``expire_at`` is that window's end + 1 s, so the transaction's "expired ->
        start from 0" branch can never apply to it (the TTL policy removes the document later)."""
        from google.cloud.firestore import Increment

        now = _now()
        batch = self._kv.client.batch()
        for k, ttl in keys:
            batch.set(
                self._kv._ref(k),
                {"k": k, "n": Increment(1), "expire_at": now + timedelta(seconds=ttl + 1)},
                merge=True,
            )
        results = await batch.commit()
        return [int(r.transform_results[0].integer_value) for r in results]

    async def incr_colocated(self, group: str, span_s: int, keys: list[tuple[str, int]]) -> list[int]:
        """``ratelimit.check_colocated``: the window counters of ``keys`` (all window keys of the
        same request) as fields of ONE document per (``group``, ``span_s`` window) -> 1 billed
        write for all of them. Field = hash of the window key, so every window counter is its own
        exact count; a window nests in exactly one span (window divides span, both epoch-aligned),
        so a key's window always lands in the same document."""
        from google.cloud.firestore import Increment

        spans = set()
        fields: list[str] = []
        for k, _ttl in keys:
            m = _WINDOW_KEY.match(k)
            if m is None:
                raise ValueError(f"not a rate-limit window key: {k!r}")
            window_s, index = int(m.group(1)), int(m.group(2))
            if span_s % window_s:
                raise ValueError("window does not divide the span")
            spans.add(index * window_s // span_s)
            fields.append("c" + kv_doc_id(k)[:32])
        if len(spans) != 1:
            raise ValueError("keys of one call must share the span window")
        span = spans.pop()
        doc_key = f"rlg:{group}:{span_s}:{span}"
        doc: dict[str, Any] = {
            "k": doc_key,
            "expire_at": datetime.fromtimestamp((span + 1) * span_s + 1, tz=UTC),
        }
        for f in fields:
            doc[f] = Increment(1)
        batch = self._kv.client.batch()
        batch.set(self._kv._ref(doc_key), doc, merge=True)
        (result,) = await batch.commit()
        # The client sends field transforms sorted by field path (plain names: string order).
        counts = (int(v.integer_value) for v in result.transform_results)
        by_field = dict(zip(sorted(set(fields)), counts, strict=True))
        return [by_field[f] for f in fields]

    async def peek(self, keys: list[str]) -> list[int]:
        if not keys:
            return []
        now = _now()
        counts: dict[str, int] = {}
        async for snap in self._kv.client.get_all([self._kv._ref(k) for k in keys]):
            data = _live(snap.to_dict() if snap.exists else None, now)
            if data is None:
                continue
            counts[snap.id] = int(data["n"]) if "n" in data else int(bytes(data.get("v", b"0")))
        return [counts.get(kv_doc_id(k), 0) for k in keys]
