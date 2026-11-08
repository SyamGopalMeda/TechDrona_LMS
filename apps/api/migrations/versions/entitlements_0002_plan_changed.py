"""entitlements: ``plan_changed`` history event (COM-14 subscription plan change moves the
subscription entitlement to the new plan's product in place; ``ux_ent_sub`` keeps one
entitlement per subscription).

Revision ID: entitlements_0002
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "entitlements_0002"
down_revision: str | Sequence[str] | None = "entitlements_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "'granted','extended','entered_grace','restored','suspended',"
    "'expired','revoked','quota_consumed','quota_credited','seat_reassigned','fp_extension'"
)


def upgrade() -> None:
    op.execute("ALTER TABLE entitlement_events DROP CONSTRAINT IF EXISTS entitlement_events_event_type_check")
    op.execute(
        "ALTER TABLE entitlement_events ADD CONSTRAINT entitlement_events_event_type_check "
        f"CHECK (event_type IN ({_OLD},'plan_changed'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE entitlement_events DROP CONSTRAINT IF EXISTS entitlement_events_event_type_check")
    op.execute(
        "ALTER TABLE entitlement_events ADD CONSTRAINT entitlement_events_event_type_check "
        f"CHECK (event_type IN ({_OLD}))"
    )
