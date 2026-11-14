"""learning: drop the foreign keys into the catalog tables (Firebase P2b)

Revision ID: learning_0004
Revises: learning_0003
Create Date: 2026-11-08

With ``TD_STORE_CATALOG=firestore`` courses and course versions are created in Firestore only,
so a Postgres foreign key from ``enrolments.course_id`` / ``enrolments.course_version_id``,
``assignments.course_id`` or ``certificates.course_id`` / ``certificates.course_version_id``
into ``courses`` / ``course_versions`` would refuse every enrolment, assignment and certificate
of such a course. The references become soft references (checked by the application through
``app.modules.catalog.api``, like the other cross-module ids in the plan §3). The columns and
their indexes stay. Downgrade re-adds the constraints (it fails if orphan ids exist then).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "learning_0004"
down_revision: str | Sequence[str] | None = "learning_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (table, column, referenced table)
FKS = (
    ("enrolments", "course_id", "courses"),
    ("enrolments", "course_version_id", "course_versions"),
    ("assignments", "course_id", "courses"),
    ("certificates", "course_id", "courses"),
    ("certificates", "course_version_id", "course_versions"),
)


def upgrade() -> None:
    # Constraint names are looked up (inline REFERENCES got PostgreSQL's generated names).
    for table, column, ref in FKS:
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
                   AND c.confrelid = '{ref}'::regclass
                   AND a.attname = '{column}'
              LOOP
                EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', r.conname);
              END LOOP;
            END $$;
            """
        )


def downgrade() -> None:
    for table, column, ref in FKS:
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {table}_{column}_fkey "
            f"FOREIGN KEY ({column}) REFERENCES {ref}(id)"
        )
