"""Phase A audit probes for the super admin panel (SUP-*). Each test asserts the CURRENT behaviour,
so a pass documents the finding; docstrings state the expected behaviour."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.audit import AuditActor, audit
from app.core.ids import uuid7
from app.modules.audit.sealer import seal_once
from tests.identity.factory import add_member, grant, make_batch, make_org, make_user
from tests.security.helpers import idem, staff, staff_browser


async def test_sup_privileged_grant_invisible_and_undecidable_in_admin_queue(client, db) -> None:
    """Expected (FR-ADM-004, role matrix §5): a privileged role grant request is decided in ADM-010.
    Actual: /admin/approvals hides it from the approver and ADM-14 returns 404."""
    sa1, sa2 = await staff(db, "super_admin"), await staff(db, "super_admin")
    target = await make_user(db)
    b1 = await staff_browser(client, sa1, ip="198.18.2.1")
    b2 = await staff_browser(client, sa2, ip="198.18.2.2")
    r = await b1.post(
        "/rbac/grants",
        {"user_id": str(target.id), "role_key": "finance_admin", "scope_type": "platform", "reason": "new hire"},
        headers=idem(),
    )
    assert r.status_code == 202, r.text
    apr_id = r.json()["approval_request_id"]
    mine = [x["approval_request_id"] for x in (await b1.get("/admin/approvals")).json()["data"]]
    theirs = [x["approval_request_id"] for x in (await b2.get("/admin/approvals")).json()["data"]]
    print("\nrequester sees:", apr_id in mine, "| approver sees:", apr_id in theirs)
    assert apr_id in mine and apr_id not in theirs
    dec = await b2.post(f"/admin/approvals/{apr_id}/approve", {"note": "ok"}, headers=idem())
    print("ADM-14 approve:", dec.status_code, dec.json().get("code"))
    assert dec.status_code == 404
    ok = await b2.post(f"/rbac/approval-requests/{apr_id}/approve", {"note": "ok"})
    print("RBAC-07 approve:", ok.status_code, ok.json().get("status"))
    assert ok.status_code == 200 and ok.json()["status"] == "executed", ok.text


async def test_sup_approval_list_has_no_payload(client, db) -> None:
    """FR-ADM-004 'payload diff': queue list rows carry no payload; the UI never fetches detail."""
    sa1, sa2 = await staff(db, "super_admin"), await staff(db, "super_admin")
    b1 = await staff_browser(client, sa1, ip="198.18.2.3")
    b2 = await staff_browser(client, sa2, ip="198.18.2.4")
    r = await b1.post(
        "/admin/policy-settings/sessions.student.max_concurrent/changes",
        {"value": 1, "change_reason": "Audit probe change"},
        headers=idem(),
    )
    assert r.status_code == 202, r.text
    rid = r.json()["approval_request_id"]
    rows = [x for x in (await b2.get("/admin/approvals")).json()["data"] if x["approval_request_id"] == rid]
    print("\nlist row keys:", sorted(rows[0].keys()))
    assert rows and "payload" not in rows[0]


async def test_sup_grantee_can_approve_own_privileged_grant(client, db) -> None:
    """Approver == grantee is not blocked by RBAC-07 (only requester != approver is checked)."""
    sa1, sa2 = await staff(db, "super_admin"), await staff(db, "super_admin")
    b1 = await staff_browser(client, sa1, ip="198.18.2.5")
    b2 = await staff_browser(client, sa2, ip="198.18.2.6")
    r = await b1.post(
        "/rbac/grants",
        {"user_id": str(sa2.id), "role_key": "security_reviewer", "scope_type": "platform", "reason": "covering"},
        headers=idem(),
    )
    assert r.status_code == 202, r.text
    ok = await b2.post(f"/rbac/approval-requests/{r.json()['approval_request_id']}/approve", {"note": "self"})
    print("\ngrantee self-approve:", ok.status_code, ok.json())
    assert ok.status_code == 200 and ok.json()["status"] == "executed"


async def test_sup_org_suspend_finance_admin_cannot_approve(client, db) -> None:
    """Role matrix §5: Suspend organization approver = finance_admin OR second super_admin."""
    sa = await staff(db, "super_admin")
    fin = await staff(db, "finance_admin")
    bsa = await staff_browser(client, sa, ip="198.18.2.7")
    bfin = await staff_browser(client, fin, ip="198.18.2.8")
    org = await make_org(db)
    r = await bsa.post(f"/orgs/{org}/suspend", {"reason": "non payment probe"}, headers=idem())
    assert r.status_code == 202, r.text
    apr_id = r.json()["approval_request_id"]
    seen = [x["approval_request_id"] for x in (await bfin.get("/admin/approvals")).json()["data"]]
    dec = await bfin.post(f"/admin/approvals/{apr_id}/approve", {"note": "ok"}, headers=idem())
    print("\nfinance sees:", apr_id in seen, "| approve:", dec.status_code, dec.json().get("code"))
    assert apr_id not in seen and dec.status_code in (403, 404)


async def test_sup_finance_admin_reads_security_audit_events(
    client, db, committed_engine: AsyncEngine, sealer_engine: AsyncEngine
) -> None:
    """AUD-01: results filtered by role (finance_admin -> commerce events only); SoD-01."""
    marker = f"security.probe.m{uuid7().hex[:12]}"
    async with committed_engine.connect() as conn, conn.begin():
        s = AsyncSession(bind=conn)
        await audit(
            s,
            AuditActor("user", user_id=uuid7(), session_id=uuid7(), roles=("security_reviewer",)),
            marker,
            "security_case",
            uuid7(),
            after={"probe": "evidence"},
            ip="203.0.113.9",
        )
        await s.close()
    while await seal_once(sealer_engine):
        pass
    fin = await staff(db, "finance_admin")
    bfin = await staff_browser(client, fin, ip="198.18.2.9")
    r = await bfin.get("/audit/events", params={"action": marker})
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    print("\nfinance rows:", [(x["action"], x["target_type"]) for x in rows])
    assert rows and rows[0]["target_type"] == "security_case"
    d = await bfin.get(f"/audit/events/{rows[0]['seq']}")
    print("detail ip present:", d.json().get("ip") is not None, "after:", d.json().get("after_state"))
    assert d.status_code == 200 and d.json()["ip"] == "203.0.113.9"


async def test_sup_coordinator_self_grants_trainer(client, db) -> None:
    """Self-grant guard covers scope_type == platform only."""
    org = await make_org(db)
    coord = await make_user(db, with_totp=True)
    await add_member(db, org, coord.id, "staff")
    await grant(db, coord.id, "college_coordinator", "organization", org)
    batch = await make_batch(db, org, coord.id)
    b = await staff_browser(client, coord, ip="198.18.2.10")
    r = await b.post(
        "/rbac/grants",
        {"user_id": str(coord.id), "role_key": "trainer", "scope_type": "batch", "scope_id": str(batch), "reason": "self"},
        headers=idem(),
    )
    print("\ncoordinator self-grant:", r.status_code, r.json())
    assert r.status_code == 201


async def test_sup_requester_cannot_self_approve_any_path(client, db) -> None:
    """Verify-OK: requester self-approval via ADM-14 and RBAC-07, and platform self-grant, refused."""
    sa1 = await staff(db, "super_admin")
    target = await make_user(db)
    b1 = await staff_browser(client, sa1, ip="198.18.2.11")
    pol = await b1.post(
        "/admin/policy-settings/sessions.student.max_concurrent/changes",
        {"value": 1, "change_reason": "Self approval probe"},
        headers=idem(),
    )
    a = await b1.post(f"/admin/approvals/{pol.json()['approval_request_id']}/approve", {}, headers=idem())
    g = await b1.post(
        "/rbac/grants",
        {"user_id": str(target.id), "role_key": "super_admin", "scope_type": "platform", "reason": "self"},
        headers=idem(),
    )
    b = await b1.post(f"/rbac/approval-requests/{g.json()['approval_request_id']}/approve", {})
    selfg = await b1.post(
        "/rbac/grants",
        {"user_id": str(sa1.id), "role_key": "finance_admin", "scope_type": "platform", "reason": "self"},
        headers=idem(),
    )
    print(
        "\nADM-14 self:", a.status_code, a.json().get("code"),
        "| RBAC-07 self:", b.status_code, b.json().get("code"),
        "| self-grant:", selfg.status_code, selfg.json().get("code"),
    )
    assert a.json()["code"] == "sod_violation" and b.json()["code"] == "sod_violation"
    assert selfg.json()["code"] == "sod_violation"


async def test_sup_plain_user_cannot_call_admin_apis(client, db) -> None:
    """Backend enforcement behind the un-gated /admin web shell."""
    st = await make_user(db, with_totp=True)
    b = await staff_browser(client, st, ip="198.18.2.12")
    codes = {}
    for p in (
        "/admin/dashboard", "/admin/users", "/admin/feature-flags", "/admin/policy-settings",
        "/admin/privacy-requests", "/admin/break-glass", "/audit/events", "/rbac/grants",
    ):
        codes[p] = (await b.get(p)).status_code
    appr = await b.get("/admin/approvals")
    print("\n", codes, "approvals:", appr.status_code, len(appr.json().get("data", [])))
    assert all(c == 403 for c in codes.values())
