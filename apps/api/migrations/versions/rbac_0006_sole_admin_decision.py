"""rbac: a sole Admin may decide their own approval request (recorded explicitly)

Revision ID: rbac_0006
Revises: rbac_0005
Create Date: 2026-11-12

Owner decision 2026-11-11: with exactly one active Admin, dual-control requests would stay
pending forever, so ``rbac.service.is_sole_admin`` lets that Admin decide their own request.
``ck_apr_distinct`` (rbac_0001) still refused ``decided_by = requested_by`` at the database
(found live: approving raised a CheckViolation / HTTP 500). The constraint now allows it only
when the row is explicitly flagged ``sole_admin_decision`` (set by the decide paths after the
sole-Admin check), so every self-decision stays visible and auditable.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "rbac_0006"
down_revision: str | Sequence[str] | None = "rbac_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE approval_requests ADD COLUMN sole_admin_decision boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE approval_requests DROP CONSTRAINT IF EXISTS ck_apr_distinct")
    op.execute(
        "ALTER TABLE approval_requests ADD CONSTRAINT ck_apr_distinct "
        "CHECK (decided_by IS NULL OR decided_by <> requested_by OR sole_admin_decision)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE approval_requests DROP CONSTRAINT IF EXISTS ck_apr_distinct")
    op.execute("UPDATE approval_requests SET decided_by = NULL WHERE sole_admin_decision")
    op.execute(
        "ALTER TABLE approval_requests ADD CONSTRAINT ck_apr_distinct "
        "CHECK (decided_by IS NULL OR decided_by <> requested_by)"
    )
    op.execute("ALTER TABLE approval_requests DROP COLUMN sole_admin_decision")
