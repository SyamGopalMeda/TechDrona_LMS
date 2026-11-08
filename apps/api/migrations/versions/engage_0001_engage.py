"""engage: live activities (quiz, poll, word cloud, survey), runs, participants, responses

Revision ID: engage_0001
Revises:
Create Date: 2026-11-06

New module (docs/wiseman-reference/build/engage.md).

* ``engage_activities`` — the authored activity (settings + type), owned by an organization
  (optionally a batch) or the platform (``organization_id`` NULL). RLS TN.
* ``engage_questions`` — the activity's questions; choice options with correct flags live in
  ``options`` (never sent to participants before reveal; enforced by the API). RLS TN.
* ``engage_runs`` — each launch / rerun; frozen ``settings`` + ``questions`` snapshot, join code,
  status ``scheduled|open|closed|finalised``, presenter state. RLS TN (participants of a public
  run from another organization read it through the API under a system context).
* ``engage_participants`` / ``engage_responses`` — one participant row per (run, user), one
  response per (participant, question). ``answered_at`` is the server clock
  (``clock_timestamp()``) used for fastest-first ordering. RLS U.

RBAC (data step, reference data): permission ``engage.activity.manage`` granted to
``college_coordinator`` (O), ``trainer`` (B), ``content_manager`` (P) and ``super_admin`` (P).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "engage_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("engage",)
depends_on: str | Sequence[str] | None = ("core_base", "identity_0001", "orgs_0001", "rbac_0003")

PERMISSIONS: tuple[tuple[str, str], ...] = (
    (
        "engage.activity.manage",
        "Create, run and review live activities (quizzes, polls, word clouds, surveys)",
    ),
)
GRANTS: tuple[tuple[str, str], ...] = (
    ("college_coordinator", "engage.activity.manage"),
    ("trainer", "engage.activity.manage"),
    ("content_manager", "engage.activity.manage"),
    ("super_admin", "engage.activity.manage"),
)
# Same deterministic id scheme as app.seeds.rbac_seed.permission_id (UUIDv5 namespace).
_NS = uuid.UUID("6f1c2a9e-5d1b-4f7a-9c1e-2b7d3e4f5a60")

TABLES = ("engage_activities", "engage_questions", "engage_runs", "engage_participants", "engage_responses")


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE engage_activities (
          id                 uuid PRIMARY KEY,
          organization_id    uuid        NULL REFERENCES organizations(id),
          batch_id           uuid        NULL REFERENCES batches(id),
          owner_id           uuid        NOT NULL REFERENCES users(id),
          activity_type      text        NOT NULL CHECK (activity_type IN ('quiz','poll','word_cloud','survey')),
          title              text        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
          description        text        NULL CHECK (description IS NULL OR char_length(description) <= 500),
          run_mode           text        NOT NULL DEFAULT 'instant' CHECK (run_mode IN ('instant','scheduled')),
          audience           text        NOT NULL DEFAULT 'members' CHECK (audience IN ('members','public')),
          identity_mode      text        NOT NULL DEFAULT 'named' CHECK (identity_mode IN ('named','anonymous')),
          results_mode       text        NOT NULL DEFAULT 'live' CHECK (results_mode IN ('live','on_publish')),
          pacing             text        NOT NULL DEFAULT 'all_at_once' CHECK (pacing IN ('all_at_once','one_by_one')),
          winner_rule        text        NULL CHECK (winner_rule IS NULL OR winner_rule IN ('fastest_first','all_correct')),
          participant_limit  int         NULL CHECK (participant_limit IS NULL OR participant_limit BETWEEN 1 AND 10000),
          opens_at           timestamptz NULL,
          closes_at          timestamptz NULL,
          deleted_at         timestamptz NULL,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_ea_quiz_rule CHECK ((activity_type = 'quiz') = (winner_rule IS NOT NULL)),
          CONSTRAINT ck_ea_window CHECK (opens_at IS NULL OR closes_at IS NULL OR closes_at > opens_at)
        );
        CREATE INDEX ix_ea_org ON engage_activities (organization_id, created_at DESC) WHERE deleted_at IS NULL;
        CREATE INDEX ix_ea_owner ON engage_activities (owner_id, created_at DESC) WHERE deleted_at IS NULL;
        COMMENT ON TABLE engage_activities IS 'Owner: engage | RLS: TN | Retention: R-LEARN | PII: P0';

        CREATE TABLE engage_questions (
          id                  uuid PRIMARY KEY,
          activity_id         uuid        NOT NULL REFERENCES engage_activities(id) ON DELETE CASCADE,
          organization_id     uuid        NULL REFERENCES organizations(id),
          position            smallint    NOT NULL CHECK (position >= 0),
          kind                text        NOT NULL CHECK (kind IN ('single_choice','multi_choice','word','text','rating')),
          prompt              text        NOT NULL CHECK (char_length(prompt) BETWEEN 1 AND 2000),
          options             jsonb       NOT NULL DEFAULT '[]',
          max_words           smallint    NULL CHECK (max_words IS NULL OR max_words BETWEEN 1 AND 5),
          source_question_id  uuid        NULL,
          source_version_id   uuid        NULL,
          created_at          timestamptz NOT NULL DEFAULT now(),
          updated_at          timestamptz NOT NULL DEFAULT now(),
          UNIQUE (activity_id, position)
        );
        COMMENT ON TABLE engage_questions IS 'Owner: engage | RLS: TN | Retention: R-LEARN | PII: P0';

        CREATE TABLE engage_runs (
          id                 uuid PRIMARY KEY,
          activity_id        uuid        NOT NULL REFERENCES engage_activities(id) ON DELETE CASCADE,
          organization_id    uuid        NULL REFERENCES organizations(id),
          run_no             int         NOT NULL CHECK (run_no >= 1),
          join_code          text        NOT NULL UNIQUE CHECK (join_code ~ '^[A-Z2-9]{8}$'),
          status             text        NOT NULL DEFAULT 'scheduled' CHECK (status IN ('scheduled','open','closed','finalised')),
          settings           jsonb       NOT NULL,
          questions          jsonb       NOT NULL,
          current_position   smallint    NOT NULL DEFAULT 0 CHECK (current_position >= 0),
          revealed_positions smallint[]  NOT NULL DEFAULT '{}',
          results_published  boolean     NOT NULL DEFAULT false,
          state_version      int         NOT NULL DEFAULT 1,
          opens_at           timestamptz NULL,
          closes_at          timestamptz NULL,
          opened_at          timestamptz NULL,
          closed_at          timestamptz NULL,
          finalised_at       timestamptz NULL,
          created_by         uuid        NOT NULL REFERENCES users(id),
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          UNIQUE (activity_id, run_no)
        );
        CREATE INDEX ix_er_activity ON engage_runs (activity_id, run_no DESC);
        CREATE INDEX ix_er_due ON engage_runs (opens_at) WHERE status = 'scheduled';
        COMMENT ON TABLE engage_runs IS 'Owner: engage | RLS: TN (+ public participants via API) | Retention: R-LEARN | PII: P0';

        CREATE TABLE engage_participants (
          id               uuid PRIMARY KEY,
          run_id           uuid        NOT NULL REFERENCES engage_runs(id) ON DELETE CASCADE,
          organization_id  uuid        NULL REFERENCES organizations(id),
          user_id          uuid        NOT NULL REFERENCES users(id),
          display_name     text        NULL CHECK (display_name IS NULL OR char_length(display_name) <= 200),
          seq              int         NOT NULL CHECK (seq >= 1),
          joined_at        timestamptz NOT NULL DEFAULT now(),
          UNIQUE (run_id, user_id),
          UNIQUE (run_id, seq)
        );
        CREATE INDEX ix_ep_user ON engage_participants (user_id);
        COMMENT ON TABLE engage_participants IS 'Owner: engage | RLS: U | Retention: R-LEARN | PII: P1';

        CREATE TABLE engage_responses (
          id               uuid PRIMARY KEY,
          run_id           uuid        NOT NULL REFERENCES engage_runs(id) ON DELETE CASCADE,
          participant_id   uuid        NOT NULL REFERENCES engage_participants(id) ON DELETE CASCADE,
          organization_id  uuid        NULL REFERENCES organizations(id),
          user_id          uuid        NOT NULL REFERENCES users(id),
          question_id      uuid        NOT NULL,
          answer           jsonb       NOT NULL,
          terms            text[]      NOT NULL DEFAULT '{}',
          filtered         boolean     NOT NULL DEFAULT false,
          is_correct       boolean     NULL,
          answered_at      timestamptz NOT NULL DEFAULT clock_timestamp(),
          UNIQUE (participant_id, question_id)
        );
        CREATE INDEX ix_eresp_run_q ON engage_responses (run_id, question_id, answered_at);
        CREATE INDEX ix_eresp_user ON engage_responses (user_id);
        COMMENT ON TABLE engage_responses IS 'Owner: engage | RLS: U | Retention: R-LEARN | PII: P1';
        """
    )
    enable_rls("engage_activities", "TN")
    enable_rls("engage_questions", "TN")
    enable_rls("engage_runs", "TN")
    enable_rls("engage_participants", "U")
    enable_rls("engage_responses", "U")
    for t in ("engage_activities", "engage_questions", "engage_runs"):
        add_updated_at_trigger(t)

    conn = op.get_bind()
    for key, desc in PERMISSIONS:
        conn.execute(
            sa.text(
                "INSERT INTO permissions (id, permission_key, module, description, is_sensitive) "
                "VALUES (:id, :k, 'engage', :d, false) ON CONFLICT (permission_key) DO UPDATE SET "
                "module = EXCLUDED.module, description = EXCLUDED.description"
            ),
            {"id": uuid.uuid5(_NS, f"permission:{key}"), "k": key, "d": desc},
        )
    for role, perm in GRANTS:
        conn.execute(
            sa.text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r, permissions p "
                "WHERE r.role_key = :r AND p.permission_key = :p ON CONFLICT DO NOTHING"
            ),
            {"r": role, "p": perm},
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE permission_key LIKE 'engage.%')"
    )
    op.execute("DELETE FROM permissions WHERE permission_key LIKE 'engage.%'")
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
