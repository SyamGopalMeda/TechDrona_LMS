"""catalog: FR-CAT-001 lesson types ``pdf`` and ``practice_set``

Revision ID: catalog_0002
Revises: catalog_0001
Create Date: 2026-11-03

PRD FR-CAT-001 and API CAT-13 list PDF and embedded practice-set lessons, but the original
CHECK allowed only video/article/quiz/coding/assignment/live_link (webstaff request 8, fix
agent w2b). A ``pdf`` lesson carries its file as a ``lesson_assets`` row (asset_type ``pdf``,
MED-02 ``lesson_file``) and needs no reference; a ``practice_set`` lesson embeds a
``practice_set`` test and, like ``quiz``, needs ``test_id``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "catalog_0002"
down_revision: str | Sequence[str] | None = "catalog_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_TYPES = "'video','article','quiz','coding','assignment','live_link'"
_NEW_TYPES = "'video','article','pdf','practice_set','quiz','coding','assignment','live_link'"

_OLD_REF = """
    (lesson_type = 'quiz'       AND test_id IS NOT NULL) OR
    (lesson_type = 'coding'     AND coding_problem_id IS NOT NULL) OR
    (lesson_type = 'assignment' AND assignment_id IS NOT NULL) OR
    (lesson_type = 'live_link'  AND live_url IS NOT NULL) OR
    (lesson_type IN ('video','article'))"""
_NEW_REF = """
    (lesson_type IN ('quiz','practice_set') AND test_id IS NOT NULL) OR
    (lesson_type = 'coding'     AND coding_problem_id IS NOT NULL) OR
    (lesson_type = 'assignment' AND assignment_id IS NOT NULL) OR
    (lesson_type = 'live_link'  AND live_url IS NOT NULL) OR
    (lesson_type IN ('video','article','pdf'))"""


def _set(types: str, ref: str, valid: str = "") -> None:
    op.execute("ALTER TABLE lessons DROP CONSTRAINT IF EXISTS lessons_lesson_type_check")
    op.execute("ALTER TABLE lessons DROP CONSTRAINT IF EXISTS ck_lesson_ref")
    op.execute(
        f"ALTER TABLE lessons ADD CONSTRAINT lessons_lesson_type_check CHECK (lesson_type IN ({types})){valid}"
    )
    op.execute(f"ALTER TABLE lessons ADD CONSTRAINT ck_lesson_ref CHECK ({ref}){valid}")


def upgrade() -> None:
    _set(_NEW_TYPES, _NEW_REF)


def downgrade() -> None:
    # Rows of the new types may exist; keep them readable rather than failing the downgrade.
    _set(_OLD_TYPES, _OLD_REF, " NOT VALID")
