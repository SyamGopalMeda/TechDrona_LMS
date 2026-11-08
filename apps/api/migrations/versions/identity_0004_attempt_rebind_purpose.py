"""identity: verification token purpose ``attempt_rebind`` (Stage 10 backlog A-10)

Revision ID: identity_0004
Revises: identity_0003
Create Date: 2026-11-03

Assessment attempt rebinding used to reuse ``step_up_otp``; a code minted for a test rebind
could then satisfy a general step-up (and vice versa). The dedicated purpose isolates them.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "identity_0004"
down_revision: str | Sequence[str] | None = "identity_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "'email_verify','phone_verify','login_otp','new_device_otp','step_up_otp','contact_change',"
    "'guardian_verify'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE verification_tokens DROP CONSTRAINT IF EXISTS verification_tokens_purpose_check")
    op.execute(
        "ALTER TABLE verification_tokens ADD CONSTRAINT verification_tokens_purpose_check "
        f"CHECK (purpose IN ({_OLD},'attempt_rebind'))"
    )


def downgrade() -> None:
    op.execute("DELETE FROM verification_tokens WHERE purpose = 'attempt_rebind'")
    op.execute("ALTER TABLE verification_tokens DROP CONSTRAINT IF EXISTS verification_tokens_purpose_check")
    op.execute(
        "ALTER TABLE verification_tokens ADD CONSTRAINT verification_tokens_purpose_check "
        f"CHECK (purpose IN ({_OLD}))"
    )
