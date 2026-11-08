"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Conventions (docs/implementation-conventions.md §4):
* revision id ``<module>_<NNNN>``; first module migration: down_revision=None,
  branch_labels=("<module>",), depends_on=("core_base",)
* every table with organization_id/user_id: RLS + FORCE in the same migration
  (``app.core.migration_helpers.enable_rls``)
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | Sequence[str] | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
