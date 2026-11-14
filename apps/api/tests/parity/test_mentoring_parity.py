"""Parity: placement package (product with mentor-session quota) -> mentoring over HTTP on the
Firebase stack.

VM expectations (``tests/mentoring``, ``tests/commerce``): finance product/plan/price 201; ENT-06
grant of the product 201 (quotas from the product's items); MNT slots 201; student slots 200
with the quota; booking 201; reschedule 200 ``rescheduled``; cancel 200 ``cancelled_by_student``
with ``credit_restored``; mentor sessions 200.
"""

from __future__ import annotations

from datetime import timedelta

from tests.parity.harness import World, grant


async def _package_product(w: World) -> str:
    _, fh = await w.staff("finance")
    r = await w.call(
        "POST",
        "/finance/products",
        fh,
        expect=201,
        json={
            "sku": "PP-PARITY-1",
            "name": "Parity pack",
            "product_kind": "placement_package",
            "status": "active",
            "items": [
                {
                    "item_type": "feature",
                    "feature_key": "mentor_sessions",
                    "quantity": 2,
                    "unit_price_paise": 50000,
                }
            ],
        },
    )
    return str(r.json()["product_id"])


async def test_package_grant_then_book_reschedule_cancel(web: World) -> None:
    from app.core.time import utcnow

    w = web
    product_id = await _package_product(w)
    student, sh = await w.learner("mentee")
    await grant(w, student.user_id, {"product_id": product_id})
    _, mh = await w.staff("mentor")

    now = utcnow()
    starts = [now + timedelta(hours=h) for h in (48, 72)]
    r = await w.call(
        "POST",
        "/mentor/slots",
        mh,
        expect=201,
        idem=True,
        json={"slots": [{"starts_at": s.isoformat(), "duration_minutes": 60} for s in starts]},
    )
    slot_ids = [s["id"] for s in r.json()["data"]]
    r = await w.call("GET", "/mentoring/slots", sh)
    assert r.json()["quota"]["mentor_sessions_remaining"] == 2, r.text
    r = await w.call(
        "POST", "/mentoring/bookings", sh, expect=(200, 201), idem=True, json={"slot_id": slot_ids[0]}
    )
    bid = r.json()["id"]
    r = await w.call("GET", "/mentoring/slots", sh)
    assert r.json()["quota"]["mentor_sessions_remaining"] == 1, r.text
    r = await w.call("POST", f"/mentoring/bookings/{bid}/reschedule", sh, json={"slot_id": slot_ids[1]})
    assert r.json()["status"] == "rescheduled"
    await w.call("GET", "/me/mentoring/bookings", sh)
    await w.call("GET", "/mentor/sessions", mh, params={"view": "upcoming"})
    r = await w.call("POST", f"/mentoring/bookings/{bid}/cancel", sh)
    assert r.json()["status"] == "cancelled_by_student" and r.json()["credit_restored"] is True, r.text
    await w.call("GET", "/mentor/slots", mh)
    await w.relay()  # outbox consumers, as the Firebase worker runs them
