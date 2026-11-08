"""support: single company — drop the college lane, requester-only ticket RLS, corporate enquiries

Revision ID: support_0004
Revises: support_0003
Create Date: 2026-11-07

REMOVAL-PLAN §1.2 (support), §1.3, §5 step 8, owner decisions D2 and D8.

* ``college_access`` tickets are remapped to ``other`` (the history is kept in
  ``context.legacy_category``) and the category CHECK no longer allows ``college_access``.
* Ticket and message RLS loses the organization branch. With one company organization every
  batch student shares the org, so ``organization_id = ANY(app.org_ids())`` would let any batch
  student read another student's ticket at the database level once ``orgs_0003`` re-homes the
  legacy rows. The predicate is now: requester (messages: via the ticket) or platform.
* New table ``corporate_enquiries`` (D8): the public corporate enquiry form
  (``POST /public/enquiries``). It holds no user id (the sender has no account), so it is not a
  ``support_tickets`` row (``requester_id`` is NOT NULL). RLS forced, platform only: the public
  route inserts under a system context, Admin reads it through ``/support/enquiries``.
  Retention: 2 years after closure (handled with support data).

Data steps run as the table owner; FORCE RLS is lifted for the statements and restored.
``downgrade()`` restores the schema only (CHECK, policies, table); restore data from the backup
dump.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger

revision: str = "support_0004"
down_revision: str | Sequence[str] | None = "support_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES = "td_app, td_readonly"
_CATS = (
    "'account_access','device_reset','billing','refund','content','assessment','technical',"
    "'grievance','privacy_request','other','certificate','appeal'"
)
_OLD_CATS = _CATS + ",'college_access'"

_TICKET_PRED = "requester_id = app.user_id() OR app.is_platform()"
_MSG_PRED = (
    "EXISTS (SELECT 1 FROM support_tickets t WHERE t.id = support_ticket_id AND "
    "(t.requester_id = app.user_id() OR app.is_platform()))"
)
_OLD_TICKET_PRED = (
    "requester_id = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) "
    "OR app.is_platform()"
)
_OLD_MSG_PRED = (
    "EXISTS (SELECT 1 FROM support_tickets t WHERE t.id = support_ticket_id AND "
    "(t.requester_id = app.user_id() OR (t.organization_id IS NOT NULL AND "
    "t.organization_id = ANY (app.org_ids())) OR app.is_platform()))"
)


def _policies(ticket_pred: str, msg_pred: str) -> None:
    for table, pred in (("support_tickets", ticket_pred), ("support_ticket_messages", msg_pred)):
        op.execute(f"DROP POLICY IF EXISTS p_custom ON {table}")
        op.execute(
            f"CREATE POLICY p_custom ON {table} FOR ALL TO {_ROLES} USING ({pred}) WITH CHECK ({pred})"
        )


def upgrade() -> None:
    # 1. Remap the college lane (owner-run data step; FORCE RLS lifted for the statement).
    op.execute("ALTER TABLE support_tickets NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE support_tickets SET category = 'other', "
        "context = context || jsonb_build_object('legacy_category', 'college_access') "
        "WHERE category = 'college_access'"
    )
    op.execute("ALTER TABLE support_tickets FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE support_tickets DROP CONSTRAINT IF EXISTS support_tickets_category_check")
    op.execute(
        f"ALTER TABLE support_tickets ADD CONSTRAINT support_tickets_category_check CHECK (category IN ({_CATS}))"
    )

    # 2. Requester-or-platform RLS (no organization branch).
    _policies(_TICKET_PRED, _MSG_PRED)

    # 3. Corporate enquiries (D8).
    op.execute("CREATE SEQUENCE IF NOT EXISTS corporate_enquiry_number_seq")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE corporate_enquiry_number_seq TO td_app")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS corporate_enquiries (
          id               uuid PRIMARY KEY,
          reference        text        NOT NULL UNIQUE,
          name             text        NOT NULL CHECK (char_length(name) BETWEEN 2 AND 100),
          company          text        NOT NULL CHECK (char_length(company) BETWEEN 2 AND 150),
          email            text        NOT NULL CHECK (char_length(email) BETWEEN 3 AND 254),
          phone            text        NULL CHECK (char_length(phone) BETWEEN 6 AND 20),
          message          text        NOT NULL CHECK (char_length(message) BETWEEN 10 AND 4000),
          consent_at       timestamptz NOT NULL,
          notice_version   text        NOT NULL CHECK (char_length(notice_version) BETWEEN 1 AND 40),
          status           text        NOT NULL DEFAULT 'new'
                                       CHECK (status IN ('new','in_progress','closed','spam')),
          assigned_to      uuid        NULL REFERENCES users(id),
          staff_note       text        NULL CHECK (char_length(staff_note) <= 4000),
          closed_at        timestamptz NULL,
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS ix_ce_status_created ON corporate_enquiries (status, created_at DESC, id DESC);
        COMMENT ON TABLE corporate_enquiries IS 'Owner: support | public corporate enquiry form (D8) | RLS: platform only | Retention: 2 y after closure | PII: P2';
        """
    )
    op.execute("ALTER TABLE corporate_enquiries ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE corporate_enquiries FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS p_platform ON corporate_enquiries")
    op.execute(
        f"CREATE POLICY p_platform ON corporate_enquiries FOR ALL TO {_ROLES} "
        "USING (app.is_platform()) WITH CHECK (app.is_platform())"
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON corporate_enquiries TO td_app")
    op.execute("GRANT SELECT ON corporate_enquiries TO td_readonly")
    op.execute("REVOKE DELETE, TRUNCATE ON corporate_enquiries FROM td_app")
    add_updated_at_trigger("corporate_enquiries")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corporate_enquiries")
    op.execute("DROP SEQUENCE IF EXISTS corporate_enquiry_number_seq")
    _policies(_OLD_TICKET_PRED, _OLD_MSG_PRED)
    op.execute("ALTER TABLE support_tickets DROP CONSTRAINT IF EXISTS support_tickets_category_check")
    op.execute(
        f"ALTER TABLE support_tickets ADD CONSTRAINT support_tickets_category_check "
        f"CHECK (category IN ({_OLD_CATS}))"
    )
