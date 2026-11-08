"""support: support_tickets, support_ticket_messages, support_user_notes

Revision ID: support_0001
Revises:
Create Date: 2026-11-03

database-schema §14 (support_tickets, support_ticket_messages, PRD CCP-07) plus implementation
columns: ``escalated_to``, ``merged_into_id``, ``related_unblock_request_id`` (link to the
unblock case), ``context`` (disclosed client context), ``csat_*``, ``closed_at``,
``last_message_at``. ``support_user_notes`` backs SUP-14 (internal account annotations).

RLS: tickets/messages use the documented custom predicate (requester, own organization,
platform); the API additionally restricts organization rows to staff holding ``ticket.read``
at that organization. Account notes are platform-only.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger

revision: str = "support_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("support",)
depends_on: str | Sequence[str] | None = (
    "core_base",
    "identity_0001",
    "orgs_0001",
    "security_0001",
    "commerce_0001",
    "admin_0001",
)

TABLES = ("support_user_notes", "support_ticket_messages", "support_tickets")
_ROLES = "td_app, td_readonly"


def upgrade() -> None:
    op.execute("CREATE SEQUENCE support_ticket_number_seq")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE support_ticket_number_seq TO td_app")
    op.execute(
        """
        CREATE TABLE support_tickets (
          id                 uuid PRIMARY KEY,
          ticket_number      text        NOT NULL UNIQUE,
          requester_id       uuid        NOT NULL REFERENCES users(id),
          organization_id    uuid        NULL REFERENCES organizations(id),
          category           text        NOT NULL CHECK (category IN ('account_access','device_reset','billing','refund',
                                            'content','assessment','technical','grievance','privacy_request','other')),
          subject            text        NOT NULL CHECK (char_length(subject) BETWEEN 3 AND 200),
          body               text        NOT NULL CHECK (char_length(body) BETWEEN 1 AND 10000),
          status             text        NOT NULL DEFAULT 'open'
                                         CHECK (status IN ('open','pending_user','pending_internal','resolved','closed')),
          priority           text        NOT NULL DEFAULT 'normal' CHECK (priority IN ('low','normal','high','urgent')),
          assigned_to        uuid        NULL REFERENCES users(id),
          related_order_id   uuid        NULL REFERENCES orders(id),
          related_case_id    uuid        NULL REFERENCES security_cases(id),
          related_unblock_request_id uuid NULL REFERENCES unblock_requests(id),
          privacy_request_id uuid        NULL REFERENCES privacy_requests(id),
          is_grievance       boolean     NOT NULL DEFAULT false,
          escalated_to       text        NULL CHECK (escalated_to IN ('finance','security','content')),
          merged_into_id     uuid        NULL REFERENCES support_tickets(id),
          context            jsonb       NOT NULL DEFAULT '{}',
          first_response_due_at timestamptz NULL,
          resolution_due_at  timestamptz NULL,
          first_responded_at timestamptz NULL,
          resolved_at        timestamptz NULL,
          closed_at          timestamptz NULL,
          last_message_at    timestamptz NULL,
          csat_score         smallint    NULL CHECK (csat_score BETWEEN 1 AND 5),
          csat_comment       text        NULL CHECK (char_length(csat_comment) <= 2000),
          csat_at            timestamptz NULL,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_st_merge_self CHECK (merged_into_id IS NULL OR merged_into_id <> id)
        );
        CREATE INDEX ix_st_queue ON support_tickets (status, priority, resolution_due_at)
          WHERE status NOT IN ('resolved','closed');
        CREATE INDEX ix_st_requester ON support_tickets (requester_id, created_at DESC);
        CREATE INDEX ix_st_org ON support_tickets (organization_id) WHERE organization_id IS NOT NULL;
        CREATE INDEX ix_st_assignee ON support_tickets (assigned_to) WHERE assigned_to IS NOT NULL;
        COMMENT ON TABLE support_tickets IS 'Owner: support | RLS: custom (requester, own org, platform) | Retention: 3 y after closure | PII: P2/P3';

        CREATE TABLE support_ticket_messages (
          id                 uuid PRIMARY KEY,
          support_ticket_id  uuid        NOT NULL REFERENCES support_tickets(id) ON DELETE CASCADE,
          organization_id    uuid        NULL REFERENCES organizations(id),
          author_id          uuid        NULL REFERENCES users(id),
          author_kind        text        NOT NULL CHECK (author_kind IN ('requester','agent','system')),
          visibility         text        NOT NULL DEFAULT 'public' CHECK (visibility IN ('public','internal')),
          body               text        NOT NULL CHECK (char_length(body) BETWEEN 1 AND 10000),
          attachments        jsonb       NOT NULL DEFAULT '[]',
          redacted_at        timestamptz NULL,
          created_at         timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_stm_ticket ON support_ticket_messages (support_ticket_id, created_at);
        COMMENT ON TABLE support_ticket_messages IS 'Owner: support | append-only except redaction | RLS: via ticket | PII: P2/P3';

        CREATE TABLE support_user_notes (
          id                 uuid PRIMARY KEY,
          user_id            uuid        NOT NULL REFERENCES users(id),
          author_id          uuid        NOT NULL REFERENCES users(id),
          support_ticket_id  uuid        NULL REFERENCES support_tickets(id),
          body               text        NOT NULL CHECK (char_length(body) BETWEEN 1 AND 4000),
          created_at         timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_sun_user ON support_user_notes (user_id, created_at DESC);
        COMMENT ON TABLE support_user_notes IS 'Owner: support | internal account notes (SUP-14) | RLS: platform only | PII: P2';
        """
    )
    ticket_pred = (
        "requester_id = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) "
        "OR app.is_platform()"
    )
    msg_pred = (
        "EXISTS (SELECT 1 FROM support_tickets t WHERE t.id = support_ticket_id AND "
        "(t.requester_id = app.user_id() OR (t.organization_id IS NOT NULL AND "
        "t.organization_id = ANY (app.org_ids())) OR app.is_platform()))"
    )
    for table, pred in (
        ("support_tickets", ticket_pred),
        ("support_ticket_messages", msg_pred),
        ("support_user_notes", "app.is_platform()"),
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY p_custom ON {table} FOR ALL TO {_ROLES} USING ({pred}) WITH CHECK ({pred})"
        )
    add_updated_at_trigger("support_tickets")
    # Thread is append-only (redaction is a platform job, not an app UPDATE path).
    op.execute("REVOKE DELETE, TRUNCATE ON support_ticket_messages FROM td_app")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON support_user_notes FROM td_app")


def downgrade() -> None:
    for t in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute("DROP SEQUENCE IF EXISTS support_ticket_number_seq")
