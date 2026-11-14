"""Security pass 3 on Firestore, no Postgres: report H1 golden numbers, rule-version propose and
shadow start, bulk-lift dry run and a report export request, through the real app.

Permission checks inside the routes (``policies.has_perm``, an rbac lookup) are answered from the
test's ``FakeAuth`` grants, like the route-level ``perm(...)`` dependencies."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core.ids import uuid7
from app.modules.security import models as m
from tests.security.fs.test_pass3_controls_reports_http import FS_MODULES, _case, _restriction, _seed, _staff  # noqa: F401

ALL = (
    "security.case.read",
    "security.evidence.read",
    "security.rule.read",
    "security.rule.propose",
    "security.rule.simulate",
    "security.restriction.bulk_lift",
    "report.export.request",
)


@pytest.fixture(autouse=True)
def _perms_from_fake_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import auth as core_auth
    from app.modules.security import api_engine, policies

    async def has_perm(_session: Any, principal: Any, perm: str) -> bool:
        return bool(await core_auth.check_permission(principal, perm))

    monkeypatch.setattr(policies, "has_perm", has_perm)
    monkeypatch.setattr(api_engine, "has_perm", has_perm)


def _idem(h: dict[str, str]) -> dict[str, str]:
    return {**h, "Idempotency-Key": uuid.uuid4().hex}


async def test_h1_top_suspicious_accounts_golden(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    users = [uuid7() for _ in range(4)]
    cases = [
        _case(users[0], level=2),
        _case(users[1], level=3),
        _case(users[2], status="closed", closed_days=1),
    ]
    states = [
        m.SecurityUserState(user_id=users[0], sharing_score=40),
        m.SecurityUserState(user_id=users[3], sharing_score=25),  # no open case
        m.SecurityUserState(user_id=users[2], sharing_score=10),  # only a closed case
    ]
    await _seed(*cases, *states)
    h = _staff(make_principal, auth, *ALL)
    r = await client.get(
        "/api/v1/security/reports/top-suspicious-accounts?reason_code=case_review", headers=h
    )
    assert r.status_code == 200, r.text
    body = r.json()
    open_cases = [c for c in cases if c.status != "closed"]
    assert len(body["rows"]) == len(open_cases)
    no_case = body.get("highest_scores_without_case") or body.get("extra", {}).get(
        "highest_scores_without_case"
    )
    expected = sorted(
        (s for s in states if s.user_id not in {c.user_id for c in open_cases}),
        key=lambda s: -s.sharing_score,
    )
    assert [x["user_id"] for x in no_case] == [str(s.user_id) for s in expected]


async def test_rule_version_propose_and_shadow(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    # the catalogue rows exist on Postgres from the seed migration, on Firestore from the backfill
    await _seed(m.RiskRule(id=uuid7(), key="SH-01", family="sharing", description="d", explanation_key="x"))
    h = _staff(make_principal, auth, *ALL)
    r = await client.post(
        "/api/v1/security/rule-versions",
        json={"rule_key": "SH-01", "semver": "9.9.9", "definition": {"threshold": 3}},
        headers=_idem(h),
    )
    assert r.status_code == 201, r.text
    vid = r.json().get("version_id") or r.json().get("id")
    listed = await client.get("/api/v1/security/rule-versions", headers=h)
    assert vid in listed.text
    s = await client.post(f"/api/v1/security/rule-versions/{vid}/start-shadow", headers=_idem(h))
    assert s.status_code == 200, s.text
    rep = await client.get(f"/api/v1/security/rule-versions/{vid}/shadow-report", headers=h)
    assert rep.status_code == 200, rep.text


async def test_bulk_lift_dry_run_counts(fs_http: Any, make_principal: Any) -> None:
    """Golden: only active engine L3 restrictions are lifted; L4 and human-applied ones are counted
    as excluded; L2 and ended ones are not considered."""
    client, _rec, auth = fs_http
    u = [uuid7() for _ in range(6)]
    human = _restriction(u[4], 3)
    human.source = "admin"
    await _seed(
        _restriction(u[0], 3),
        _restriction(u[1], 3),
        _restriction(u[2], 4),
        _restriction(u[3], 2),
        human,
        _restriction(u[5], 3, ended=True),
    )
    h = _staff(make_principal, auth, *ALL)
    r = await client.post(
        "/api/v1/security/restrictions/bulk-lift-requests",
        json={
            "selector": {"applied_from": "2000-01-01T00:00:00Z"},
            "dry_run": True,
            "reason": "false positive wave",
        },
        headers=_idem(h),
    )
    assert r.status_code in (200, 202), r.text
    body = r.json()
    assert body["matched"] == 2
    assert body["excluded_by_reason"] == {
        "l4": 1,
        "high_risk": 0,
        "takeover": 0,
        "human_applied": 1,
        "pending_decision": 0,
    }


async def test_export_request_for_aggregate_report(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    h = _staff(make_principal, auth, *ALL)
    r = await client.post(
        "/api/v1/security/reports/engine-health/exports", json={"filters": {}}, headers=_idem(h)
    )
    assert r.status_code == 202, r.text
    lst = await client.get("/api/v1/security/reports/exports", headers=h)
    assert lst.status_code == 200 and len(lst.json()["data"]) == 1
