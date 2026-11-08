"""assessments: owning batch on tests (ADM-49)

Revision ID: assessments_0003
Revises: assessments_0002
Create Date: 2026-11-03

A test created by a batch-scoped trainer (``POST /studio/tests`` with ``batch_id``) records that
batch. Batch-scoped holders of ``test.edit`` / ``test.publish`` / ``test.override.grant`` then act
on the test through ``ScopeRef("batch", tests.batch_id)`` (matrix trainer = B), so every trainer of
the owning batch can edit it and no trainer of another batch in the same organization can.
Existing rows stay NULL (they keep the creator-only rule). RLS on ``tests`` is unchanged (TN).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "assessments_0003"
down_revision: str | Sequence[str] | None = "assessments_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE tests ADD COLUMN batch_id uuid NULL REFERENCES batches(id)")
    op.execute("CREATE INDEX ix_tests_batch ON tests (batch_id) WHERE batch_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tests_batch")
    op.execute("ALTER TABLE tests DROP COLUMN IF EXISTS batch_id")
