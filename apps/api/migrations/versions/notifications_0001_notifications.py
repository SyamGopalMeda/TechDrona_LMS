"""notifications: in-app inbox and delivery log

Revision ID: notifications_0001
Revises:
Create Date: 2026-11-03

database-schema §13 ``notifications`` (RLS O). Templates (NTF-07..09) and preferences
(NTF-04/05) are Planned.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "notifications_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("notifications",)
depends_on: str | Sequence[str] | None = ("core_base", "identity_0001", "orgs_0001")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE notifications (
          id                 uuid PRIMARY KEY,
          user_id            uuid        NOT NULL REFERENCES users(id),
          organization_id    uuid        NULL REFERENCES organizations(id),
          template_key       text        NOT NULL,
          template_version   smallint    NOT NULL,
          category           text        NOT NULL CHECK (category IN ('security','transactional','learning','marketing','system')),
          channels           text[]      NOT NULL CHECK (channels <@ ARRAY['in_app','email','sms','push']::text[]),
          data               jsonb       NOT NULL DEFAULT '{}',
          priority           text        NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','critical')),
          status             text        NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sent','partially_sent','failed','suppressed')),
          delivery           jsonb       NOT NULL DEFAULT '{}',
          dedupe_key         text        NULL,
          read_at            timestamptz NULL,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ux_notif_dedupe ON notifications (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL;
        CREATE INDEX ix_notif_inbox ON notifications (user_id, created_at DESC) WHERE 'in_app' = ANY (channels);
        COMMENT ON TABLE notifications IS 'Owner: notifications | RLS: O | Retention: 180 days (security R-SEC) | PII: P2';
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON notifications TO td_app")
    op.execute("GRANT SELECT ON notifications TO td_readonly")
    add_updated_at_trigger("notifications")
    enable_rls("notifications", "O")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS notifications CASCADE")
