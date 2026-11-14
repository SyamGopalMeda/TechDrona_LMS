"""admissions: "open the admission-letter step after enrolling" setting

Revision ID: admissions_0004
Revises: admissions_0003
Create Date: 2026-11-14

After "Verify & add to batch" (or "Enrol now") the admin is offered the admission / offer letter
step (preview, edit, issue through the documents register). ``letter_step_auto`` on the single
"pay to" settings row says whether that step opens by itself; NULL (no choice saved yet) = on.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "admissions_0004"
down_revision: str | Sequence[str] | None = "admissions_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE admission_pay_settings ADD COLUMN letter_step_auto boolean NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE admission_pay_settings DROP COLUMN IF EXISTS letter_step_auto")
