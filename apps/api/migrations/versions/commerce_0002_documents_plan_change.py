"""commerce: invoice PDFs, B2B contract invoices, GST register exports, plan change.

* ``invoices``: ``contract_id`` (COM-42 B2B invoice against an institution contract),
  ``description``, ``due_on``. ``pdf_s3_key`` already existed (COM-16).
* ``order_items``: ``plan_id`` / ``price_id`` nullable — offline-PO contract invoice lines have
  no catalogue price (``ck_oi_catalogue``: both or neither).
* ``subscriptions``: scheduled downgrade (``scheduled_plan_id``, ``scheduled_price_id``,
  ``scheduled_change_at``) and the prorated upgrade amount added to the next debit
  (``pending_addon_paise``) — COM-14 (FR-COM-006).
* ``gst_exports`` (COM-37): platform-only GST register export jobs.

Revision ID: commerce_0002
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "commerce_0002"
down_revision: str | Sequence[str] | None = "commerce_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = ("rbac_0001",)


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE order_items ALTER COLUMN plan_id DROP NOT NULL;
        ALTER TABLE order_items ALTER COLUMN price_id DROP NOT NULL;
        ALTER TABLE order_items ADD CONSTRAINT ck_oi_catalogue CHECK (num_nonnulls(plan_id, price_id) IN (0, 2));

        ALTER TABLE invoices ADD COLUMN contract_id uuid NULL REFERENCES institution_contracts(id);
        ALTER TABLE invoices ADD COLUMN description text NULL;
        ALTER TABLE invoices ADD COLUMN due_on date NULL;
        CREATE INDEX ix_inv_contract ON invoices (contract_id) WHERE contract_id IS NOT NULL;
        CREATE INDEX ix_inv_issue_date ON invoices (issue_date);

        ALTER TABLE subscriptions ADD COLUMN scheduled_plan_id uuid NULL REFERENCES plans(id);
        ALTER TABLE subscriptions ADD COLUMN scheduled_price_id uuid NULL REFERENCES prices(id);
        ALTER TABLE subscriptions ADD COLUMN scheduled_change_at timestamptz NULL;
        ALTER TABLE subscriptions ADD COLUMN pending_addon_paise bigint NOT NULL DEFAULT 0;
        ALTER TABLE subscriptions ADD CONSTRAINT ck_sub_scheduled
          CHECK (num_nonnulls(scheduled_plan_id, scheduled_price_id, scheduled_change_at) IN (0, 3));
        ALTER TABLE subscriptions ADD CONSTRAINT ck_sub_addon
          CHECK (pending_addon_paise >= 0 AND pending_addon_paise <= 1500000);

        CREATE TABLE gst_exports (
          id                   uuid        PRIMARY KEY,
          requested_by         uuid        NOT NULL,
          period_from          date        NOT NULL,
          period_to            date        NOT NULL,
          reason               text        NULL,
          status               text        NOT NULL CHECK (status IN ('awaiting_approval','ready','rejected','expired','failed')),
          row_count            integer     NULL,
          approval_request_id  uuid        NULL,
          approved_by          uuid        NULL,
          s3_key               text        NULL,
          download_expires_at  timestamptz NULL,
          created_at           timestamptz NOT NULL DEFAULT now(),
          completed_at         timestamptz NULL,
          updated_at           timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_gst_period CHECK (period_to >= period_from),
          CONSTRAINT ck_gst_approver CHECK (approved_by IS NULL OR approved_by <> requested_by),
          CONSTRAINT ck_gst_ready CHECK (status <> 'ready' OR s3_key IS NOT NULL)
        );
        CREATE INDEX ix_gst_exports_requester ON gst_exports (requested_by, created_at DESC);
        COMMENT ON TABLE gst_exports IS 'Owner: commerce | RLS: platform only | Retention: R-FIN | PII: P2 (file)';
        """
    )
    op.execute("ALTER TABLE gst_exports ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE gst_exports FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY p_platform ON gst_exports FOR ALL TO td_app, td_readonly "
        "USING (app.is_platform()) WITH CHECK (app.is_platform())"
    )
    op.execute("REVOKE DELETE, TRUNCATE ON gst_exports FROM td_app")
    op.execute(
        "CREATE TRIGGER trg_gst_exports_updated_at BEFORE UPDATE ON gst_exports "
        "FOR EACH ROW EXECUTE FUNCTION app.set_updated_at()"
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE IF EXISTS gst_exports;
        ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS ck_sub_addon;
        ALTER TABLE subscriptions DROP CONSTRAINT IF EXISTS ck_sub_scheduled;
        ALTER TABLE subscriptions DROP COLUMN IF EXISTS pending_addon_paise;
        ALTER TABLE subscriptions DROP COLUMN IF EXISTS scheduled_change_at;
        ALTER TABLE subscriptions DROP COLUMN IF EXISTS scheduled_price_id;
        ALTER TABLE subscriptions DROP COLUMN IF EXISTS scheduled_plan_id;
        DROP INDEX IF EXISTS ix_inv_issue_date;
        DROP INDEX IF EXISTS ix_inv_contract;
        ALTER TABLE invoices DROP COLUMN IF EXISTS due_on;
        ALTER TABLE invoices DROP COLUMN IF EXISTS description;
        ALTER TABLE invoices DROP COLUMN IF EXISTS contract_id;
        ALTER TABLE order_items DROP CONSTRAINT IF EXISTS ck_oi_catalogue;
        """
    )
