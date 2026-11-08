"""identity: RLS on verification_tokens and password_reset_tokens (owner or platform)

Revision ID: identity_0003
Revises: identity_0002
Create Date: 2026-11-03

database-schema §3 lists these as RLS NONE (accessed by hash in pre-auth flows). They carry
``user_id``, so the migration RLS lint (tests/core/test_rls.py) requires ENABLE + FORCE; the
pre-auth routes already run under a named system context, so family O is a strict superset.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.core.migration_helpers import enable_rls

revision: str = "identity_0003"
down_revision: str | Sequence[str] | None = "identity_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    enable_rls("verification_tokens", "O")
    enable_rls("password_reset_tokens", "O")


def downgrade() -> None:
    from alembic import op

    for t in ("verification_tokens", "password_reset_tokens"):
        op.execute(f"DROP POLICY IF EXISTS p_o ON {t}")
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
