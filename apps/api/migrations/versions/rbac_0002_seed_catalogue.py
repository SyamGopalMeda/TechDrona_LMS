"""rbac: seed roles, permissions and role_permissions from the role matrix catalogue

Revision ID: rbac_0002
Revises: rbac_0001
Create Date: 2026-11-03

Reference data (role-permission-matrix.md v0.4) via ``app.seeds.rbac_seed.sync``; idempotent.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "rbac_0002"
down_revision: str | Sequence[str] | None = "rbac_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from app.seeds.rbac_seed import sync

    sync(op.get_bind())


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions")
    op.execute("DELETE FROM permissions")
    op.execute("DELETE FROM roles WHERE NOT EXISTS (SELECT 1 FROM role_grants g WHERE g.role_id = roles.id)")
