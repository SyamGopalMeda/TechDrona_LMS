"""OPS audit probe: PATCH max_redemptions=null makes an active coupon unlimited without Dual."""
from __future__ import annotations

from app.core.time import utcnow
from tests.commerce.factory import make_buyer
from tests.commerce.test_coupons_refunds_subscriptions import finance


async def test_patch_coupon_to_unlimited_bypasses_dual(api, db, client, fake_gw) -> None:
    f = finance(api, await make_buyer(db))
    r = await f.post(
        "/finance/coupons",
        {"code": "SMALL10", "discount_type": "percent", "percent_off": "10", "max_redemptions": 100,
         "valid_from": utcnow().isoformat()},
    )
    print("CREATE", r.status_code, r.json().get("status"), r.json().get("max_redemptions"))
    cid = r.json()["coupon_id"]
    r = await f.patch(f"/finance/coupons/{cid}", {"max_redemptions": None})
    print("PATCH", r.status_code, r.json().get("status"), r.json().get("max_redemptions"))
    assert not (r.status_code == 200 and r.json().get("max_redemptions") is None and r.json().get("status") == "active"), "unlimited active coupon without Dual"
