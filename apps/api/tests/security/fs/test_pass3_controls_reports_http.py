"""Security pass 3 on Firestore, no Postgres: dashboard GROUP BYs, rule lists, the engine-health
and device-association reports, the report-exports list and the retention purge. Expected
numbers are computed from the fixtures (``TD_TEST_NO_PG=1``, ``TD_TEST_DB_NAME=secp3_test``)."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import timedelta
from typing import Any

import pytest

from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.security import models as m
from app.modules.security import repo_fs_controls as secx
from tests.commerce.firestore.conftest import FakeSession

FS_MODULES = ("security", "audit", "core", "admin", "rbac", "sessions", "identity", "support")


async def _seed(*rows: Any) -> None:
    s = FakeSession().as_platform()
    for r in rows:
        secx.add(s, r)
    await s.commit()


def _case(
    user: uuid.UUID, *, status: str = "open", level: int = 2, closed_days: int | None = None
) -> m.SecurityCase:
    c = m.SecurityCase(
        id=uuid7(),
        case_ref=f"SC-{uuid.uuid4().hex[:8].upper()}",
        user_id=user,
        family="sharing",
        level=level,
        opened_reason="test",
        status=status,
    )
    if closed_days is not None:
        c.closed_at = clock.now() - timedelta(days=closed_days)
    return c


def _restriction(
    user: uuid.UUID, level: int, *, ended: bool = False, case: Any = None
) -> m.AccountRestriction:
    return m.AccountRestriction(
        id=uuid7(),
        user_id=user,
        level=level,
        family="sharing",
        scope="account",
        source="engine",
        starts_at=clock.now() - timedelta(days=1),
        ended_at=clock.now() if ended else None,
        case_id=case.id if case else None,
    )


def _staff(make_principal: Any, auth: Any, *perms: str) -> dict[str, str]:
    p = make_principal(
        is_platform=True, roles=("super_admin",), tier="privileged", last_step_up_at=clock.now()
    )
    for perm in perms:
        auth.grant(p, perm)
    return auth.login(p)


async def test_dashboard_group_bys_match_fixtures(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    users = [uuid7() for _ in range(4)]
    cases = [
        _case(users[0], status="open"),
        _case(users[1], status="open"),
        _case(users[2], status="under_review"),
        _case(users[3], status="closed", closed_days=1),
    ]
    restrictions = [
        _restriction(users[0], 2),
        _restriction(users[1], 3),
        _restriction(users[2], 3),
        _restriction(users[3], 1, ended=True),
    ]
    appeals = [
        m.UnblockRequest(id=uuid7(), reference=f"UR-{i}", case_id=cases[i].id, user_id=users[i], state=st)
        for i, st in enumerate(("submitted", "under_review", "draft"))
    ]
    await _seed(*cases, *restrictions, *appeals)
    h = _staff(make_principal, auth, "security.case.read", "security.rule.read")
    r = await client.get("/api/v1/security/dashboard", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["queue"] == dict(Counter(c.status for c in cases if c.status != "closed"))
    assert body["restrictions"] == {
        f"L{k}": v for k, v in Counter(x.level for x in restrictions if not x.ended_at).items()
    }
    assert body["pending_unblock_requests"] == sum(
        1 for a in appeals if a.state in ("submitted", "under_review", "info_requested", "escalated")
    )


async def test_engine_health_report_counts(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    users = [uuid7() for _ in range(3)]
    rs = [_restriction(users[0], 2), _restriction(users[1], 2), _restriction(users[2], 4)]
    now = clock.now()
    sigs = [
        m.SecuritySignal(
            id=uuid7(),
            user_id=users[i % 3],
            family="sharing",
            category="device",
            rule_key=k,
            occurred_at=now - timedelta(hours=i + 1),
            evidence={},
        )
        for i, k in enumerate(("SH-01", "SH-01", "SH-02"))
    ]
    await _seed(*rs, *sigs)
    h = _staff(make_principal, auth, "security.case.read", "security.rule.read")
    r = await client.get("/api/v1/security/reports/engine-health", headers=h)
    assert r.status_code == 200, r.text
    extra = r.json()
    dist = extra.get("level_distribution") or extra.get("extra", {}).get("level_distribution")
    assert dist == {str(k): v for k, v in Counter(x.level for x in rs).items()}
    vol = extra.get("signal_volumes") or extra.get("extra", {}).get("signal_volumes")
    assert vol == dict(Counter(s.rule_key for s in sigs))


async def test_rules_and_versions_listing(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    rule = m.RiskRule(id=uuid7(), key="SH-99", family="sharing", description="test rule", explanation_key="x")
    v1 = m.RiskRuleVersion(
        id=uuid7(),
        family="sharing",
        ruleset_version="2026.11.1",
        semver="1.0.0",
        definition={"rules": []},
        proposed_by=uuid7(),
        status="draft",
    )
    await _seed(rule, v1)
    h = _staff(make_principal, auth, "security.rule.read")
    rules = await client.get("/api/v1/security/rules", headers=h)
    assert rules.status_code == 200, rules.text
    assert "SH-01" in rules.text  # the rule catalogue (code) with its stored state
    versions = await client.get("/api/v1/security/rule-versions", headers=h)
    assert versions.status_code == 200, versions.text
    assert str(v1.id) in versions.text


async def test_report_exports_list_is_the_requesters(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    h = _staff(make_principal, auth, "security.case.read", "report.export.request")
    r = await client.get("/api/v1/security/reports/exports", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["data"] == []


async def test_retention_purge_runner_on_firestore(fs_env: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """``maint.purge_closed_cases`` semantics on Firestore: old closed cases without open
    appeals / active restrictions / attachments are deleted with their rows; others stay."""
    from app.core import runtime
    from app.modules.admin import public as admin_public
    from app.modules.security import retention

    monkeypatch.setattr(runtime, "postgres_enabled", lambda: False)  # the Firebase stack

    async def one_year(_s: Any, table: str) -> Any:
        assert table == "security_cases"
        return admin_public.PgInterval(months=12)

    monkeypatch.setattr(admin_public, "retention_interval", one_year)
    u1, u2, u3 = uuid7(), uuid7(), uuid7()
    old = _case(u1, status="closed", closed_days=400)
    blocked = _case(u2, status="closed", closed_days=400)  # still has an active restriction
    young = _case(u3, status="closed", closed_days=30)
    note = m.CaseNote(id=uuid7(), case_id=old.id, body="ok", attachments=[])
    await _seed(
        old,
        blocked,
        young,
        note,
        _restriction(u2, 2, case=blocked),
        _restriction(u1, 1, ended=True, case=old),
    )
    out = await retention.purge_closed_cases()
    assert out is not None
    assert out["rows_deleted"]["security_cases"] == 1
    assert out["rows_deleted"]["case_notes"] == 1 and out["rows_deleted"]["account_restrictions"] == 1
    s = FakeSession().as_platform()
    from sqlalchemy import select

    left = {c.id for c in (await secx.execute(s, select(m.SecurityCase))).scalars()}
    assert left == {blocked.id, young.id}


async def _async(v: Any) -> Any:
    return v
