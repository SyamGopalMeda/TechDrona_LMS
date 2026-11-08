"""entitlements: entitlements, entitlement_events (append-only), seat_waitlist

Revision ID: entitlements_0001
Revises:
Create Date: 2026-11-03

database-schema §11 (PRD CCP-05). ``course_id`` keeps the id without FK until the catalog
module ships ``courses``. RLS: U on all three tables (own rows; org staff for org rows;
platform). ``entitlement_events`` is append-only for td_app.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls, revoke_app_writes

revision: str = "entitlements_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("entitlements",)
depends_on: str | Sequence[str] | None = ("core_base", "identity_0001", "orgs_0001", "commerce_0001")


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE entitlements (
          id                        uuid PRIMARY KEY,
          user_id                   uuid        NOT NULL REFERENCES users(id),
          organization_id           uuid        NULL REFERENCES organizations(id),
          product_id                uuid        NULL REFERENCES products(id),
          course_id                 uuid        NULL,
          feature_key               text        NULL,
          source_type               text        NOT NULL CHECK (source_type IN ('free_enrolment','purchase','placement_package',
                                                   'subscription','coupon_grant','institution_contract','admin_grant','trial')),
          order_item_id             uuid        NULL REFERENCES order_items(id),
          subscription_id           uuid        NULL REFERENCES subscriptions(id),
          institution_contract_id   uuid        NULL REFERENCES institution_contracts(id),
          coupon_redemption_id      uuid        NULL REFERENCES coupon_redemptions(id),
          granted_by                uuid        NULL REFERENCES users(id),
          grant_reason              text        NULL,
          status                    text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','grace','suspended','revoked','expired')),
          starts_at                 timestamptz NOT NULL DEFAULT now(),
          ends_at                   timestamptz NULL,
          grace_ends_at             timestamptz NULL,
          mentor_sessions_remaining smallint    NULL CHECK (mentor_sessions_remaining >= 0),
          mocks_remaining           smallint    NULL CHECK (mocks_remaining >= 0),
          resume_reviews_remaining  smallint    NULL CHECK (resume_reviews_remaining >= 0),
          revoked_at                timestamptz NULL,
          revoked_by                uuid        NULL REFERENCES users(id),
          revoke_reason             text        NULL CHECK (revoke_reason IN ('refund','chargeback','contract_end','contract_terminated',
                                                   'seat_unassigned','admin','fraud','superseded')),
          created_at                timestamptz NOT NULL DEFAULT now(),
          updated_at                timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_ent_target CHECK (num_nonnulls(product_id, course_id, feature_key) >= 1),
          CONSTRAINT ck_ent_source CHECK (
            (source_type IN ('purchase','placement_package') AND order_item_id IS NOT NULL
                                                  AND num_nonnulls(subscription_id, institution_contract_id, coupon_redemption_id) = 0) OR
            (source_type = 'subscription'         AND subscription_id IS NOT NULL
                                                  AND num_nonnulls(order_item_id, institution_contract_id, coupon_redemption_id) = 0) OR
            (source_type = 'institution_contract' AND institution_contract_id IS NOT NULL AND organization_id IS NOT NULL
                                                  AND num_nonnulls(order_item_id, subscription_id, coupon_redemption_id) = 0) OR
            (source_type = 'coupon_grant'         AND coupon_redemption_id IS NOT NULL
                                                  AND num_nonnulls(order_item_id, subscription_id, institution_contract_id) = 0) OR
            (source_type = 'admin_grant'          AND granted_by IS NOT NULL
                                                  AND num_nonnulls(order_item_id, subscription_id, institution_contract_id, coupon_redemption_id) = 0) OR
            (source_type IN ('free_enrolment','trial')
                                                  AND num_nonnulls(order_item_id, subscription_id, institution_contract_id, coupon_redemption_id) = 0)),
          CONSTRAINT ck_ent_window CHECK (ends_at IS NULL OR ends_at > starts_at),
          CONSTRAINT ck_ent_open_end CHECK (ends_at IS NOT NULL OR source_type IN ('free_enrolment','admin_grant')),
          CONSTRAINT ck_ent_grace CHECK (status <> 'grace' OR grace_ends_at IS NOT NULL),
          CONSTRAINT ck_ent_revoked CHECK ((status = 'revoked') = (revoked_at IS NOT NULL))
        );
        CREATE UNIQUE INDEX ux_ent_order_item ON entitlements (order_item_id) WHERE order_item_id IS NOT NULL;
        CREATE UNIQUE INDEX ux_ent_sub ON entitlements (subscription_id) WHERE subscription_id IS NOT NULL;
        CREATE UNIQUE INDEX ux_ent_seat ON entitlements (institution_contract_id, user_id)
          WHERE institution_contract_id IS NOT NULL AND status IN ('active','grace','suspended');
        CREATE UNIQUE INDEX ux_ent_coupon ON entitlements (coupon_redemption_id) WHERE coupon_redemption_id IS NOT NULL;
        CREATE INDEX ix_ent_user_active ON entitlements (user_id, ends_at) WHERE status IN ('active','grace');
        CREATE INDEX ix_ent_contract_active ON entitlements (institution_contract_id) WHERE status IN ('active','grace');
        CREATE INDEX ix_ent_expiry ON entitlements (ends_at) WHERE status = 'active' AND ends_at IS NOT NULL;
        CREATE INDEX ix_ent_grace ON entitlements (grace_ends_at) WHERE status = 'grace';
        COMMENT ON TABLE entitlements IS 'Owner: entitlements | RLS: U | Retention: R-FIN (8 years) | PII: P1';

        CREATE TABLE entitlement_events (
          id                uuid PRIMARY KEY,
          entitlement_id    uuid        NOT NULL REFERENCES entitlements(id),
          user_id           uuid        NOT NULL REFERENCES users(id),
          organization_id   uuid        NULL REFERENCES organizations(id),
          event_type        text        NOT NULL CHECK (event_type IN ('granted','extended','entered_grace','restored','suspended',
                                            'expired','revoked','quota_consumed','quota_credited','seat_reassigned','fp_extension')),
          from_status       text        NULL,
          to_status         text        NULL,
          delta             jsonb       NOT NULL DEFAULT '{}',
          reason            text        NULL,
          actor_type        text        NOT NULL CHECK (actor_type IN ('user','system','gateway')),
          actor_user_id     uuid        NULL REFERENCES users(id),
          source_ref        uuid        NULL,
          occurred_at       timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_ee_ent ON entitlement_events (entitlement_id, occurred_at);
        CREATE INDEX ix_ee_user ON entitlement_events (user_id, occurred_at DESC);
        COMMENT ON TABLE entitlement_events IS 'Owner: entitlements | RLS: U | Retention: R-FIN | PII: P1 | append-only';

        CREATE TABLE seat_waitlist (
          id                       uuid PRIMARY KEY,
          institution_contract_id  uuid        NOT NULL REFERENCES institution_contracts(id),
          organization_id          uuid        NOT NULL REFERENCES organizations(id),
          user_id                  uuid        NOT NULL REFERENCES users(id),
          status                   text        NOT NULL DEFAULT 'waiting' CHECK (status IN ('waiting','assigned','cancelled')),
          added_by                 uuid        NULL REFERENCES users(id),
          entitlement_id           uuid        NULL REFERENCES entitlements(id),
          created_at               timestamptz NOT NULL DEFAULT now(),
          updated_at               timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ux_sw_waiting ON seat_waitlist (institution_contract_id, user_id) WHERE status = 'waiting';
        COMMENT ON TABLE seat_waitlist IS 'Owner: entitlements | RLS: U | Retention: R-ORG | PII: P1';
        """
    )
    for t in ("entitlements", "entitlement_events", "seat_waitlist"):
        enable_rls(t, "U")
    add_updated_at_trigger("entitlements")
    add_updated_at_trigger("seat_waitlist")
    revoke_app_writes("entitlement_events")


def downgrade() -> None:
    for t in ("seat_waitlist", "entitlement_events", "entitlements"):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
