"""placement: question_reports (PLC-33..35 reported-error queue)

Revision ID: placement_0003
Revises: placement_0002
Create Date: 2026-11-03

Table added during implementation (proposed back to the schema owner, database-schema §8):
a learner's report of an error in a bank question. RLS U: the reporter sees their own rows;
staff of the question's organization (``organization_id`` = the question's) and platform staff
see the queue. One open report per (reporter, question) is enforced by a partial unique index.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "placement_0003"
down_revision: str | Sequence[str] | None = "placement_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE question_reports (
          id                   uuid PRIMARY KEY,
          question_id          uuid        NOT NULL REFERENCES questions(id),
          question_version_id  uuid        NULL REFERENCES question_versions(id),
          organization_id      uuid        NULL REFERENCES organizations(id),
          user_id              uuid        NOT NULL REFERENCES users(id),
          category             text        NOT NULL CHECK (category IN
                                 ('wrong_answer','wrong_explanation','typo','unclear','other')),
          message              text        NOT NULL CHECK (char_length(message) BETWEEN 1 AND 1000),
          status               text        NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved')),
          resolution           text        NULL CHECK (resolution IS NULL OR resolution IN
                                 ('fixed','no_change','duplicate','invalid')),
          resolution_note      text        NULL CHECK (resolution_note IS NULL OR char_length(resolution_note) <= 1000),
          resolved_by          uuid        NULL REFERENCES users(id),
          resolved_at          timestamptz NULL,
          created_at           timestamptz NOT NULL DEFAULT now(),
          updated_at           timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_qr_resolved CHECK (
            (status = 'open' AND resolution IS NULL AND resolved_at IS NULL AND resolved_by IS NULL)
            OR (status = 'resolved' AND resolution IS NOT NULL AND resolved_at IS NOT NULL
                AND resolved_by IS NOT NULL))
        );
        CREATE UNIQUE INDEX ux_qr_open_per_user ON question_reports (user_id, question_id) WHERE status = 'open';
        CREATE INDEX ix_qr_queue ON question_reports (status, created_at DESC);
        CREATE INDEX ix_qr_question ON question_reports (question_id);
        COMMENT ON TABLE question_reports IS
          'Owner: placement | RLS: U | Retention: R-CONTENT (2 years after resolution) | PII: P1 (free text)';
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON question_reports TO td_app")
    op.execute("GRANT SELECT ON question_reports TO td_readonly")
    enable_rls("question_reports", "U")
    add_updated_at_trigger("question_reports")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS question_reports CASCADE")
