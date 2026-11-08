"""commerce: products, plans, prices, coupons, orders, payments, webhook events,
subscriptions, refunds, invoices, institution contracts, reconciliation runs

Revision ID: commerce_0001
Revises:
Create Date: 2026-11-03

database-schema §11. FKs to catalog/placement/assessments tables (courses, tests,
company_paths, topics) are deferred: those modules have no migration yet, so
``product_items`` keeps the ids without FK (to be added by a later commerce revision that
``depends_on`` those modules). Additions beyond §11 are listed in
``app/modules/commerce/models.py``.

RLS: products/product_items/plans/prices/coupons TN; orders/order_items/payments/refunds/
invoices U (user's own, org coordinators for org rows, platform); coupon_redemptions and
subscriptions O; institution_contracts T; payment_webhook_events, invoice_sequences and
reconciliation_runs platform-only.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "commerce_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("commerce",)
depends_on: str | Sequence[str] | None = ("core_base", "identity_0001", "orgs_0001", "rbac_0001")

TABLES = (
    "reconciliation_runs",
    "institution_contracts",
    "invoices",
    "invoice_sequences",
    "refunds",
    "payment_webhook_events",
    "payments",
    "coupon_redemptions",
    "order_items",
    "orders",
    "subscriptions",
    "coupons",
    "prices",
    "plans",
    "product_items",
    "products",
)


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE products (
          id               uuid PRIMARY KEY,
          organization_id  uuid        NULL REFERENCES organizations(id),
          sku              citext      NOT NULL UNIQUE CHECK (sku ~ '^[A-Za-z0-9][A-Za-z0-9-]{1,63}$'),
          name             text        NOT NULL CHECK (char_length(name) BETWEEN 2 AND 200),
          product_kind     text        NOT NULL CHECK (product_kind IN ('free_resource','free_course','course','bundle',
                                           'subscription_plan','placement_package','mock_pack','institution_seat','extra_learner_seat')),
          description_md   text        NULL,
          sac_code         text        NOT NULL DEFAULT '9992',
          gst_rate         numeric(5,2) NOT NULL DEFAULT 18.00 CHECK (gst_rate BETWEEN 0 AND 28),
          refund_policy_key text       NOT NULL,
          status           text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','retired')),
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE products IS 'Owner: commerce | RLS: TN | Retention: R-FIN | PII: P0';

        CREATE TABLE product_items (
          id               uuid PRIMARY KEY,
          product_id       uuid        NOT NULL REFERENCES products(id) ON DELETE CASCADE,
          organization_id  uuid        NULL REFERENCES organizations(id),
          item_type        text        NOT NULL CHECK (item_type IN ('course','test','company_path','topic_practice','feature')),
          course_id        uuid        NULL,
          test_id          uuid        NULL,
          company_path_id  uuid        NULL,
          topic_id         uuid        NULL,
          feature_key      text        NULL CHECK (feature_key ~ '^[a-z][a-z0-9_]{1,62}$'),
          quantity         int         NULL CHECK (quantity > 0),
          unit_price_paise bigint      NULL CHECK (unit_price_paise >= 0),
          CONSTRAINT ck_pi_ref CHECK (num_nonnulls(course_id, test_id, company_path_id, topic_id, feature_key) = 1),
          CONSTRAINT ck_pi_type CHECK (
            (item_type = 'course' AND course_id IS NOT NULL) OR (item_type = 'test' AND test_id IS NOT NULL) OR
            (item_type = 'company_path' AND company_path_id IS NOT NULL) OR
            (item_type = 'topic_practice' AND topic_id IS NOT NULL) OR (item_type = 'feature' AND feature_key IS NOT NULL))
        );
        CREATE UNIQUE INDEX ux_pi ON product_items (product_id, item_type,
          (coalesce(course_id, test_id, company_path_id, topic_id)::text), (coalesce(feature_key, '')));
        CREATE INDEX ix_pi_course ON product_items (course_id) WHERE course_id IS NOT NULL;
        CREATE INDEX ix_pi_test ON product_items (test_id) WHERE test_id IS NOT NULL;
        CREATE INDEX ix_pi_path ON product_items (company_path_id) WHERE company_path_id IS NOT NULL;
        CREATE INDEX ix_pi_topic ON product_items (topic_id) WHERE topic_id IS NOT NULL;
        CREATE INDEX ix_pi_feature ON product_items (feature_key) WHERE feature_key IS NOT NULL;
        COMMENT ON TABLE product_items IS 'Owner: commerce | RLS: TN | Retention: R-FIN | PII: P0';

        CREATE TABLE plans (
          id                    uuid PRIMARY KEY,
          product_id            uuid        NOT NULL REFERENCES products(id),
          organization_id       uuid        NULL REFERENCES organizations(id),
          code                  citext      NOT NULL UNIQUE,
          billing_type          text        NOT NULL CHECK (billing_type IN ('one_time','recurring')),
          interval_unit         text        NULL CHECK (interval_unit IN ('month','year')),
          interval_count        smallint    NULL CHECK (interval_count BETWEEN 1 AND 12),
          access_duration_days  int         NULL CHECK (access_duration_days > 0),
          trial_days            smallint    NOT NULL DEFAULT 0,
          gateway_plan_ids      jsonb       NOT NULL DEFAULT '{}',
          status                text        NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','retired')),
          created_at            timestamptz NOT NULL DEFAULT now(),
          updated_at            timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_plan_shape CHECK (
            (billing_type = 'one_time'  AND access_duration_days IS NOT NULL AND interval_unit IS NULL) OR
            (billing_type = 'recurring' AND interval_unit IS NOT NULL AND interval_count IS NOT NULL))
        );
        CREATE INDEX ix_plans_product ON plans (product_id);
        COMMENT ON TABLE plans IS 'Owner: commerce | RLS: TN | Retention: R-FIN | PII: P0';

        CREATE TABLE prices (
          id                 uuid PRIMARY KEY,
          plan_id            uuid        NOT NULL REFERENCES plans(id),
          organization_id    uuid        NULL REFERENCES organizations(id),
          currency           char(3)     NOT NULL DEFAULT 'INR' CHECK (currency = 'INR'),
          amount_paise       bigint      NOT NULL CHECK (amount_paise > 0),
          tax_inclusive      boolean     NOT NULL DEFAULT true,
          is_recurring       boolean     NOT NULL,
          valid_from         timestamptz NOT NULL DEFAULT now(),
          valid_until        timestamptz NULL,
          is_active          boolean     NOT NULL DEFAULT true,
          created_by         uuid        NOT NULL REFERENCES users(id),
          created_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_price_mandate CHECK (NOT is_recurring OR amount_paise <= 1500000),
          CONSTRAINT ck_price_window CHECK (valid_until IS NULL OR valid_until > valid_from)
        );
        CREATE INDEX ix_prices_plan_active ON prices (plan_id) WHERE is_active;
        ALTER TABLE prices ADD CONSTRAINT ex_price_overlap EXCLUDE USING gist
          (plan_id WITH =, tstzrange(valid_from, coalesce(valid_until, 'infinity')) WITH &&) WHERE (is_active);
        COMMENT ON TABLE prices IS 'Owner: commerce | RLS: TN | Retention: R-FIN | PII: P0';

        CREATE TABLE coupons (
          id                    uuid PRIMARY KEY,
          organization_id       uuid        NULL REFERENCES organizations(id),
          code                  citext      NOT NULL UNIQUE CHECK (code ~ '^[A-Za-z0-9_-]{3,32}$'),
          discount_type         text        NOT NULL CHECK (discount_type IN ('percent','flat','free_access')),
          percent_off           numeric(5,2) NULL CHECK (percent_off > 0 AND percent_off <= 100),
          amount_off_paise      bigint      NULL CHECK (amount_off_paise > 0),
          applicable_product_ids uuid[]     NOT NULL DEFAULT '{}',
          min_order_paise       bigint      NULL,
          max_redemptions       int         NULL CHECK (max_redemptions > 0),
          per_user_limit        smallint    NOT NULL DEFAULT 1 CHECK (per_user_limit >= 1),
          redeemed_count        int         NOT NULL DEFAULT 0,
          valid_from            timestamptz NOT NULL,
          valid_until           timestamptz NULL,
          first_time_only       boolean     NOT NULL DEFAULT false,
          status                text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','paused','expired')),
          created_by            uuid        NOT NULL REFERENCES users(id),
          created_at            timestamptz NOT NULL DEFAULT now(),
          updated_at            timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_coupon_shape CHECK (
            (discount_type = 'percent' AND percent_off IS NOT NULL AND amount_off_paise IS NULL) OR
            (discount_type = 'flat' AND amount_off_paise IS NOT NULL AND percent_off IS NULL) OR
            (discount_type = 'free_access')),
          CONSTRAINT ck_coupon_cap CHECK (max_redemptions IS NULL OR redeemed_count <= max_redemptions)
        );
        COMMENT ON TABLE coupons IS 'Owner: commerce | RLS: TN | Retention: R-FIN | PII: P0';

        CREATE TABLE subscriptions (
          id                        uuid PRIMARY KEY,
          user_id                   uuid        NOT NULL REFERENCES users(id),
          plan_id                   uuid        NOT NULL REFERENCES plans(id),
          price_id                  uuid        NOT NULL REFERENCES prices(id),
          gateway                   text        NOT NULL CHECK (gateway IN ('razorpay','cashfree')),
          gateway_subscription_id   text        NOT NULL,
          status                    text        NOT NULL CHECK (status IN ('created','authenticated','active','pending','halted',
                                                   'paused','cancelled','completed','expired')),
          mandate_max_amount_paise  bigint      NOT NULL CHECK (mandate_max_amount_paise <= 1500000),
          current_period_start      timestamptz NULL,
          current_period_end        timestamptz NULL,
          next_charge_at            timestamptz NULL,
          pre_debit_notified_at     timestamptz NULL,
          total_count               int         NULL,
          paid_count                int         NOT NULL DEFAULT 0,
          cancel_at_period_end      boolean     NOT NULL DEFAULT false,
          cancelled_at              timestamptz NULL,
          cancel_reason             text        NULL,
          grace_until               timestamptz NULL,
          created_at                timestamptz NOT NULL DEFAULT now(),
          updated_at                timestamptz NOT NULL DEFAULT now(),
          UNIQUE (gateway, gateway_subscription_id)
        );
        CREATE INDEX ix_sub_user ON subscriptions (user_id);
        CREATE INDEX ix_sub_next_charge ON subscriptions (next_charge_at) WHERE status = 'active';
        COMMENT ON TABLE subscriptions IS 'Owner: commerce | RLS: O | Retention: R-FIN | PII: P1';

        CREATE SEQUENCE commerce_order_number_seq;

        CREATE TABLE orders (
          id                 uuid PRIMARY KEY,
          order_number       text        NOT NULL UNIQUE,
          user_id            uuid        NULL REFERENCES users(id),
          organization_id    uuid        NULL REFERENCES organizations(id),
          status             text        NOT NULL DEFAULT 'created' CHECK (status IN ('created','pending_payment','paid','failed',
                                            'expired','cancelled','refunded','partially_refunded')),
          currency           char(3)     NOT NULL DEFAULT 'INR',
          subtotal_paise     bigint      NOT NULL CHECK (subtotal_paise >= 0),
          discount_paise     bigint      NOT NULL DEFAULT 0 CHECK (discount_paise >= 0),
          tax_paise          bigint      NOT NULL CHECK (tax_paise >= 0),
          total_paise        bigint      NOT NULL CHECK (total_paise >= 0),
          gateway            text        NULL CHECK (gateway IN ('razorpay','cashfree','offline_po')),
          gateway_order_id   text        NULL,
          subscription_id    uuid        NULL REFERENCES subscriptions(id),
          idempotency_key    text        NOT NULL,
          billing_name       text        NULL,
          billing_gstin      text        NULL CHECK (billing_gstin ~ '^[0-9]{2}[A-Z0-9]{13}$'),
          place_of_supply    char(2)     NULL,
          expires_at         timestamptz NOT NULL,
          paid_at            timestamptz NULL,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_order_total CHECK (total_paise = subtotal_paise - discount_paise + tax_paise),
          CONSTRAINT ck_order_owner CHECK (user_id IS NOT NULL OR organization_id IS NOT NULL),
          CONSTRAINT ck_order_paid CHECK (status NOT IN ('paid','refunded','partially_refunded') OR paid_at IS NOT NULL)
        );
        CREATE UNIQUE INDEX ux_orders_gateway ON orders (gateway, gateway_order_id) WHERE gateway_order_id IS NOT NULL;
        CREATE UNIQUE INDEX ux_orders_idem ON orders ((coalesce(user_id, organization_id)), idempotency_key);
        CREATE INDEX ix_orders_pending ON orders (created_at) WHERE status = 'pending_payment';
        CREATE INDEX ix_orders_user ON orders (user_id, created_at DESC);
        COMMENT ON TABLE orders IS 'Owner: commerce | RLS: U | Retention: R-FIN | PII: P2/P3';

        CREATE TABLE order_items (
          id                uuid PRIMARY KEY,
          order_id          uuid        NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
          user_id           uuid        NULL,
          organization_id   uuid        NULL,
          product_id        uuid        NOT NULL REFERENCES products(id),
          plan_id           uuid        NOT NULL REFERENCES plans(id),
          price_id          uuid        NOT NULL REFERENCES prices(id),
          quantity          int         NOT NULL DEFAULT 1 CHECK (quantity >= 1),
          unit_amount_paise bigint      NOT NULL,
          discount_paise    bigint      NOT NULL DEFAULT 0,
          taxable_paise     bigint      NOT NULL,
          cgst_paise        bigint      NOT NULL DEFAULT 0,
          sgst_paise        bigint      NOT NULL DEFAULT 0,
          igst_paise        bigint      NOT NULL DEFAULT 0,
          total_paise       bigint      NOT NULL,
          gst_rate          numeric(5,2) NOT NULL,
          sac_code          text        NOT NULL,
          CONSTRAINT ck_oi_gst CHECK ((igst_paise = 0) OR (cgst_paise = 0 AND sgst_paise = 0))
        );
        CREATE INDEX ix_oi_order ON order_items (order_id);
        COMMENT ON TABLE order_items IS 'Owner: commerce | RLS: U | Retention: R-FIN | PII: P0';

        CREATE TABLE coupon_redemptions (
          id                    uuid PRIMARY KEY,
          coupon_id             uuid        NOT NULL REFERENCES coupons(id),
          user_id               uuid        NOT NULL REFERENCES users(id),
          order_id              uuid        NOT NULL REFERENCES orders(id),
          discount_paise        bigint      NOT NULL CHECK (discount_paise >= 0),
          status                text        NOT NULL DEFAULT 'reserved' CHECK (status IN ('reserved','consumed','released')),
          reserved_until        timestamptz NOT NULL,
          created_at            timestamptz NOT NULL DEFAULT now(),
          updated_at            timestamptz NOT NULL DEFAULT now(),
          UNIQUE (coupon_id, order_id)
        );
        CREATE INDEX ix_cr_coupon_user ON coupon_redemptions (coupon_id, user_id) WHERE status IN ('reserved','consumed');
        COMMENT ON TABLE coupon_redemptions IS 'Owner: commerce | RLS: O | Retention: R-FIN | PII: P1';

        CREATE TABLE payments (
          id                   uuid PRIMARY KEY,
          order_id             uuid        NULL REFERENCES orders(id),
          subscription_id      uuid        NULL REFERENCES subscriptions(id),
          user_id              uuid        NULL REFERENCES users(id),
          organization_id      uuid        NULL REFERENCES organizations(id),
          gateway              text        NOT NULL CHECK (gateway IN ('razorpay','cashfree','offline_po')),
          gateway_payment_id   text        NOT NULL,
          method               text        NULL CHECK (method IN ('upi','card','netbanking','wallet','emandate','bank_transfer','emi')),
          status               text        NOT NULL CHECK (status IN ('created','authorized','captured','failed','refunded','partially_refunded')),
          amount_paise         bigint      NOT NULL CHECK (amount_paise > 0),
          fee_paise            bigint      NULL,
          tax_on_fee_paise     bigint      NULL,
          card_last4           char(4)     NULL,
          card_network         text        NULL,
          card_issuer          text        NULL,
          vpa_masked           text        NULL,
          bank_code            text        NULL,
          error_code           text        NULL,
          error_description    text        NULL,
          authorized_at        timestamptz NULL,
          captured_at          timestamptz NULL,
          created_at           timestamptz NOT NULL DEFAULT now(),
          updated_at           timestamptz NOT NULL DEFAULT now(),
          UNIQUE (gateway, gateway_payment_id),
          CONSTRAINT ck_pay_target CHECK (order_id IS NOT NULL OR subscription_id IS NOT NULL)
        );
        CREATE INDEX ix_pay_order ON payments (order_id);
        CREATE INDEX ix_pay_sub ON payments (subscription_id) WHERE subscription_id IS NOT NULL;
        COMMENT ON TABLE payments IS 'Owner: commerce | RLS: U | Retention: R-FIN | PII: P3 (never PAN/CVV)';

        CREATE TABLE payment_webhook_events (
          id                 uuid PRIMARY KEY,
          gateway            text        NOT NULL CHECK (gateway IN ('razorpay','cashfree')),
          event_id           text        NOT NULL,
          event_type         text        NOT NULL,
          signature_valid    boolean     NOT NULL,
          payload            jsonb       NOT NULL,
          payload_sha256     bytea       NOT NULL CHECK (octet_length(payload_sha256) = 32),
          gateway_created_at timestamptz NULL,
          received_at        timestamptz NOT NULL DEFAULT now(),
          status             text        NOT NULL DEFAULT 'received' CHECK (status IN ('received','processing','processed','ignored','failed')),
          attempts           smallint    NOT NULL DEFAULT 0,
          last_error         text        NULL,
          processed_at       timestamptz NULL,
          order_id           uuid        NULL REFERENCES orders(id),
          payment_id         uuid        NULL REFERENCES payments(id),
          subscription_id    uuid        NULL REFERENCES subscriptions(id),
          is_stale           boolean     NOT NULL DEFAULT false,
          refetched_at       timestamptz NULL,
          refetch_status     text        NULL CHECK (refetch_status IN ('ok','failed','not_required')),
          UNIQUE (gateway, event_id)
        );
        CREATE INDEX ix_pwe_status ON payment_webhook_events (status, received_at) WHERE status IN ('received','processing','failed');
        COMMENT ON TABLE payment_webhook_events IS 'Owner: commerce | RLS: platform only | Retention: R-FIN (payload scrubbed after 180 d) | PII: P3/P4';

        CREATE TABLE refunds (
          id                 uuid PRIMARY KEY,
          payment_id         uuid        NOT NULL REFERENCES payments(id),
          order_id           uuid        NOT NULL REFERENCES orders(id),
          user_id            uuid        NULL REFERENCES users(id),
          organization_id    uuid        NULL REFERENCES organizations(id),
          gateway_refund_id  text        NULL,
          amount_paise       bigint      NOT NULL CHECK (amount_paise > 0),
          reason_code        text        NOT NULL CHECK (reason_code IN ('within_policy_window','content_issue','duplicate_payment',
                                           'service_failure','goodwill','chargeback','other')),
          reason_note        text        NULL,
          consumption_pct    numeric(5,2) NULL,
          status             text        NOT NULL DEFAULT 'requested' CHECK (status IN ('requested','approved','rejected','processing','processed','failed')),
          requested_by       uuid        NOT NULL REFERENCES users(id),
          approved_by        uuid        NULL REFERENCES users(id),
          approval_request_id uuid       NULL REFERENCES approval_requests(id),
          processed_at       timestamptz NULL,
          idempotency_key    text        NOT NULL UNIQUE,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_refund_approver CHECK (approved_by IS NULL OR approved_by <> requested_by OR reason_code = 'within_policy_window'),
          CONSTRAINT ck_refund_goodwill_dual CHECK (reason_code <> 'goodwill' OR status IN ('requested','rejected') OR approval_request_id IS NOT NULL)
        );
        CREATE UNIQUE INDEX ux_refund_gateway ON refunds (gateway_refund_id) WHERE gateway_refund_id IS NOT NULL;
        CREATE INDEX ix_refund_order ON refunds (order_id);
        COMMENT ON TABLE refunds IS 'Owner: commerce | RLS: U | Retention: R-FIN | PII: P1';

        CREATE TABLE invoice_sequences (
          series       text     NOT NULL CHECK (series IN ('TD','TDCN')),
          fiscal_year  text     NOT NULL CHECK (fiscal_year ~ '^[0-9]{4}-[0-9]{2}$'),
          next_value   bigint   NOT NULL DEFAULT 1 CHECK (next_value >= 1),
          PRIMARY KEY (series, fiscal_year)
        );
        COMMENT ON TABLE invoice_sequences IS 'Owner: commerce | RLS: platform only | Retention: R-FIN | PII: P0';

        CREATE TABLE invoices (
          id                uuid PRIMARY KEY,
          invoice_number    text        NOT NULL UNIQUE CHECK (char_length(invoice_number) <= 16),
          invoice_type      text        NOT NULL CHECK (invoice_type IN ('tax_invoice','credit_note')),
          order_id          uuid        NOT NULL REFERENCES orders(id),
          refund_id         uuid        NULL REFERENCES refunds(id),
          original_invoice_id uuid      NULL REFERENCES invoices(id),
          user_id           uuid        NULL REFERENCES users(id),
          organization_id   uuid        NULL REFERENCES organizations(id),
          seller_gstin      text        NOT NULL,
          buyer_name        text        NOT NULL,
          buyer_gstin       text        NULL,
          buyer_address     jsonb       NULL,
          place_of_supply   char(2)     NOT NULL,
          issue_date        date        NOT NULL,
          taxable_paise     bigint      NOT NULL,
          cgst_paise        bigint      NOT NULL DEFAULT 0,
          sgst_paise        bigint      NOT NULL DEFAULT 0,
          igst_paise        bigint      NOT NULL DEFAULT 0,
          total_paise       bigint      NOT NULL,
          irn               text        NULL,
          pdf_s3_key        text        NULL,
          status            text        NOT NULL DEFAULT 'issued' CHECK (status IN ('issued','cancelled')),
          created_at        timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_inv_cn CHECK ((invoice_type = 'credit_note') = (original_invoice_id IS NOT NULL)),
          CONSTRAINT ck_inv_total CHECK (total_paise = taxable_paise + cgst_paise + sgst_paise + igst_paise)
        );
        CREATE INDEX ix_inv_order ON invoices (order_id);
        CREATE UNIQUE INDEX ux_inv_tax_order ON invoices (order_id) WHERE invoice_type = 'tax_invoice' AND status = 'issued';
        CREATE UNIQUE INDEX ux_inv_cn_refund ON invoices (refund_id) WHERE refund_id IS NOT NULL;
        COMMENT ON TABLE invoices IS 'Owner: commerce | RLS: U | Retention: R-FIN (72 months) | PII: P2/P3';

        CREATE TABLE institution_contracts (
          id                uuid PRIMARY KEY,
          organization_id   uuid        NOT NULL REFERENCES organizations(id),
          contract_number   text        NOT NULL UNIQUE,
          product_id        uuid        NOT NULL REFERENCES products(id),
          seat_count        int         NOT NULL CHECK (seat_count > 0),
          starts_on         date        NOT NULL,
          ends_on           date        NOT NULL,
          amount_paise      bigint      NOT NULL CHECK (amount_paise >= 0),
          price_per_seat_paise bigint   NULL CHECK (price_per_seat_paise >= 0),
          billing_schedule  text        NOT NULL DEFAULT 'upfront' CHECK (billing_schedule IN ('upfront','milestones')),
          po_number         text        NULL,
          order_id          uuid        NULL REFERENCES orders(id),
          dpa_version       text        NOT NULL,
          dpa_signed_at     timestamptz NOT NULL,
          data_return_days  smallint    NOT NULL DEFAULT 30,
          grace_days        smallint    NOT NULL DEFAULT 7 CHECK (grace_days BETWEEN 0 AND 60),
          reassignment_allowance int    NOT NULL CHECK (reassignment_allowance >= 0),
          reassignments_used int        NOT NULL DEFAULT 0 CHECK (reassignments_used >= 0),
          seats_burned      int         NOT NULL DEFAULT 0 CHECK (seats_burned >= 0),
          status            text        NOT NULL DEFAULT 'active' CHECK (status IN ('draft','active','expired','terminated')),
          version           int         NOT NULL DEFAULT 1,
          terminated_at     timestamptz NULL,
          created_by        uuid        NOT NULL REFERENCES users(id),
          created_at        timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_ic_dates CHECK (ends_on > starts_on),
          CONSTRAINT ck_ic_reassign CHECK (reassignments_used <= reassignment_allowance),
          CONSTRAINT ck_ic_terminated CHECK ((status = 'terminated') = (terminated_at IS NOT NULL))
        );
        CREATE INDEX ix_ic_org ON institution_contracts (organization_id);
        COMMENT ON TABLE institution_contracts IS 'Owner: commerce | RLS: T | Retention: R-FIN | PII: P2';

        CREATE TABLE reconciliation_runs (
          id           uuid PRIMARY KEY,
          gateway      text        NOT NULL,
          range_from   timestamptz NOT NULL,
          range_to     timestamptz NOT NULL,
          status       text        NOT NULL DEFAULT 'completed' CHECK (status IN ('running','completed','failed')),
          summary      jsonb       NOT NULL DEFAULT '{}',
          mismatches   jsonb       NOT NULL DEFAULT '[]',
          triggered_by text        NOT NULL,
          created_at   timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE reconciliation_runs IS 'Owner: commerce | RLS: platform only | Retention: R-FIN | PII: P0';
        """
    )
    for t in ("products", "product_items", "plans", "prices", "coupons"):
        enable_rls(t, "TN")
    for t in ("orders", "order_items", "payments", "refunds", "invoices"):
        enable_rls(t, "U")
    for t in ("coupon_redemptions", "subscriptions"):
        enable_rls(t, "O")
    enable_rls("institution_contracts", "T")
    for t in ("payment_webhook_events", "invoice_sequences", "reconciliation_runs"):
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY p_platform ON {t} FOR ALL TO td_app, td_readonly "
            "USING (app.is_platform()) WITH CHECK (app.is_platform())"
        )
    op.execute("GRANT USAGE, SELECT ON SEQUENCE commerce_order_number_seq TO td_app")
    for t in (
        "products",
        "plans",
        "coupons",
        "coupon_redemptions",
        "subscriptions",
        "orders",
        "payments",
        "refunds",
        "institution_contracts",
    ):
        add_updated_at_trigger(t)
    # Invoices are immutable after issue (corrections via credit note).
    op.execute("REVOKE DELETE, TRUNCATE ON invoices FROM td_app")
    op.execute("REVOKE DELETE, TRUNCATE ON payment_webhook_events FROM td_app")


def downgrade() -> None:
    for t in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute("DROP SEQUENCE IF EXISTS commerce_order_number_seq")
