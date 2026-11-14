"""rbac: Admin may review and publish questions (question.review/publish → super_admin)

Revision ID: rbac_0005
Revises: rbac_0004
Create Date: 2026-11-11

QA audit 2026-11-11 (F10): reviewer != author (separation of duties) and only content managers
held ``question.review``, so with a single content manager that person's questions could never
be reviewed. The catalogue (``app/modules/rbac/catalogue.py``) now grants ``question.review`` to
Admin (``super_admin``), and ``question.publish`` too: the publisher must also differ from the
author (ADM-48), so a lone content manager could not publish their own approved question either.
This adds the matching ``role_permissions`` rows. Reviewer != author and publisher != author are
still enforced by the placement module.

Targeted on purpose (not ``rbac_seed.sync``): a full sync here would also touch permission rows
that other branches' migrations insert later. Same branch, no cross-branch dependency.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "rbac_0005"
down_revision: str | Sequence[str] | None = "rbac_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ROLE = "super_admin"
PERMS = ("question.review", "question.publish")


def upgrade() -> None:
    for perm in PERMS:
        op.get_bind().execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r, permissions p "
                "WHERE r.role_key = :r AND p.permission_key = :p ON CONFLICT DO NOTHING"
            ),
            {"r": ROLE, "p": perm},
        )


def downgrade() -> None:
    for perm in PERMS:
        op.get_bind().execute(
            text(
                "DELETE FROM role_permissions rp USING roles r, permissions p "
                "WHERE rp.role_id = r.id AND rp.permission_id = p.id "
                "AND r.role_key = :r AND p.permission_key = :p"
            ),
            {"r": ROLE, "p": perm},
        )
