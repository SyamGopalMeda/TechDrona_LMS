"""entitlements: drop the B2B institution seats (single company)

Revision ID: entitlements_0003
Revises: entitlements_0002
Create Date: 2026-11-07

Single-company LMS (docs/single-company/REMOVAL-PLAN.md §1.2, §5 step 5; WS2):

* every ``institution_contract`` entitlement that is not already revoked is revoked now
  (``revoke_reason='contract_terminated'``; history event ``revoked`` with reason
  ``college_removal``). The rows are kept: entitlements are R-FIN records;
* ``seat_waitlist`` is dropped;
* ``entitlements.institution_contract_id`` is dropped (with ``ux_ent_seat`` and
  ``ix_ent_contract_active``); ``ck_ent_source`` is rebuilt without it. The source type
  ``institution_contract`` stays valid only for the historic, revoked rows
  (``ck_ent_no_institution``), so no live institution entitlement can be created again;
* RLS: ``entitlements`` and ``entitlement_events`` move from family ``U`` (own rows + rows of
  the caller's organizations) to family ``O`` (own rows only). With one company organization
  the org branch would let every company member read every other member's institution
  entitlements once ``orgs_0003`` re-homes them. FORCE RLS stays on.

Must run before ``commerce_0004`` (which drops ``institution_contracts``) and before
``orgs_0003_rehome_and_lock``.

Data migrations run as the table owner; FORCE RLS applies to the owner, so it is lifted for the
statements and restored in the same transaction.

Downgrade restores the schema (column, indexes, CHECKs, ``seat_waitlist`` with RLS ``U``, the
``U`` policies) but **not** the data: the revoked entitlements stay revoked and the waitlist is
empty. Restore the data from ``backups/techdrona-dev-before-college-removal-20261106.dump``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.core.migration_helpers import add_updated_at_trigger, enable_rls, rls_sql

revision: str = "entitlements_0003"
down_revision: str | Sequence[str] | None = "entitlements_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FORCED = ("entitlements", "entitlement_events", "seat_waitlist")

_OLD_SOURCE = """
    (source_type IN ('purchase','placement_package') AND order_item_id IS NOT NULL
        AND num_nonnulls(subscription_id, institution_contract_id, coupon_redemption_id) = 0) OR
    (source_type = 'subscription' AND subscription_id IS NOT NULL
        AND num_nonnulls(order_item_id, institution_contract_id, coupon_redemption_id) = 0) OR
    (source_type = 'institution_contract' AND institution_contract_id IS NOT NULL AND organization_id IS NOT NULL
        AND num_nonnulls(order_item_id, subscription_id, coupon_redemption_id) = 0) OR
    (source_type = 'coupon_grant' AND coupon_redemption_id IS NOT NULL
        AND num_nonnulls(order_item_id, subscription_id, institution_contract_id) = 0) OR
    (source_type = 'admin_grant' AND granted_by IS NOT NULL
        AND num_nonnulls(order_item_id, subscription_id, institution_contract_id, coupon_redemption_id) = 0) OR
    (source_type IN ('free_enrolment','trial')
        AND num_nonnulls(order_item_id, subscription_id, institution_contract_id, coupon_redemption_id) = 0)
"""

_NEW_SOURCE = """
    (source_type IN ('purchase','placement_package') AND order_item_id IS NOT NULL
        AND num_nonnulls(subscription_id, coupon_redemption_id) = 0) OR
    (source_type = 'subscription' AND subscription_id IS NOT NULL
        AND num_nonnulls(order_item_id, coupon_redemption_id) = 0) OR
    (source_type = 'institution_contract' AND status = 'revoked'
        AND num_nonnulls(order_item_id, subscription_id, coupon_redemption_id) = 0) OR
    (source_type = 'coupon_grant' AND coupon_redemption_id IS NOT NULL
        AND num_nonnulls(order_item_id, subscription_id) = 0) OR
    (source_type = 'admin_grant' AND granted_by IS NOT NULL
        AND num_nonnulls(order_item_id, subscription_id, coupon_redemption_id) = 0) OR
    (source_type IN ('free_enrolment','trial')
        AND num_nonnulls(order_item_id, subscription_id, coupon_redemption_id) = 0)
"""


def _lift_force(conn: Connection, tables: Sequence[str]) -> list[str]:
    """Lift FORCE RLS (owner-run data migration) on the tables that have it; returns them."""
    forced = list(
        conn.execute(
            text(
                "SELECT relname FROM pg_class WHERE relname = ANY (:t) AND relkind IN ('r','p') "
                "AND relforcerowsecurity AND relnamespace = 'public'::regnamespace"
            ),
            {"t": list(tables)},
        ).scalars()
    )
    for t in forced:
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
    return forced


def _restore_force(tables: Sequence[str]) -> None:
    for t in tables:
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")


def _swap_policy(table: str, old: str, family: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS {old} ON {table}")
    op.execute(f"DROP POLICY IF EXISTS p_{family.lower()} ON {table}")
    # rls_sql = ENABLE, FORCE, CREATE POLICY: re-asserting ENABLE/FORCE is harmless.
    for stmt in rls_sql(table, family):
        op.execute(stmt)


def upgrade() -> None:
    conn = op.get_bind()
    forced = _lift_force(conn, FORCED)

    # 1. End every institution entitlement that is still live (or could be revived by a
    #    false-positive credit), with one history row each. Idempotent: revoked rows are skipped.
    op.execute(
        """
        WITH ended AS (
          UPDATE entitlements e
             SET status = 'revoked', revoked_at = now(), revoke_reason = 'contract_terminated',
                 updated_at = now()
            FROM (SELECT id, status AS old_status FROM entitlements
                   WHERE source_type = 'institution_contract' AND status <> 'revoked'
                   FOR UPDATE) o
           WHERE e.id = o.id
          RETURNING e.id, e.user_id, e.organization_id, o.old_status
        )
        INSERT INTO entitlement_events (id, entitlement_id, user_id, organization_id, event_type,
                                        from_status, to_status, delta, reason, actor_type, occurred_at)
        SELECT gen_random_uuid(), id, user_id, organization_id, 'revoked', old_status, 'revoked',
               jsonb_build_object('migration', 'entitlements_0003'), 'college_removal', 'system', now()
          FROM ended
        """
    )

    # 2. The seat waitlist goes (no legal retention; the dump keeps the rows).
    op.execute("DROP TABLE IF EXISTS seat_waitlist")

    # 3. Drop the contract reference; institution rows stay as revoked history only.
    op.execute(
        f"""
        DROP INDEX IF EXISTS ux_ent_seat;
        DROP INDEX IF EXISTS ix_ent_contract_active;
        ALTER TABLE entitlements DROP CONSTRAINT IF EXISTS ck_ent_source;
        ALTER TABLE entitlements DROP CONSTRAINT IF EXISTS ck_ent_no_institution;
        ALTER TABLE entitlements DROP COLUMN IF EXISTS institution_contract_id;
        ALTER TABLE entitlements ADD CONSTRAINT ck_ent_source CHECK ({_NEW_SOURCE});
        ALTER TABLE entitlements ADD CONSTRAINT ck_ent_no_institution
          CHECK (source_type <> 'institution_contract' OR status = 'revoked');
        """
    )

    # 4. Own rows only (no org-membership visibility on access records).
    for t in ("entitlements", "entitlement_events"):
        _swap_policy(t, "p_u", "O")

    _restore_force([t for t in forced if t != "seat_waitlist"])


def downgrade() -> None:
    """Schema only; restore the data from the backup dump (see the module docstring)."""
    for t in ("entitlements", "entitlement_events"):
        _swap_policy(t, "p_o", "U")
    op.execute(
        f"""
        ALTER TABLE entitlements DROP CONSTRAINT IF EXISTS ck_ent_no_institution;
        ALTER TABLE entitlements DROP CONSTRAINT IF EXISTS ck_ent_source;
        ALTER TABLE entitlements ADD COLUMN IF NOT EXISTS institution_contract_id uuid NULL
          REFERENCES institution_contracts(id);
        ALTER TABLE entitlements ADD CONSTRAINT ck_ent_source CHECK ({_OLD_SOURCE}) NOT VALID;
        CREATE UNIQUE INDEX IF NOT EXISTS ux_ent_seat ON entitlements (institution_contract_id, user_id)
          WHERE institution_contract_id IS NOT NULL AND status IN ('active','grace','suspended');
        CREATE INDEX IF NOT EXISTS ix_ent_contract_active ON entitlements (institution_contract_id)
          WHERE status IN ('active','grace');

        CREATE TABLE IF NOT EXISTS seat_waitlist (
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
        CREATE UNIQUE INDEX IF NOT EXISTS ux_sw_waiting ON seat_waitlist (institution_contract_id, user_id)
          WHERE status = 'waiting';
        COMMENT ON TABLE seat_waitlist IS 'Owner: entitlements | RLS: U | Retention: R-ORG | PII: P1';
        """
    )
    enable_rls("seat_waitlist", "U")
    add_updated_at_trigger("seat_waitlist")
