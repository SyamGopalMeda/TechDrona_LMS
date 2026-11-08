"""orgs: re-home every organization-owned row to the company org; lock the singleton

Revision ID: orgs_0003
Revises: orgs_0002
Create Date: 2026-11-06

docs/single-company/REMOVAL-PLAN.md §5 step 9. Runs LAST (``depends_on`` every single-company
revision of the other workstreams).

1. Unique conflicts are resolved first: ``org_memberships (organization_id, user_id)`` keeps
   one row per user (an active row first, then the most recently updated); ``batches
   (organization_id, code)`` of other organizations get the suffix ``-<old slug>``.
2. Every table with an ``organization_id`` column (from ``information_schema``; partitions are
   reached through their parent) gets ``organization_id = COMPANY_ORG_ID`` where it is
   non-NULL and not already the company. NULL stays NULL (platform content).
   Excluded, because they are evidence and must not be rewritten: ``audit_log`` (append-only,
   hash-chained), ``consents`` (legal consent evidence), ``outbox_events`` (event history).
   User triggers are disabled per table during the update (published question versions are
   otherwise immutable) and FORCE RLS is lifted for the owner and restored in the same
   transaction.
3. Other organizations are deleted; one that is still referenced (by an excluded table) is
   soft-deleted instead (``status='archived'``, ``deleted_at=now()``).
4. The college columns of ``organizations`` are dropped (gstin, billing_*, state_code,
   contact_*, data_role, settings).
5. Lock: only the company org may be live (``ck_org_single_company``), and at most one live
   row exists (``ux_organizations_singleton``).

Downgrade restores the dropped columns and removes the lock, **not** the data: restore
original owners from ``backups/techdrona-dev-before-college-removal-20261106.dump``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

from app.core.company import COMPANY_ORG_ID

revision: str = "orgs_0003"
down_revision: str | Sequence[str] | None = "orgs_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = (
    # Every OTHER branch head (the 17 "(head)" revisions of ``alembic heads`` before this one),
    # so the re-homing sees every table with ``organization_id`` and runs after each
    # workstream's data steps. Alembic 1.20 pitfall: list only revisions that are real rows of
    # ``alembic_version`` at upgrade time. An "effective head" that another revision already
    # depends on (entitlements_0003, media_0001, notifications_0001, audit_0001,
    # core_base_0002) is NOT stored there; listing it makes the merge step fail with
    # ``KeyError`` in update_to_step (reproduced on the restored dev dump with media_0001).
    # They still run first: each is an ancestor of a head listed here. Likewise no OTHER
    # revision may list orgs_0002 in depends_on (ws1.md §2).
    # WS1 (steps 2-4)
    "rbac_0004",
    "identity_0005",
    "sessions_0003",
    # WS2 (step 5): commerce_0004 depends on entitlements_0003; its organization snapshot
    # reads the college columns, so it must run before step 4 below drops them
    "commerce_0004",
    # WS3 (step 6)
    "admin_0004",
    "ai_0002",
    # WS4 (step 7); learning_0004 / notifications_0002 were not needed
    "catalog_0003",
    "paths_0002",
    "engage_0002",
    "learning_0003",
    "mentoring_0001",
    # WS5 (step 8); placement/assessments/coding needed no new revision
    "analytics_0003",
    "support_0004",
    "security_0003",
    "placement_0005",
    "assessments_0004",
    "coding_0003",
)

EXCLUDED = ("organizations", "audit_log", "consents", "outbox_events")
COLLEGE_COLUMNS = (
    "data_role",
    "gstin",
    "billing_name",
    "billing_address",
    "state_code",
    "contact_name",
    "contact_email",
    "contact_phone_e164",
    "settings",
)
C = f"'{COMPANY_ORG_ID}'::uuid"


def _tables(conn) -> list[tuple[str, bool]]:  # type: ignore[no-untyped-def]
    """(table, has FORCE RLS) for every non-partition table with organization_id."""
    rows = conn.execute(
        text(
            "SELECT c.relname, c.relforcerowsecurity FROM pg_class c "
            "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = 'organization_id' AND NOT a.attisdropped "
            "WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r','p') "
            "AND NOT c.relispartition AND NOT (c.relname = ANY (:ex)) ORDER BY c.relname"
        ),
        {"ex": list(EXCLUDED)},
    ).all()
    return [(r[0], bool(r[1])) for r in rows]


def upgrade() -> None:
    conn = op.get_bind()
    tables = _tables(conn)
    forced = [t for t, f in tables if f] + ["organizations"]
    for t in forced:
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")

    # 0. retired policy key (D5: trusted networks are gone; the registry no longer knows it)
    ps_forced = bool(
        conn.execute(
            text("SELECT relforcerowsecurity FROM pg_class WHERE oid = 'policy_settings'::regclass")
        ).scalar()
    )
    if ps_forced:
        op.execute("ALTER TABLE policy_settings NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM policy_settings WHERE setting_key = 'risk.trusted_network_multiplier'")
    if ps_forced:
        op.execute("ALTER TABLE policy_settings FORCE ROW LEVEL SECURITY")

    # 1. unique conflicts
    op.execute(
        f"""
        DELETE FROM org_memberships m USING (
          SELECT id, row_number() OVER (PARTITION BY user_id
                   ORDER BY (status = 'active') DESC, (organization_id = {C}) DESC, updated_at DESC) AS rn
            FROM org_memberships) r
         WHERE m.id = r.id AND r.rn > 1;
        UPDATE batches b
           SET code = left(b.code, 40) || '-' || left(o.slug::text, 23)
          FROM organizations o
         WHERE o.id = b.organization_id AND b.organization_id <> {C}
           AND EXISTS (SELECT 1 FROM batches x WHERE x.code = b.code AND x.id <> b.id);
        """
    )

    # 2. re-home
    for t, _ in tables:
        op.execute(f"ALTER TABLE {t} DISABLE TRIGGER USER")
        op.execute(
            f"UPDATE {t} SET organization_id = {C} "
            f"WHERE organization_id IS NOT NULL AND organization_id <> {C}"
        )
        op.execute(f"ALTER TABLE {t} ENABLE TRIGGER USER")

    # 3. other organizations
    op.execute(
        f"""
        DO $$
        DECLARE r record;
        BEGIN
          FOR r IN SELECT id FROM organizations WHERE id <> {C} LOOP
            BEGIN
              DELETE FROM organizations WHERE id = r.id;
            EXCEPTION WHEN foreign_key_violation THEN
              UPDATE organizations SET status = 'archived', deleted_at = coalesce(deleted_at, now())
               WHERE id = r.id;
            END;
          END LOOP;
        END $$;
        UPDATE organizations SET status = 'active', deleted_at = NULL, org_type = 'internal' WHERE id = {C};
        """
    )

    # 4. college columns
    for col in COLLEGE_COLUMNS:
        op.execute(f"ALTER TABLE organizations DROP COLUMN IF EXISTS {col}")

    # 5. lock
    op.execute(
        "ALTER TABLE organizations ADD CONSTRAINT ck_org_single_company "
        f"CHECK (deleted_at IS NOT NULL OR (id = {C} AND org_type = 'internal'))"
    )
    op.execute(
        "CREATE UNIQUE INDEX ux_organizations_singleton ON organizations ((true)) WHERE deleted_at IS NULL"
    )
    op.execute(
        "COMMENT ON TABLE organizations IS 'Owner: orgs | RLS: custom (id in org_ids or platform) | "
        "single company org (COMPANY_ORG_ID) | Retention: R-ORG | PII: P0'"
    )

    for t in forced:
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_organizations_singleton")
    op.execute("ALTER TABLE organizations DROP CONSTRAINT IF EXISTS ck_org_single_company")
    op.execute(
        r"""
        ALTER TABLE organizations
          ADD COLUMN data_role text NOT NULL DEFAULT 'tech_drona_processor'
              CHECK (data_role IN ('tech_drona_processor','independent_fiduciaries')),
          ADD COLUMN gstin text NULL CHECK (gstin ~ '^[0-9]{2}[A-Z0-9]{13}$'),
          ADD COLUMN billing_name text NULL,
          ADD COLUMN billing_address jsonb NULL,
          ADD COLUMN state_code char(2) NULL,
          ADD COLUMN contact_name text NULL,
          ADD COLUMN contact_email citext NULL,
          ADD COLUMN contact_phone_e164 text NULL,
          ADD COLUMN settings jsonb NOT NULL DEFAULT '{}';
        """
    )
