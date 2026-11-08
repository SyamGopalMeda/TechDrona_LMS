"""privacy D8 / §7 ``purge_closed_cases`` (migration support_0003; core request 6, secadmin 9).

Attachments 90 days after closure (objects deleted through the storage abstraction, here an
in-memory store), case data 1 year after closure (3 years if disputed), legal holds and live
restrictions kept. Everything runs as td_owner inside a transaction that is rolled back; a
temporary policy (rolled back with it) lets the owner insert the user rows the cases need.
"""

from __future__ import annotations

import random
import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
from sqlalchemy import make_url, pool, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.modules.media import storage
from app.modules.security import retention
from tests.conftest import TEST_DB_NAME

FUNCS = (
    "maint.closed_case_attachments(integer)",
    "maint.clear_closed_case_attachments(text, uuid[])",
    "maint.purge_closed_cases(integer)",
)
BUCKET = "test-uploads"
_ALPHA = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


@pytest.fixture
async def owner(owner_engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    async with owner_engine.connect() as conn:
        tx = await conn.begin()
        await conn.execute(text("SELECT set_config('app.maint', 'on', true)"))
        await conn.execute(
            text("CREATE POLICY p_test_owner ON users FOR ALL TO td_owner USING (true) WITH CHECK (true)")
        )
        try:
            yield conn
        finally:
            await tx.rollback()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> storage.MemoryObjectStore:
    mem = storage.MemoryObjectStore()
    storage.set_object_store(mem)
    monkeypatch.setattr(storage.storage_settings(), "S3_BUCKET_UPLOADS", BUCKET)
    yield mem  # type: ignore[misc]
    storage.set_object_store(None)


def _ref(prefix: str) -> str:
    return f"{prefix}-2611-" + "".join(random.choice(_ALPHA) for _ in range(6))


async def _q(conn: AsyncConnection, sql: str, **p: Any) -> Any:
    return (await conn.execute(text(sql), p)).scalar()


async def _user(conn: AsyncConnection) -> uuid.UUID:
    uid = uuid.uuid4()
    await conn.execute(text("INSERT INTO users (id, status) VALUES (:i, 'deleted')"), {"i": uid})
    return uid


async def _case(
    conn: AsyncConnection,
    reviewer: uuid.UUID,
    *,
    closed_days: int | None,
    legal_hold: bool = False,
    appeal: bool = False,
    live_restriction: bool = False,
) -> dict[str, Any]:
    """A case with a restriction, a closed unblock request (one attachment), a decision and a
    note (one attachment). ``closed_days=None`` leaves the case open."""
    uid = await _user(conn)
    ids = {k: uuid.uuid4() for k in ("case", "restriction", "request", "decision", "note")}
    closed = closed_days is not None
    await conn.execute(
        text(
            "INSERT INTO security_cases (id, case_ref, user_id, family, level, status, opened_reason, "
            "legal_hold, closed_at, created_at) VALUES (:id, :ref, :u, 'sharing', 3, :st, 'engine_L3', :lh, "
            "CASE WHEN :closed THEN now() - make_interval(days => :d) END, now() - make_interval(days => :d + 30))"
        ),
        {
            "id": ids["case"],
            "ref": _ref("SEC"),
            "u": uid,
            "st": "closed" if closed else "open",
            "lh": legal_hold,
            "closed": closed,
            "d": closed_days or 0,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO account_restrictions (id, user_id, level, family, scope, source, case_id, ended_at, "
            "end_reason) VALUES (:id, :u, 3, 'sharing', 'learning_access', 'engine', :c, "
            "CASE WHEN :live THEN NULL ELSE now() END, CASE WHEN :live THEN NULL ELSE 'case_decision' END)"
        ),
        {"id": ids["restriction"], "u": uid, "c": ids["case"], "live": live_restriction},
    )
    key_ur = f"uploads/unblock_request/{uid}/{ids['request']}/a1/proof.pdf"
    key_note = f"uploads/unblock_request/{uid}/{ids['note']}/n1/note.png"
    await conn.execute(
        text(
            "INSERT INTO unblock_requests (id, reference, case_id, user_id, restriction_id, state, closure_reason, "
            "explanation, submitted_at, declaration_at, attachments, is_second_level_appeal, appeal_used) "
            "VALUES (:id, :ref, :c, :u, :r, 'closed', 'completed', :expl, now(), now(), "
            "jsonb_build_array(jsonb_build_object('attachment_id', 'a1', 's3_key', CAST(:k AS text))), :ap, :ap)"
        ),
        {
            "id": ids["request"],
            "ref": _ref("APL"),
            "c": ids["case"],
            "u": uid,
            "r": ids["restriction"],
            "expl": "I share an office computer with colleagues.",
            "k": key_ur,
            "ap": appeal,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO case_decisions (id, case_id, unblock_request_id, outcome, rationale, decided_by) "
            "VALUES (:id, :c, :r, 'lift_false_positive', 'Shared lab device.', :by)"
        ),
        {"id": ids["decision"], "c": ids["case"], "r": ids["request"], "by": reviewer},
    )
    await conn.execute(
        text("UPDATE account_restrictions SET decision_id = :d WHERE id = :r"),
        {"d": ids["decision"], "r": ids["restriction"]},
    )
    await conn.execute(
        text(
            "INSERT INTO case_notes (id, case_id, author_id, body, attachments) VALUES (:id, :c, :a, 'Checked.', "
            "jsonb_build_array(jsonb_build_object('attachment_id', 'n1', 's3_key', CAST(:k AS text))))"
        ),
        {"id": ids["note"], "c": ids["case"], "a": reviewer, "k": key_note},
    )
    return {**ids, "keys": (key_ur, key_note)}


def _runner(conn: AsyncConnection) -> retention.Runner:
    async def run(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        async with conn.begin_nested():
            return [dict(r) for r in (await conn.execute(text(sql), params)).mappings().all()]

    return run


async def _exists(conn: AsyncConnection, table: str, rid: uuid.UUID) -> bool:
    return bool(await _q(conn, f"SELECT count(*) FROM {table} WHERE id = :i", i=rid))


async def _attachments(conn: AsyncConnection, case: dict[str, Any]) -> tuple[int, int]:
    ur = await _q(
        conn, "SELECT jsonb_array_length(attachments) FROM unblock_requests WHERE id = :i", i=case["request"]
    )
    note = await _q(
        conn, "SELECT jsonb_array_length(attachments) FROM case_notes WHERE id = :i", i=case["note"]
    )
    return ur, note


# --------------------------------------------------------------------------- grants


async def test_purge_functions_are_definer_and_maintenance_only(owner) -> None:
    for sig in FUNCS:
        row = (
            await owner.execute(
                text("SELECT p.prosecdef, p.proconfig FROM pg_proc p WHERE p.oid = CAST(:s AS regprocedure)"),
                {"s": sig},
            )
        ).one()
        assert row[0] is True and any(c.startswith("search_path=pg_catalog") for c in row[1]), sig
        for role, allowed in (("td_maintenance", True), ("td_app", False), ("td_readonly", False)):
            got = await _q(
                owner, "SELECT has_function_privilege(:r, CAST(:s AS regprocedure), 'EXECUTE')", r=role, s=sig
            )
            assert got is allowed, (role, sig)


async def test_retention_registry_names_purge_closed_cases(owner) -> None:
    rows = (
        await owner.execute(
            text(
                "SELECT table_name, data_category, retention_interval::text, job_name FROM retention_policies "
                "WHERE owner_module = 'security' AND table_name NOT IN ('security_signals', 'risk_evaluations')"
            )
        )
    ).all()
    got = {r.table_name: (r.data_category, r.retention_interval, r.job_name) for r in rows}
    for t in ("security_cases", "case_notes", "case_decisions", "account_restrictions"):
        assert got[t] == ("D8", "1 year", "purge_closed_cases"), t
    assert got["unblock_requests"][0::2] == ("D8", "purge_closed_cases")
    assert await _q(owner, "SELECT count(*) FROM retention_policies WHERE job_name = 'purge_cases'") == 0


# --------------------------------------------------------------------------- behaviour


async def test_purge_closed_cases_attachments_at_90_days_and_cases_at_1_or_3_years(owner, store) -> None:
    reviewer = await _user(owner)
    recent = await _case(owner, reviewer, closed_days=30)  # nothing yet
    att_due = await _case(owner, reviewer, closed_days=120)  # attachments only
    old = await _case(owner, reviewer, closed_days=400)  # everything
    disputed = await _case(owner, reviewer, closed_days=400, appeal=True)  # attachments only (3 years)
    disputed_old = await _case(owner, reviewer, closed_days=3 * 365 + 10, appeal=True)  # everything
    held = await _case(owner, reviewer, closed_days=2000, legal_hold=True)  # nothing
    open_case = await _case(owner, reviewer, closed_days=None)  # nothing
    live = await _case(owner, reviewer, closed_days=400, live_restriction=True)  # attachments only
    every = (recent, att_due, old, disputed, disputed_old, held, open_case, live)
    for c in every:
        for k in c["keys"]:
            store.put(BUCKET, k)
    # A support ticket that cites the old case survives the purge (privacy D13), unlinked.
    ticket = uuid.uuid4()
    await owner.execute(
        text(
            "INSERT INTO support_tickets (id, ticket_number, requester_id, category, subject, body, "
            "related_case_id, related_unblock_request_id) VALUES (:t, :n, :u, 'account_access', 'Blocked', "
            "'Please help.', :c, :r)"
        ),
        {
            "t": ticket,
            "n": f"TD-{random.randint(10**7, 10**8)}",
            "u": reviewer,
            "c": old["case"],
            "r": old["request"],
        },
    )

    result = await retention.purge_closed_cases(_runner(owner))
    assert result is not None

    purged_attachments = (att_due, old, disputed, disputed_old, live)
    for c in every:
        gone = c in purged_attachments
        for k in c["keys"]:
            assert ((BUCKET, k) in store.objects) is not gone, (c["case"], k)
    assert result["attachment_objects_deleted"] == 2 * len(purged_attachments)
    assert result["rows_deleted"]["security_cases"] == 2

    for c in (old, disputed_old):
        for table, key in (
            ("security_cases", "case"),
            ("unblock_requests", "request"),
            ("case_decisions", "decision"),
            ("case_notes", "note"),
            ("account_restrictions", "restriction"),
        ):
            assert not await _exists(owner, table, c[key]), (table, c["case"])
    for c in (recent, att_due, disputed, held, open_case, live):
        assert await _exists(owner, "security_cases", c["case"])
        assert await _exists(owner, "case_notes", c["note"])
        assert await _exists(owner, "unblock_requests", c["request"])
    for c in (att_due, disputed, live):
        assert await _attachments(owner, c) == (0, 0)
    for c in (recent, held, open_case):
        assert await _attachments(owner, c) == (1, 1)
    row = (
        await owner.execute(
            text("SELECT related_case_id, related_unblock_request_id FROM support_tickets WHERE id = :t"),
            {"t": ticket},
        )
    ).one()
    assert tuple(row) == (None, None)
    audits = await _q(
        owner,
        "SELECT count(*) FROM audit_outbox WHERE record->>'action' IN "
        "('security.case_attachments.purged', 'security.closed_cases.purged') AND occurred_at > now() - interval '1 hour'",
    )
    assert audits >= 3

    # Idempotent: a re-run finds nothing more.
    again = await retention.purge_closed_cases(_runner(owner))
    assert again is not None and again["attachment_objects_deleted"] == 0
    assert again["rows_deleted"]["security_cases"] == 0


async def test_failed_object_delete_keeps_references(owner, store, monkeypatch) -> None:
    reviewer = await _user(owner)
    c = await _case(owner, reviewer, closed_days=120)

    async def boom(bucket: str, key: str) -> None:
        raise storage.StorageUnavailable("down")

    monkeypatch.setattr(store, "delete", boom)
    with pytest.raises(storage.StorageUnavailable):
        await retention.purge_closed_cases(_runner(owner))
    assert await _attachments(owner, c) == (1, 1)


# --------------------------------------------------------------------------- td_maintenance + beat


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


async def test_td_maintenance_can_run_the_purge_but_not_read_cases() -> None:
    url = _maintenance_url()
    if url is None:
        pytest.fail("DATABASE_MAINTENANCE_URL must be configured for the maintenance tests")
    eng = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with eng.connect() as conn:
            tx = await conn.begin()
            try:
                await conn.execute(text("SELECT * FROM maint.closed_case_attachments(5)"))
                rows = (await conn.execute(text("SELECT * FROM maint.purge_closed_cases(1)"))).all()
                assert [r.table_name for r in rows][-1] == "security_cases"
                from sqlalchemy.exc import DBAPIError

                with pytest.raises(DBAPIError, match="permission denied"):
                    async with conn.begin_nested():
                        await conn.execute(text("SELECT 1 FROM security_cases LIMIT 1"))
            finally:
                await tx.rollback()
    finally:
        await eng.dispose()


async def test_job_skips_without_maintenance_url_and_is_scheduled_weekly(monkeypatch) -> None:
    from app.core import maintenance
    from app.core.config import Settings

    monkeypatch.setattr(
        maintenance, "get_settings", lambda: Settings(_env_file=None, DATABASE_MAINTENANCE_URL="")
    )  # type: ignore[call-arg]
    assert await retention.purge_closed_cases() is None

    from app.modules.security import tasks
    from app.worker import celery_app

    entry = celery_app.conf.beat_schedule[tasks.PURGE_CLOSED_CASES_JOB]
    assert entry["task"] == retention.PURGE_CLOSED_CASES_TASK
    assert entry["options"]["queue"] == "maintenance"
    assert entry["schedule"].day_of_week == {0}
    assert retention.PURGE_CLOSED_CASES_TASK in celery_app.tasks
    assert "security.retention_policies" not in celery_app.conf.beat_schedule
