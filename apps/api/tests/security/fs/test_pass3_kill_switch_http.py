"""Security pass 3 on Firestore, no Postgres: kill switch on one rule (the rule's active version
goes back to shadow and ``risk_rules.active_version_id`` is cleared, in one commit), engine state
and the blocked-accounts report (H5) computed from fixtures."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.core.ids import uuid7
from app.modules.security import models as m
from app.modules.security import repo_fs_controls as secx
from tests.commerce.firestore.conftest import FakeSession
from tests.security.fs.test_pass3_controls_reports_http import FS_MODULES, _restriction, _seed, _staff  # noqa: F401


async def test_kill_switch_one_rule(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    version = m.RiskRuleVersion(
        id=uuid7(),
        family="sharing",
        ruleset_version="2026.11.2",
        semver="1.2.0",
        definition={"rules": []},
        proposed_by=uuid7(),
        approved_by=uuid7(),
        status="active",
    )
    rule = m.RiskRule(
        id=uuid7(),
        key="SH-01",
        family="sharing",
        description="d",
        explanation_key="x",
        active_version_id=version.id,
    )
    version.rule_id = rule.id
    await _seed(rule, version)
    h = _staff(make_principal, auth, "security.engine.kill_switch", "security.rule.read")
    r = await client.post(
        "/api/v1/security/engine/kill-switch",
        json={"target": "rule", "rule_key": "SH-01", "reason": "false positives spike"},
        headers={**h, "Idempotency-Key": uuid.uuid4().hex},
    )
    assert r.status_code == 200, r.text
    s = FakeSession().as_platform()
    v = await secx.get(s, m.RiskRuleVersion, version.id)
    ru = (await secx.execute(s, select(m.RiskRule).where(m.RiskRule.key == "SH-01"))).scalar_one()
    assert v.status == "shadow" and v.status_change_reason == "kill_switch"
    assert ru.active_version_id is None
