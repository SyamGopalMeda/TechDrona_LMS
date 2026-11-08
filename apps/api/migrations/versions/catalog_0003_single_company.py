"""catalog: single company — drop course visibility 'org_only'

Revision ID: catalog_0003
Revises: catalog_0002
Create Date: 2026-11-07

docs/single-company/REMOVAL-PLAN.md §1.2 (catalog), §1.3, §5 step 7, §6 WS4. ``org_only``
("visible to my college") is removed. Existing ``org_only`` courses become ``private``; company
courses (``organization_id`` = the company org) stay enrollable by the company's batch learners and
staff through ``learning.service.course_enrollable``. The visibility CHECK then allows only
``public``, ``unlisted`` and ``private``.

Data step runs as the table owner; FORCE RLS on ``courses`` is lifted for the statement and
restored in the same transaction.

Downgrade restores the wider CHECK, **not** the data: restore it from
``backups/techdrona-dev-before-college-removal-20261106.dump``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from sqlalchemy import text

revision: str = "catalog_0003"
down_revision: str | Sequence[str] | None = "catalog_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _forced() -> bool:
    return bool(
        op.get_bind()
        .execute(
            text(
                "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'courses' "
                "AND relnamespace = 'public'::regnamespace"
            )
        )
        .scalar()
    )


def upgrade() -> None:
    forced = _forced()
    if forced:
        op.execute("ALTER TABLE courses NO FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        UPDATE courses SET visibility = 'private', updated_at = now() WHERE visibility = 'org_only';
        ALTER TABLE courses DROP CONSTRAINT IF EXISTS courses_visibility_check;
        ALTER TABLE courses DROP CONSTRAINT IF EXISTS ck_courses_visibility;
        ALTER TABLE courses ADD CONSTRAINT ck_courses_visibility
          CHECK (visibility IN ('public','unlisted','private'));
        """
    )
    if forced:
        op.execute("ALTER TABLE courses FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Schema only: the remapped rows stay ``private`` (restore data from the backup dump)."""
    op.execute(
        """
        ALTER TABLE courses DROP CONSTRAINT IF EXISTS ck_courses_visibility;
        ALTER TABLE courses ADD CONSTRAINT courses_visibility_check
          CHECK (visibility IN ('public','unlisted','private','org_only'));
        """
    )
