"""engage: single company — no organization-wide activities; permanently closed positions

Revision ID: engage_0002
Revises: engage_0001
Create Date: 2026-11-07

Single-company LMS (docs/single-company/REMOVAL-PLAN.md §1.2 engage, §5 step 7, §6 WS4):

* "Whole organization" activities (``organization_id`` set, ``batch_id`` NULL) are no longer a
  target: an activity is either a batch activity or a platform activity. Existing live
  organization-wide activities are soft-deleted (``deleted_at = now()``) and their live runs are
  closed; past results stay readable to the participants (``/me/engage/runs``).
* ``ck_ea_no_org_wide`` enforces ``organization_id IS NULL OR batch_id IS NOT NULL`` for every
  activity that is not deleted.
* SEC-06: new column ``engage_runs.closed_positions`` — positions that were ever revealed. They
  stay closed for answering even after the host hides the reveal again. Backfilled from
  ``revealed_positions``.

Data steps run as the table owner; FORCE RLS is lifted for the statements and restored in the
same transaction.

Downgrade restores the schema only (drops the CHECK and the column). Soft-deleted activities are
not restored: recover them from ``backups/techdrona-dev-before-college-removal-20261106.dump``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "engage_0002"
down_revision: str | Sequence[str] | None = "engage_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE engage_runs ADD COLUMN IF NOT EXISTS closed_positions smallint[] NOT NULL DEFAULT '{}'"
    )
    for t in ("engage_activities", "engage_runs"):
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        UPDATE engage_runs SET closed_positions = revealed_positions
         WHERE closed_positions = '{}' AND revealed_positions <> '{}';
        UPDATE engage_runs r
           SET status = 'closed', closed_at = coalesce(r.closed_at, now()),
               state_version = r.state_version + 1
          FROM engage_activities a
         WHERE a.id = r.activity_id AND a.organization_id IS NOT NULL AND a.batch_id IS NULL
           AND a.deleted_at IS NULL AND r.status IN ('scheduled', 'open');
        UPDATE engage_activities SET deleted_at = now()
         WHERE organization_id IS NOT NULL AND batch_id IS NULL AND deleted_at IS NULL;
        """
    )
    for t in ("engage_activities", "engage_runs"):
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE engage_activities DROP CONSTRAINT IF EXISTS ck_ea_no_org_wide")
    op.execute(
        "ALTER TABLE engage_activities ADD CONSTRAINT ck_ea_no_org_wide "
        "CHECK (organization_id IS NULL OR batch_id IS NOT NULL OR deleted_at IS NOT NULL)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE engage_activities DROP CONSTRAINT IF EXISTS ck_ea_no_org_wide")
    op.execute("ALTER TABLE engage_runs DROP COLUMN IF EXISTS closed_positions")
