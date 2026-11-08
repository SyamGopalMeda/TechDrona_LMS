"""security: enforcement rows are read-only for their owner (DB-05)

Revision ID: security_0002
Revises: security_0001
Create Date: 2026-11-03

security_0001 applied RLS family O (``user_id = app.user_id() OR app.is_platform()``) ``FOR ALL``
on the enforcement tables, so a learner context could UPDATE or DELETE its own restriction,
case, unblock request, engine state or notice rows. Split the policy: the owner may SELECT;
INSERT / UPDATE / DELETE need platform scope (staff with a platform grant, or a named system
job — every learner-facing write path already runs under ``system_context``).
``account_restrictions`` and ``security_cases`` are never deleted (R-RISK retention): revoke DELETE.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import APP_ROLES

revision: str = "security_0002"
down_revision: str | Sequence[str] | None = "security_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "account_restrictions",
    "security_cases",
    "unblock_requests",
    "security_user_state",
    "security_notices",
)
NO_DELETE = ("account_restrictions", "security_cases")


def upgrade() -> None:
    for t in TABLES:
        op.execute(f"DROP POLICY IF EXISTS p_o ON {t}")
        op.execute(
            f"CREATE POLICY p_o_read ON {t} FOR SELECT TO {APP_ROLES} "
            "USING (user_id = app.user_id() OR app.is_platform())"
        )
        op.execute(
            f"CREATE POLICY p_o_write ON {t} FOR ALL TO {APP_ROLES} "
            "USING (app.is_platform()) WITH CHECK (app.is_platform())"
        )
    for t in NO_DELETE:
        op.execute(f"REVOKE DELETE, TRUNCATE ON {t} FROM td_app")


def downgrade() -> None:
    for t in NO_DELETE:
        op.execute(f"GRANT DELETE ON {t} TO td_app")
    for t in TABLES:
        op.execute(f"DROP POLICY IF EXISTS p_o_write ON {t}")
        op.execute(f"DROP POLICY IF EXISTS p_o_read ON {t}")
        op.execute(
            f"CREATE POLICY p_o ON {t} FOR ALL TO {APP_ROLES} "
            "USING (user_id = app.user_id() OR app.is_platform()) "
            "WITH CHECK (user_id = app.user_id() OR app.is_platform())"
        )
