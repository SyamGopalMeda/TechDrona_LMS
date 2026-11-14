"""Admin module (single company): policy settings (bounds, flags, scopes, Dual = two different
admins), precedence user > plan > platform, identity policy delegation, feature flags (no org
allowlist), approvals queue, DPDP privacy requests (basic flow)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.admin import policy as pol
from app.modules.admin.policy import get_value
from app.modules.identity.policy import get_policy
from tests.identity.factory import Browser, company_org
from tests.security.helpers import adult, idem, set_policy, staff, staff_browser


async def approve(b: Browser, approval_id: str):
    return await b.post(f"/admin/approvals/{approval_id}/approve", {"note": "ok"}, headers=idem())


@pytest.mark.usefixtures("admin_backend")
async def test_policy_bounds_locks_scopes_and_dual_control(client, db) -> None:
    a1, a2 = await staff(db, "super_admin"), await staff(db, "super_admin")
    cm = await staff(db, "content_manager")
    b1, b2 = await staff_browser(client, a1), await staff_browser(client, a2, ip="198.18.0.7")
    bcm = await staff_browser(client, cm, ip="198.18.0.8")
    listing = await b1.get("/admin/policy-settings")
    keys = {s["setting_key"]: s for s in listing.json()["data"]}
    assert (
        keys["risk.network_points_cap"]["locked"] and keys["devices.student.max_trusted"]["max_value"] == 10
    )
    assert "org_overridable" not in keys["devices.student.max_trusted"]
    assert "org.notify_coordinator_on_restriction" not in keys  # removed key
    assert keys["auth.require_mfa_students"]["value"] is False  # platform MFA key (WS1) registered

    async def propose(b: Browser, key: str, **body: Any):
        return await b.post(
            f"/admin/policy-settings/{key}/changes",
            {"change_reason": "Tuning after pilot", **body},
            headers=idem(),
        )

    oob = await propose(b1, "devices.student.max_trusted", value=11)
    assert oob.status_code == 422 and oob.json()["errors"][0]["code"] == "out_of_bounds"
    org = company_org()
    no_org = await propose(
        b1, "sessions.student.max_concurrent", value=1, scope_type="organization", scope_id=str(org)
    )
    assert no_org.status_code in (400, 422)  # the organization layer is gone
    plan = str(uuid.uuid4())
    locked = await propose(b1, "risk.network_points_cap", value=10, scope_type="plan", scope_id=plan)
    assert locked.json()["errors"][0]["code"] == "locked_key"
    s3 = await propose(b1, "risk.separation.multiplier.S3", value=0.5)
    assert s3.status_code == 422  # SEP-04: S3 is locked at 1.0
    not_plan = await propose(b1, "sessions.student.idle_minutes", value=30, scope_type="plan", scope_id=plan)
    assert not_plan.json()["errors"][0]["code"] == "not_overridable_at_scope"
    tighten = await propose(b1, "risk.threshold.L1", value=20, scope_type="plan", scope_id=plan)
    assert tighten.json()["errors"][0]["code"] == "override_may_only_tighten"
    user_scope = await propose(
        b1, "devices.student.max_trusted", value=4, scope_type="user", scope_id=str(a1.id)
    )
    assert user_scope.json()["errors"][0]["code"] == "user_scope_requires_case_decision"
    # Folded roles (D2): any Admin may propose any namespace; a non-admin may not propose.
    commerce = await propose(b1, "analytics.k_min.cohort", value=12)
    assert commerce.status_code == 202
    denied = await propose(bcm, "analytics.k_min.cohort", value=12)
    assert denied.status_code == 403 and denied.json()["code"] == "permission_denied"

    cap = await propose(b1, "sessions.student.max_concurrent", value=1)
    assert cap.status_code == 202 and cap.json()["required_approver_role"] == "super_admin"
    # Dual control = two DIFFERENT admins.
    assert (await approve(b1, cap.json()["approval_request_id"])).json()["code"] == "sod_violation"
    done = await approve(b2, cap.json()["approval_request_id"])
    assert done.status_code == 200 and done.json()["result"]["version"] >= 1
    member = await adult(db)
    assert await get_value(db, "sessions.student.max_concurrent", user_id=member.id) == 1
    assert await get_value(db, "sessions.student.max_concurrent", user_id=member.id, org_id=org) == 1
    assert (
        await get_policy(db, "sessions.student.max_concurrent", user_id=member.id) == 1
    )  # identity delegates
    hist = await b1.get("/admin/policy-settings/sessions.student.max_concurrent")
    assert hist.status_code == 200 and hist.json()["history"][0]["approved_by"] == str(a2.id)


@pytest.mark.usefixtures("admin_backend")
async def test_policy_precedence_plan_over_platform_and_versioning(db) -> None:
    u = await adult(db)
    plan = uuid.uuid4()
    await set_policy(db, "devices.student.max_trusted", 5)
    assert await get_value(db, "devices.student.max_trusted", user_id=u.id) == 5
    await set_policy(db, "devices.student.max_trusted", 2, "plan", plan)
    assert await get_value(db, "devices.student.max_trusted", user_id=u.id, plan_id=plan) == 2
    assert await get_value(db, "devices.student.max_trusted", user_id=u.id) == 5  # other plans
    await set_policy(db, "devices.student.max_trusted", 6)  # new platform version
    rows = [
        r
        for r in await pol.history_rows(db, "devices.student.max_trusted")  # either store
        if r.scope_type == "platform"
    ]
    assert sum(r.is_active for r in rows) == 1 and max(r.version for r in rows) >= 2
    assert await get_value(db, "devices.student.max_trusted") == 6
    assert await get_value(db, "devices.student.max_trusted", plan_id=plan) == 2


async def test_policy_precedence_user_over_plan_over_platform() -> None:
    """Ranking only (a user exception row needs a security case decision, covered by the
    security suite): user > plan > platform, whatever order the rows come back in."""
    uid, plan = uuid.uuid4(), uuid.uuid4()
    rows = [
        SimpleNamespace(scope_type="platform", scope_id=None, value=5),
        SimpleNamespace(scope_type="plan", scope_id=plan, value=4),
        SimpleNamespace(scope_type="user", scope_id=uid, value=3),
    ]

    class FakeSession:
        def __init__(self, rows: list[Any]) -> None:
            self.rows = rows

        async def execute(self, _q: Any) -> Any:
            return SimpleNamespace(all=lambda: self.rows)

    key = "devices.student.max_trusted"
    assert await pol.resolve(FakeSession(rows), key, user_id=uid, plan_id=plan) == 3  # type: ignore[arg-type]
    assert await pol.resolve(FakeSession(rows[:2]), key, plan_id=plan) == 4  # type: ignore[arg-type]
    assert await pol.resolve(FakeSession(rows[:1]), key) == 5  # type: ignore[arg-type]
    assert await pol.resolve(FakeSession([]), key) == 3  # type: ignore[arg-type]  # code default


@pytest.mark.usefixtures("admin_backend")
async def test_feature_flags_and_approval_queue_visibility(client, db) -> None:
    sa, r1 = await staff(db, "super_admin"), await staff(db, "super_admin")
    cm = await staff(db, "content_manager")
    bsa, b1 = await staff_browser(client, sa), await staff_browser(client, r1, ip="198.18.0.6")
    bcm = await staff_browser(client, cm, ip="198.18.0.9")
    flags = await bsa.get("/admin/feature-flags")
    assert any(f["flag_key"] == "platform.maintenance_mode" for f in flags.json()["data"])
    assert all("org_allowlist" not in f for f in flags.json()["data"])
    patched = await bsa.patch(
        "/admin/feature-flags/payments.cashfree_enabled", {"is_enabled": True, "rollout_percent": 100}
    )
    assert patched.status_code == 200 and patched.json()["is_enabled"]
    gone = await bsa.patch("/admin/feature-flags/payments.cashfree_enabled", {"org_allowlist": []})
    assert gone.status_code in (400, 422)
    assert (
        await bcm.patch("/admin/feature-flags/payments.cashfree_enabled", {"is_enabled": False})
    ).status_code == 403
    prop = await b1.post(
        "/admin/policy-settings/risk.window_days/changes",
        {"value": 21, "change_reason": "Shorter window trial"},
        headers=idem(),
    )
    aid = prop.json()["approval_request_id"]
    mine = (await b1.get("/admin/approvals")).json()["data"]
    assert any(a["approval_request_id"] == aid for a in mine)  # requester sees own
    theirs = (await bsa.get("/admin/approvals")).json()["data"]
    assert any(a["approval_request_id"] == aid for a in theirs)
    detail = await bsa.get(f"/admin/approvals/{aid}")
    assert detail.json()["payload"]["value"] == 21 and len(detail.json()["payload_hash"]) == 64
    cancel = await b1.post(f"/admin/approvals/{aid}/cancel")
    assert cancel.json()["status"] == "cancelled"
    assert (await approve(bsa, aid)).status_code == 409


async def test_org_privacy_route_is_gone(client, db) -> None:
    sa = await staff(db, "super_admin")
    bsa = await staff_browser(client, sa, ip="198.18.0.10")
    assert (await bsa.get(f"/orgs/{uuid.uuid4()}/privacy-requests")).status_code == 404


async def test_privacy_requests_basic_flow(client, browser, db) -> None:
    u = await adult(db)
    assert (await browser.login(u.email)).json()["result"] == "authenticated"
    erase = await browser.post(
        "/me/privacy-requests", {"request_type": "erasure", "confirm": True}, headers=idem()
    )
    assert erase.status_code == 401 and erase.json()["code"] == "step_up_required"
    exp = await browser.post("/me/privacy-requests", {"request_type": "access_export"}, headers=idem())
    assert exp.status_code == 201 and exp.json()["request_ref"].startswith("PRV-")
    rid = exp.json()["request_id"]
    assert (await browser.get(f"/me/privacy-requests/{rid}/export")).status_code == 409
    sa = await staff(db, "super_admin")
    bsa = await staff_browser(client, sa, ip="198.18.0.7")
    queue = await bsa.get("/admin/privacy-requests")
    assert any(x["request_id"] == rid for x in queue.json()["data"])
    done = await bsa.post(
        f"/admin/privacy-requests/{rid}/complete", {"response_summary": "Export generated"}, headers=idem()
    )
    assert done.status_code == 200 and done.json()["status"] == "completed"
    data = await browser.get(f"/me/privacy-requests/{rid}/export")
    assert data.status_code == 200 and data.json()["account"]["email"] == u.email
    other = await adult(db)
    ob = Browser(client)
    await ob.login(other.email)
    assert (await ob.get(f"/me/privacy-requests/{rid}")).status_code == 404
    g = await browser.post(
        "/me/privacy-requests", {"request_type": "grievance", "details": "Slow support"}, headers=idem()
    )
    w = await browser.post(f"/me/privacy-requests/{g.json()['request_id']}/withdraw")
    assert w.json()["status"] == "withdrawn"
    third = await browser.post("/me/privacy-requests", {"request_type": "correction"}, headers=idem())
    assert third.status_code == 201
    fourth = await browser.post("/me/privacy-requests", {"request_type": "correction"}, headers=idem())
    assert fourth.status_code == 429
    rej = await bsa.post(
        f"/admin/privacy-requests/{third.json()['request_id']}/reject", {"reason": "Unverifiable correction"}
    )
    assert rej.json()["status"] == "rejected"
    student_view = (await browser.get("/me/privacy-requests")).json()["data"]
    assert {x["status"] for x in student_view} >= {"completed", "withdrawn", "rejected"}
    assert (await bsa.get("/admin/retention-policies")).status_code == 200
