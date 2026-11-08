"""Regression tests for audit Phase B fixes in admin/rbac: one approvals registry for privileged
role grants (ADM-13), grantee cannot approve own grant (ADM-19), no self-grants at any scope
(ADM-20), expired status persists (ADM-23), actionable-only dashboard count (ADM-22), 0 %
feature-flag rollout (ADM-17) and honest erasure with a ledger (DB-01)."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select, update

from app.core.db import system_context
from app.modules.admin import privacy as prv
from app.modules.admin.models import ErasureLedger, PrivacyRequest
from app.modules.admin.router import flag_enabled
from app.modules.identity import clock
from app.modules.identity.models import User
from app.modules.rbac.models import ApprovalRequest, Role, RoleGrant
from tests.identity.factory import company_org, make_batch, make_user
from tests.security.helpers import adult, idem, staff, staff_browser


async def _grant_request(b: Any, user_id: Any, role: str = "super_admin") -> str:
    r = await b.post(
        "/rbac/grants",
        {"user_id": str(user_id), "role_key": role, "scope_type": "platform", "reason": "new hire"},
        headers=idem(),
    )
    assert r.status_code == 202, r.text
    return str(r.json()["approval_request_id"])


async def _has_role(db: Any, user_id: Any, role: str) -> bool:
    await system_context(db, "test.check")
    q = (
        select(RoleGrant.id)
        .join(Role, Role.id == RoleGrant.role_id)
        .where(RoleGrant.user_id == user_id, Role.role_key == role, RoleGrant.revoked_at.is_(None))
    )
    return (await db.execute(q)).first() is not None


async def test_adm13_privileged_grant_and_revoke_decided_from_admin_queue(client, db) -> None:
    sa1, sa2 = await staff(db, "super_admin"), await staff(db, "super_admin")
    target = await make_user(db)
    b1 = await staff_browser(client, sa1, ip="198.18.3.1")
    b2 = await staff_browser(client, sa2, ip="198.18.3.2")
    aid = await _grant_request(b1, target.id)
    queue = (await b2.get("/admin/approvals")).json()["data"]
    assert any(a["approval_request_id"] == aid for a in queue)
    detail = await b2.get(f"/admin/approvals/{aid}")
    assert detail.status_code == 200 and detail.json()["payload"]["role_key"] == "super_admin"
    ok = await b2.post(f"/admin/approvals/{aid}/approve", {"note": "ok"}, headers=idem())
    assert ok.status_code == 200 and ok.json()["status"] == "executed", ok.text
    assert ok.json()["result"]["grant_id"]
    assert await _has_role(db, target.id, "super_admin")

    rev = await b1.post(f"/rbac/grants/{ok.json()['result']['grant_id']}/revoke", {"reason": "left team"})
    assert rev.status_code == 202, rev.text
    rid = rev.json()["approval_request_id"]
    assert (await b1.post(f"/admin/approvals/{rid}/approve", {}, headers=idem())).json()[
        "code"
    ] == "sod_violation"
    done = await b2.post(f"/admin/approvals/{rid}/approve", {"note": "ok"}, headers=idem())
    assert done.status_code == 200 and done.json()["status"] == "executed", done.text
    assert not await _has_role(db, target.id, "super_admin")


async def test_adm19_grantee_cannot_approve_own_privileged_grant(client, db) -> None:
    sa1, sa2 = await staff(db, "super_admin"), await staff(db, "super_admin")
    b1 = await staff_browser(client, sa1, ip="198.18.3.3")
    b2 = await staff_browser(client, sa2, ip="198.18.3.4")
    # A re-grant of Admin to an existing Admin: still dual control; the grantee may not decide it.
    aid = await _grant_request(b1, sa2.id, "super_admin")
    via_admin = await b2.post(f"/admin/approvals/{aid}/approve", {}, headers=idem())
    assert via_admin.status_code == 403 and via_admin.json()["code"] == "sod_violation"
    via_rbac = await b2.post(f"/rbac/approval-requests/{aid}/approve", {"note": "self"})
    assert via_rbac.status_code == 403 and via_rbac.json()["code"] == "sod_violation"
    assert await _status(db, aid) == "pending"


async def test_adm20_admin_cannot_self_grant_trainer(client, db) -> None:
    org = company_org()
    sa = await staff(db, "super_admin")
    batch = await make_batch(db, org, sa.id)
    b = await staff_browser(client, sa, ip="198.18.3.5")
    r = await b.post(
        "/rbac/grants",
        {
            "user_id": str(sa.id),
            "role_key": "trainer",
            "scope_type": "batch",
            "scope_id": str(batch),
            "reason": "self",
        },
        headers=idem(),
    )
    assert r.status_code == 403 and r.json()["code"] == "sod_violation", r.text


async def _expire(db: Any, aid: str) -> None:
    await system_context(db, "test.expire")
    await db.execute(
        update(ApprovalRequest)
        .where(ApprovalRequest.id == uuid.UUID(aid))
        .values(expires_at=clock.now() - timedelta(hours=1))
    )


async def _status(db: Any, aid: str) -> str:
    await system_context(db, "test.check")
    db.expire_all()
    return str(
        (
            await db.execute(select(ApprovalRequest.status).where(ApprovalRequest.id == uuid.UUID(aid)))
        ).scalar_one()
    )


async def test_adm23_expired_status_persists_on_every_decide_path(client, db) -> None:
    sa1, sa2 = await staff(db, "super_admin"), await staff(db, "super_admin")
    b1 = await staff_browser(client, sa1, ip="198.18.3.6")
    b2 = await staff_browser(client, sa2, ip="198.18.3.7")
    for path in ("rbac", "admin", "cancel"):
        aid = await _grant_request(b1, (await make_user(db)).id)
        await _expire(db, aid)
        if path == "rbac":
            res = await b2.post(f"/rbac/approval-requests/{aid}/approve", {})
        elif path == "admin":
            res = await b2.post(f"/admin/approvals/{aid}/approve", {}, headers=idem())
        else:
            res = await b1.post(f"/admin/approvals/{aid}/cancel")
        assert res.status_code == 409 and res.json()["current_state"] == "expired", (path, res.text)
        assert await _status(db, aid) == "expired", path


async def test_adm22_dashboard_counts_only_actionable_approvals(client, db) -> None:
    sa1, sa2 = await staff(db, "super_admin"), await staff(db, "super_admin")
    b1 = await staff_browser(client, sa1, ip="198.18.3.8")
    b2 = await staff_browser(client, sa2, ip="198.18.3.9")

    async def pending(b: Any) -> int:
        d = await b.get("/admin/dashboard")
        assert d.status_code == 200, d.text
        return int(d.json()["approvals"]["pending"])

    c1, c2 = await pending(b1), await pending(b2)
    await _grant_request(b1, (await make_user(db)).id)
    assert await pending(b1) == c1  # own request: not actionable
    assert await pending(b2) == c2 + 1


async def test_adm17_zero_percent_rollout_is_off_and_allowlists_apply(client, db) -> None:
    sa = await staff(db, "super_admin")
    bsa = await staff_browser(client, sa, ip="198.18.3.10")
    u = await make_user(db)
    key = "payments.cashfree_enabled"
    p = await bsa.patch(f"/admin/feature-flags/{key}", {"is_enabled": True, "rollout_percent": 0})
    assert p.status_code == 200, p.text
    assert await flag_enabled(db, key) is False  # anonymous at 0 %: off
    assert await flag_enabled(db, key, user_id=u.id) is False
    p = await bsa.patch(f"/admin/feature-flags/{key}", {"user_allowlist": [str(u.id)]})
    assert p.status_code == 200 and p.json()["user_allowlist"] == [str(u.id)]
    assert await flag_enabled(db, key, user_id=u.id) is True
    await bsa.patch(f"/admin/feature-flags/{key}", {"rollout_percent": 100})
    assert await flag_enabled(db, key) is True


async def test_db01_erasure_not_completed_until_every_module_erased(client, db, monkeypatch) -> None:
    u = await adult(db)
    await system_context(db, "test.privacy")
    req = await prv.create(db, u.id, "erasure", None, None)
    req.cooling_off_until = clock.now() - timedelta(days=1)
    await db.flush()
    rid = req.id
    sa = await staff(db, "super_admin")
    bsa = await staff_browser(client, sa, ip="198.18.3.11")
    # Every required module registers a provider at import now (w2a); simulate one missing.
    monkeypatch.delitem(prv._ERASURE_PROVIDERS, "identity", raising=False)

    first = await bsa.post(
        f"/admin/privacy-requests/{rid}/complete", {"response_summary": "Erased"}, headers=idem()
    )
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "in_progress"
    assert "identity" in first.json()["response_summary"]
    await system_context(db, "test.check")
    db.expire_all()
    assert (await db.execute(select(User.status).where(User.id == u.id))).scalar_one() == "deactivated"
    ledger = (
        (await db.execute(select(ErasureLedger).where(ErasureLedger.privacy_request_id == rid)))
        .scalars()
        .all()
    )
    assert len(ledger) == 1 and ledger[0].subject_hash == prv.subject_hash(u.id)
    assert "analytics" in ledger[0].scope["modules"] and "identity" in ledger[0].pending_modules

    calls: list[str] = []
    for m in prv.REQUIRED_ERASURE_MODULES:
        if m == "analytics":
            continue

        async def fake(session: Any, user_id: Any, _m: str = m) -> dict[str, Any]:
            calls.append(_m)
            return {"rows": 0}

        monkeypatch.setitem(prv._ERASURE_PROVIDERS, m, fake)
    second = await bsa.post(
        f"/admin/privacy-requests/{rid}/complete", {"response_summary": "Erased"}, headers=idem()
    )
    assert second.status_code == 200 and second.json()["status"] == "completed", second.text
    assert sorted(calls) == sorted(m for m in prv.REQUIRED_ERASURE_MODULES if m != "analytics")
    await system_context(db, "test.check")
    db.expire_all()
    st = (await db.execute(select(PrivacyRequest.status).where(PrivacyRequest.id == rid))).scalar_one()
    assert st == "completed"
