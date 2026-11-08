"""identity: org-visibility RLS on users/user_profiles; consents.organization_id FK

Revision ID: identity_0002
Revises: identity_0001
Create Date: 2026-11-03

database-schema §3 users policy: ``id = app.user_id() OR app.is_platform() OR
app.user_visible_in_orgs(id)`` (read only — writes stay own-row/platform).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "identity_0002"
down_revision: str | Sequence[str] | None = "identity_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = ("orgs_0001",)


def upgrade() -> None:
    op.execute("DROP POLICY IF EXISTS p_users ON users")
    op.execute(
        "CREATE POLICY p_users ON users FOR ALL TO td_app, td_readonly "
        "USING (id = app.user_id() OR app.is_platform() OR app.user_visible_in_orgs(id)) "
        "WITH CHECK (id = app.user_id() OR app.is_platform())"
    )
    op.execute("DROP POLICY IF EXISTS p_o ON user_profiles")
    op.execute(
        "CREATE POLICY p_o ON user_profiles FOR ALL TO td_app, td_readonly "
        "USING (user_id = app.user_id() OR app.is_platform() OR app.user_visible_in_orgs(user_id)) "
        "WITH CHECK (user_id = app.user_id() OR app.is_platform())"
    )
    op.execute(
        "ALTER TABLE consents ADD CONSTRAINT fk_consents_organization_id_organizations "
        "FOREIGN KEY (organization_id) REFERENCES organizations(id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE consents DROP CONSTRAINT IF EXISTS fk_consents_organization_id_organizations")
    op.execute("DROP POLICY IF EXISTS p_o ON user_profiles")
    op.execute(
        "CREATE POLICY p_o ON user_profiles FOR ALL TO td_app, td_readonly "
        "USING (user_id = app.user_id() OR app.is_platform()) WITH CHECK (user_id = app.user_id() OR app.is_platform())"
    )
    op.execute("DROP POLICY IF EXISTS p_users ON users")
    op.execute(
        "CREATE POLICY p_users ON users FOR ALL TO td_app, td_readonly "
        "USING (id = app.user_id() OR app.is_platform()) WITH CHECK (id = app.user_id() OR app.is_platform())"
    )
