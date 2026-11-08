"""paths: guided learning paths, steps, versions, articles, allocations, step progress

Revision ID: paths_0001
Revises:
Create Date: 2026-11-06

New module ``paths`` (feature build from the reference demo, docs/wiseman-reference/build/paths.md).
Organization-owned guided learning paths (distinct from placement ``company_paths`` and from the
catalog course curriculum):

* ``learning_paths`` / ``learning_path_steps``: the editable draft (steps form a two-level tree:
  ``super_step`` rows group child steps through ``parent_key``).
* ``learning_path_versions`` / ``learning_path_version_steps``: immutable snapshot written on every
  publish; allocations pin one version. ``step_key`` is stable across versions (progress key).
* ``path_articles``: authored markdown articles (sanitised server-side) with publish & share
  audience (org / chosen batches / chosen people).
* ``path_allocations``: a published version allocated to a batch or to chosen learners with flow
  (lenient|strict), sequential flag, start date and study pace (server-computed finish date).
* ``path_step_progress``: per-learner step state and credits.

RLS: every table T (organization) except ``path_step_progress`` U (learner's own rows + org staff).
RBAC (data step, reference rows owned by this module): ``path.manage`` and ``path.allocate`` for
college_coordinator (O), trainer (B), content_manager (P), mirroring ``test.create``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "paths_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("paths",)
depends_on: str | Sequence[str] | None = (
    "core_base",
    "identity_0001",
    "orgs_0001",
    "catalog_0001",
    "learning_0001",
    "assessments_0001",
    "rbac_0002",
)

TABLES = (
    "learning_paths",
    "path_articles",
    "learning_path_steps",
    "learning_path_versions",
    "learning_path_version_steps",
    "path_allocations",
    "path_step_progress",
)

PERMS = {
    "path.manage": "Create, edit, publish and archive learning paths and path articles",
    "path.allocate": "Allocate learning paths to batches or learners and view their progress",
}
GRANTEES = ("college_coordinator", "trainer", "content_manager")

_STEP_COLS = r"""
          step_key        uuid        NOT NULL,
          parent_key      uuid        NULL,
          position        int         NOT NULL CHECK (position >= 0),
          step_type       text        NOT NULL CHECK (step_type IN ('reading','video','article','assignment','assessment','super_step')),
          title           text        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 300),
          description_md  text        NOT NULL DEFAULT '' CHECK (char_length(description_md) <= 5000),
          est_hours       numeric(6,2) NOT NULL DEFAULT 0 CHECK (est_hours >= 0 AND est_hours <= 1000),
          credits         int         NOT NULL DEFAULT 0 CHECK (credits >= 0 AND credits <= 10000),
          url             text        NULL CHECK (url IS NULL OR (url LIKE 'https://%' AND char_length(url) <= 2048)),
          lesson_id       uuid        NULL REFERENCES lessons(id),
          assignment_id   uuid        NULL REFERENCES assignments(id),
          test_id         uuid        NULL REFERENCES tests(id),
          article_id      uuid        NULL REFERENCES path_articles(id),
"""


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE learning_paths (
          id                 uuid PRIMARY KEY,
          organization_id    uuid        NOT NULL REFERENCES organizations(id),
          title              text        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
          description_md     text        NOT NULL DEFAULT '' CHECK (char_length(description_md) <= 5000),
          level              text        NOT NULL DEFAULT 'beginner' CHECK (level IN ('beginner','intermediate','advanced')),
          status             text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','archived')),
          source             text        NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','ai')),
          version_no         int         NOT NULL DEFAULT 0 CHECK (version_no >= 0),
          current_version_id uuid        NULL,
          has_unpublished_changes boolean NOT NULL DEFAULT true,
          created_by         uuid        NOT NULL REFERENCES users(id),
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_lp_org ON learning_paths (organization_id, updated_at DESC) WHERE status <> 'archived';
        COMMENT ON TABLE learning_paths IS 'Owner: paths | RLS: T | Retention: R-CONTENT | PII: P0';

        CREATE TABLE path_articles (
          id                 uuid PRIMARY KEY,
          organization_id    uuid        NOT NULL REFERENCES organizations(id),
          title              text        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 200),
          subtitle           text        NOT NULL DEFAULT '' CHECK (char_length(subtitle) <= 500),
          level              text        NOT NULL DEFAULT 'beginner' CHECK (level IN ('beginner','intermediate','advanced')),
          est_minutes        int         NOT NULL DEFAULT 0 CHECK (est_minutes BETWEEN 0 AND 6000),
          body_md            text        NOT NULL DEFAULT '' CHECK (char_length(body_md) <= 200000),
          toc                jsonb       NOT NULL DEFAULT '[]',
          status             text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published')),
          audience           text        NULL CHECK (audience IS NULL OR audience IN ('org','batches','people')),
          batch_ids          uuid[]      NOT NULL DEFAULT '{}',
          user_ids           uuid[]      NOT NULL DEFAULT '{}',
          published_at       timestamptz NULL,
          deleted_at         timestamptz NULL,
          created_by         uuid        NOT NULL REFERENCES users(id),
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_pa_published CHECK ((status = 'published') = (audience IS NOT NULL))
        );
        CREATE INDEX ix_pa_org ON path_articles (organization_id, updated_at DESC) WHERE deleted_at IS NULL;
        COMMENT ON TABLE path_articles IS 'Owner: paths | RLS: T (+ audience checks in API) | Retention: R-CONTENT | PII: P0';
        """
    )
    op.execute(
        r"""
        CREATE TABLE learning_path_steps (
          id              uuid PRIMARY KEY,
          path_id         uuid        NOT NULL REFERENCES learning_paths(id) ON DELETE CASCADE,
          organization_id uuid        NOT NULL REFERENCES organizations(id),
        """
        + _STEP_COLS
        + r"""
          created_at      timestamptz NOT NULL DEFAULT now(),
          UNIQUE (path_id, step_key)
        );
        CREATE INDEX ix_lps_path ON learning_path_steps (path_id, parent_key, position);
        COMMENT ON TABLE learning_path_steps IS 'Owner: paths | RLS: T | Retention: R-CONTENT | PII: P0';

        CREATE TABLE learning_path_versions (
          id              uuid PRIMARY KEY,
          path_id         uuid        NOT NULL REFERENCES learning_paths(id),
          organization_id uuid        NOT NULL REFERENCES organizations(id),
          version_no      int         NOT NULL CHECK (version_no >= 1),
          title           text        NOT NULL,
          description_md  text        NOT NULL DEFAULT '',
          level           text        NOT NULL,
          total_hours     numeric(8,2) NOT NULL,
          total_credits   int         NOT NULL,
          published_by    uuid        NOT NULL REFERENCES users(id),
          published_at    timestamptz NOT NULL DEFAULT now(),
          UNIQUE (path_id, version_no)
        );
        COMMENT ON TABLE learning_path_versions IS 'Owner: paths | RLS: T | Retention: R-CONTENT | PII: P0';
        ALTER TABLE learning_paths ADD CONSTRAINT fk_lp_current_version
          FOREIGN KEY (current_version_id) REFERENCES learning_path_versions(id);

        CREATE TABLE learning_path_version_steps (
          id              uuid PRIMARY KEY,
          path_version_id uuid        NOT NULL REFERENCES learning_path_versions(id),
          organization_id uuid        NOT NULL REFERENCES organizations(id),
        """
        + _STEP_COLS
        + r"""
          UNIQUE (path_version_id, step_key)
        );
        CREATE INDEX ix_lpvs_version ON learning_path_version_steps (path_version_id);
        CREATE INDEX ix_lpvs_assignment ON learning_path_version_steps (assignment_id) WHERE assignment_id IS NOT NULL;
        CREATE INDEX ix_lpvs_test ON learning_path_version_steps (test_id) WHERE test_id IS NOT NULL;
        CREATE INDEX ix_lpvs_article ON learning_path_version_steps (article_id) WHERE article_id IS NOT NULL;
        COMMENT ON TABLE learning_path_version_steps IS 'Owner: paths | RLS: T | Retention: R-CONTENT | PII: P0';

        CREATE TABLE path_allocations (
          id              uuid PRIMARY KEY,
          organization_id uuid        NOT NULL REFERENCES organizations(id),
          path_id         uuid        NOT NULL REFERENCES learning_paths(id),
          path_version_id uuid        NOT NULL REFERENCES learning_path_versions(id),
          target_type     text        NOT NULL CHECK (target_type IN ('batch','users')),
          batch_id        uuid        NULL REFERENCES batches(id),
          user_ids        uuid[]      NOT NULL DEFAULT '{}',
          flow            text        NOT NULL CHECK (flow IN ('lenient','strict')),
          sequential      boolean     NOT NULL DEFAULT false,
          start_date      date        NOT NULL,
          pace            jsonb       NOT NULL,
          weekly_hours    numeric(6,2) NOT NULL CHECK (weekly_hours > 0),
          total_hours     numeric(8,2) NOT NULL,
          finish_date     date        NOT NULL,
          status          text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','revoked')),
          created_by      uuid        NOT NULL REFERENCES users(id),
          revoked_at      timestamptz NULL,
          created_at      timestamptz NOT NULL DEFAULT now(),
          updated_at      timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_pal_target CHECK ((target_type = 'batch') = (batch_id IS NOT NULL)
                                          AND (target_type = 'batch' OR cardinality(user_ids) > 0))
        );
        CREATE INDEX ix_pal_path ON path_allocations (path_id, created_at DESC);
        CREATE INDEX ix_pal_batch ON path_allocations (batch_id) WHERE status = 'active' AND batch_id IS NOT NULL;
        CREATE INDEX ix_pal_users ON path_allocations USING gin (user_ids) WHERE status = 'active';
        CREATE INDEX ix_pal_version ON path_allocations (path_version_id) WHERE status = 'active';
        COMMENT ON TABLE path_allocations IS 'Owner: paths | RLS: T | Retention: R-LEARN | PII: P1';

        CREATE TABLE path_step_progress (
          id              uuid PRIMARY KEY,
          allocation_id   uuid        NOT NULL REFERENCES path_allocations(id),
          organization_id uuid        NOT NULL REFERENCES organizations(id),
          user_id         uuid        NOT NULL REFERENCES users(id),
          step_key        uuid        NOT NULL,
          status          text        NOT NULL CHECK (status IN ('in_progress','completed')),
          opened_at       timestamptz NULL,
          completed_at    timestamptz NULL,
          credits_awarded int         NOT NULL DEFAULT 0 CHECK (credits_awarded >= 0),
          source          text        NULL CHECK (source IS NULL OR source IN ('learner','event')),
          evidence        jsonb       NOT NULL DEFAULT '{}',
          created_at      timestamptz NOT NULL DEFAULT now(),
          updated_at      timestamptz NOT NULL DEFAULT now(),
          UNIQUE (allocation_id, user_id, step_key),
          CONSTRAINT ck_psp_completed CHECK ((status = 'completed') = (completed_at IS NOT NULL))
        );
        CREATE INDEX ix_psp_user ON path_step_progress (user_id, allocation_id);
        COMMENT ON TABLE path_step_progress IS 'Owner: paths | RLS: U | Retention: R-LEARN | PII: P1';
        """
    )
    for t in TABLES:
        enable_rls(t, "U" if t == "path_step_progress" else "T")
    for t in ("learning_paths", "path_articles", "path_allocations", "path_step_progress"):
        add_updated_at_trigger(t)
    # Snapshots are immutable for the application role.
    op.execute(
        "REVOKE UPDATE, DELETE, TRUNCATE ON learning_path_versions, learning_path_version_steps FROM td_app"
    )

    # RBAC reference rows for this module (td_app cannot write them; migrations run as owner).
    from sqlalchemy import text

    from app.seeds.rbac_seed import permission_id

    conn = op.get_bind()
    for key, desc in PERMS.items():
        conn.execute(
            text(
                "INSERT INTO permissions (id, permission_key, module, description, is_sensitive) "
                "VALUES (:id, :k, 'paths', :d, false) ON CONFLICT (permission_key) DO NOTHING"
            ),
            {"id": permission_id(key), "k": key, "d": desc},
        )
        for role in GRANTEES:
            conn.execute(
                text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT r.id, p.id FROM roles r, permissions p "
                    "WHERE r.role_key = :r AND p.permission_key = :k ON CONFLICT DO NOTHING"
                ),
                {"r": role, "k": key},
            )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE permission_key IN ('path.manage','path.allocate'))"
    )
    op.execute("DELETE FROM permissions WHERE permission_key IN ('path.manage','path.allocate')")
    op.execute("ALTER TABLE learning_paths DROP CONSTRAINT IF EXISTS fk_lp_current_version")
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
