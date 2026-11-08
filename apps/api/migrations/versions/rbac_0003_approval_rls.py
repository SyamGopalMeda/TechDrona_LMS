"""rbac: RLS on approval_requests (requester, own org, or platform)

Revision ID: rbac_0003
Revises: rbac_0002
Create Date: 2026-11-03

database-schema §13 lists approval_requests as RLS NONE (platform queue filtered by the API).
It carries organization_id, so the migration RLS lint requires ENABLE + FORCE. Approvers are
platform principals (``app.is_platform()``); requesters always see their own requests.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "rbac_0003"
down_revision: str | Sequence[str] | None = "rbac_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE approval_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE approval_requests FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY p_apr ON approval_requests FOR ALL TO td_app, td_readonly "
        "USING (requested_by = app.user_id() OR app.is_platform() "
        "       OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids()))) "
        "WITH CHECK (requested_by = app.user_id() OR app.is_platform())"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS p_apr ON approval_requests")
    op.execute("ALTER TABLE approval_requests NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE approval_requests DISABLE ROW LEVEL SECURITY")
