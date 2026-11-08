"""commerce: money integrity, refund state machine, subscription billing state, webhook backoff.

Audit Phase B fixes (docs/audit/fixes/commerce.md):

* DB-07: ``>= 0`` CHECKs on ``order_items`` money columns, ``payments.fee_paise`` /
  ``tax_on_fee_paise`` and ``coupons.min_order_paise``; ``ck_oi_total`` (item total = taxable +
  CGST + SGST + IGST). Added ``NOT VALID`` and validated only when no existing row violates them
  (a dev database with bad rows keeps the constraint for new rows and logs a NOTICE).
* COM-11 / ADM-24: ``orders.refunded_paise`` — the sum of refunds that are approved, processing
  or processed (reserved at approval under the order row lock, released when the provider
  reports the refund failed). ``ck_order_refunded`` makes an over-refund impossible even if an
  application check is bypassed.
* COM-01: refund reason ``price_adjustment`` (finance-only partial refund that keeps access).
* COM-02: provider-submit retry bookkeeping on ``refunds`` (``submit_attempts``,
  ``next_submit_at``, ``last_error``).
* COM-10: billing state / GSTIN / name captured on ``subscriptions`` for every debit invoice.
* COM-13: ``payment_webhook_events.next_attempt_at`` (exponential backoff instead of a fixed
  8-attempt limit).

Revision ID: commerce_0003
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "commerce_0003"
down_revision: str | Sequence[str] | None = "commerce_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECKS: list[tuple[str, str, str]] = [
    ("order_items", "ck_oi_unit_nonneg", "unit_amount_paise >= 0"),
    ("order_items", "ck_oi_taxable_nonneg", "taxable_paise >= 0"),
    ("order_items", "ck_oi_discount_nonneg", "discount_paise >= 0"),
    ("order_items", "ck_oi_total_nonneg", "total_paise >= 0"),
    ("order_items", "ck_oi_total", "total_paise = taxable_paise + cgst_paise + sgst_paise + igst_paise"),
    ("payments", "ck_pay_fee_nonneg", "fee_paise >= 0"),
    ("payments", "ck_pay_fee_tax_nonneg", "tax_on_fee_paise >= 0"),
    ("coupons", "ck_coupon_min_order_nonneg", "min_order_paise >= 0"),
]

_REASONS_OLD = "'within_policy_window','content_issue','duplicate_payment','service_failure','goodwill','chargeback','other'"


def _add_check(table: str, name: str, expr: str) -> None:
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({expr}) NOT VALID")
    op.execute(
        f"""
        DO $$
        BEGIN
          IF NOT EXISTS (SELECT 1 FROM {table} WHERE NOT ({expr})) THEN
            ALTER TABLE {table} VALIDATE CONSTRAINT {name};
          ELSE
            RAISE NOTICE 'constraint {name} left NOT VALID: existing rows violate it';
          END IF;
        END $$;
        """
    )


def upgrade() -> None:
    for table, name, expr in _CHECKS:
        _add_check(table, name, expr)

    op.execute(
        """
        ALTER TABLE orders ADD COLUMN refunded_paise bigint NOT NULL DEFAULT 0;
        UPDATE orders o SET refunded_paise = s.amount
          FROM (SELECT order_id, sum(amount_paise) AS amount FROM refunds
                WHERE status IN ('approved','processing','processed') GROUP BY order_id) s
         WHERE s.order_id = o.id;
        COMMENT ON COLUMN orders.refunded_paise IS
          'Sum of refunds approved/processing/processed (reserved at approval; released on provider failure)';
        """
    )
    _add_check("orders", "ck_order_refunded", "refunded_paise >= 0 AND refunded_paise <= total_paise")

    op.execute(
        f"""
        ALTER TABLE refunds DROP CONSTRAINT IF EXISTS refunds_reason_code_check;
        ALTER TABLE refunds ADD CONSTRAINT refunds_reason_code_check
          CHECK (reason_code IN ({_REASONS_OLD},'price_adjustment'));
        ALTER TABLE refunds ADD COLUMN submit_attempts smallint NOT NULL DEFAULT 0;
        ALTER TABLE refunds ADD COLUMN next_submit_at timestamptz NULL;
        ALTER TABLE refunds ADD COLUMN last_error text NULL;
        CREATE INDEX ix_refund_unsubmitted ON refunds (next_submit_at)
          WHERE status = 'approved' AND gateway_refund_id IS NULL;
        CREATE INDEX ix_refund_processing ON refunds (created_at) WHERE status = 'processing';

        ALTER TABLE subscriptions ADD COLUMN billing_name text NULL;
        ALTER TABLE subscriptions ADD COLUMN billing_state_code text NULL CHECK (billing_state_code ~ '^[0-9]{{2}}$');
        ALTER TABLE subscriptions ADD COLUMN billing_gstin text NULL CHECK (billing_gstin ~ '^[0-9]{{2}}[A-Z0-9]{{13}}$');

        ALTER TABLE payment_webhook_events ADD COLUMN next_attempt_at timestamptz NULL;
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE payment_webhook_events DROP COLUMN IF EXISTS next_attempt_at;
        ALTER TABLE subscriptions DROP COLUMN IF EXISTS billing_gstin;
        ALTER TABLE subscriptions DROP COLUMN IF EXISTS billing_state_code;
        ALTER TABLE subscriptions DROP COLUMN IF EXISTS billing_name;
        DROP INDEX IF EXISTS ix_refund_processing;
        DROP INDEX IF EXISTS ix_refund_unsubmitted;
        ALTER TABLE refunds DROP COLUMN IF EXISTS last_error;
        ALTER TABLE refunds DROP COLUMN IF EXISTS next_submit_at;
        ALTER TABLE refunds DROP COLUMN IF EXISTS submit_attempts;
        ALTER TABLE refunds DROP CONSTRAINT IF EXISTS refunds_reason_code_check;
        ALTER TABLE refunds ADD CONSTRAINT refunds_reason_code_check CHECK (reason_code IN ({_REASONS_OLD}));
        ALTER TABLE orders DROP CONSTRAINT IF EXISTS ck_order_refunded;
        ALTER TABLE orders DROP COLUMN IF EXISTS refunded_paise;
        """
    )
    for table, name, _ in reversed(_CHECKS):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
