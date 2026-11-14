"""sessions on Firestore: devices, user devices, session lifecycle, revocation, login attempts
and back-off, the resolver's lookup helpers, backfill/verify (emulator only)."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.ids import uuid7
from app.core.security import get_keyring, hash_token
from app.modules.identity.fs_codec import obj_doc, row_doc
from app.modules.sessions import service as ss
from app.modules.sessions.models import AuthSession, LoginAttempt, UserDevice
from app.modules.sessions.repo_firestore import SessionsRepo, system_repo
from app.modules.sessions.ua import parse_ua
from tests.identity.fs.conftest import FakePgSession

S: Any = None
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def info(token: str | None = None, ip: str | None = "203.0.113.7") -> ss.ClientInfo:
    return ss.ClientInfo(ip=ip, ua=parse_ua(UA), device_token=token)


def test_repo_is_scoped() -> None:
    from app.core.firestore.repository import assert_repository_scoped

    assert_repository_scoped(SessionsRepo)


async def test_devices(fs: Any) -> None:
    dev, raw, issued = await ss.resolve_device(S, info())
    assert issued and raw
    again, raw2, issued2 = await ss.resolve_device(S, info(raw))
    assert again.id == dev.id and raw2 == raw and not issued2
    assert await ss.device_hash_matches(S, dev.id, raw)
    assert not await ss.device_hash_matches(S, dev.id, "x" * 22)
    uid = uuid.uuid4()
    uds = await asyncio.gather(*(ss.ensure_user_device(S, uid, dev) for _ in range(4)))
    assert len({u.id for u in uds}) == 1  # ux_ud_user_device under concurrency
    ud = uds[0]
    assert ud.trust_status == "pending_otp" and (await ss.get_user_device(S, uid, dev.id)).id == ud.id  # type: ignore[union-attr]
    await ss.trust_device(S, ud, "email_otp", owner_verified=True)
    assert [d.id for d in await ss.trusted_devices(S, uid)] == [ud.id]
    assert not await ss.has_device_history(S, uid)
    dev2, _r, _i = await ss.resolve_device(S, info())
    ud2 = await ss.ensure_user_device(S, uid, dev2)
    assert await ss.has_device_history(S, uid)
    s, _tok = await ss.create_session(
        S,
        user_id=uid,
        tier="student",
        status="active",
        created_via="password",
        info=info(raw),
        device=dev,
        user_device=ud,
        amr=["pwd"],
    )
    ended = await ss.remove_user_device(S, ud, "self_service_signout", removed_by=uid)
    assert ended == 1 and (await system_repo().get_session(s.id)).status == "revoked"  # type: ignore[union-attr]
    assert await ss.get_user_device(S, uid, dev.id) is None
    fresh = await ss.ensure_user_device(S, uid, dev)  # the slot is free again
    assert fresh.id != ud.id
    await ss.trust_device(S, ud2, "email_otp", owner_verified=False)  # sign-out + new device = replacement
    used, nxt = await ss.replacements_used(S, uid)
    assert used == 1 and nxt is not None


async def test_session_lifecycle_and_lookup(fs: Any) -> None:
    uid = uuid.uuid4()
    s, token = await ss.create_session(
        S,
        user_id=uid,
        tier="staff",
        status="pending_mfa",
        created_via="password",
        info=info(),
        device=None,
        user_device=None,
        amr=["pwd", "pwd"],
    )
    repo = system_repo()
    got = await repo.session_by_token(hash_token(token))
    assert got is not None and got.id == s.id and got.amr == ["pwd"] and got.scope == "full"
    assert got.idle_expires_at <= got.created_at + timedelta(minutes=10, seconds=1)
    await ss.activate_session(S, got)
    assert (await repo.get_session(s.id)).status == "active"  # type: ignore[union-attr]
    new_token = await ss.rotate_token(S, got)
    assert await repo.session_by_token(hash_token(token)) is None
    assert (await repo.session_by_token(hash_token(new_token))).id == s.id  # type: ignore[union-attr]
    assert [x.id for x in await ss.active_sessions(S, uid)] == [s.id]
    # an ended session is never resurrected by a stale writer
    stale = await repo.get_session(s.id)
    await ss.end_session(S, got, status="revoked", reason="user_logout")
    assert stale is not None
    await ss.activate_session(S, stale)
    assert (await repo.get_session(s.id)).status == "revoked"  # type: ignore[union-attr]
    assert stale.status == "revoked"
    assert await ss.active_sessions(S, uid) == []


async def test_revoke_all(fs: Any) -> None:
    from app.modules.identity.models import User
    from app.modules.identity.repo_firestore import system_repo as identity_repo

    uid = uuid7()
    await identity_repo().create_user(User(id=uid, email="s@x.in", status="active", is_minor=False))
    made = []
    for _ in range(3):
        s, _t = await ss.create_session(
            S,
            user_id=uid,
            tier="student",
            status="active",
            created_via="password",
            info=info(),
            device=None,
            user_device=None,
            amr=["pwd"],
        )
        made.append(s)
    n = await ss.revoke_all_sessions(S, uid, "password_changed", except_session_id=made[0].id)
    assert n == 2
    assert [x.id for x in await ss.active_sessions(S, uid)] == [made[0].id]
    assert (await identity_repo().get_user(uid)).sessions_valid_after is None  # type: ignore[union-attr]
    n = await ss.revoke_all_sessions(S, uid, "admin_kill")
    assert n == 1 and (await identity_repo().get_user(uid)).sessions_valid_after is not None  # type: ignore[union-attr]


async def test_login_attempts_backoff_and_ip_limit(fs: Any) -> None:
    ident = get_keyring("login").sign("someone@x.in")
    uid = uuid.uuid4()
    assert await ss.backoff_remaining(S, [ident]) == 0
    await ss.record_login_attempt(S, identifier=ident, user_id=uid, outcome="bad_credentials", info=info())
    assert await ss.backoff_remaining(S, [ident]) == 1  # base 1 s
    await ss.record_login_attempt(S, identifier=ident, user_id=uid, outcome="bad_credentials", info=info())
    assert await ss.backoff_remaining(S, [ident]) == 2  # 1 * 2^(2-1)
    await ss.record_login_attempt(
        S, identifier=ident, user_id=uid, outcome="bad_credentials", info=info(), pre_auth_blocked=True
    )
    assert await ss.backoff_remaining(S, [ident]) == 2  # pre-auth blocks don't count
    await ss.record_login_attempt(S, identifier=ident, user_id=uid, outcome="success", info=info())
    assert await ss.backoff_remaining(S, [ident]) == 0  # success resets
    await ss.record_login_attempt(S, identifier=ident, user_id=uid, outcome="mfa_failed", info=info())
    from app.modules.identity import service as ids

    assert await ids.mfa_failures_recent(S, uid) == 1
    assert not await ss.ip_failures_exceeded(S, "203.0.113.7")
    assert not await ss.ip_failures_exceeded(S, None)


async def test_end_sessions_reads_only_open_sessions(fs: Any, monkeypatch: Any) -> None:
    """Cost: ending a user's sessions (sign-in "replaced_same_device", revoke-all, restrictions)
    reads the not-ended sessions only, not the whole sign-in history; same sessions end."""
    from google.api_core import exceptions as gexc

    from app.modules.identity.models import User
    from app.modules.identity.repo_firestore import system_repo as identity_repo

    uid = uuid7()
    await identity_repo().create_user(User(id=uid, email="hist@x.in", status="active", is_minor=False))
    made = []
    for status in ("active", "active", "active", "pending_mfa", "active"):
        s, _t = await ss.create_session(
            S, user_id=uid, tier="student", status=status, created_via="password", info=info(),
            device=None, user_device=None, amr=["pwd"],
        )  # fmt: skip
        made.append(s)
    repo = system_repo()
    assert await repo.end_sessions(uid, status="revoked", reason="user_logout", where=lambda o: o.id in {made[0].id, made[1].id}) == 2
    seen: list[str] = []
    real = SessionsRepo._objs

    async def spy(self: Any, model: Any, collection: str, **kw: Any) -> Any:
        rows = await real(self, model, collection, **kw)
        if collection == "auth_sessions":
            seen.extend(r.status for r in rows)
        return rows

    monkeypatch.setattr(SessionsRepo, "_objs", spy)
    n = await repo.end_sessions(uid, status="revoked", reason="admin_kill", where=lambda o: o.id != made[4].id)
    assert n == 2  # made[2] (active) and made[3] (pending_mfa); the two ended ones are not even read
    assert sorted(seen) == ["active", "active", "pending_mfa"]
    statuses = {s.id: s.status for s in await repo.sessions_for(uid)}
    assert [statuses[m.id] for m in made] == ["revoked", "revoked", "revoked", "revoked", "active"]

    real_objs = real

    async def refuse(self: Any, model: Any, collection: str, **kw: Any) -> Any:
        if collection == "auth_sessions" and kw.get("filters"):
            raise gexc.FailedPrecondition("The query requires an index.")
        return await real_objs(self, model, collection, **kw)

    monkeypatch.setattr(SessionsRepo, "_objs", refuse)  # fallback: the whole history, same answer
    assert await repo.end_sessions(uid, status="revoked", reason="admin_kill") == 1


async def test_touch_engaged_skips_only_writes_that_change_nothing(fs: Any, monkeypatch: Any) -> None:
    """Cost: a credited heartbeat writes the session only when the idle expiry moves or
    ``last_seen_at`` is older than the resolver's own 60 s granularity."""
    from datetime import timedelta as td

    from app.modules.identity import clock
    from app.modules.identity.models import User
    from app.modules.identity.repo_firestore import system_repo as identity_repo
    from app.modules.sessions.resolver import touch_engaged

    uid = uuid7()
    await identity_repo().create_user(User(id=uid, email="touch@x.in", status="active", is_minor=False))
    t0 = datetime.now(UTC)
    now = [t0]
    monkeypatch.setattr(clock, "now", lambda: now[0])
    monkeypatch.setattr(ss, "postgres_available", lambda: False)  # the Firebase stack: NO_POSTGRES
    s, _t = await ss.create_session(
        S, user_id=uid, tier="student", status="active", created_via="password", info=info(),
        device=None, user_device=None, amr=["pwd"],
    )  # fmt: skip
    repo = system_repo()
    saves: list[Any] = []
    real_save = ss.save_session

    async def counting(session: Any, obj: Any) -> Any:
        saves.append(obj.last_seen_at)
        return await real_save(session, obj)

    monkeypatch.setattr(ss, "save_session", counting)

    # normal timeouts: the idle expiry moves on every credit -> always written (as before)
    now[0] = t0 + td(seconds=10)
    await touch_engaged(s.id)
    now[0] = t0 + td(seconds=20)
    await touch_engaged(s.id)
    assert len(saves) == 2
    cur = await repo.get_session(s.id)
    assert cur.last_seen_at == now[0] and cur.idle_expires_at == min(now[0] + ss.session_timeouts("student")[0], cur.absolute_expires_at)  # type: ignore[union-attr]

    # idle expiry capped at the absolute expiry (e.g. TD_SIMPLE_AUTH): a credit 30 s later changes
    # nothing a reader uses -> no write; 61 s after the last write -> written again
    cap = (cur.absolute_expires_at - now[0]) + td(hours=1)  # type: ignore[union-attr]
    monkeypatch.setattr(ss, "session_timeouts", lambda tier: (cap, cap))
    now[0] = t0 + td(seconds=30)
    await touch_engaged(s.id)  # first capped credit: idle moves to the absolute expiry -> write
    assert len(saves) == 3
    now[0] = t0 + td(seconds=60)
    await touch_engaged(s.id)
    assert len(saves) == 3
    now[0] = t0 + td(seconds=91)
    await touch_engaged(s.id)
    assert len(saves) == 4 and (await repo.get_session(s.id)).last_seen_at == now[0]  # type: ignore[union-attr]


async def test_ip_failure_count_is_an_aggregation_with_the_same_number(fs: Any, monkeypatch: Any) -> None:
    """Cost: the per-login IP failure check counts with one aggregation instead of reading every
    attempt from that IP (a campus NAT); same number, and the old full read answers if the
    project refuses the aggregation (missing composite index)."""
    from google.api_core import exceptions as gexc

    from app.core.firestore.store import ScopedStore

    ip = "198.51.100.9"
    ident = get_keyring("login").sign("nat@x.in")
    for outcome in ("bad_credentials", "unknown_identifier", "success", "mfa_failed", "bad_credentials"):
        await ss.record_login_attempt(S, identifier=ident, user_id=None, outcome=outcome, info=info(ip=ip))
    await ss.record_login_attempt(S, identifier=ident, user_id=None, outcome="bad_credentials", info=info(ip="192.0.2.1"))
    since = datetime.now(UTC) - timedelta(minutes=10)
    repo = system_repo()
    assert await repo.count_attempts(ip=ip, outcomes=ss.FAILURE_OUTCOMES, since=since) == 3
    assert await repo.count_attempts(ip=ip, since=since) == 5
    assert await repo.count_attempts(ip=ip, outcome="success", since=since) == 1

    async def refused(*a: Any, **kw: Any) -> int:
        raise gexc.FailedPrecondition("The query requires an index.")

    monkeypatch.setattr(ScopedStore, "count", refused)
    assert await system_repo().count_attempts(ip=ip, outcomes=ss.FAILURE_OUTCOMES, since=since) == 3
    assert await system_repo().count_attempts(ip=ip, since=since) == 5


async def test_backfill_and_verify(fs: Any) -> None:
    from app.core.firestore.backfill import backfill, verify

    now = datetime(2026, 11, 12, tzinfo=UTC)
    uid, dev = uuid.uuid4(), uuid.uuid4()
    ud = UserDevice(
        id=uuid.uuid4(),
        user_id=uid,
        device_id=dev,
        trust_status="trusted",
        counts_toward_cap=True,
        remember_token_hash=b"\x05",
        created_at=now,
        updated_at=now,
    )
    gone = UserDevice(
        id=uuid.uuid4(),
        user_id=uid,
        device_id=dev,
        trust_status="removed",
        counts_toward_cap=True,
        created_at=now,
        updated_at=now,
    )
    s = AuthSession(
        id=uuid.uuid4(),
        token_hash=b"\x07" * 32,
        user_id=uid,
        client_type="web",
        session_tier="student",
        scope="full",
        status="active",
        aal=1,
        amr=["pwd"],
        created_via="password",
        auth_time=now,
        remember_device=False,
        restriction_level_at_issue=0,
        created_at=now,
        last_seen_at=now,
        idle_expires_at=now,
        absolute_expires_at=now,
        ip_first="10.1.2.3",
        updated_at=now,
    )
    la = LoginAttempt(
        id=uuid.uuid4(),
        attempted_at=now,
        identifier_hash=b"\x01",
        key_version=1,
        method="password",
        outcome="success",
        pre_auth_blocked=False,
    )

    def rows(*objs: Any) -> list[dict[str, Any]]:
        return [{c.name: getattr(o, c.key) for c in type(o).__table__.columns} for o in objs]  # type: ignore[attr-defined]

    pg = FakePgSession(
        {"user_devices": rows(ud, gone), "auth_sessions": rows(s), "login_attempts": rows(la)},
        {"trust_status <> 'removed'": lambda r: r["trust_status"] != "removed"},
    )
    written = await backfill(pg, "sessions", client=fs)  # type: ignore[arg-type]
    assert written["user_devices"] == 2 and written["user_devices_live"] == 1
    reports = await verify(pg, "sessions", client=fs)  # type: ignore[arg-type]
    assert all(r.ok for r in reports), [r.as_dict() for r in reports if not r.ok]
    assert obj_doc(s) == row_doc(AuthSession, rows(s)[0])
    repo = system_repo()
    assert (await repo.session_by_token(b"\x07" * 32)).ip_first == "10.1.2.3"  # type: ignore[union-attr]
    assert (await repo.live_user_device(uid, dev)).id == ud.id  # type: ignore[union-attr]
    assert (await repo.user_device_by_remember(b"\x05")).id == ud.id  # type: ignore[union-attr]
