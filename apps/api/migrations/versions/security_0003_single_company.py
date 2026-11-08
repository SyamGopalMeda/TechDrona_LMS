"""security: single company — drop org trusted networks, rename the lab unblock reason

Revision ID: security_0003
Revises: security_0002
Create Date: 2026-11-07

docs/single-company/REMOVAL-PLAN.md §1.2 (security), §1.3, §5 step 8 and owner decision D5:

* ``org_trusted_networks`` is dropped. The trusted-network routes, the org security summary and
  the trusted-network discounts in the risk engine were removed from the application.
* The unblock "what happened" option ``college_lab_or_shared_computer`` is renamed
  ``shared_computer``; existing ``unblock_requests.what_happened`` arrays are remapped. The
  column has no CHECK (the API validates the options), so nothing needs tightening.

Data steps run as the table owner; FORCE RLS is lifted on ``unblock_requests`` for the
statement and restored in the same transaction.

Downgrade restores the schema of ``org_trusted_networks`` (columns, CHECKs, indexes, RLS) and
maps the reason back, but **not** the network rows: restore them from
``backups/techdrona-dev-before-college-removal-20261106.dump``.

Note: no ``depends_on`` (in particular never ``orgs_0002``; see docs/single-company/ws1.md §2).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "security_0003"
down_revision: str | Sequence[str] | None = "security_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _remap(old: str, new: str) -> None:
    conn = op.get_bind()
    forced = bool(
        conn.execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'unblock_requests' "
                "AND relnamespace = 'public'::regnamespace"
            )
        ).scalar()
    )
    if forced:
        op.execute("ALTER TABLE unblock_requests NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"UPDATE unblock_requests SET what_happened = array_replace(what_happened, '{old}', '{new}') "
        f"WHERE '{old}' = ANY (what_happened)"
    )
    if forced:
        op.execute("ALTER TABLE unblock_requests FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS org_trusted_networks")
    _remap("college_lab_or_shared_computer", "shared_computer")


def downgrade() -> None:
    _remap("shared_computer", "college_lab_or_shared_computer")
    op.execute(
        """
        CREATE TABLE org_trusted_networks (
          id               uuid PRIMARY KEY,
          organization_id  uuid        NOT NULL REFERENCES organizations(id),
          cidr             cidr        NULL CHECK (cidr IS NULL OR (family(cidr) = 4 AND masklen(cidr) >= 16) OR family(cidr) = 6),
          asn              integer     NULL,
          status           text        NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','verified','rejected','expired')),
          proposed_by      uuid        NOT NULL REFERENCES users(id),
          verified_by      uuid        NULL REFERENCES users(id),
          verified_at      timestamptz NULL,
          evidence_ref     text        NULL,
          decision_note    text        NULL,
          expires_at       timestamptz NULL,
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_otn_target CHECK (num_nonnulls(cidr, asn) = 1),
          CONSTRAINT ck_otn_verify CHECK (status <> 'verified' OR (verified_by IS NOT NULL AND verified_by <> proposed_by))
        );
        CREATE INDEX ix_otn_org ON org_trusted_networks (organization_id) WHERE status = 'verified';
        CREATE INDEX gist_otn_cidr ON org_trusted_networks USING gist (cidr inet_ops) WHERE status = 'verified';
        COMMENT ON TABLE org_trusted_networks IS 'Owner: security | RLS: T | Retention: R-ORG | PII: P0/P1';
        """
    )
    add_updated_at_trigger("org_trusted_networks")
    enable_rls("org_trusted_networks", "T")
