"""support: FR-SUP-001 categories (certificate, college_access, appeal) + SLA queue index

Revision ID: support_0002
Revises: support_0001
Create Date: 2026-11-03

FR-SUP-001 lists certificate, college access and appeal tickets, which the original CHECK
did not allow (audit BE-16/BE-17). ``college_access`` is the only category a college
coordinator sees (API §22 SUP-07). The queue is keyset-paginated on
``(resolution_due_at, id)`` (audit ADM-38), backed by a matching index.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "support_0002"
down_revision: str | Sequence[str] | None = "support_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "'account_access','device_reset','billing','refund','content','assessment','technical',"
    "'grievance','privacy_request','other'"
)
_NEW = _OLD + ",'certificate','college_access','appeal'"


def upgrade() -> None:
    op.execute("ALTER TABLE support_tickets DROP CONSTRAINT IF EXISTS support_tickets_category_check")
    op.execute(
        f"ALTER TABLE support_tickets ADD CONSTRAINT support_tickets_category_check "
        f"CHECK (category IN ({_NEW}))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_st_due_id ON support_tickets "
        "(COALESCE(resolution_due_at, '9999-01-01 00:00:00+00'::timestamptz), id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_st_due_id")
    op.execute("ALTER TABLE support_tickets DROP CONSTRAINT IF EXISTS support_tickets_category_check")
    op.execute(
        f"ALTER TABLE support_tickets ADD CONSTRAINT support_tickets_category_check "
        f"CHECK (category IN ({_OLD})) NOT VALID"
    )
