"""RLS helper functions, policy behaviour and the RLS lint (ADR-0003)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import set_rls_context, system_context, tenant_context
from app.core.ids import uuid7
from app.core.principal import Principal

# Tables that carry organization_id/user_id but are RLS NONE by design (database-schema §2.3/§13).
RLS_EXEMPT = {"outbox_events"}


async def test_app_connects_as_non_owner_without_bypass(db) -> None:
    row = (
        await db.execute(
            text(
                "SELECT current_user, r.rolsuper, r.rolbypassrls FROM pg_roles r WHERE r.rolname = current_user"
            )
        )
    ).one()
    assert row[0] == "td_app"
    assert row[1] is False and row[2] is False


async def test_context_functions(db) -> None:
    uid, o1, o2 = uuid7(), uuid7(), uuid7()
    p = Principal(user_id=uid, session_id=uuid7(), org_ids=(o1, o2), is_platform=False, privacy_tier="adult")
    await tenant_context(db, p)
    r = (
        await db.execute(
            text(
                "SELECT app.user_id(), app.org_ids(), app.is_platform(), app.actor(), app.privacy_tier(), "
                "app.current_user_id(), app.current_org_ids()"
            )
        )
    ).one()
    assert r[0] == uid
    assert list(r[1]) == [o1, o2]
    assert r[2] is False
    assert r[3] == f"user:{uid}"
    assert r[4] == "adult"
    assert r[5] == uid and list(r[6]) == [o1, o2]

    await system_context(db, "audit_sealer")
    r = (await db.execute(text("SELECT app.user_id(), app.org_ids(), app.is_platform(), app.actor()"))).one()
    assert r[0] is None and list(r[1]) == [] and r[2] is True and r[3] == "system:audit_sealer"

    await set_rls_context(db, roles=["super_admin"], is_platform=True)
    r = (
        await db.execute(
            text(
                "SELECT app.has_role('super_admin'), app.has_platform_role('super_admin'), "
                "app.has_platform_role('trainer')"
            )
        )
    ).one()
    assert tuple(r) == (True, True, False)


async def test_context_is_transaction_local(app_engine) -> None:
    async with app_engine.connect() as conn:
        async with conn.begin():
            await conn.execute(text("SELECT set_config('app.user_id', :u, true)"), {"u": str(uuid.uuid4())})
        async with conn.begin():
            v = (await conn.execute(text("SELECT app.user_id()"))).scalar()
    assert v is None  # pooled connections cannot leak tenant context


async def test_policy_o_with_check_blocks_foreign_rows(db) -> None:
    me, other = uuid7(), uuid7()
    await set_rls_context(db, user_id=str(me))
    insert = text(
        "INSERT INTO idempotency_keys (id, user_id, route_key, idem_key, request_hash, status, expires_at) "
        "VALUES (:id, :uid, 'POST /x', 'k-12345678', decode(repeat('ab', 32), 'hex'), 'in_progress', now() + interval '1 day')"
    )
    await db.execute(insert, {"id": uuid7(), "uid": me})
    nested = await db.begin_nested()
    with pytest.raises(DBAPIError, match="row-level security"):
        await db.execute(insert, {"id": uuid7(), "uid": other})
    await nested.rollback()
    # anonymous context sees nothing
    await set_rls_context(db)
    n = (
        await db.execute(text("SELECT count(*) FROM idempotency_keys WHERE user_id = :u"), {"u": me})
    ).scalar()
    assert n == 0


async def test_rls_lint_every_tenant_table_has_force_rls(db) -> None:
    """Migration lint (ADR-0003/0009): any table with organization_id or user_id must have
    ENABLE + FORCE row level security (partitions included)."""
    rows = (
        await db.execute(
            text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
                  AND EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid AND NOT a.attisdropped
                              AND a.attname IN ('organization_id', 'user_id'))
                """
            )
        )
    ).all()
    offenders = [
        r.relname
        for r in rows
        if r.relname not in RLS_EXEMPT and not (r.relrowsecurity and r.relforcerowsecurity)
    ]
    assert offenders == [], f"tables missing ENABLE+FORCE RLS: {offenders}"
    assert {r.relname for r in rows} >= {"idempotency_keys", "audit_log"}
