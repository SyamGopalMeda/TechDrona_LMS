"""Round 7 additions: ``fs_journal.savepoint()``, the login-attempt network prefix query, and
the session-cap serialisation (``sessions.lock_user`` -> ``request_locks``) under concurrency."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import app.modules.identity.store_specs  # noqa: F401 - registers the collections used below
from app.modules.identity import public as ipub
from app.modules.identity.fs_journal import JournalingStore, journal, savepoint
from app.modules.sessions import public as spub
from app.modules.sessions import service as ss
from app.modules.sessions.ua import parse_ua
from tests.identity.fs.conftest import fs_user

S: Any = None
COLL = "users_by_username"  # any registered system collection works for the journal tests


# --------------------------------------------------------------------------- savepoint


async def _val(store: Any, doc_id: str) -> Any:
    d = await store.get(COLL, doc_id)
    return None if d is None else d["user_id"]


async def test_savepoint_failure_inside_successful_outer(fs: Any) -> None:
    store = JournalingStore.system("test.sp")
    await store.create(COLL, {"user_id": "base"}, doc_id="x")
    async with journal():
        await store.run_transaction(lambda tx: tx.update(COLL, "x", {"user_id": "outer"}))
        try:
            async with savepoint():
                await store.create(COLL, {"user_id": "inner"}, doc_id="y")
                await store.run_transaction(lambda tx: tx.update(COLL, "x", {"user_id": "inner-x"}))
                raise ValueError("detector failed")
        except ValueError:
            pass  # swallowed: the savepoint's own writes are already undone
        assert await _val(store, "y") is None
        assert await _val(store, "x") == "outer"  # back to the state at savepoint entry
        await store.create(COLL, {"user_id": "after"}, doc_id="z")
    # the outer scope succeeded: its writes stay
    assert await _val(store, "x") == "outer" and await _val(store, "z") == "after"


async def test_successful_savepoint_joins_outer_rollback(fs: Any) -> None:
    store = JournalingStore.system("test.sp")
    await store.create(COLL, {"user_id": "base"}, doc_id="x")
    with pytest.raises(RuntimeError):
        async with journal():
            async with savepoint():
                await store.create(COLL, {"user_id": "inner"}, doc_id="y")
                await store.run_transaction(lambda tx: tx.update(COLL, "x", {"user_id": "inner-x"}))
            raise RuntimeError("outer fails later")
    assert await _val(store, "y") is None and await _val(store, "x") == "base"


async def test_savepoint_without_outer_scope(fs: Any) -> None:
    store = JournalingStore.system("test.sp")
    with pytest.raises(KeyError):
        async with savepoint():
            await store.create(COLL, {"user_id": "a"}, doc_id="solo")
            raise KeyError("x")
    assert await _val(store, "solo") is None
    async with savepoint():
        await store.create(COLL, {"user_id": "b"}, doc_id="kept")
    assert await _val(store, "kept") == "b"


# --------------------------------------------------------------------------- network prefix


def test_ip_prefix() -> None:
    assert spub.ip_prefix("203.0.113.77") == "203.0.113.0/24"
    assert spub.ip_prefix("2001:db8:1:2::5") == "2001:db8:1::/48"
    assert spub.ip_prefix(None) is None and spub.ip_prefix("not-an-ip") is None


async def test_attempts_by_prefix_equal_a_full_scan(fs: Any) -> None:
    ident = (1, b"\x01" * 32)
    t0 = datetime.now(UTC)
    for ip, outcome in [
        ("203.0.113.5", "bad_credentials"),
        ("203.0.113.200", "unknown_identifier"),
        ("203.0.114.5", "bad_credentials"),  # other /24
        ("2001:db8:1:ffff::1", "bad_credentials"),
        ("2001:db8:2::1", "bad_credentials"),  # other /48
        ("203.0.113.9", "success"),
    ]:
        info = ss.ClientInfo(ip=ip, ua=parse_ua("Mozilla/5.0 Chrome/130.0"), device_token=None)
        await ss.record_login_attempt(S, identifier=ident, user_id=None, outcome=outcome, info=info)
    since = t0 - timedelta(seconds=1)
    every = await spub.list_login_attempts(S, since=since)
    for ip in ("203.0.113.1", "2001:db8:1::9"):
        net = spub.ip_prefix(ip)
        for outs in (None, ["bad_credentials", "unknown_identifier"]):
            fast = await spub.list_login_attempts_in_prefix(S, ip, since=since, outcomes=outs)
            slow = [a for a in every if spub.ip_prefix(a.ip) == net and (outs is None or a.outcome in outs)]
            assert [a.id for a in fast] == [a.id for a in slow]
    assert len(await spub.list_login_attempts_in_prefix(S, "203.0.113.1", since=since)) == 3
    assert await spub.list_login_attempts_in_prefix(S, "bad", since=since) == []


# --------------------------------------------------------------------------- session cap under concurrency


async def _trusted_browser(http: Any, user: Any) -> Any:
    b = http.fork()
    info = ss.ClientInfo(ip=b.ip, ua=parse_ua(b.ua), device_token=None)
    dev, raw, _new = await ss.resolve_device(S, info)
    ud = await ss.ensure_user_device(S, user.id, dev)
    await ss.trust_device(S, ud, None, owner_verified=True)
    b.device = raw
    return b


async def test_concurrent_logins_respect_the_session_cap(http: Any) -> None:
    """Two simultaneous logins from trusted devices while one session exists (student cap 2):
    ``lock_user`` serialises the cap check, so exactly one gets in and the other is asked to
    choose -- never three active sessions."""
    u = await fs_user("cap@x.in")
    first = await http.login(u.email, u.password)
    assert first.json()["result"] == "authenticated", first.text
    b2, b3 = await _trusted_browser(http, u), await _trusted_browser(http, u)
    r2, r3 = await asyncio.gather(b2.login(u.email, u.password), b3.login(u.email, u.password))
    outcomes = sorted((r.json().get("result") or r.json().get("code")) for r in (r2, r3))
    assert outcomes == ["authenticated", "session_cap_reached"], (r2.text, r3.text)
    active = await spub.list_sessions(S, user_id=u.id, active_at=datetime.now(UTC))
    assert len(active) == 2
    assert (await ipub.get_user(S, u.id)) is not None


async def test_shared_devices_of_user_matches_the_having_query(fs: Any) -> None:
    """``sessions.public.shared_devices_of_user`` (security SH-11) against expectations computed
    from the fixture rows with the SQL's rules (last_used_at > since, distinct accounts >= N)."""
    import uuid as _uuid

    from app.modules.sessions.models import UserDevice
    from app.modules.sessions.repo_firestore import system_repo as srepo

    now = datetime.now(UTC)
    since = now - timedelta(days=7)
    me = _uuid.uuid4()
    d_shared, d_old, d_mine_only, d_three = (_uuid.uuid4() for _ in range(4))
    others = [_uuid.uuid4() for _ in range(4)]
    rows: list[tuple[_uuid.UUID, _uuid.UUID, datetime | None]] = [
        (me, d_shared, now),
        *[(o, d_shared, now - timedelta(days=1)) for o in others[:3]],  # 4 accounts recently
        (me, d_old, now),
        *[(o, d_old, now - timedelta(days=30)) for o in others],  # others too old: only 1 recent
        (me, d_mine_only, None),  # never used
        (me, d_three, now),
        *[(o, d_three, now) for o in others[:2]],  # 3 accounts: below N=4
        (others[3], d_shared, None),  # a never-used row does not count
    ]
    for u, d, used in rows:
        await srepo().save_user_device(
            UserDevice(
                id=_uuid.uuid4(),
                user_id=u,
                device_id=d,
                trust_status="trusted",
                counts_toward_cap=True,
                last_used_at=used,
            )
        )
    recent: dict[_uuid.UUID, set[_uuid.UUID]] = {}
    for u, d, used in rows:
        if used is not None and used > since:
            recent.setdefault(d, set()).add(u)
    expected = [d for u, d, _ in rows if u == me and len(recent.get(d, ())) >= 4]
    got = await spub.shared_devices_of_user(S, me, min_accounts=4, since=since)
    assert sorted(got) == sorted(expected) == [d_shared]
    assert sorted(await spub.shared_devices_of_user(S, me, min_accounts=3, since=since)) == sorted(
        [d_shared, d_three]
    )
    assert await spub.shared_devices_of_user(S, _uuid.uuid4(), min_accounts=1, since=since) == []
