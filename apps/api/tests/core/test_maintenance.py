"""DB-02 / DB-04: maint.* partition maintenance and retention purge (migration core_base_0002).

Every DB test runs inside a transaction that is rolled back, so no partition or deletion leaks
into the shared test database.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from tests.conftest import TEST_DB_NAME

FUNCS = (
    "maint.ensure_partitions(regclass, integer)",
    "maint.drop_expired_partitions(regclass)",
    "maint.purge_expired_rows(text, integer, integer)",
    "maint.run_partition_maintenance(integer)",
    "maint.run_retention(integer, integer)",
)


@pytest.fixture
async def owner(owner_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with owner_engine.connect() as conn:
        tx = await conn.begin()
        await conn.execute(text("SELECT set_config('app.maint', 'on', true)"))
        try:
            yield conn
        finally:
            await tx.rollback()


def _maintenance_url() -> str | None:
    from app.core.security import load_env_mapping

    raw = load_env_mapping().get("DATABASE_MAINTENANCE_URL")
    if not raw:
        return None
    return (
        make_url(raw)
        .set(database=TEST_DB_NAME, drivername="postgresql+asyncpg")
        .render_as_string(hide_password=False)
    )


async def _scalar(conn: AsyncConnection, sql: str, **params: Any) -> Any:
    return (await conn.execute(text(sql), params)).scalar()


# --------------------------------------------------------------------------- grants


async def test_maint_functions_are_definer_with_pinned_path_and_maintenance_only(owner) -> None:
    for sig in FUNCS:
        row = (
            await owner.execute(
                text(
                    "SELECT p.prosecdef, p.proconfig, pg_get_userbyid(p.proowner) "
                    "FROM pg_proc p WHERE p.oid = CAST(:s AS regprocedure)"
                ),
                {"s": sig},
            )
        ).one()
        assert row[0] is True, sig
        assert any(c.startswith("search_path=pg_catalog") for c in row[1]), (sig, row[1])
        for role, allowed in (("td_maintenance", True), ("td_app", False), ("td_readonly", False)):
            got = await _scalar(
                owner, "SELECT has_function_privilege(:r, CAST(:s AS regprocedure), 'EXECUTE')", r=role, s=sig
            )
            assert got is allowed, (role, sig)


async def test_retention_registry_covers_privacy_jobs(owner) -> None:
    rows = dict(
        (
            await owner.execute(text("SELECT table_name, retention_interval::text FROM retention_policies"))
        ).all()
    )
    assert rows["login_attempts"] == "395 days" and rows["auth_sessions"] == "395 days"
    assert rows["security_signals"] == "180 days" and rows["playback_sessions"] == "180 days"
    assert rows["attempt_events"] == "2 years" and rows["notifications"] == "1 year"
    assert rows["verification_tokens"] == "7 days" and rows["outbox_events"] == "7 days"
    assert "idempotency_keys" in rows


# --------------------------------------------------------------------------- DB-04


async def _insert_login_attempt(conn: AsyncConnection, days_ago: int) -> uuid.UUID:
    rid = uuid.uuid4()
    await conn.execute(
        text(
            "INSERT INTO login_attempts (id, attempted_at, identifier_hash, key_version, method, outcome) "
            "VALUES (:id, now() - make_interval(days => :w), :h, 1, 'password', 'bad_credentials')"
        ),
        {"id": rid, "w": days_ago, "h": b"\x01" * 32},
    )
    return rid


async def test_db04_new_partition_hardened_like_default_and_default_rows_moved(owner) -> None:
    rid = await _insert_login_attempt(owner, 0)
    res = (await owner.execute(text("SELECT * FROM maint.ensure_partitions('login_attempts', 1)"))).all()
    assert len(res) == 2
    this_month = res[0]
    assert this_month.action == "created_moved" and this_month.moved_rows >= 1, res
    assert res[1].action == "created"
    child = this_month.partition_name
    rls = (
        await owner.execute(
            text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = CAST(:c AS regclass)"),
            {"c": child},
        )
    ).one()
    assert tuple(rls) == (True, True)
    for role in ("td_app", "td_readonly"):
        for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            assert not await _scalar(owner, "SELECT has_table_privilege(:r, :c, :p)", r=role, c=child, p=priv)
    policies = set(
        (
            await owner.execute(text("SELECT policyname FROM pg_policies WHERE tablename = :c"), {"c": child})
        ).scalars()
    )
    assert {"p_o", "p_maint"} <= policies
    # the row now lives in the new child, not in DEFAULT, and is still visible via the parent
    where = f"SELECT count(*) FROM {child} WHERE id = :i"
    assert await _scalar(owner, where, i=rid) == 1
    assert await _scalar(owner, "SELECT count(*) FROM login_attempts_default WHERE id = :i", i=rid) == 0
    assert await _scalar(owner, "SELECT count(*) FROM login_attempts WHERE id = :i", i=rid) == 1
    # DEFAULT is attached again; a second run is a no-op
    assert (
        await _scalar(
            owner,
            "SELECT count(*) FROM pg_partitioned_table WHERE partrelid = 'login_attempts'::regclass AND partdefid <> 0",
        )
        == 1
    )
    again = (
        await owner.execute(text("SELECT action FROM maint.ensure_partitions('login_attempts', 1)"))
    ).scalars()
    assert set(again) == {"exists"}


async def test_db04_immutable_audit_log_month_with_default_rows_is_skipped(owner) -> None:
    await owner.execute(
        text(
            "INSERT INTO audit_log (seq, occurred_at, id, actor_type, action, target_type, prev_hash, row_hash) "
            "VALUES ((SELECT coalesce(max(seq), 0) + 1000000 FROM audit_log), now(), :id, 'system', "
            "'maint.test.row', 'test', :h, :h)"
        ),
        {"id": uuid.uuid4(), "h": b"\x02" * 32},
    )
    res = (await owner.execute(text("SELECT * FROM maint.ensure_partitions('audit_log', 0)"))).all()
    assert [r.action for r in res] == ["skipped_default_rows"]


async def test_db04_refuses_unregistered_tables(owner) -> None:
    with pytest.raises(DBAPIError, match="not a registered partitioned parent"):
        await owner.execute(text("SELECT * FROM maint.ensure_partitions('users', 1)"))


async def test_db04_run_partition_maintenance_covers_every_parent_and_audits(owner) -> None:
    before = await _scalar(
        owner, "SELECT count(*) FROM audit_outbox WHERE record->>'action' = 'maint.partitions.premade'"
    )
    rows = (await owner.execute(text("SELECT * FROM maint.run_partition_maintenance(0)"))).all()
    assert len({r.parent for r in rows}) == 10
    after = await _scalar(
        owner, "SELECT count(*) FROM audit_outbox WHERE record->>'action' = 'maint.partitions.premade'"
    )
    assert after == before + 1


# --------------------------------------------------------------------------- DB-02


async def test_db02_purge_deletes_only_expired_rows(owner) -> None:
    old_la = await _insert_login_attempt(owner, 400)
    new_la = await _insert_login_attempt(owner, 10)
    ids = {
        k: uuid.uuid4()
        for k in ("tok_old", "tok_new", "tok_live", "ob_old", "ob_new", "ob_pending", "idem_old", "idem_live")
    }
    await owner.execute(
        text(
            "INSERT INTO verification_tokens (id, purpose, channel, destination_hmac, token_hash, max_attempts, "
            "expires_at, consumed_at, created_at) VALUES "
            "(:a, 'email_verify', 'email', :d, :h1, 5, now() - interval '9 days', now() - interval '8 days', now() - interval '10 days'),"
            "(:b, 'email_verify', 'email', :d, :h2, 5, now() - interval '1 day', now() - interval '1 day', now() - interval '2 days'),"
            "(:c, 'email_verify', 'email', :d, :h3, 5, now() + interval '1 day', NULL, now())"
        ),
        {
            "a": ids["tok_old"],
            "b": ids["tok_new"],
            "c": ids["tok_live"],
            "d": b"\x03" * 32,
            "h1": uuid.uuid4().bytes * 2,
            "h2": uuid.uuid4().bytes * 2,
            "h3": uuid.uuid4().bytes * 2,
        },
    )
    await owner.execute(
        text(
            "INSERT INTO outbox_events (id, event_type, aggregate_type, aggregate_id, payload, occurred_at, dispatched_at, attempts) VALUES "
            "(:a, 't.e', 't', :a, '{}', now() - interval '9 days', now() - interval '8 days', 1),"
            "(:b, 't.e', 't', :b, '{}', now() - interval '2 days', now() - interval '1 day', 1),"
            "(:c, 't.e', 't', :c, '{}', now() - interval '30 days', NULL, 2)"
        ),
        {"a": ids["ob_old"], "b": ids["ob_new"], "c": ids["ob_pending"]},
    )
    await owner.execute(
        text(
            "INSERT INTO idempotency_keys (id, route_key, idem_key, request_hash, status, created_at, expires_at) VALUES "
            "(:a, 'r', 'k-old-0001', :h, 'completed', now() - interval '2 days', now() - interval '1 day'),"
            "(:b, 'r', 'k-live-0001', :h, 'completed', now(), now() + interval '1 day')"
        ),
        {"a": ids["idem_old"], "b": ids["idem_live"], "h": b"\x04" * 32},
    )
    for table in ("login_attempts", "verification_tokens", "outbox_events", "idempotency_keys"):
        n = await _scalar(owner, "SELECT maint.purge_expired_rows(:t, 2, 1000)", t=table)
        assert n >= 1, table

    async def exists(table: str, rid: uuid.UUID) -> bool:
        return bool(await _scalar(owner, f"SELECT count(*) FROM {table} WHERE id = :i", i=rid))

    assert not await exists("login_attempts", old_la) and await exists("login_attempts", new_la)
    assert not await exists("verification_tokens", ids["tok_old"])
    assert await exists("verification_tokens", ids["tok_new"]) and await exists(
        "verification_tokens", ids["tok_live"]
    )
    assert not await exists("outbox_events", ids["ob_old"])
    assert await exists("outbox_events", ids["ob_new"]) and await exists("outbox_events", ids["ob_pending"])
    assert not await exists("idempotency_keys", ids["idem_old"]) and await exists(
        "idempotency_keys", ids["idem_live"]
    )


async def test_db02_purge_refuses_tables_without_policy(owner) -> None:
    with pytest.raises(DBAPIError, match="no active retention policy"):
        await owner.execute(text("SELECT maint.purge_expired_rows('users', 10, 1)"))


async def test_db02_drop_expired_partitions_drops_only_old_children(owner) -> None:
    await owner.execute(
        text(
            "CREATE TABLE playback_sessions_2020_01 PARTITION OF playback_sessions "
            "FOR VALUES FROM ('2020-01-01') TO ('2020-02-01')"
        )
    )
    await owner.execute(text("SELECT * FROM maint.ensure_partitions('playback_sessions', 0)"))
    dropped = await _scalar(owner, "SELECT maint.drop_expired_partitions('playback_sessions')")
    assert dropped == 1
    assert await _scalar(owner, "SELECT to_regclass('playback_sessions_2020_01')") is None
    names = set(
        (
            await owner.execute(
                text(
                    "SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                    "WHERE i.inhparent = 'playback_sessions'::regclass"
                )
            )
        ).scalars()
    )
    assert "playback_sessions_default" in names and len(names) == 2  # default + current month


async def test_db02_run_retention_as_td_maintenance_and_no_table_access() -> None:
    url = _maintenance_url()
    if url is None:
        pytest.fail("DATABASE_MAINTENANCE_URL must be configured for the maintenance tests")
    eng = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with eng.connect() as conn:
            tx = await conn.begin()
            try:
                rows = (await conn.execute(text("SELECT * FROM maint.run_retention(1000, 5)"))).all()
                assert {r.table_name for r in rows} >= {"login_attempts", "auth_sessions", "notifications"}
                with pytest.raises(DBAPIError, match="permission denied"):
                    async with conn.begin_nested():
                        await conn.execute(text("SELECT 1 FROM login_attempts LIMIT 1"))
            finally:
                await tx.rollback()
    finally:
        await eng.dispose()


# --------------------------------------------------------------------------- jobs


async def test_jobs_skip_without_maintenance_url_and_are_scheduled(monkeypatch) -> None:
    from app.core import maintenance
    from app.core.config import Settings

    monkeypatch.setattr(
        maintenance, "get_settings", lambda: Settings(_env_file=None, DATABASE_MAINTENANCE_URL="")
    )  # type: ignore[call-arg]
    assert await maintenance.run_retention() is None
    assert await maintenance.run_partition_maintenance() is None

    from app.worker import celery_app

    beat = celery_app.conf.beat_schedule
    for name, task in (
        ("core.maint_partitions", maintenance.PARTITIONS_TASK),
        ("core.maint_retention", maintenance.RETENTION_TASK),
    ):
        assert beat[name]["task"] == task and beat[name]["options"]["queue"] == "maintenance"
        assert task in celery_app.tasks
