"""orgs: batch delivery (course links, plan, classes, attendance) moved from the website

Revision ID: orgs_0005
Revises: orgs_0004
Create Date: 2026-11-11

The website back office (``web_courses`` batch plans, its class register and attendance) moves
into the LMS by extending batches; there is still one "course" concept per system:

* ``batches.course_id`` (nullable, soft reference into the catalog like ``enrolments.course_id``
  since ``learning_0004``: catalog rows may live in Firestore) and ``batches.website_course_slug``
  (the website catalogue page, ``catalog.json`` / ``web_course_public``).
* ``batch_plans`` (RLS ``T``): one row per batch, ``plan`` JSONB validated by
  ``app.modules.orgs.course_plan.PlanBody`` (hours, working days, holidays, weeks, activities),
  ``min_attendance_percent`` (certificate gate, NULL = off) and ``source_ref``
  (``web_courses/<doc id>``, unique: the website import is idempotent).
* ``class_sessions`` (RLS ``T``): one class per batch and date (``uq_class_sessions_batch_date``).
* ``class_attendance`` (RLS ``US``, user-owned table after ``orgs_0004``): one mark per class and
  learner (``uq_class_attendance_session_user``), ``P``/``L``/``A``.
* Permission ``batch.class.manage`` (Trainer at batch scope, Admin at platform scope): schedule
  classes and mark attendance. Reading uses ``org.member.read`` and editing the plan
  ``batch.update`` (Admin), like the other batch routes.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "orgs_0005"
down_revision: str | Sequence[str] | None = "orgs_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERM = "batch.class.manage"
PERM_DESC = "Schedule classes and mark attendance in a batch"
GRANTEES = ("trainer", "super_admin")
TABLES = ("batch_plans", "class_sessions", "class_attendance")


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE batches
          ADD COLUMN course_id uuid NULL,
          ADD COLUMN website_course_slug text NULL
            CONSTRAINT ck_batches_site_slug CHECK (website_course_slug IS NULL OR website_course_slug ~ '^[a-z0-9][a-z0-9-]{0,79}$');
        CREATE INDEX ix_batches_course ON batches (course_id) WHERE course_id IS NOT NULL;
        CREATE INDEX ix_batches_site_slug ON batches (website_course_slug) WHERE website_course_slug IS NOT NULL;

        CREATE TABLE batch_plans (
          batch_id               uuid PRIMARY KEY REFERENCES batches(id) ON DELETE CASCADE,
          organization_id        uuid        NOT NULL REFERENCES organizations(id),
          plan                   jsonb       NOT NULL DEFAULT '{}'::jsonb
                                   CHECK (jsonb_typeof(plan) = 'object' AND pg_column_size(plan) <= 262144),
          min_attendance_percent smallint    NULL CHECK (min_attendance_percent BETWEEN 1 AND 100),
          source_ref             text        NULL CHECK (source_ref IS NULL OR char_length(source_ref) <= 200),
          updated_by             uuid        NULL REFERENCES users(id),
          created_at             timestamptz NOT NULL DEFAULT now(),
          updated_at             timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_batch_plans_source_ref UNIQUE (source_ref)
        );
        COMMENT ON TABLE batch_plans IS 'Owner: orgs | RLS: T | Retention: R-ORG | PII: P0';

        CREATE TABLE class_sessions (
          id               uuid PRIMARY KEY,
          batch_id         uuid        NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
          organization_id  uuid        NOT NULL REFERENCES organizations(id),
          session_date     date        NOT NULL,
          starts_at        time        NULL,
          duration_minutes smallint    NULL CHECK (duration_minutes BETWEEN 1 AND 720),
          topic            text        NOT NULL DEFAULT '' CHECK (char_length(topic) <= 200),
          meet_url         text        NULL CHECK (meet_url IS NULL OR (meet_url ~* '^https://\S+$' AND char_length(meet_url) <= 500)),
          recording_url    text        NULL CHECK (recording_url IS NULL OR (recording_url ~* '^https://\S+$' AND char_length(recording_url) <= 500)),
          notes            text        NULL CHECK (notes IS NULL OR char_length(notes) <= 4000),
          cancelled        boolean     NOT NULL DEFAULT false,
          created_by       uuid        NOT NULL REFERENCES users(id),
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_class_sessions_batch_date UNIQUE (batch_id, session_date)
        );
        CREATE INDEX ix_cs_date ON class_sessions (session_date);
        COMMENT ON TABLE class_sessions IS 'Owner: orgs | RLS: T | Retention: R-ORG | PII: P0';

        CREATE TABLE class_attendance (
          id               uuid PRIMARY KEY,
          session_id       uuid        NOT NULL REFERENCES class_sessions(id) ON DELETE CASCADE,
          batch_id         uuid        NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
          organization_id  uuid        NOT NULL REFERENCES organizations(id),
          user_id          uuid        NOT NULL REFERENCES users(id),
          status           text        NOT NULL CHECK (status IN ('P','L','A')),
          marked_by        uuid        NOT NULL REFERENCES users(id),
          marked_at        timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_class_attendance_session_user UNIQUE (session_id, user_id)
        );
        CREATE INDEX ix_ca_user_batch ON class_attendance (user_id, batch_id);
        CREATE INDEX ix_ca_batch ON class_attendance (batch_id);
        COMMENT ON TABLE class_attendance IS 'Owner: orgs | RLS: US | Retention: R-ORG | PII: P1';
        """
    )
    for t in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {t} TO td_app")
        op.execute(f"GRANT SELECT ON {t} TO td_readonly")
    enable_rls("batch_plans", "T")
    enable_rls("class_sessions", "T")
    enable_rls("class_attendance", "US")
    for t in TABLES:
        add_updated_at_trigger(t)

    # RBAC reference rows (td_app cannot write them; migrations run as owner). Same pattern as
    # paths_0001; ``app.seeds.rbac_seed.sync`` produces the same rows from the catalogue.
    from sqlalchemy import text

    from app.seeds.rbac_seed import permission_id

    conn = op.get_bind()
    conn.execute(
        text(
            "INSERT INTO permissions (id, permission_key, module, description, is_sensitive) "
            "VALUES (:id, :k, 'orgs', :d, false) ON CONFLICT (permission_key) DO NOTHING"
        ),
        {"id": permission_id(PERM), "k": PERM, "d": PERM_DESC},
    )
    for role in GRANTEES:
        conn.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT r.id, p.id FROM roles r, permissions p "
                "WHERE r.role_key = :r AND p.permission_key = :k ON CONFLICT DO NOTHING"
            ),
            {"r": role, "k": PERM},
        )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        f"(SELECT id FROM permissions WHERE permission_key = '{PERM}')"
    )
    op.execute(f"DELETE FROM permissions WHERE permission_key = '{PERM}'")
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t}")
    op.execute("DROP INDEX IF EXISTS ix_batches_site_slug")
    op.execute("DROP INDEX IF EXISTS ix_batches_course")
    op.execute(
        "ALTER TABLE batches DROP COLUMN IF EXISTS website_course_slug, DROP COLUMN IF EXISTS course_id"
    )
