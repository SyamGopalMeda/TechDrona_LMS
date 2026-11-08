"""placement: question SoD editors + review comment + retire reason (audit ADM-46 / ADM-55)

Revision ID: placement_0004
Revises: placement_0003
Create Date: 2026-11-03

* ``question_versions.edited_by``: users other than ``authored_by`` who edited this version in
  place (PLC-07 on a draft). Any of them is refused as reviewer (PLC-09) and as publisher
  (PLC-10), so a reviewer cannot rewrite a draft and approve their own content.
* ``question_versions.review_comment``: the latest PLC-09 reviewer comment (request-changes
  feedback for the author).
* ``questions.retired_reason``: the PLC-11 reason.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "placement_0004"
down_revision: str | Sequence[str] | None = "placement_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE question_versions
          ADD COLUMN edited_by uuid[] NOT NULL DEFAULT '{}',
          ADD COLUMN review_comment text NULL
            CONSTRAINT ck_qv_review_comment CHECK (review_comment IS NULL OR char_length(review_comment) <= 2000);
        ALTER TABLE questions
          ADD COLUMN retired_reason text NULL
            CONSTRAINT ck_q_retired_reason CHECK (retired_reason IS NULL OR char_length(retired_reason) <= 500);
        COMMENT ON COLUMN question_versions.edited_by IS
          'Users (other than authored_by) who edited this version in place; excluded from review/publish (SoD)';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE questions DROP COLUMN IF EXISTS retired_reason;
        ALTER TABLE question_versions DROP COLUMN IF EXISTS review_comment;
        ALTER TABLE question_versions DROP COLUMN IF EXISTS edited_by;
        """
    )
