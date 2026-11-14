"""commerce: drop the foreign keys from other modules into commerce tables (Firebase P6 flip)

Revision ID: commerce_0005
Revises: commerce_0004
Create Date: 2026-11-12

**NOT APPLIED. Run only at the commerce flip** (``TD_STORE_COMMERCE=firestore``). This file sits
in ``migrations/flip/``, outside ``version_locations`` (``alembic.ini``: ``migrations/versions``),
so ``alembic upgrade heads``, the test suite and deployments never see it. At flip time, as part
of the documented flip (docs/firebase/agents/data-money.md §Flip):

    git mv apps/api/migrations/flip/commerce_0005_drop_inbound_fks.py apps/api/migrations/versions/
    cd apps/api && .venv/Scripts/python -m alembic upgrade heads

Why: with commerce on Firestore, products, order items, subscriptions, coupon redemptions and
orders are created in Firestore only, so these Postgres foreign keys would refuse every
entitlement grant (``ent.grant`` with ``order_item_id`` / ``product_id`` / ``subscription_id`` /
``coupon_redemption_id``) and every support ticket that names a new order:

* ``entitlements.product_id``            -> ``products``
* ``entitlements.order_item_id``         -> ``order_items``
* ``entitlements.subscription_id``       -> ``subscriptions``
* ``entitlements.coupon_redemption_id``  -> ``coupon_redemptions``
* ``support_tickets.related_order_id``   -> ``orders``

The references become soft references checked by the application (``commerce.public``), like the
catalog ids after ``learning_0004``. Columns and their indexes stay. Downgrade re-adds the
constraints (it fails if orphan ids exist then; reseed first).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "commerce_0005"
down_revision: str | Sequence[str] | None = "commerce_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = ("entitlements_0003", "support_0004")

# (table, column, referenced table)
FKS = (
    ("entitlements", "product_id", "products"),
    ("entitlements", "order_item_id", "order_items"),
    ("entitlements", "subscription_id", "subscriptions"),
    ("entitlements", "coupon_redemption_id", "coupon_redemptions"),
    ("support_tickets", "related_order_id", "orders"),
)


def upgrade() -> None:
    # Constraint names are looked up (inline REFERENCES got PostgreSQL's generated names).
    for table, column, ref in FKS:
        op.execute(
            f"""
            DO $$
            DECLARE r record;
            BEGIN
              FOR r IN
                SELECT c.conname
                  FROM pg_constraint c
                  JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
                 WHERE c.contype = 'f'
                   AND c.conrelid = '{table}'::regclass
                   AND c.confrelid = '{ref}'::regclass
                   AND a.attname = '{column}'
              LOOP
                EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', r.conname);
              END LOOP;
            END $$;
            """
        )


def downgrade() -> None:
    for table, column, ref in FKS:
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_{column}_fkey "
            f"FOREIGN KEY ({column}) REFERENCES {ref}(id)"
        )
