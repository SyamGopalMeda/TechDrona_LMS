"""identity: optional sign-in username (users.username)

Revision ID: identity_0006
Revises: identity_0005
Create Date: 2026-11-12

Admissions "Verify & Add to Batch" creates the student's LMS account with a generated username
(``td`` + 6 digits) and a temporary password. ``POST /auth/login`` accepts the email, the mobile
number or the username as the identifier.

Lower case only (the CHECK allows no capitals, so a case-insensitive login is a plain ``=`` on the
lower-cased input), 3-32 characters of ``[a-z0-9._-]``, unique among live accounts.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "identity_0006"
down_revision: str | Sequence[str] | None = "identity_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE users ADD COLUMN username text NULL
          CONSTRAINT ck_users_username CHECK (username ~ '^[a-z0-9._-]{3,32}$');
        CREATE UNIQUE INDEX ux_users_username ON users (username)
          WHERE username IS NOT NULL AND deleted_at IS NULL;
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_users_username")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS username")
