"""Firestore replacement for the Redis cache (emulator): Redis semantics, rate limits, entitlements."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.core import ratelimit
from app.core.errors import ProblemError
from app.core.firestore import kv as kv_mod
from app.core.firestore.kv import FirestoreRateLimitBackend, FirestoreRedis


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    now = [datetime(2026, 11, 12, 10, 0, tzinfo=UTC)]
    monkeypatch.setattr(kv_mod, "_now", lambda: now[0])
    return now


async def test_get_set_returns_bytes_like_redis(fs_client: Any) -> None:
    r = FirestoreRedis(fs_client)
    assert await r.get("k1") is None
    assert await r.set("k1", "hello") is True
    assert await r.get("k1") == b"hello"
    assert await r.set("k1", 42) is True
    assert int(await r.get("k1")) == 42  # type: ignore[arg-type]
    assert await r.ping() is True
    with pytest.raises(TypeError):
        await r.set("k1", True)


async def test_expiry_nx_xx_ttl(fs_client: Any, clock: list[datetime]) -> None:
    r = FirestoreRedis(fs_client)
    await r.set("e", "v", ex=60)
    assert 59 <= await r.ttl("e") <= 60
    assert await r.set("e", "other", nx=True) is None
    assert await r.set("missing", "x", xx=True) is None
    clock[0] += timedelta(seconds=61)
    assert await r.get("e") is None
    assert await r.ttl("e") == -2
    assert await r.set("e", "again", nx=True) is True
    assert await r.ttl("e") == -1
    await r.set("p", "v", px=1500)
    clock[0] += timedelta(seconds=2)
    assert await r.get("p") is None


async def test_incr_keeps_ttl_and_expire_delete(fs_client: Any, clock: list[datetime]) -> None:
    r = FirestoreRedis(fs_client)
    assert await r.incr("c") == 1
    assert await r.incr("c") == 2
    assert await r.expire("c", 30) is True
    assert await r.incr("c") == 3
    assert 29 <= await r.ttl("c") <= 30
    assert await r.expire("nope", 30) is False
    await r.set("bad", "x")
    with pytest.raises(ValueError):
        await r.incr("bad")
    assert await r.delete("c", "bad", "nope") == 2
    assert await r.get("c") is None
    assert await r.exists("c") == 0


async def test_mget_and_pipeline(fs_client: Any) -> None:
    r = FirestoreRedis(fs_client)
    await r.set("a", "1")
    await r.set("b", "2")
    assert await r.mget(["a", "zz", "b"]) == [b"1", None, b"2"]
    pipe = r.pipeline()
    pipe.incr("ent:ver:u1")
    pipe.expire("ent:ver:u1", 7 * 86_400)
    assert await pipe.execute() == [1, True]
    assert await r.get("ent:ver:u1") == b"1"


async def test_concurrent_incr_is_exact(fs_client: Any) -> None:
    r = FirestoreRedis(fs_client)
    results = await asyncio.gather(*(r.incr("hot") for _ in range(8)))
    assert sorted(results) == list(range(1, 9))
    assert await r.get("hot") == b"8"


async def test_rate_limit_backend_429_like_redis(fs_client: Any) -> None:
    prev = ratelimit.set_backend(FirestoreRateLimitBackend(fs_client))
    try:
        rules = (ratelimit.Rule(3, 60),)
        for _ in range(3):
            await ratelimit.hit("login:ip:1.2.3.4", rules, scope="login")
        assert await ratelimit.exhausted("login:ip:1.2.3.4", rules)
        with pytest.raises(ProblemError) as ei:
            await ratelimit.hit("login:ip:1.2.3.4", rules, scope="login")
        assert ei.value.code == "rate_limited"
        assert ei.value.headers["RateLimit-Policy"] == '"login";q=3;w=60'
        assert not await ratelimit.exhausted("login:ip:9.9.9.9", rules)
    finally:
        ratelimit.set_backend(prev)


async def test_entitlement_cache_runs_on_the_facade(fs_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """The unchanged entitlements cache module works against the Firestore facade."""
    from app.modules.entitlements import cache

    facade = FirestoreRedis(fs_client)
    monkeypatch.setattr(cache, "_redis", lambda: facade)
    uid = uuid.uuid4()
    assert await cache.version(uid) == 0
    await cache.bump(uid)
    await cache.bump(uid)
    assert await cache.version(uid) == 2


async def test_window_counters_are_server_increments_without_reads(
    fs_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cost: ``app.core.ratelimit`` window keys are counted with ``Increment`` writes (no read, no
    transaction), with the same counts, concurrency-exact, and ``exhausted`` sees them."""
    backend = FirestoreRateLimitBackend(fs_client)

    async def no_tx(fn: Any) -> Any:
        raise AssertionError("window keys must not open a transaction")

    monkeypatch.setattr(backend._kv, "_tx", no_tx)
    prev = ratelimit.set_backend(backend)
    try:
        rules = (ratelimit.Rule(5, 60), ratelimit.Rule(50, 3600))
        results = await asyncio.gather(*(ratelimit.check("anl:u:probe", rules) for _ in range(5)))
        assert results == [None] * 5
        assert await ratelimit.exhausted("anl:u:probe", rules)
        with pytest.raises(ProblemError) as ei:
            await ratelimit.hit("anl:u:probe", rules, scope="user")
        assert ei.value.code == "rate_limited" and ei.value.headers["RateLimit-Policy"] == '"user";q=5;w=60'
        assert not await ratelimit.exhausted("anl:u:other", rules)
        keys = [k for k, _r, _t in ratelimit._windows("anl:u:probe", rules)]
        assert await backend.peek(keys) == [6, 6]
        snap = await fs_client.collection("lms_kv").document(kv_mod.kv_doc_id(keys[0])).get()
        doc = snap.to_dict()
        assert doc["k"] == keys[0] and doc["n"] == 6 and doc["expire_at"] is not None
    finally:
        ratelimit.set_backend(prev)


async def test_window_counter_peek_reads_a_pre_change_counter(fs_client: Any) -> None:
    """A counter written before the change (bytes ``v``) is still read by ``peek``."""
    await FirestoreRedis(fs_client).set("rl:x:60:1", b"4", ex=60)
    assert await FirestoreRateLimitBackend(fs_client).peek(["rl:x:60:1", "rl:none:60:1"]) == [4, 0]


async def test_other_keys_keep_the_transaction_and_expiry_restart(fs_client: Any, clock: list[datetime]) -> None:
    """Keys that are not ratelimit windows (e.g. the Google ID-token replay guard) restart after
    expiry exactly like Redis INCR + EXPIRE."""
    backend = FirestoreRateLimitBackend(fs_client)
    assert await backend.incr([("auth_google_idt:abc", 3600)]) == [1]
    assert await backend.incr([("auth_google_idt:abc", 3600)]) == [2]
    clock[0] += timedelta(seconds=3602)
    assert await backend.incr([("auth_google_idt:abc", 3600)]) == [1]


async def test_colocated_counters_match_separate_checks(fs_client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """``check_colocated`` (analytics: session + user counters in one document per minute) gives
    exactly the answers of separate ``check`` calls, in one write per call."""
    rules = [("anl:s:S1", ratelimit.Rule(4, 60)), ("anl:sb:S1", ratelimit.Rule(2, 10)), ("anl:u:U1", ratelimit.Rule(5, 60))]
    other = [("anl:s:S2", ratelimit.Rule(4, 60)), ("anl:sb:S2", ratelimit.Rule(2, 10)), ("anl:u:U1", ratelimit.Rule(5, 60))]

    async def run(backend: Any) -> list[list[str | None]]:
        prev = ratelimit.set_backend(backend)
        try:
            out = []
            for checks in (rules, rules, other, rules, other, rules):
                probs = await ratelimit.check_colocated(checks, group="anl:u:U1", span_s=60, scope="user")
                out.append([p.headers["RateLimit-Policy"] if p else None for p in probs])
            return out
        finally:
            ratelimit.set_backend(prev)

    # one minute-aligned instant for both runs (the 10 s and 60 s windows must not roll over)
    import time as _t
    import types

    base = (int(_t.time()) // 60) * 60 + 5
    monkeypatch.setattr(ratelimit, "time", types.SimpleNamespace(time=lambda: base))
    try:
        commits: list[int] = []
        fs_backend = FirestoreRateLimitBackend(fs_client)
        real_batch = fs_client.batch

        def counting_batch() -> Any:
            b = real_batch()
            orig = b.commit

            async def commit(*a: Any, **kw: Any) -> Any:
                commits.append(len(b._write_pbs))
                return await orig(*a, **kw)

            b.commit = commit
            return b

        fs_backend._kv._client = type("C", (), {"batch": staticmethod(counting_batch), "collection": fs_client.collection, "get_all": fs_client.get_all})()
        got = await run(fs_backend)
        want = await run(ratelimit.MemoryBackend())
    finally:
        monkeypatch.undo()
    assert got == want
    assert want[3] == [None, '"user";q=2;w=10', None]  # third hit of S1 in 10 s
    assert want[5][2] == '"user";q=5;w=60'  # sixth request of U1 this minute
    assert commits == [1] * 6  # one document written per call


async def test_colocated_rejects_windows_that_do_not_nest() -> None:
    with pytest.raises(ValueError):
        await ratelimit.check_colocated([("k", ratelimit.Rule(1, 7))], group="g", span_s=60)
