"""placement: taxonomy, companies, company paths, question bank, practice, recommendations

Revision ID: placement_0001
Revises:
Create Date: 2026-11-03

database-schema §8. RLS: topics/companies none (global, no tenant columns); question bank and
company paths TN (NULL organization = platform bank); practice + recommendations U.
``topic_mastery`` is analytics-owned and NOT created here. Mentoring and résumé tables are
not created yet (PLC-36..52 are not implemented in this stage).

Deviation (proposed contract change): ``practice_sessions.served`` jsonb holds the served
question list with server ``served_at`` and reveal flags — the schema has no other place for
questions that were served but not yet answered (PLC-20).

``company_path_steps.test_id`` gets its FK in placement_0002 (tests live in assessments,
which depends on this revision).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "placement_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("placement",)
depends_on: str | Sequence[str] | None = ("core_base", "identity_0001", "orgs_0001")

GLOBAL_TABLES = ("topics", "companies")
TN_TABLES = (
    "company_paths",
    "company_path_steps",
    "questions",
    "question_versions",
    "question_options",
    "question_tags",
)
U_TABLES = ("practice_sessions", "practice_responses", "recommendations")


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE topics (
          id          uuid PRIMARY KEY,
          parent_id   uuid        NULL REFERENCES topics(id),
          kind        text        NOT NULL CHECK (kind IN ('subject','topic','subtopic')),
          slug        citext      NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
          name        text        NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
          path        text        NOT NULL UNIQUE,
          depth       smallint    NOT NULL CHECK (depth BETWEEN 0 AND 2),
          position    int         NOT NULL DEFAULT 0,
          is_active   boolean     NOT NULL DEFAULT true,
          created_at  timestamptz NOT NULL DEFAULT now(),
          updated_at  timestamptz NOT NULL DEFAULT now(),
          UNIQUE (parent_id, slug),
          CONSTRAINT ck_topic_root CHECK ((kind = 'subject') = (parent_id IS NULL)),
          CONSTRAINT ck_topic_depth CHECK ((kind = 'subject' AND depth = 0) OR (kind = 'topic' AND depth = 1)
                                           OR (kind = 'subtopic' AND depth = 2))
        );
        CREATE UNIQUE INDEX ux_topics_root_slug ON topics (slug) WHERE parent_id IS NULL;
        CREATE INDEX ix_topics_path ON topics (path text_pattern_ops);
        COMMENT ON TABLE topics IS 'Owner: placement | RLS: none (global taxonomy) | Retention: R-CONTENT | PII: P0';

        CREATE TABLE companies (
          id             uuid PRIMARY KEY,
          slug           citext      NOT NULL UNIQUE CHECK (slug ~ '^[a-z0-9][a-z0-9-]{0,62}$'),
          name           text        NOT NULL CHECK (char_length(name) BETWEEN 1 AND 200),
          logo_s3_key    text        NULL,
          industry       text        NULL,
          hub_status     text        NOT NULL DEFAULT 'draft' CHECK (hub_status IN ('draft','published','archived')),
          description_md text        NULL,
          created_at     timestamptz NOT NULL DEFAULT now(),
          updated_at     timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE companies IS 'Owner: placement | RLS: none | Retention: R-CONTENT | PII: P0';

        CREATE TABLE company_paths (
          id               uuid PRIMARY KEY,
          company_id       uuid        NOT NULL REFERENCES companies(id),
          organization_id  uuid        NULL REFERENCES organizations(id),
          role_name        text        NOT NULL,
          version_no       int         NOT NULL DEFAULT 1,
          pattern          jsonb       NOT NULL,
          status           text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','retired')),
          published_at     timestamptz NULL,
          created_by       uuid        NOT NULL REFERENCES users(id),
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now(),
          UNIQUE (company_id, role_name, version_no)
        );
        COMMENT ON TABLE company_paths IS 'Owner: placement | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE company_path_steps (
          id                uuid PRIMARY KEY,
          company_path_id   uuid        NOT NULL REFERENCES company_paths(id) ON DELETE CASCADE,
          organization_id   uuid        NULL REFERENCES organizations(id),
          position          int         NOT NULL,
          step_type         text        NOT NULL CHECK (step_type IN ('lesson','practice_set','test','coding_set')),
          lesson_key        uuid        NULL,
          test_id           uuid        NULL,
          topic_id          uuid        NULL REFERENCES topics(id),
          title             text        NOT NULL,
          is_required       boolean     NOT NULL DEFAULT true,
          UNIQUE (company_path_id, position),
          CONSTRAINT ck_cps_ref CHECK (num_nonnulls(lesson_key, test_id, topic_id) = 1)
        );
        COMMENT ON TABLE company_path_steps IS 'Owner: placement | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE questions (
          id                    uuid PRIMARY KEY,
          organization_id       uuid        NULL REFERENCES organizations(id),
          question_type         text        NOT NULL CHECK (question_type IN ('mcq_single','mcq_multi','numeric','fill_blank',
                                                'coding','descriptive')),
          primary_topic_id      uuid        NOT NULL REFERENCES topics(id),
          status                text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','active','retired')),
          current_version_id    uuid        NULL,
          external_ref          text        NULL,
          created_by            uuid        NOT NULL REFERENCES users(id),
          created_at            timestamptz NOT NULL DEFAULT now(),
          updated_at            timestamptz NOT NULL DEFAULT now(),
          deleted_at            timestamptz NULL
        );
        CREATE INDEX ix_q_topic ON questions (primary_topic_id, status);
        COMMENT ON TABLE questions IS 'Owner: placement | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE question_versions (
          id                 uuid PRIMARY KEY,
          question_id        uuid        NOT NULL REFERENCES questions(id),
          organization_id    uuid        NULL REFERENCES organizations(id),
          version_no         int         NOT NULL CHECK (version_no >= 1),
          stem               jsonb       NOT NULL,
          answer_key         jsonb       NULL,
          explanation        jsonb       NULL,
          difficulty         smallint    NOT NULL CHECK (difficulty BETWEEN 1 AND 5),
          item_rating        smallint    NOT NULL DEFAULT 1000,
          default_marks      numeric(6,2) NOT NULL DEFAULT 1 CHECK (default_marks > 0),
          default_negative   numeric(6,2) NOT NULL DEFAULT 0 CHECK (default_negative >= 0),
          expected_seconds   int         NULL,
          coding_problem_id  uuid        NULL,
          status             text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','in_review','published','retired')),
          content_hash       bytea       NOT NULL CHECK (octet_length(content_hash) = 32),
          authored_by        uuid        NOT NULL REFERENCES users(id),
          reviewed_by        uuid        NULL REFERENCES users(id),
          published_at       timestamptz NULL,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          UNIQUE (question_id, version_no),
          CONSTRAINT ck_qv_review CHECK (status <> 'published' OR (reviewed_by IS NOT NULL AND published_at IS NOT NULL)),
          CONSTRAINT ck_qv_reviewer CHECK (reviewed_by IS NULL OR reviewed_by <> authored_by OR organization_id IS NOT NULL)
        );
        ALTER TABLE questions ADD CONSTRAINT fk_q_current FOREIGN KEY (current_version_id) REFERENCES question_versions(id);
        CREATE INDEX ix_qv_pool ON question_versions (difficulty, status) INCLUDE (question_id) WHERE status = 'published';
        CREATE INDEX ix_qv_question ON question_versions (question_id, version_no DESC);
        COMMENT ON TABLE question_versions IS 'Owner: placement | RLS: TN | Retention: R-CONTENT | PII: P0 | immutable after publish';

        CREATE TABLE question_options (
          id                   uuid PRIMARY KEY,
          question_version_id  uuid        NOT NULL REFERENCES question_versions(id) ON DELETE CASCADE,
          organization_id      uuid        NULL REFERENCES organizations(id),
          label                text        NOT NULL,
          body                 jsonb       NOT NULL,
          is_correct           boolean     NOT NULL DEFAULT false,
          position             smallint    NOT NULL,
          feedback             jsonb       NULL,
          UNIQUE (question_version_id, position),
          UNIQUE (question_version_id, label)
        );
        COMMENT ON TABLE question_options IS 'Owner: placement | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE question_tags (
          id               uuid PRIMARY KEY,
          question_id      uuid        NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
          organization_id  uuid        NULL REFERENCES organizations(id),
          tag_type         text        NOT NULL CHECK (tag_type IN ('topic','company','skill','exam_pattern','source','custom')),
          topic_id         uuid        NULL REFERENCES topics(id),
          company_id       uuid        NULL REFERENCES companies(id),
          tag_value        text        NULL,
          created_at       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_qt_payload CHECK (
            (tag_type = 'topic'   AND topic_id IS NOT NULL) OR
            (tag_type = 'company' AND company_id IS NOT NULL) OR
            (tag_type NOT IN ('topic','company') AND tag_value IS NOT NULL))
        );
        CREATE UNIQUE INDEX ux_qt ON question_tags (question_id, tag_type, coalesce(topic_id::text, company_id::text, tag_value));
        CREATE INDEX ix_qt_topic ON question_tags (topic_id) WHERE topic_id IS NOT NULL;
        CREATE INDEX ix_qt_company ON question_tags (company_id) WHERE company_id IS NOT NULL;
        COMMENT ON TABLE question_tags IS 'Owner: placement | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE practice_sessions (
          id                   uuid PRIMARY KEY,
          user_id              uuid        NOT NULL REFERENCES users(id),
          organization_id      uuid        NULL REFERENCES organizations(id),
          mode                 text        NOT NULL CHECK (mode IN ('adaptive','topic_set','company_step','revision')),
          topic_id             uuid        NULL REFERENCES topics(id),
          company_path_step_id uuid        NULL REFERENCES company_path_steps(id),
          status               text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','completed','abandoned')),
          target_count         smallint    NULL,
          answered_count       smallint    NOT NULL DEFAULT 0,
          correct_count        smallint    NOT NULL DEFAULT 0,
          served               jsonb       NOT NULL DEFAULT '[]',
          started_at           timestamptz NOT NULL DEFAULT now(),
          ended_at             timestamptz NULL,
          updated_at           timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_prs_user ON practice_sessions (user_id, started_at DESC);
        COMMENT ON TABLE practice_sessions IS 'Owner: placement | RLS: U | Retention: R-LEARN | PII: P1';

        CREATE TABLE practice_responses (
          id                   uuid PRIMARY KEY,
          practice_session_id  uuid        NOT NULL REFERENCES practice_sessions(id) ON DELETE CASCADE,
          user_id              uuid        NOT NULL REFERENCES users(id),
          organization_id      uuid        NULL REFERENCES organizations(id),
          question_version_id  uuid        NOT NULL REFERENCES question_versions(id),
          topic_id             uuid        NOT NULL REFERENCES topics(id),
          response             jsonb       NOT NULL,
          is_correct           boolean     NULL,
          attempt_no           smallint    NOT NULL DEFAULT 1 CHECK (attempt_no >= 1),
          served_at            timestamptz NOT NULL,
          time_spent_ms        int         NOT NULL CHECK (time_spent_ms >= 0),
          hint_used            boolean     NOT NULL DEFAULT false,
          solution_viewed      boolean     NOT NULL DEFAULT false,
          rating_before        smallint    NULL,
          rating_after         smallint    NULL,
          answered_at          timestamptz NOT NULL DEFAULT now(),
          UNIQUE (practice_session_id, question_version_id),
          CONSTRAINT ck_pr_time CHECK (answered_at >= served_at)
        );
        CREATE INDEX ix_pr_user_q ON practice_responses (user_id, question_version_id, answered_at DESC);
        CREATE INDEX ix_pr_user_topic ON practice_responses (user_id, topic_id, answered_at);
        COMMENT ON TABLE practice_responses IS 'Owner: placement | RLS: U | Retention: R-LEARN | PII: P1';

        CREATE TABLE recommendations (
          id               uuid PRIMARY KEY,
          user_id          uuid        NOT NULL REFERENCES users(id),
          organization_id  uuid        NULL REFERENCES organizations(id),
          rule_key         text        NOT NULL CHECK (rule_key IN ('weak_topic','stale_topic','path_next_step','assigned_due','readiness_gap')),
          rule_version     smallint    NOT NULL DEFAULT 1,
          reason           text        NOT NULL,
          evidence         jsonb       NOT NULL DEFAULT '{}',
          target_type      text        NOT NULL CHECK (target_type IN ('lesson','practice_set','test','topic','company_path_step')),
          target_id        uuid        NOT NULL,
          priority         smallint    NOT NULL DEFAULT 50,
          status           text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','dismissed','completed','expired')),
          generated_at     timestamptz NOT NULL DEFAULT now(),
          expires_at       timestamptz NOT NULL
        );
        CREATE INDEX ix_rec_user_active ON recommendations (user_id, priority DESC) WHERE status = 'active';
        CREATE UNIQUE INDEX ux_rec_dedupe ON recommendations (user_id, rule_key, target_type, target_id) WHERE status = 'active';
        COMMENT ON TABLE recommendations IS 'Owner: placement | RLS: U | Retention: 90 days after expiry | PII: P1';

        -- Published question versions (and their options) are immutable (database-schema §8).
        CREATE FUNCTION placement_qv_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.status IN ('published','retired') AND (
               NEW.stem IS DISTINCT FROM OLD.stem OR NEW.answer_key IS DISTINCT FROM OLD.answer_key
            OR NEW.explanation IS DISTINCT FROM OLD.explanation OR NEW.difficulty IS DISTINCT FROM OLD.difficulty
            OR NEW.default_marks IS DISTINCT FROM OLD.default_marks
            OR NEW.default_negative IS DISTINCT FROM OLD.default_negative
            OR NEW.content_hash IS DISTINCT FROM OLD.content_hash OR NEW.question_id IS DISTINCT FROM OLD.question_id
            OR NEW.version_no IS DISTINCT FROM OLD.version_no) THEN
            RAISE EXCEPTION 'published question versions are immutable' USING ERRCODE = 'check_violation';
          END IF;
          IF OLD.status IN ('published','retired') AND NEW.status NOT IN ('published','retired') THEN
            RAISE EXCEPTION 'published question versions cannot return to draft' USING ERRCODE = 'check_violation';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_qv_immutable BEFORE UPDATE ON question_versions
          FOR EACH ROW EXECUTE FUNCTION placement_qv_immutable();

        CREATE FUNCTION placement_qo_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE st text;
        BEGIN
          SELECT status INTO st FROM question_versions WHERE id = OLD.question_version_id;
          IF st IN ('published','retired') THEN
            RAISE EXCEPTION 'options of a published question version are immutable' USING ERRCODE = 'check_violation';
          END IF;
          IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER trg_qo_immutable BEFORE UPDATE OR DELETE ON question_options
          FOR EACH ROW EXECUTE FUNCTION placement_qo_immutable();
        """
    )
    all_tables = GLOBAL_TABLES + TN_TABLES + U_TABLES
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(all_tables)} TO td_app")
    op.execute(f"GRANT SELECT ON {', '.join(all_tables)} TO td_readonly")
    for t in TN_TABLES:
        enable_rls(t, "TN")
    for t in U_TABLES:
        enable_rls(t, "U")
    for t in (
        "topics",
        "companies",
        "company_paths",
        "questions",
        "question_versions",
        "practice_sessions",
    ):
        add_updated_at_trigger(t)


def downgrade() -> None:
    for t in (
        "recommendations",
        "practice_responses",
        "practice_sessions",
        "question_tags",
        "question_options",
    ):
        op.execute(f"DROP TABLE IF EXISTS {t}")
    op.execute("ALTER TABLE questions DROP CONSTRAINT IF EXISTS fk_q_current")
    for t in ("question_versions", "questions", "company_path_steps", "company_paths", "companies", "topics"):
        op.execute(f"DROP TABLE IF EXISTS {t}")
    op.execute("DROP FUNCTION IF EXISTS placement_qv_immutable()")
    op.execute("DROP FUNCTION IF EXISTS placement_qo_immutable()")
