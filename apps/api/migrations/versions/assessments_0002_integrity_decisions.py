"""assessments: attempt integrity review decisions (ASM-20)

Revision ID: assessments_0002
Revises: assessments_0001
Create Date: 2026-11-03

Human review outcomes for advisory integrity flags (``no_action``, ``refer_security``,
``invalidate``). Append-only for td_app (a newer row supersedes an older one; the latest row is
the attempt's current decision). RLS U like every other attempt table: the student's own rows,
staff of the attempt's organization, platform.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import enable_rls, revoke_app_writes

revision: str = "assessments_0002"
down_revision: str | Sequence[str] | None = "assessments_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE attempt_integrity_decisions (
          id                 uuid PRIMARY KEY,
          attempt_id         uuid        NOT NULL REFERENCES test_attempts(id),
          test_id            uuid        NOT NULL REFERENCES tests(id),
          user_id            uuid        NOT NULL REFERENCES users(id),
          organization_id    uuid        NULL REFERENCES organizations(id),
          batch_id           uuid        NULL REFERENCES batches(id),
          outcome            text        NOT NULL CHECK (outcome IN ('no_action','refer_security','invalidate')),
          note               text        NOT NULL CHECK (char_length(note) BETWEEN 3 AND 2000),
          signals            jsonb       NOT NULL DEFAULT '{}',
          security_case_id   uuid        NULL,
          security_case_ref  text        NULL,
          decided_by         uuid        NOT NULL REFERENCES users(id),
          created_at         timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_aid_attempt ON attempt_integrity_decisions (attempt_id, created_at DESC);
        CREATE INDEX ix_aid_test ON attempt_integrity_decisions (test_id);
        COMMENT ON TABLE attempt_integrity_decisions IS
          'Owner: assessments | RLS: U | Retention: R-LEARN | PII: P1 | append-only';
        """
    )
    op.execute("GRANT SELECT, INSERT ON attempt_integrity_decisions TO td_app")
    op.execute("GRANT SELECT ON attempt_integrity_decisions TO td_readonly")
    revoke_app_writes("attempt_integrity_decisions")
    enable_rls("attempt_integrity_decisions", "U")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS attempt_integrity_decisions CASCADE")
