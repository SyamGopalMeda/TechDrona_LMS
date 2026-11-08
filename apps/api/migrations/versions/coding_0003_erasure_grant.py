"""coding: column-level UPDATE on ``submission_results.stdout_excerpt`` for privacy erasure (DB-01).

``submission_results`` is otherwise immutable for ``td_app`` (``REVOKE UPDATE`` in coding_0001):
verdicts, times and scores stay unchangeable; only the learner-output excerpt can be cleared by
``coding.privacy.erase_user``.

Revision ID: coding_0003
Revises: coding_0002
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "coding_0003"
down_revision: str | Sequence[str] | None = "coding_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT UPDATE (stdout_excerpt) ON submission_results TO td_app")


def downgrade() -> None:
    op.execute("REVOKE UPDATE (stdout_excerpt) ON submission_results FROM td_app")
