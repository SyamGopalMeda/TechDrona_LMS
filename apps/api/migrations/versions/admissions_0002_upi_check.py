"""admissions: fix the UPI ID CHECK constraints (PostgreSQL caps a regex bound at 255)

Revision ID: admissions_0002
Revises: admissions_0001
Create Date: 2026-11-11

``admissions_0001`` declared ``upi_id ~ '^[a-zA-Z0-9._-]{2,256}@...'`` on
``admission_pay_settings`` and ``admission_fee_plans``. PostgreSQL rejects a repetition bound above
255 (RE_DUP_MAX) at evaluation time with SQLSTATE 2201B, so saving ANY non-null UPI ID failed
(found by the live end-to-end test, 2026-11-11). Recreate both checks with ``{2,255}``; the API
keeps the same rule (``rules.UPI_ID_RE``).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "admissions_0002"
down_revision: str | Sequence[str] | None = "admissions_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UPI = r"'^[a-zA-Z0-9._-]{2,255}@[a-zA-Z][a-zA-Z0-9.-]{1,64}$'"
TABLES = ("admission_pay_settings", "admission_fee_plans")


def _drop_upi_checks(table: str) -> None:
    # the 0001 checks were declared inline, so their names are generated: find them by definition
    op.execute(
        f"""
        DO $$
        DECLARE c record;
        BEGIN
          FOR c IN SELECT conname FROM pg_constraint
                   WHERE conrelid = '{table}'::regclass AND contype = 'c'
                     AND pg_get_constraintdef(oid) LIKE '%upi_id%'
          LOOP
            EXECUTE format('ALTER TABLE {table} DROP CONSTRAINT %I', c.conname);
          END LOOP;
        END $$;
        """
    )


def upgrade() -> None:
    for t in TABLES:
        _drop_upi_checks(t)
        op.execute(f"ALTER TABLE {t} ADD CONSTRAINT {t}_upi_id_format CHECK (upi_id ~ {UPI})")


def downgrade() -> None:
    for t in TABLES:
        op.execute(f"ALTER TABLE {t} DROP CONSTRAINT IF EXISTS {t}_upi_id_format")
        op.execute(
            f"ALTER TABLE {t} ADD CONSTRAINT {t}_upi_id_check "
            r"CHECK (upi_id ~ '^[a-zA-Z0-9._-]{2,255}@[a-zA-Z][a-zA-Z0-9.-]{1,64}$')"
        )
