"""security: ``close_no_action`` case decision outcome

Revision ID: security_0004
Revises: security_0003
Create Date: 2026-11-11

A case opened by hand (support escalation, manual, integrity referral) with no restriction on the
account could not be finished: every outcome except ``convert_L4`` needs an active restriction
(found by the live admin audit, 2026-11-11). ``close_no_action`` closes such a case without
touching the account. The rationale stays mandatory; the student summary is optional (the
learner may never have known about the case), and the decision is audited like the others.

``case_decisions.outcome`` was declared with an inline CHECK, so its generated name is looked up
by definition and the check is recreated under a stable name.

Note: no ``depends_on`` (see docs/single-company/ws1.md §2).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "security_0004"
down_revision: str | Sequence[str] | None = "security_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "'lift_false_positive','lift_with_warning','lift_conditions','uphold','convert_L4','reduce_level'"
NEW = OLD + ",'close_no_action'"


def _drop_outcome_check() -> None:
    op.execute(
        """
        DO $$
        DECLARE c record;
        BEGIN
          FOR c IN SELECT conname FROM pg_constraint
                   WHERE conrelid = 'case_decisions'::regclass AND contype = 'c'
                     AND pg_get_constraintdef(oid) LIKE '%outcome%'
                     AND pg_get_constraintdef(oid) LIKE '%lift_false_positive%'
          LOOP
            EXECUTE format('ALTER TABLE case_decisions DROP CONSTRAINT %I', c.conname);
          END LOOP;
        END $$;
        """
    )


def upgrade() -> None:
    _drop_outcome_check()
    op.execute(f"ALTER TABLE case_decisions ADD CONSTRAINT ck_cd_outcome CHECK (outcome IN ({NEW}))")


def downgrade() -> None:
    op.execute("DELETE FROM case_decisions WHERE outcome = 'close_no_action'")
    _drop_outcome_check()
    op.execute(f"ALTER TABLE case_decisions ADD CONSTRAINT ck_cd_outcome CHECK (outcome IN ({OLD}))")
