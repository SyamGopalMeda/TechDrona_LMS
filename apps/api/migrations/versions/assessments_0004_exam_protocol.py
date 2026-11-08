"""assessments: exam protocol events + human/AI-assisted item grading

Revision ID: assessments_0004
Revises: assessments_0003
Create Date: 2026-11-06

* ``attempt_events.event_type`` gains the exam-protocol evidence types (``window_blur``, ``copy``,
  ``cut``, ``resize``, ``right_click``) and the server's own ``integrity_flagged`` marker.
* ``test_attempts.submit_reason`` gains ``integrity_limit`` (opt-in auto-submit after N recorded
  events; off by default).
* ``attempt_item_grades``: per (attempt, question version) grading of free-text items. AI columns
  hold a pending *suggestion*; ``final_*`` is written by a person and is the only value scoring
  uses. RLS U like every other attempt table (learner's own rows, staff of the org, platform).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "assessments_0004"
down_revision: str | Sequence[str] | None = "assessments_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BASE_EVENTS = (
    "'start','resume','answer_saved','answer_cleared','flag',"
    "'section_enter','section_submit','navigate','focus_lost','focus_gained','fullscreen_exit','paste',"
    "'disconnect','reconnect','rebind_requested','rebind','rebind_refused','session_revoked_security',"
    "'timer_sync','submit','auto_submit','override_applied','regrade','invalidate',"
    "'reattach_same_device'"
)
_NEW_EVENTS = "'window_blur','copy','cut','resize','right_click','integrity_flagged'"
_BASE_REASONS = "'user','deadline','section_end','admin_force','session_end'"


def upgrade() -> None:
    op.execute("ALTER TABLE attempt_events DROP CONSTRAINT IF EXISTS attempt_events_event_type_check")
    op.execute(
        "ALTER TABLE attempt_events ADD CONSTRAINT attempt_events_event_type_check "
        f"CHECK (event_type IN ({_BASE_EVENTS},{_NEW_EVENTS}))"
    )
    op.execute("ALTER TABLE test_attempts DROP CONSTRAINT IF EXISTS test_attempts_submit_reason_check")
    op.execute(
        "ALTER TABLE test_attempts ADD CONSTRAINT test_attempts_submit_reason_check "
        f"CHECK (submit_reason IN ({_BASE_REASONS},'integrity_limit'))"
    )
    op.execute(
        r"""
        CREATE TABLE attempt_item_grades (
          attempt_id           uuid         NOT NULL REFERENCES test_attempts(id) ON DELETE CASCADE,
          question_version_id  uuid         NOT NULL REFERENCES question_versions(id),
          test_id              uuid         NOT NULL REFERENCES tests(id),
          user_id              uuid         NOT NULL REFERENCES users(id),
          organization_id      uuid         NULL REFERENCES organizations(id),
          max_marks            numeric(7,2) NOT NULL CHECK (max_marks >= 0),
          ai_status            text         NOT NULL DEFAULT 'none' CHECK (ai_status IN ('none','pending','failed')),
          ai_marks             numeric(7,2) NULL CHECK (ai_marks IS NULL OR ai_marks >= 0),
          ai_feedback          text         NULL,
          ai_confidence        numeric(4,3) NULL CHECK (ai_confidence IS NULL OR ai_confidence BETWEEN 0 AND 1),
          ai_criteria          jsonb        NULL,
          ai_error             text         NULL,
          ai_graded_at         timestamptz  NULL,
          final_marks          numeric(7,2) NULL CHECK (final_marks IS NULL OR (final_marks >= 0 AND final_marks <= max_marks)),
          final_feedback       text         NULL CHECK (final_feedback IS NULL OR char_length(final_feedback) <= 10000),
          finalized_by         uuid         NULL REFERENCES users(id),
          finalized_at         timestamptz  NULL,
          created_at           timestamptz  NOT NULL DEFAULT now(),
          updated_at           timestamptz  NOT NULL DEFAULT now(),
          PRIMARY KEY (attempt_id, question_version_id),
          CONSTRAINT ck_aig_final CHECK ((final_marks IS NULL) = (finalized_at IS NULL))
        );
        CREATE INDEX ix_aig_test ON attempt_item_grades (test_id);
        COMMENT ON TABLE attempt_item_grades IS 'Owner: assessments | RLS: U | Retention: R-LEARN | PII: P1';
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON attempt_item_grades TO td_app")
    op.execute("GRANT SELECT ON attempt_item_grades TO td_readonly")
    enable_rls("attempt_item_grades", "U")
    add_updated_at_trigger("attempt_item_grades")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS attempt_item_grades")
    op.execute("ALTER TABLE test_attempts DROP CONSTRAINT IF EXISTS test_attempts_submit_reason_check")
    op.execute(
        "ALTER TABLE test_attempts ADD CONSTRAINT test_attempts_submit_reason_check "
        f"CHECK (submit_reason IN ({_BASE_REASONS}))"
    )
    op.execute("ALTER TABLE attempt_events DROP CONSTRAINT IF EXISTS attempt_events_event_type_check")
    op.execute(
        "ALTER TABLE attempt_events ADD CONSTRAINT attempt_events_event_type_check "
        f"CHECK (event_type IN ({_BASE_EVENTS}))"
    )
