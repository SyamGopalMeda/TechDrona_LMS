"""learning: structured assignments (sections -> items), batch allocations with schedules and
per-section grading engines, per-item responses + grading, regrade requests

Revision ID: learning_0003
Revises: learning_0002
Create Date: 2026-11-06

WISEMAN-FEATURES build (assign). Extends the existing assignment tables instead of adding a
parallel model:

* ``assignments``: + ``submission_type = 'structured'``, + ``ai_help_enabled`` /
  ``ai_help_limit`` (per-learner tutor interactions; NULL = unlimited, still capped by the org's
  AI settings in the ai module).
* ``assignment_submissions``: + ``allocation_id`` (the allocation the learner works under),
  + ``ai_help_used``; ``status = 'draft'`` (already allowed) is the in-progress workspace.
* ``assignment_sections`` / ``assignment_items`` (RLS TN like ``assignments``). Bank items are
  soft references to placement ``questions`` / ``question_versions`` (the version is pinned
  when the structure is saved); inline items carry their own prompt.
* ``assignment_allocations`` (RLS T): batch or explicit learner list, the four schedule dates,
  ``section_engines`` {section_id: engine}, ``evaluator_ids``, per-learner ``extensions``.
* ``assignment_item_responses`` (RLS U): one row per (submission, item): learner response,
  deterministic ``auto_marks``, AI suggestion (pending until a staff finalize), final marks.
* ``assignment_regrade_requests`` (RLS U): one open request per submission (partial unique).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "learning_0003"
down_revision: str | Sequence[str] | None = "learning_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_TABLES = (
    "assignment_sections",
    "assignment_items",
    "assignment_allocations",
    "assignment_item_responses",
    "assignment_regrade_requests",
)


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE assignments DROP CONSTRAINT IF EXISTS assignments_submission_type_check;
        ALTER TABLE assignments
          ADD CONSTRAINT assignments_submission_type_check
            CHECK (submission_type IN ('file','text','link','code','structured')),
          ADD COLUMN ai_help_enabled boolean NOT NULL DEFAULT false,
          ADD COLUMN ai_help_limit integer NULL CHECK (ai_help_limit IS NULL OR ai_help_limit BETWEEN 0 AND 1000);

        CREATE TABLE assignment_sections (
          id               uuid PRIMARY KEY,
          assignment_id    uuid        NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
          organization_id  uuid        NULL REFERENCES organizations(id),
          position         smallint    NOT NULL CHECK (position >= 1),
          title            text        NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
          max_score        numeric(7,2) NULL CHECK (max_score IS NULL OR max_score > 0),
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now(),
          UNIQUE (assignment_id, position)
        );
        COMMENT ON TABLE assignment_sections IS 'Owner: learning | RLS: TN | Retention: R-LEARN | PII: none';

        CREATE TABLE assignment_items (
          id                  uuid PRIMARY KEY,
          section_id          uuid        NOT NULL REFERENCES assignment_sections(id) ON DELETE CASCADE,
          assignment_id       uuid        NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
          organization_id     uuid        NULL REFERENCES organizations(id),
          position            smallint    NOT NULL CHECK (position >= 1),
          source              text        NOT NULL CHECK (source IN ('bank','inline')),
          item_type           text        NOT NULL CHECK (item_type IN
                                ('mcq_single','mcq_multi','numeric','fill_blank','coding','essay','short_text','file')),
          question_id         uuid        NULL,
          question_version_id uuid        NULL,
          coding_problem_id   uuid        NULL,
          prompt_md           text        NULL,
          marks               numeric(7,2) NOT NULL DEFAULT 0 CHECK (marks >= 0),
          rubric              jsonb       NULL,
          reference_answer_md text        NULL,
          created_at          timestamptz NOT NULL DEFAULT now(),
          updated_at          timestamptz NOT NULL DEFAULT now(),
          UNIQUE (section_id, position),
          CONSTRAINT ck_aitem_source CHECK (
            (source = 'bank' AND question_id IS NOT NULL AND question_version_id IS NOT NULL)
            OR (source = 'inline' AND prompt_md IS NOT NULL)
          ),
          CONSTRAINT ck_aitem_coding CHECK (item_type <> 'coding' OR coding_problem_id IS NOT NULL)
        );
        CREATE INDEX ix_aitem_assignment ON assignment_items (assignment_id);
        COMMENT ON TABLE assignment_items IS 'Owner: learning | RLS: TN | Retention: R-LEARN | PII: none';

        CREATE TABLE assignment_allocations (
          id               uuid PRIMARY KEY,
          assignment_id    uuid        NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
          organization_id  uuid        NOT NULL REFERENCES organizations(id),
          batch_id         uuid        NULL REFERENCES batches(id),
          user_ids         uuid[]      NOT NULL DEFAULT '{}',
          visible_from     timestamptz NULL,
          visible_until    timestamptz NULL,
          start_at         timestamptz NULL,
          due_at           timestamptz NOT NULL,
          section_engines  jsonb       NOT NULL DEFAULT '{}',
          evaluator_ids    uuid[]      NOT NULL DEFAULT '{}',
          extensions       jsonb       NOT NULL DEFAULT '{}',
          status           text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
          created_by       uuid        NOT NULL REFERENCES users(id),
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_aalloc_target CHECK ((batch_id IS NOT NULL) <> (cardinality(user_ids) > 0)),
          CONSTRAINT ck_aalloc_window CHECK (
            (visible_from IS NULL OR visible_until IS NULL OR visible_from < visible_until)
            AND (start_at IS NULL OR start_at < due_at)
          )
        );
        CREATE INDEX ix_aalloc_assignment ON assignment_allocations (assignment_id);
        CREATE INDEX ix_aalloc_batch ON assignment_allocations (batch_id) WHERE batch_id IS NOT NULL;
        CREATE INDEX ix_aalloc_users ON assignment_allocations USING gin (user_ids);
        COMMENT ON TABLE assignment_allocations IS 'Owner: learning | RLS: T | Retention: R-LEARN | PII: P1';

        ALTER TABLE assignment_submissions
          ADD COLUMN allocation_id uuid NULL REFERENCES assignment_allocations(id),
          ADD COLUMN ai_help_used integer NOT NULL DEFAULT 0 CHECK (ai_help_used >= 0);

        CREATE TABLE assignment_item_responses (
          id                 uuid PRIMARY KEY,
          submission_id      uuid        NOT NULL REFERENCES assignment_submissions(id) ON DELETE CASCADE,
          item_id            uuid        NOT NULL REFERENCES assignment_items(id) ON DELETE CASCADE,
          user_id            uuid        NOT NULL REFERENCES users(id),
          organization_id    uuid        NULL REFERENCES organizations(id),
          response           jsonb       NULL,
          saved_at           timestamptz NULL,
          auto_marks         numeric(7,2) NULL CHECK (auto_marks IS NULL OR auto_marks >= 0),
          ai_status          text        NOT NULL DEFAULT 'none'
                               CHECK (ai_status IN ('none','queued','pending','failed','accepted')),
          ai_marks           numeric(7,2) NULL CHECK (ai_marks IS NULL OR ai_marks >= 0),
          ai_feedback_md     text        NULL,
          ai_confidence      real        NULL,
          ai_criteria        jsonb       NULL,
          ai_error           text        NULL,
          final_marks        numeric(7,2) NULL CHECK (final_marks IS NULL OR final_marks >= 0),
          final_feedback_md  text        NULL,
          grade_source       text        NULL CHECK (grade_source IS NULL OR grade_source IN ('auto','ai','human')),
          graded_by          uuid        NULL REFERENCES users(id),
          graded_at          timestamptz NULL,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          UNIQUE (submission_id, item_id)
        );
        CREATE INDEX ix_air_ai_status ON assignment_item_responses (ai_status) WHERE ai_status = 'queued';
        COMMENT ON TABLE assignment_item_responses IS 'Owner: learning | RLS: U | Retention: R-LEARN | PII: P2';

        CREATE TABLE assignment_regrade_requests (
          id               uuid PRIMARY KEY,
          submission_id    uuid        NOT NULL REFERENCES assignment_submissions(id) ON DELETE CASCADE,
          assignment_id    uuid        NOT NULL REFERENCES assignments(id) ON DELETE CASCADE,
          user_id          uuid        NOT NULL REFERENCES users(id),
          organization_id  uuid        NULL REFERENCES organizations(id),
          item_id          uuid        NULL REFERENCES assignment_items(id) ON DELETE SET NULL,
          reason           text        NOT NULL CHECK (length(reason) BETWEEN 10 AND 2000),
          status           text        NOT NULL DEFAULT 'open' CHECK (status IN ('open','resolved','rejected')),
          resolution_note  text        NULL,
          resolved_by      uuid        NULL REFERENCES users(id),
          resolved_at      timestamptz NULL,
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_arr_resolved CHECK ((status = 'open') = (resolved_at IS NULL))
        );
        CREATE UNIQUE INDEX ux_arr_one_open ON assignment_regrade_requests (submission_id) WHERE status = 'open';
        CREATE INDEX ix_arr_assignment ON assignment_regrade_requests (assignment_id, status);
        COMMENT ON TABLE assignment_regrade_requests IS 'Owner: learning | RLS: U | Retention: R-LEARN | PII: P2';
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(NEW_TABLES)} TO td_app")
    op.execute(f"GRANT SELECT ON {', '.join(NEW_TABLES)} TO td_readonly")
    for t in NEW_TABLES:
        add_updated_at_trigger(t)
    enable_rls("assignment_sections", "TN")
    enable_rls("assignment_items", "TN")
    enable_rls("assignment_allocations", "T")
    enable_rls("assignment_item_responses", "U")
    enable_rls("assignment_regrade_requests", "U")


def downgrade() -> None:
    for t in reversed(NEW_TABLES):
        if t == "assignment_allocations":
            op.execute(
                "ALTER TABLE assignment_submissions DROP COLUMN IF EXISTS allocation_id, "
                "DROP COLUMN IF EXISTS ai_help_used"
            )
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute(
        """
        ALTER TABLE assignments DROP COLUMN IF EXISTS ai_help_limit, DROP COLUMN IF EXISTS ai_help_enabled;
        DELETE FROM assignment_submissions WHERE assignment_id IN
          (SELECT id FROM assignments WHERE submission_type = 'structured');
        DELETE FROM assignments WHERE submission_type = 'structured';
        ALTER TABLE assignments DROP CONSTRAINT IF EXISTS assignments_submission_type_check;
        ALTER TABLE assignments ADD CONSTRAINT assignments_submission_type_check
          CHECK (submission_type IN ('file','text','link','code'));
        """
    )
