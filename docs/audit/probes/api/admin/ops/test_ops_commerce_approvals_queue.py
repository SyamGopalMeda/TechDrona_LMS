"""OPS audit probe: commerce Dual requests are invisible/undecidable via admin/approvals (the queue the finance UI uses)."""
from __future__ import annotations

from app.core.time import utcnow
from tests.commerce.factory import make_buyer
from tests.commerce.test_coupons_refunds_subscriptions import finance


async def test_coupon_dual_not_in_admin_approvals(api, db, client, fake_gw) -> None:
    f1 = finance(api, await make_buyer(db))
    r = await f1.post(
        "/finance/coupons",
        {"code": "BIG60", "discount_type": "percent", "percent_off": "60", "max_redemptions": 10,
         "valid_from": utcnow().isoformat()},
    )
    appr = r.json()["approval_request_id"]
    print("CREATE", r.status_code, r.json().get("status"))
    f2 = finance(api, await make_buyer(db))
    r = await f2.get("/admin/approvals")
    ids = [x["approval_request_id"] for x in r.json().get("data", [])]
    print("LIST", r.status_code, "visible_to_second_finance_admin=", appr in ids)
    r = await f2.post(f"/admin/approvals/{appr}/approve", {"note": "ok"}, idem=True)
    print("ADMIN_APPROVE", r.status_code, r.json().get("code"))
    r = await f2.post(f"/finance/approval-requests/{appr}/approve", {"note": "ok"})
    print("FIN_APPROVE", r.status_code, r.json().get("status"))
