"""coding: judge languages, problems, test cases (hidden = encrypted), submissions, results

Revision ID: coding_0001
Revises:
Create Date: 2026-11-03

database-schema §10 with these documented deviations (proposed back to the schema owner):

* ``coding_problems.is_free`` — free practice problems pass ``require_access(is_free=True)``.
* ``code_submissions.judge_provider`` also allows ``'fake'`` (FakeJudgeAdapter, never in
  production); ``normalized_sha256`` (plagiarism hook) and ``retry_count`` (one automatic
  retry after ``judge_timeout``) added.
* ``coding_test_case_blobs`` — private ciphertext store standing in for S3
  ``td-judge-private`` (``input_s3_key``/``expected_s3_key`` hold ``db:blob/<uuid>``).
* Soft references (no FK yet, owning modules not built): ``primary_topic_id`` → topics,
  ``attempt_id`` → test_attempts, ``practice_session_id`` → practice_sessions.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "coding_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("coding",)
depends_on: str | Sequence[str] | None = ("core_base", "identity_0001", "orgs_0001")

TENANT_TABLES = ("coding_problems", "coding_test_cases", "coding_test_case_blobs")
USER_TABLES = ("code_submissions", "submission_results")


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE judge_languages (
          id                    uuid PRIMARY KEY,
          language_key          text        NOT NULL UNIQUE CHECK (language_key ~ '^[a-z][a-z0-9_]{0,31}$'),
          display_name          text        NOT NULL,
          version_label         text        NULL,
          provider_language_id  int         NOT NULL,
          time_multiplier       numeric(4,2) NOT NULL DEFAULT 1.0 CHECK (time_multiplier BETWEEN 0.5 AND 5),
          memory_extra_kb       int         NOT NULL DEFAULT 0 CHECK (memory_extra_kb >= 0),
          max_processes         smallint    NOT NULL DEFAULT 64 CHECK (max_processes BETWEEN 1 AND 256),
          is_enabled            boolean     NOT NULL DEFAULT true,
          starter_template      text        NULL,
          updated_at            timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE judge_languages IS 'Owner: coding | RLS: NONE (reference) | Retention: R-CONTENT | PII: P0';

        CREATE TABLE coding_problems (
          id                uuid PRIMARY KEY,
          organization_id   uuid        NULL REFERENCES organizations(id),
          slug              citext      NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,79}$'),
          title             text        NOT NULL CHECK (char_length(title) BETWEEN 3 AND 200),
          version_no        int         NOT NULL DEFAULT 1,
          statement_md      text        NOT NULL,
          input_format_md   text        NULL,
          output_format_md  text        NULL,
          constraints_md    text        NULL,
          difficulty        smallint    NOT NULL CHECK (difficulty BETWEEN 1 AND 5),
          primary_topic_id  uuid        NULL,
          time_limit_ms     int         NOT NULL DEFAULT 2000 CHECK (time_limit_ms BETWEEN 100 AND 5000),
          wall_limit_ms     int         NOT NULL DEFAULT 5000 CHECK (wall_limit_ms BETWEEN 200 AND 10000),
          memory_limit_kb   int         NOT NULL DEFAULT 262144 CHECK (memory_limit_kb BETWEEN 16384 AND 524288),
          allowed_languages text[]      NOT NULL DEFAULT '{c,cpp17,java17,python3}',
          checker_type      text        NOT NULL DEFAULT 'exact' CHECK (checker_type IN ('exact','token','float_tolerance','custom')),
          checker_config    jsonb       NULL,
          scoring_mode      text        NOT NULL DEFAULT 'weighted_cases' CHECK (scoring_mode IN ('weighted_cases','all_or_nothing')),
          status            text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','in_review','published','retired')),
          is_free           boolean     NOT NULL DEFAULT false,
          created_by        uuid        NOT NULL REFERENCES users(id),
          published_by      uuid        NULL REFERENCES users(id),
          published_at      timestamptz NULL,
          created_at        timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_cp_wall CHECK (wall_limit_ms >= time_limit_ms)
        );
        CREATE UNIQUE INDEX ux_cp_slug ON coding_problems (coalesce(organization_id, '00000000-0000-0000-0000-000000000000'::uuid), slug);
        CREATE INDEX ix_cp_status ON coding_problems (status, difficulty);
        COMMENT ON TABLE coding_problems IS 'Owner: coding | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE coding_test_case_blobs (
          id                  uuid PRIMARY KEY,
          coding_problem_id   uuid        NOT NULL REFERENCES coding_problems(id) ON DELETE CASCADE,
          organization_id     uuid        NULL REFERENCES organizations(id),
          ciphertext          bytea       NOT NULL CHECK (octet_length(ciphertext) BETWEEN 28 AND 8388636),
          created_at          timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_ctcb_problem ON coding_test_case_blobs (coding_problem_id);
        COMMENT ON TABLE coding_test_case_blobs IS 'Owner: coding | RLS: TN | AES-256-GCM ciphertext only (stand-in for S3 td-judge-private) | PII: P0/P4';

        CREATE TABLE coding_test_cases (
          id                  uuid PRIMARY KEY,
          coding_problem_id   uuid        NOT NULL REFERENCES coding_problems(id) ON DELETE CASCADE,
          organization_id     uuid        NULL REFERENCES organizations(id),
          problem_version     int         NOT NULL,
          ordinal             smallint    NOT NULL CHECK (ordinal >= 1),
          is_sample           boolean     NOT NULL DEFAULT false,
          is_hidden           boolean     NOT NULL DEFAULT true,
          weight              numeric(6,2) NOT NULL DEFAULT 1 CHECK (weight >= 0),
          sample_input        text        NULL,
          sample_output       text        NULL,
          input_s3_key        text        NULL,
          expected_s3_key     text        NULL,
          wrapped_data_key    bytea       NULL,
          input_sha256        bytea       NULL CHECK (input_sha256 IS NULL OR octet_length(input_sha256) = 32),
          expected_sha256     bytea       NULL CHECK (expected_sha256 IS NULL OR octet_length(expected_sha256) = 32),
          size_bytes          int         NULL,
          created_at          timestamptz NOT NULL DEFAULT now(),
          UNIQUE (coding_problem_id, problem_version, ordinal),
          CONSTRAINT ck_ctc_mode CHECK (is_sample <> is_hidden),
          CONSTRAINT ck_ctc_sample CHECK (NOT is_sample OR (sample_input IS NOT NULL AND sample_output IS NOT NULL)),
          CONSTRAINT ck_ctc_hidden CHECK (NOT is_hidden OR (input_s3_key IS NOT NULL AND expected_s3_key IS NOT NULL
                                          AND wrapped_data_key IS NOT NULL AND sample_input IS NULL AND sample_output IS NULL))
        );
        COMMENT ON TABLE coding_test_cases IS 'Owner: coding | RLS: TN | Retention: R-CONTENT | PII: P0 (P4 for keys)';

        CREATE TABLE code_submissions (
          id                  uuid PRIMARY KEY,
          user_id             uuid        NOT NULL REFERENCES users(id),
          organization_id     uuid        NULL REFERENCES organizations(id),
          coding_problem_id   uuid        NOT NULL REFERENCES coding_problems(id),
          problem_version     int         NOT NULL,
          language_key        text        NOT NULL REFERENCES judge_languages(language_key),
          mode                text        NOT NULL CHECK (mode IN ('run','submit')),
          attempt_id          uuid        NULL,
          practice_session_id uuid        NULL,
          source_code         text        NOT NULL CHECK (octet_length(source_code) <= 65536),
          custom_input        text        NULL CHECK (custom_input IS NULL OR octet_length(custom_input) <= 65536),
          status              text        NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','running','completed','judge_error','judge_timeout','rejected')),
          verdict             text        NULL CHECK (verdict IN ('AC','WA','TLE','MLE','RE','CE','PARTIAL','IE')),
          score               numeric(7,2) NULL,
          max_score           numeric(7,2) NULL,
          passed_cases        smallint    NULL,
          total_cases         smallint    NULL,
          max_time_ms         int         NULL,
          max_memory_kb       int         NULL,
          compile_output      text        NULL CHECK (compile_output IS NULL OR octet_length(compile_output) <= 16384),
          judge_provider      text        NOT NULL CHECK (judge_provider IN ('judge0_cloud','judge0_selfhosted','fake')),
          queue_name          text        NOT NULL CHECK (queue_name IN ('judge_assessment','judge_submit','judge_run')),
          idempotency_key     text        NOT NULL,
          normalized_sha256   bytea       NULL CHECK (normalized_sha256 IS NULL OR octet_length(normalized_sha256) = 32),
          similarity_flag     boolean     NOT NULL DEFAULT false,
          retry_count         smallint    NOT NULL DEFAULT 0,
          notice              text        NULL,
          queued_at           timestamptz NOT NULL DEFAULT now(),
          started_at          timestamptz NULL,
          completed_at        timestamptz NULL,
          UNIQUE (user_id, idempotency_key),
          CONSTRAINT ck_cs_custom_run CHECK (mode = 'run' OR custom_input IS NULL)
        );
        CREATE INDEX ix_cs_user_problem ON code_submissions (user_id, coding_problem_id, queued_at DESC);
        CREATE INDEX ix_cs_attempt ON code_submissions (attempt_id) WHERE attempt_id IS NOT NULL;
        CREATE INDEX ix_cs_pending ON code_submissions (queued_at) WHERE status IN ('queued','running');
        CREATE INDEX ix_cs_similarity ON code_submissions (coding_problem_id, normalized_sha256) WHERE mode = 'submit';
        COMMENT ON TABLE code_submissions IS 'Owner: coding | RLS: U | Retention: R-LEARN (practice runs purged after 90 days) | PII: P1';

        CREATE TABLE submission_results (
          id                  uuid PRIMARY KEY,
          code_submission_id  uuid        NOT NULL REFERENCES code_submissions(id) ON DELETE CASCADE,
          user_id             uuid        NOT NULL,
          organization_id     uuid        NULL,
          test_case_id        uuid        NULL REFERENCES coding_test_cases(id),
          ordinal             smallint    NOT NULL,
          is_hidden           boolean     NOT NULL,
          verdict             text        NOT NULL CHECK (verdict IN ('AC','WA','TLE','MLE','RE','CE','IE','SKIPPED')),
          time_ms             int         NULL,
          memory_kb           int         NULL,
          exit_code           smallint    NULL,
          stdout_excerpt      text        NULL CHECK (stdout_excerpt IS NULL OR octet_length(stdout_excerpt) <= 4096),
          judge_token         text        NULL,
          weight_awarded      numeric(6,2) NOT NULL DEFAULT 0,
          UNIQUE (code_submission_id, ordinal),
          CONSTRAINT ck_sr_hidden_output CHECK (NOT is_hidden OR stdout_excerpt IS NULL)
        );
        COMMENT ON TABLE submission_results IS 'Owner: coding | RLS: U | Retention: as code_submissions | PII: P1';
        """
    )
    # Reference data: languages are read by everyone, written only by migrations/seeds.
    op.execute("GRANT SELECT ON judge_languages TO td_app, td_readonly")
    op.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON judge_languages FROM td_app")
    for t in (*TENANT_TABLES, *USER_TABLES):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO td_app")
        op.execute(f"GRANT SELECT ON {t} TO td_readonly")
    # Results are immutable once written by the judge worker.
    op.execute("REVOKE UPDATE ON submission_results FROM td_app")
    for t in TENANT_TABLES:
        enable_rls(t, "TN")
    for t in USER_TABLES:
        enable_rls(t, "U")
    add_updated_at_trigger("coding_problems")
    add_updated_at_trigger("judge_languages")
    # Judge0 CE language ids (configurable; verify against the provider's /languages).
    op.execute(
        r"""
        INSERT INTO judge_languages (id, language_key, display_name, version_label, provider_language_id,
                                     time_multiplier, memory_extra_kb, max_processes, starter_template) VALUES
          ('0193f000-0000-7000-8000-000000000001', 'c', 'C', 'GCC 9.2.0', 50, 1.0, 0, 64,
           E'#include <stdio.h>\n\nint main(void) {\n    return 0;\n}\n'),
          ('0193f000-0000-7000-8000-000000000002', 'cpp17', 'C++17', 'GCC 9.2.0', 54, 1.0, 0, 64,
           E'#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    return 0;\n}\n'),
          ('0193f000-0000-7000-8000-000000000003', 'java17', 'Java', 'OpenJDK', 62, 2.0, 65536, 128,
           E'import java.util.*;\n\npublic class Main {\n    public static void main(String[] args) {\n    }\n}\n'),
          ('0193f000-0000-7000-8000-000000000004', 'python3', 'Python 3', '3.8', 71, 2.5, 0, 64,
           E'import sys\n\ndef main():\n    data = sys.stdin.read().split()\n\nmain()\n')
        """
    )


def downgrade() -> None:
    for t in (
        "submission_results",
        "code_submissions",
        "coding_test_cases",
        "coding_test_case_blobs",
        "coding_problems",
        "judge_languages",
    ):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
