"""sessions: drop shared lab devices (college computer labs)

Revision ID: sessions_0003
Revises: sessions_0002
Create Date: 2026-11-06

docs/single-company/REMOVAL-PLAN.md §5 step 4, owner decision D5: the shared/lab-device
feature is deleted. Drops ``devices.shared_organization_id``, ``shared_registered_by``,
``shared_registered_at`` and the ``ck_dev_shared`` CHECK. ``user_devices.counts_toward_cap``
stays (it is now always true for new rows).

Downgrade restores the columns and the CHECK, **not** their values: restore them from
``backups/techdrona-dev-before-college-removal-20261106.dump``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "sessions_0003"
down_revision: str | Sequence[str] | None = "sessions_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE devices DROP CONSTRAINT IF EXISTS ck_dev_shared;
        ALTER TABLE devices DROP COLUMN IF EXISTS shared_registered_at;
        ALTER TABLE devices DROP COLUMN IF EXISTS shared_registered_by;
        ALTER TABLE devices DROP COLUMN IF EXISTS shared_organization_id;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE devices ADD COLUMN shared_organization_id uuid NULL REFERENCES organizations(id);
        ALTER TABLE devices ADD COLUMN shared_registered_by uuid NULL REFERENCES users(id);
        ALTER TABLE devices ADD COLUMN shared_registered_at timestamptz NULL;
        ALTER TABLE devices ADD CONSTRAINT ck_dev_shared
          CHECK ((shared_organization_id IS NULL) = (shared_registered_by IS NULL));
        """
    )
