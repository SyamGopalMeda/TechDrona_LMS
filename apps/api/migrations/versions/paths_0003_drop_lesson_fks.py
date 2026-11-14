"""paths: drop the foreign keys from path steps into ``lessons`` (Firebase P2b)

Revision ID: paths_0003
Revises: paths_0002
Create Date: 2026-11-08

With ``TD_STORE_CATALOG=firestore`` lessons are created in Firestore only, so the Postgres
foreign keys ``learning_path_steps.lesson_id`` and ``learning_path_version_steps.lesson_id`` ->
``lessons(id)`` would refuse linking a path step to such a lesson. The link is already checked
by the application (``paths.service`` validates the id through ``catalog.api.get_lessons``).
The columns stay. Downgrade re-adds the constraints (it fails if orphan ids exist then).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "paths_0003"
down_revision: str | Sequence[str] | None = "paths_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("learning_path_steps", "learning_path_version_steps")


def upgrade() -> None:
    for table in TABLES:
        op.execute(
            f"""
            DO $$
            DECLARE r record;
            BEGIN
              FOR r IN
                SELECT c.conname
                  FROM pg_constraint c
                  JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
                 WHERE c.contype = 'f'
                   AND c.conrelid = '{table}'::regclass
                   AND c.confrelid = 'lessons'::regclass
                   AND a.attname = 'lesson_id'
              LOOP
                EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', r.conname);
              END LOOP;
            END $$;
            """
        )


def downgrade() -> None:
    for table in TABLES:
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_lesson_id_fkey "
            "FOREIGN KEY (lesson_id) REFERENCES lessons(id)"
        )
