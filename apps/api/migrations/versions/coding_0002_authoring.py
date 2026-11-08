"""coding: editor drafts, reference solutions, validation runs, hidden-case content tokens

Revision ID: coding_0002
Revises: coding_0001
Create Date: 2026-11-03

Tables added during implementation (proposed back to the schema owner, database-schema §10):

* ``coding_drafts`` (RLS O) — COD-04/05 autosaved editor code, one row per (user, problem,
  language); ``window_started_at``/``window_count`` carry the 20/min save limit.
* ``coding_reference_solutions`` (RLS TN) — author reference solutions run by COD-18.
* ``coding_problem_validations`` (RLS TN) — COD-18 results: per-case verdict/time/memory only
  (never input/expected/stdout); ``fingerprint`` = sha256 of the case set + limits + checker,
  so publish (COD-19) can require a passing validation of exactly the current definition.
* ``coding_testcase_content_tokens`` (RLS O) — COD-17 single-use, 5-minute download tokens
  (sha256 of the token only), bound to the requesting user; also the 30/h counter.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "coding_0002"
down_revision: str | Sequence[str] | None = "coding_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OWNER_TABLES = ("coding_drafts", "coding_testcase_content_tokens")
TENANT_TABLES = ("coding_reference_solutions", "coding_problem_validations")


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE coding_drafts (
          id                 uuid PRIMARY KEY,
          user_id            uuid        NOT NULL REFERENCES users(id),
          coding_problem_id  uuid        NOT NULL REFERENCES coding_problems(id) ON DELETE CASCADE,
          language_key       text        NOT NULL REFERENCES judge_languages(language_key),
          source_code        text        NOT NULL CHECK (octet_length(source_code) <= 65536),
          window_started_at  timestamptz NOT NULL DEFAULT now(),
          window_count       smallint    NOT NULL DEFAULT 1 CHECK (window_count >= 0),
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ux_cd_user_problem_lang UNIQUE (user_id, coding_problem_id, language_key)
        );
        COMMENT ON TABLE coding_drafts IS
          'Owner: coding | RLS: O | Retention: R-LEARN (drafts; purge 180 days after update) | PII: P1';

        CREATE TABLE coding_reference_solutions (
          id                 uuid PRIMARY KEY,
          coding_problem_id  uuid        NOT NULL REFERENCES coding_problems(id) ON DELETE CASCADE,
          organization_id    uuid        NULL REFERENCES organizations(id),
          language_key       text        NOT NULL REFERENCES judge_languages(language_key),
          source_code        text        NOT NULL CHECK (octet_length(source_code) <= 65536),
          updated_by         uuid        NOT NULL REFERENCES users(id),
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ux_crs_problem_lang UNIQUE (coding_problem_id, language_key)
        );
        COMMENT ON TABLE coding_reference_solutions IS
          'Owner: coding | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE coding_problem_validations (
          id                 uuid PRIMARY KEY,
          coding_problem_id  uuid        NOT NULL REFERENCES coding_problems(id) ON DELETE CASCADE,
          organization_id    uuid        NULL REFERENCES organizations(id),
          problem_version    int         NOT NULL,
          fingerprint        bytea       NOT NULL CHECK (octet_length(fingerprint) = 32),
          status             text        NOT NULL CHECK (status IN ('passed','failed','error')),
          results            jsonb       NOT NULL DEFAULT '[]'::jsonb,
          detail             text        NULL CHECK (detail IS NULL OR char_length(detail) <= 500),
          requested_by       uuid        NOT NULL REFERENCES users(id),
          created_at         timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_cpv_problem ON coding_problem_validations (coding_problem_id, created_at DESC);
        CREATE INDEX ix_cpv_requester ON coding_problem_validations (requested_by, created_at DESC);
        COMMENT ON TABLE coding_problem_validations IS
          'Owner: coding | RLS: TN | Retention: R-CONTENT | PII: P0 (verdicts only, never case content)';

        CREATE TABLE coding_testcase_content_tokens (
          id                 uuid PRIMARY KEY,
          token_hash         bytea       NOT NULL UNIQUE CHECK (octet_length(token_hash) = 32),
          request_id         uuid        NOT NULL,
          user_id            uuid        NOT NULL REFERENCES users(id),
          test_case_id       uuid        NOT NULL REFERENCES coding_test_cases(id) ON DELETE CASCADE,
          coding_problem_id  uuid        NOT NULL REFERENCES coding_problems(id) ON DELETE CASCADE,
          organization_id    uuid        NULL REFERENCES organizations(id),
          part               text        NOT NULL CHECK (part IN ('input','expected')),
          reason             text        NOT NULL CHECK (char_length(reason) BETWEEN 10 AND 500),
          expires_at         timestamptz NOT NULL,
          used_at            timestamptz NULL,
          created_at         timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_cttok_user ON coding_testcase_content_tokens (user_id, created_at DESC);
        COMMENT ON TABLE coding_testcase_content_tokens IS
          'Owner: coding | RLS: O | Retention: 30 days | PII: P1 (reason text)';
        """
    )
    for t in (*OWNER_TABLES, *TENANT_TABLES):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO td_app")
        op.execute(f"GRANT SELECT ON {t} TO td_readonly")
    # Validation records are immutable once written.
    op.execute("REVOKE UPDATE ON coding_problem_validations FROM td_app")
    for t in OWNER_TABLES:
        enable_rls(t, "O")
    for t in TENANT_TABLES:
        enable_rls(t, "TN")
    add_updated_at_trigger("coding_drafts")
    add_updated_at_trigger("coding_reference_solutions")


def downgrade() -> None:
    for t in (
        "coding_testcase_content_tokens",
        "coding_problem_validations",
        "coding_reference_solutions",
        "coding_drafts",
    ):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
