"""assessments: tests, sections, draw rules, assignments, overrides, attempts, results

Revision ID: assessments_0001
Revises:
Create Date: 2026-11-03

database-schema §9 / ADR-0013. RLS: test definitions TN; assignments TN (platform-wide drives
have NULL organization); overrides and every attempt table U. ``attempt_events`` is partitioned
monthly on ``occurred_at`` (DEFAULT partition here; pg_partman monthly partitions Planned) and
append-only for td_app.

FKs to ``courses`` (catalog) and ``coding_problems`` (coding) are deferred until those modules
ship their tables (columns exist, no FK yet).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls, revoke_app_writes

revision: str = "assessments_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("assessments",)
depends_on: str | Sequence[str] | None = (
    "core_base",
    "identity_0001",
    "orgs_0001",
    "sessions_0001",
    "placement_0001",
)

TN_TABLES = ("tests", "test_sections", "test_section_rules", "test_assignments")
U_TABLES = (
    "attempt_overrides",
    "test_attempts",
    "attempt_sections",
    "attempt_responses",
    "attempt_events",
    "attempt_results",
)


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE tests (
          id                  uuid PRIMARY KEY,
          organization_id     uuid        NULL REFERENCES organizations(id),
          test_kind           text        NOT NULL CHECK (test_kind IN ('practice_set','mock','company_mock','diagnostic','course_quiz','drive')),
          title               text        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 300),
          slug                citext      NULL,
          company_id          uuid        NULL REFERENCES companies(id),
          company_path_id     uuid        NULL REFERENCES company_paths(id),
          status              text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','closed','archived')),
          version             int         NOT NULL DEFAULT 1,
          duration_seconds    int         NULL CHECK (duration_seconds > 0),
          grace_seconds       int         NOT NULL DEFAULT 30 CHECK (grace_seconds BETWEEN 0 AND 300),
          navigation_mode     text        NOT NULL DEFAULT 'free' CHECK (navigation_mode IN ('free','sequential','section_locked')),
          attempts_allowed    smallint    NULL CHECK (attempts_allowed > 0),
          grading_method      text        NOT NULL DEFAULT 'highest' CHECK (grading_method IN ('highest','latest','first','average')),
          shuffle_questions   boolean     NOT NULL DEFAULT true,
          shuffle_options     boolean     NOT NULL DEFAULT true,
          review_policy       jsonb       NOT NULL,
          integrity_settings  jsonb       NOT NULL DEFAULT jsonb_build_object('fullscreen', false, 'log_focus', true, 'log_paste', true),
          pass_percentage     numeric(5,2) NULL,
          is_free             boolean     NOT NULL DEFAULT false,
          available_from      timestamptz NULL,
          available_until     timestamptz NULL,
          settings_locked_at  timestamptz NULL,
          published_at        timestamptz NULL,
          created_by          uuid        NOT NULL REFERENCES users(id),
          created_at          timestamptz NOT NULL DEFAULT now(),
          updated_at          timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_tests_window CHECK (available_until IS NULL OR available_from IS NULL OR available_until > available_from)
        );
        CREATE INDEX ix_tests_company ON tests (company_id) WHERE company_id IS NOT NULL;
        CREATE INDEX ix_tests_org ON tests (organization_id, status);
        COMMENT ON TABLE tests IS 'Owner: assessments | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE test_sections (
          id                uuid PRIMARY KEY,
          test_id           uuid        NOT NULL REFERENCES tests(id) ON DELETE CASCADE,
          organization_id   uuid        NULL REFERENCES organizations(id),
          title             text        NOT NULL,
          position          smallint    NOT NULL,
          duration_seconds  int         NULL CHECK (duration_seconds > 0),
          instructions_md   text        NULL,
          min_attempt_required smallint NULL,
          UNIQUE (test_id, position)
        );
        COMMENT ON TABLE test_sections IS 'Owner: assessments | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE test_section_rules (
          id                   uuid PRIMARY KEY,
          test_section_id      uuid        NOT NULL REFERENCES test_sections(id) ON DELETE CASCADE,
          organization_id      uuid        NULL REFERENCES organizations(id),
          position             smallint    NOT NULL,
          rule_type            text        NOT NULL CHECK (rule_type IN ('fixed','random')),
          question_id          uuid        NULL REFERENCES questions(id),
          question_version_id  uuid        NULL REFERENCES question_versions(id),
          topic_id             uuid        NULL REFERENCES topics(id),
          company_id           uuid        NULL REFERENCES companies(id),
          question_types       text[]      NULL,
          difficulty_min       smallint    NULL CHECK (difficulty_min BETWEEN 1 AND 5),
          difficulty_max       smallint    NULL CHECK (difficulty_max BETWEEN 1 AND 5),
          tag_filter           jsonb       NULL,
          draw_count           smallint    NOT NULL DEFAULT 1 CHECK (draw_count >= 1),
          marks_each           numeric(6,2) NULL CHECK (marks_each > 0),
          negative_marks_each  numeric(6,2) NULL CHECK (negative_marks_each >= 0),
          UNIQUE (test_section_id, position),
          CONSTRAINT ck_tsr_type CHECK (
            (rule_type = 'fixed'  AND question_id IS NOT NULL AND draw_count = 1) OR
            (rule_type = 'random' AND question_id IS NULL AND topic_id IS NOT NULL)),
          CONSTRAINT ck_tsr_diff CHECK (difficulty_min IS NULL OR difficulty_max IS NULL OR difficulty_min <= difficulty_max)
        );
        COMMENT ON TABLE test_section_rules IS 'Owner: assessments | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE test_assignments (
          id                 uuid PRIMARY KEY,
          test_id            uuid        NOT NULL REFERENCES tests(id),
          organization_id    uuid        NULL REFERENCES organizations(id),
          batch_id           uuid        NULL REFERENCES batches(id),
          course_id          uuid        NULL,
          available_from     timestamptz NOT NULL,
          available_until    timestamptz NOT NULL,
          attempts_allowed   smallint    NULL CHECK (attempts_allowed > 0),
          release_mode       text        NOT NULL DEFAULT 'immediate' CHECK (release_mode IN ('immediate','after_window','scheduled','manual')),
          results_release_at timestamptz NULL,
          assigned_by        uuid        NOT NULL REFERENCES users(id),
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_ta_target CHECK (num_nonnulls(batch_id, course_id) >= 1 OR organization_id IS NOT NULL),
          CONSTRAINT ck_ta_window CHECK (available_until > available_from),
          CONSTRAINT ck_ta_scheduled CHECK (release_mode <> 'scheduled' OR results_release_at IS NOT NULL)
        );
        CREATE INDEX ix_ta_batch ON test_assignments (batch_id, available_from) WHERE batch_id IS NOT NULL;
        CREATE INDEX ix_ta_test ON test_assignments (test_id);
        COMMENT ON TABLE test_assignments IS 'Owner: assessments | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE attempt_overrides (
          id                       uuid PRIMARY KEY,
          test_id                  uuid        NOT NULL REFERENCES tests(id),
          test_assignment_id       uuid        NULL REFERENCES test_assignments(id),
          organization_id          uuid        NULL REFERENCES organizations(id),
          user_id                  uuid        NULL REFERENCES users(id),
          batch_id                 uuid        NULL REFERENCES batches(id),
          extra_time_seconds       int         NOT NULL DEFAULT 0 CHECK (extra_time_seconds >= 0),
          extra_attempts           smallint    NOT NULL DEFAULT 0 CHECK (extra_attempts >= 0),
          window_extension_seconds int         NOT NULL DEFAULT 0 CHECK (window_extension_seconds >= 0),
          reason                   text        NOT NULL CHECK (char_length(reason) BETWEEN 3 AND 500),
          granted_by               uuid        NOT NULL REFERENCES users(id),
          created_at               timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_ao_target CHECK (num_nonnulls(user_id, batch_id) = 1)
        );
        CREATE INDEX ix_ao_user ON attempt_overrides (test_id, user_id) WHERE user_id IS NOT NULL;
        CREATE INDEX ix_ao_batch ON attempt_overrides (test_id, batch_id) WHERE batch_id IS NOT NULL;
        COMMENT ON TABLE attempt_overrides IS 'Owner: assessments | RLS: U | Retention: R-LEARN | PII: P1';

        CREATE TABLE test_attempts (
          id                   uuid PRIMARY KEY,
          test_id              uuid        NOT NULL REFERENCES tests(id),
          test_version         int         NOT NULL,
          test_assignment_id   uuid        NULL REFERENCES test_assignments(id),
          user_id              uuid        NOT NULL REFERENCES users(id),
          organization_id      uuid        NULL REFERENCES organizations(id),
          batch_id             uuid        NULL REFERENCES batches(id),
          attempt_no           smallint    NOT NULL CHECK (attempt_no >= 1),
          status               text        NOT NULL DEFAULT 'in_progress' CHECK (status IN ('in_progress','submitted','auto_submitted',
                                               'grading','awaiting_manual','graded','invalidated','abandoned')),
          selection_seed       bytea       NOT NULL CHECK (octet_length(selection_seed) = 16),
          layout               jsonb       NOT NULL,
          started_at           timestamptz NOT NULL DEFAULT now(),
          deadline_at          timestamptz NULL,
          extra_time_seconds   int         NOT NULL DEFAULT 0,
          submitted_at         timestamptz NULL,
          submit_reason        text        NULL CHECK (submit_reason IN ('user','deadline','section_end','admin_force','session_end')),
          last_seen_at         timestamptz NOT NULL DEFAULT now(),
          current_section_id   uuid        NULL REFERENCES test_sections(id),
          bound_session_id     uuid        NULL REFERENCES auth_sessions(id),
          bound_device_id      uuid        NULL REFERENCES devices(id),
          rebind_count         smallint    NOT NULL DEFAULT 0 CHECK (rebind_count >= 0),
          start_ip             inet        NULL,
          idempotency_key      text        NOT NULL,
          integrity_status     text        NOT NULL DEFAULT 'none' CHECK (integrity_status IN ('none','review_recommended','cleared','invalidated')),
          created_at           timestamptz NOT NULL DEFAULT now(),
          updated_at           timestamptz NOT NULL DEFAULT now(),
          UNIQUE (test_id, user_id, attempt_no),
          UNIQUE (user_id, idempotency_key),
          CONSTRAINT ck_att_submit CHECK ((status IN ('in_progress','abandoned')) OR submitted_at IS NOT NULL)
        );
        CREATE UNIQUE INDEX ux_att_one_open ON test_attempts (test_id, user_id) WHERE status = 'in_progress';
        CREATE INDEX ix_att_deadline ON test_attempts (deadline_at) WHERE status = 'in_progress';
        CREATE INDEX ix_att_user ON test_attempts (user_id, started_at DESC);
        CREATE INDEX ix_att_assignment ON test_attempts (test_assignment_id, status) WHERE test_assignment_id IS NOT NULL;
        CREATE INDEX ix_att_bound_session ON test_attempts (bound_session_id) WHERE status = 'in_progress';
        CREATE INDEX ix_att_test ON test_attempts (test_id, status);
        COMMENT ON TABLE test_attempts IS 'Owner: assessments | RLS: U | Retention: R-LEARN | PII: P1/P3';

        CREATE TABLE attempt_sections (
          attempt_id        uuid        NOT NULL REFERENCES test_attempts(id) ON DELETE CASCADE,
          test_section_id   uuid        NOT NULL REFERENCES test_sections(id),
          user_id           uuid        NOT NULL,
          organization_id   uuid        NULL,
          position          smallint    NOT NULL,
          status            text        NOT NULL DEFAULT 'not_started' CHECK (status IN ('not_started','active','submitted','timed_out')),
          started_at        timestamptz NULL,
          deadline_at       timestamptz NULL,
          submitted_at      timestamptz NULL,
          PRIMARY KEY (attempt_id, test_section_id)
        );
        COMMENT ON TABLE attempt_sections IS 'Owner: assessments | RLS: U | Retention: R-LEARN | PII: P1';

        CREATE TABLE attempt_responses (
          id                   uuid PRIMARY KEY,
          attempt_id           uuid        NOT NULL REFERENCES test_attempts(id) ON DELETE CASCADE,
          user_id              uuid        NOT NULL,
          organization_id      uuid        NULL,
          test_section_id      uuid        NOT NULL REFERENCES test_sections(id),
          question_version_id  uuid        NOT NULL REFERENCES question_versions(id),
          response             jsonb       NULL,
          client_seq           bigint      NOT NULL CHECK (client_seq >= 0),
          flagged              boolean     NOT NULL DEFAULT false,
          time_spent_ms        int         NOT NULL DEFAULT 0,
          first_answered_at    timestamptz NULL,
          saved_at             timestamptz NOT NULL DEFAULT now(),
          is_correct           boolean     NULL,
          marks_awarded        numeric(7,2) NULL,
          manual_grade_by      uuid        NULL REFERENCES users(id),
          UNIQUE (attempt_id, question_version_id)
        );
        COMMENT ON TABLE attempt_responses IS 'Owner: assessments | RLS: U | Retention: R-LEARN | PII: P1';

        CREATE TABLE attempt_events (
          id                   uuid        NOT NULL,
          occurred_at          timestamptz NOT NULL,
          attempt_id           uuid        NOT NULL,
          user_id              uuid        NOT NULL,
          organization_id      uuid        NULL,
          event_type           text        NOT NULL CHECK (event_type IN ('start','resume','answer_saved','answer_cleared','flag',
                                  'section_enter','section_submit','navigate','focus_lost','focus_gained','fullscreen_exit','paste',
                                  'disconnect','reconnect','rebind_requested','rebind','rebind_refused','session_revoked_security',
                                  'timer_sync','submit','auto_submit','override_applied','regrade','invalidate',
                                  'reattach_same_device')),
          question_version_id  uuid        NULL,
          client_seq           bigint      NULL,
          payload              jsonb       NOT NULL DEFAULT '{}',
          auth_session_id      uuid        NULL,
          ip                   inet        NULL,
          PRIMARY KEY (id, occurred_at)
        ) PARTITION BY RANGE (occurred_at);
        CREATE TABLE attempt_events_default PARTITION OF attempt_events DEFAULT;
        CREATE INDEX ix_ae_attempt ON attempt_events (attempt_id, occurred_at);
        COMMENT ON TABLE attempt_events IS 'Owner: assessments | RLS: U | Retention: R-ASSESS-EVT | PII: P1/P3 | append-only';

        CREATE TABLE attempt_results (
          attempt_id          uuid PRIMARY KEY REFERENCES test_attempts(id),
          user_id             uuid        NOT NULL REFERENCES users(id),
          organization_id     uuid        NULL REFERENCES organizations(id),
          test_id             uuid        NOT NULL REFERENCES tests(id),
          scoring_version     smallint    NOT NULL DEFAULT 1,
          score               numeric(8,2) NOT NULL,
          max_score           numeric(8,2) NOT NULL CHECK (max_score > 0),
          percentage          numeric(5,2) NOT NULL,
          correct_count       smallint    NOT NULL,
          incorrect_count     smallint    NOT NULL,
          unanswered_count    smallint    NOT NULL,
          time_taken_seconds  int         NOT NULL,
          section_scores      jsonb       NOT NULL,
          topic_scores        jsonb       NOT NULL,
          percentile          numeric(5,2) NULL,
          rank                int         NULL,
          rank_provisional    boolean     NOT NULL DEFAULT true,
          passed              boolean     NULL,
          graded_at           timestamptz NOT NULL DEFAULT now(),
          released_at         timestamptz NULL,
          updated_at          timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_ares_test_score ON attempt_results (test_id, score DESC);
        COMMENT ON TABLE attempt_results IS 'Owner: assessments | RLS: U | Retention: R-LEARN | PII: P1';
        """
    )
    all_tables = TN_TABLES + U_TABLES
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(all_tables)} TO td_app")
    op.execute(f"GRANT SELECT ON {', '.join(all_tables)} TO td_readonly")
    # App roles reach the partition only through the RLS-protected parent.
    op.execute("REVOKE ALL ON attempt_events_default FROM td_app, td_readonly")
    revoke_app_writes("attempt_events")
    for t in TN_TABLES:
        enable_rls(t, "TN")
    for t in U_TABLES:
        enable_rls(t, "U")
    enable_rls("attempt_events_default", "U")
    for t in ("tests", "test_assignments", "test_attempts", "attempt_results"):
        add_updated_at_trigger(t)


def downgrade() -> None:
    for t in (
        "attempt_results",
        "attempt_events",
        "attempt_responses",
        "attempt_sections",
        "test_attempts",
        "attempt_overrides",
        "test_assignments",
        "test_section_rules",
        "test_sections",
        "tests",
    ):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
