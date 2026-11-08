"""w2a commerce fixes: coupon status filter and approval envelope (webstaff R6), the
``payments.cashfree_enabled`` flag consumer (ADM-17), and the runtime outbox consumers (learn R3;
single company: the COM-04 ``orgs.member_removed`` consumer is gone, cache invalidation stays)."""

from __future__ import annotations

from app.core.time import utcnow
from app.modules.commerce.gateway import set_gateway
from tests.commerce.factory import make_buyer, make_coupon
from tests.commerce.test_coupons_refunds_subscriptions import finance


async def test_coupon_create_returns_approval_envelope_and_list_filters(api, db, fake_gw) -> None:
    uid = await make_buyer(db)
    f = finance(api, uid)
    await make_coupon(db, uid, code="LIVE10")
    r = await f.post(
        "/finance/coupons",
        {
            "code": "BIG60",
            "discount_type": "percent",
            "percent_off": "60",
            "max_redemptions": 10,
            "valid_from": utcnow().isoformat(),
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "paused" and body["approval_status"] == "approval_pending"
    assert body["action_type"] == "commerce.coupon.activate"
    assert body["required_approver_role"] == "super_admin"
    assert body["expires_at"] and body["approval_request_id"]
    apr_id = body["approval_request_id"]

    r = await f.get("/finance/coupons", params={"status": "paused"})
    assert r.status_code == 200, r.text
    codes = {c["code"]: c for c in r.json()["data"]}
    assert "BIG60" in codes and "LIVE10" not in codes
    assert codes["BIG60"]["approval_request_id"] == apr_id
    r = await f.get("/finance/coupons", params={"status": "active"})
    data = r.json()["data"]
    assert all(c["status"] == "active" for c in data) and any(c["code"] == "LIVE10" for c in data)
    assert all(c["approval_request_id"] is None for c in data)
    r = await f.get("/finance/coupons", params={"status": "bogus"})
    assert r.status_code in (400, 422)


async def test_cashfree_webhook_is_gated_by_feature_flag(client, db, fake_gw) -> None:
    from tests.security.helpers import staff, staff_browser

    sa = await staff(db, "super_admin")
    bsa = await staff_browser(client, sa, ip="198.18.3.31")
    key = "payments.cashfree_enabled"
    set_gateway("cashfree", fake_gw)
    try:
        assert (await bsa.patch(f"/admin/feature-flags/{key}", {"is_enabled": False})).status_code == 200
        r = await client.post("/api/v1/webhooks/cashfree", content=b"{}")
        assert r.status_code == 404, r.text
        p = await bsa.patch(f"/admin/feature-flags/{key}", {"is_enabled": True, "rollout_percent": 100})
        assert p.status_code == 200, p.text
        r = await client.post("/api/v1/webhooks/cashfree", content=b"{}")
        assert r.status_code == 400 and r.json()["code"] == "webhook_signature_invalid", r.text
    finally:
        set_gateway("cashfree", None)
        await bsa.patch(f"/admin/feature-flags/{key}", {"is_enabled": False, "rollout_percent": 0})


def test_entitlement_consumers_in_api_and_worker_and_no_member_removed_hook() -> None:
    """Fresh interpreters, so an earlier import in this test session cannot mask a gap."""
    import subprocess
    import sys
    from pathlib import Path

    api_dir = Path(__file__).resolve().parents[2]
    for boot in (
        "from app.main import create_app; create_app()",
        "from app.worker import create_celery; create_celery()",
    ):
        code = "\n".join(
            [
                boot,
                "from app.core.outbox import handlers_for",
                "from app.modules.entitlements.service import on_entitlement_event",
                "assert on_entitlement_event in handlers_for('entitlement.revoked')",
                "assert not handlers_for('orgs.member_removed')",
                "print('OK')",
            ]
        )
        out = subprocess.run(  # noqa: S603 - fixed argv
            [sys.executable, "-c", code], cwd=api_dir, capture_output=True, text=True, timeout=180
        )
        assert out.returncode == 0 and "OK" in out.stdout, (boot, out.stderr[-2000:])
