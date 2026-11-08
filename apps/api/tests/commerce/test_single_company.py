"""Single company (REMOVAL-PLAN §1.2, migration ``commerce_0004``): the B2B schema is gone, the
contract-invoice archive is platform-read-only, college coupons and institution seat products
can no longer exist, and the public coupon read path still works."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.core.db import system_context, tenant_context
from app.core.ids import uuid7
from tests.commerce.factory import make_buyer, make_coupon, make_product, principal


async def _scalar(db, sql: str, **kw):
    return (await db.execute(text(sql), kw)).scalar()


async def test_b2b_schema_dropped_and_archive_locked(db) -> None:
    await system_context(db, "test")
    assert await _scalar(db, "SELECT to_regclass('public.institution_contracts')") is None
    for table, column in (("invoices", "contract_id"), ("coupons", "organization_id")):
        n = await _scalar(
            db,
            "SELECT count(*) FROM information_schema.columns WHERE table_name = :t AND column_name = :c",
            t=table,
            c=column,
        )
        assert n == 0, (table, column)
    forced = await _scalar(
        db,
        "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE relname = 'commerce_b2b_archive'",
    )
    assert forced is True
    for t in ("orders", "order_items", "payments", "refunds", "invoices", "coupons", "products"):
        assert await _scalar(db, "SELECT relforcerowsecurity FROM pg_class WHERE relname = :t", t=t), t
    # td_app may never write the archive, even as platform
    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await db.execute(
                text(
                    "INSERT INTO commerce_b2b_archive (record_type, source_id, payload, archived_by) "
                    "VALUES ('contract_invoice', :i, '{}', 'test')"
                ),
                {"i": uuid7()},
            )


async def test_institution_seat_product_cannot_be_active(db) -> None:
    cat = await make_product(db)
    await system_context(db, "test")
    with pytest.raises(IntegrityError):
        async with db.begin_nested():
            await db.execute(
                text("UPDATE products SET product_kind = 'institution_seat' WHERE id = :i"),
                {"i": cat.product.id},
            )
    async with db.begin_nested():
        await db.execute(
            text("UPDATE products SET product_kind = 'institution_seat', status = 'retired' WHERE id = :i"),
            {"i": cat.product.id},
        )


async def test_coupons_readable_by_everyone_writable_by_platform_only(db) -> None:
    uid = await make_buyer(db)
    c = await make_coupon(db, uid, code=f"PUB{uuid7().hex[-6:]}")
    await tenant_context(db, principal(uid))
    assert await _scalar(db, "SELECT count(*) FROM coupons WHERE id = :i", i=c.id) == 1
    res = await db.execute(text("UPDATE coupons SET status = 'paused' WHERE id = :i"), {"i": c.id})
    assert res.rowcount == 0  # USING (is_platform) hides the row from writers
    res = await db.execute(text("DELETE FROM coupons WHERE id = :i"), {"i": c.id})
    assert res.rowcount == 0
