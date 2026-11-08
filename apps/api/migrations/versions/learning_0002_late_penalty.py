"""learning: raw (pre-penalty) score on assignment submissions (BE-08)

Revision ID: learning_0002
Revises: learning_0001
Create Date: 2026-11-03

``assignments.late_penalty_pct`` was stored but never applied. Grading a submission made after
``due_at`` now stores the grader's score in ``raw_score`` and the penalised score in ``score``
(``score = raw_score * (1 - late_penalty_pct / 100)``), so the learner sees the final score and
staff can see both.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "learning_0002"
down_revision: str | Sequence[str] | None = "learning_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE assignment_submissions
          ADD COLUMN raw_score numeric(7,2),
          ADD COLUMN late_penalty_pct numeric(5,2),
          ADD CONSTRAINT ck_asub_raw_score CHECK (raw_score IS NULL OR raw_score >= 0),
          ADD CONSTRAINT ck_asub_late_penalty CHECK
            (late_penalty_pct IS NULL OR (late_penalty_pct >= 0 AND late_penalty_pct <= 100));
        COMMENT ON COLUMN assignment_submissions.raw_score IS
          'Grader''s score before the late penalty; score holds the final (penalised) score';
        COMMENT ON COLUMN assignment_submissions.late_penalty_pct IS
          'Late penalty applied to raw_score (copied from the assignment at grading time)';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE assignment_submissions
          DROP CONSTRAINT IF EXISTS ck_asub_late_penalty,
          DROP CONSTRAINT IF EXISTS ck_asub_raw_score,
          DROP COLUMN IF EXISTS late_penalty_pct,
          DROP COLUMN IF EXISTS raw_score;
        """
    )
