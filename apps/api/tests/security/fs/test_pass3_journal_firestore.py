"""Approval-executed security actions are all-or-nothing on Firestore (access undo journal,
docs/firebase/agents/data-access.md §9): the engine's commit inside a journal registers its
undo, so a failure later in the decision restores the documents; without a failure the change
stays. Also the journaled kill-switch route: a failure after the writes leaves nothing behind."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.core.ids import uuid7
from app.core.principal import Principal
from app.modules.security import models as m
from app.modules.security import repo_fs_controls as secx
from tests.commerce.firestore.conftest import FakeSession
from tests.security.fs.test_pass3_controls_reports_http import FS_MODULES, _seed, _staff  # noqa: F401


async def _job_status(job_id: uuid.UUID) -> str:
    j = await secx.get(FakeSession().as_platform(), m.SecurityReportExport, job_id)
    return str(j.status)


async def test_executor_writes_roll_back_with_the_decision(fs_env: Any) -> None:
    from app.modules.identity.fs_journal import journal
    from app.modules.security import controls

    requester = uuid7()
    job = m.SecurityReportExport(
        id=uuid7(), report_key="engine-health", requested_by=requester, status="pending_approval"
    )
    await _seed(job)
    approver = Principal(user_id=requester, session_id=uuid7(), is_platform=True)  # self-cancel: no notice
    req = SimpleNamespace(target_type="security_report_export", payload={"export_job_id": str(job.id)})

    with pytest.raises(RuntimeError):
        async with journal():
            await controls._export_rejected(None, approver, req)  # NO_POSTGRES-like decision session
            assert await _job_status(job.id) == "rejected"  # committed inside the scope ...
            raise RuntimeError("mark_executed failed")
    assert await _job_status(job.id) == "pending_approval"  # ... and undone with the decision

    async with journal():
        await controls._export_rejected(None, approver, req)
    assert await _job_status(job.id) == "rejected"


async def test_kill_switch_failure_after_writes_leaves_nothing(
    fs_http: Any, make_principal: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.rbac import public as rbac_public
    from app.modules.security import controls

    client, _rec, auth = fs_http
    version = m.RiskRuleVersion(
        id=uuid7(),
        family="sharing",
        ruleset_version="2026.11.3",
        semver="1.3.0",
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

    async def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("audit store down")

    monkeypatch.setattr(controls, "audit", boom)
    h = _staff(make_principal, auth, "security.engine.kill_switch", "security.rule.read")
    try:
        r = await client.post(
            "/api/v1/security/engine/kill-switch",
            json={"target": "rule", "rule_key": "SH-01", "reason": "false positives spike"},
            headers={**h, "Idempotency-Key": uuid.uuid4().hex},
        )
        assert r.status_code >= 500
    except RuntimeError:
        pass  # the in-process transport re-raises the server error
    s = FakeSession().as_platform()
    v = await secx.get(s, m.RiskRuleVersion, version.id)
    ru = (await secx.execute(s, select(m.RiskRule).where(m.RiskRule.key == "SH-01"))).scalar_one()
    assert v.status == "active" and ru.active_version_id == version.id
    pending = await rbac_public.find_approvals(
        FakeSession().as_platform(), action_type="risk.kill_switch.ratify"
    )
    assert pending == []
