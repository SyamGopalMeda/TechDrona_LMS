"""Audit probes (database area). Run on an own DB:
TD_TEST_DB_NAME=techdrona_audit_database TD_TEST_RESET_DB=1 .venv/Scripts/python -m pytest tests/_audit_scratch/database -q -s
Data is committed (probe DB only)."""

from __future__ import annotations

import asyncio
import uuid
from collections import Counter
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.db import system_context
from app.core.ids import uuid7

API = "/api/v1"


@pytest.fixture
async def committed(committed_engine: AsyncEngine):
    yield async_sessionmaker(committed_engine, expire_on_commit=False)


async def _try(sm, ctx_sql: str, stmt: str, **p: Any) -> str:
    async with sm() as s:
        try:
            async with s.begin():
                await s.execute(text(ctx_sql))
                r = await s.execute(text(stmt), p)
                return f"OK rowcount={r.rowcount}"
        except Exception as e:  # noqa: BLE001
            return f"ERR {str(getattr(e, "orig", e)).splitlines()[0][:120]}"


async def test_probe_attempt_start_race(client, committed, rbac) -> None:
    from tests.assessments.test_attempts import assign, fixed, make_bank, make_test
    from tests.placement.world import build_world

    async with committed() as s, s.begin():
        w = await build_world(s, rbac)
        _, qs = await make_bank(s, w)
        test_id = await make_test(s, w, [("Quant", None, [fixed(q) for q in qs])], duration_seconds=1800)
        await assign(s, w, test_id)
    st = w.personas["student"]

    async def go() -> Any:
        return await client.post(
            f"{API}/attempts",
            json={"test_id": str(test_id)},
            headers={**st.headers, "Idempotency-Key": uuid.uuid4().hex},
        )

    raw = await asyncio.gather(*[go() for _ in range(6)], return_exceptions=True)
    rs = [r for r in raw if not isinstance(r, BaseException)]
    print('UNHANDLED', [type(r).__name__ for r in raw if isinstance(r, BaseException)])
    print("ATTEMPT_RACE", Counter(r.status_code for r in rs), [r.json().get("code") for r in rs if r.status_code >= 400])
    async with committed() as s, s.begin():
        await system_context(s, "probe")
        n = (await s.execute(text("select count(*) from test_attempts where test_id=:t"), {"t": test_id})).scalar()
    print("ATTEMPT_ROWS", n)
    assert n == 1
    assert not [r for r in raw if isinstance(r, BaseException)], "unique violation unhandled (500)"


async def test_probe_enrol_race(client, committed, rbac) -> None:
    from tests.catalog.factory import make_published_course
    from tests.placement.world import build_world

    async with committed() as s, s.begin():
        w = await build_world(s, rbac)
        course = await make_published_course(s, w.personas["author"].id, is_free=True)
    st = w.personas["student"]

    async def go() -> Any:
        return await client.post(
            f"{API}/me/enrolments",
            json={"course_id": str(course.course_id)},
            headers={**st.headers, "Idempotency-Key": uuid.uuid4().hex},
        )

    raw = await asyncio.gather(*[go() for _ in range(6)], return_exceptions=True)
    rs = [r for r in raw if not isinstance(r, BaseException)]
    print('UNHANDLED', [type(r).__name__ for r in raw if isinstance(r, BaseException)])
    print("ENROL_RACE", Counter(r.status_code for r in rs), [r.json().get("code") for r in rs if r.status_code >= 400])
    assert not [r for r in raw if isinstance(r, BaseException)], 'unique violation unhandled (500)'


async def test_probe_grants_and_rls(committed) -> None:
    from tests.identity.factory import make_user

    async with committed() as s, s.begin():
        u = await make_user(s)
        await system_context(s, "probe")
        rid = uuid7()
        await s.execute(
            text(
                "insert into account_restrictions (id,user_id,level,family,scope,source)"
                " values (:i,:u,2,'sharing','learning_access','engine')"
            ),
            {"i": rid, "u": u.id},
        )
    plat = "select set_config('app.is_platform','on',true)"
    learner = f"select set_config('app.user_id','{u.id}',true)"
    out = {
        "audit_log UPDATE as platform": await _try(committed, plat, "update audit_log set action=action"),
        "audit_log DELETE as platform": await _try(committed, plat, "delete from audit_log"),
        "audit_outbox SELECT as td_app": await _try(committed, plat, "select 1 from audit_outbox"),
        "login_attempts DELETE (retention)": await _try(committed, plat, "delete from login_attempts where attempted_at < now() - interval '395 days'"),
        "security_signals DELETE (retention)": await _try(committed, plat, "delete from security_signals where occurred_at < now() - interval '180 days'"),
        "attempt_events DELETE (retention)": await _try(committed, plat, "delete from attempt_events where occurred_at < now() - interval '24 months'"),
        "learner UPDATE own account_restriction": await _try(committed, learner, "update account_restrictions set ended_at=now(), end_reason='deescalated' where id=:i", i=rid),
        "learner DELETE own account_restriction": await _try(committed, learner, "delete from account_restrictions where id=:i", i=rid),
    }
    for k, v in out.items():
        print("GRANT_PROBE", k, "=>", v)
