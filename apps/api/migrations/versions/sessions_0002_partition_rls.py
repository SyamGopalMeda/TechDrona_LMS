"""sessions: ENABLE + FORCE RLS on the DEFAULT partitions

Revision ID: sessions_0002
Revises: sessions_0001
Create Date: 2026-11-03

App roles reach partitions only through the RLS-protected parents (privileges on the
partitions are revoked); this makes direct partition access fail closed as well and satisfies
the migration RLS lint. pg_partman-created monthly partitions must get the same treatment
(maintenance job, Planned).
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.migration_helpers import enable_rls

revision: str = "sessions_0002"
down_revision: str | Sequence[str] | None = "sessions_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    enable_rls("login_attempts_default", "O")
    enable_rls("session_network_observations_default", "O")


def downgrade() -> None:
    from alembic import op

    for t in ("login_attempts_default", "session_network_observations_default"):
        op.execute(f"DROP POLICY IF EXISTS p_o ON {t}")
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
