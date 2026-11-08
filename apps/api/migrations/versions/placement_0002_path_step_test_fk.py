"""placement: company_path_steps.test_id -> tests(id)

Revision ID: placement_0002
Revises: placement_0001
Create Date: 2026-11-03

``tests`` is created by assessments_0001 (which itself depends on placement_0001), so the FK is
added in this follow-up revision.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "placement_0002"
down_revision: str | Sequence[str] | None = "placement_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = ("assessments_0001",)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE company_path_steps ADD CONSTRAINT fk_company_path_steps_test_id_tests "
        "FOREIGN KEY (test_id) REFERENCES tests(id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE company_path_steps DROP CONSTRAINT IF EXISTS fk_company_path_steps_test_id_tests")
