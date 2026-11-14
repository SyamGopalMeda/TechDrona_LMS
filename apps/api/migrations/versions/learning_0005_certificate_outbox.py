"""learning: certificate email outbox (approval queue) + feature flag ``certificates.auto_send``

Revision ID: learning_0005
Revises: learning_0004
Create Date: 2026-11-11

* ``certificate_outbox`` (RLS ``US``, the user-owned family required for new tables after
  ``orgs_0004``): one row per certificate - the email to the learner with the PDF attached.
  Status machine ``awaiting -> pending -> sent | failed``, ``cancelled`` from any unsent state,
  ``failed -> pending`` on retry (``app.modules.learning.certificates.OUTBOX_TRANSITIONS``).
  The address is read from ``users`` at send time (never copied here).
* ``feature_flags``: ``certificates.auto_send`` (off). Off = automatically issued certificates
  wait in the queue for an admin's approval; on = they are sent by the worker.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "learning_0005"
down_revision: str | Sequence[str] | None = "learning_0004"
branch_labels: str | Sequence[str] | None = None
# orgs_0004: app.caller_is_org_staff() used by the US policy; admin_0001: feature_flags.
depends_on: str | Sequence[str] | None = (
    None  # orgs_0004 and admin_0001 are long applied; a cross-branch depends_on breaks "alembic upgrade heads"
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE certificate_outbox (
          id                  uuid PRIMARY KEY,
          certificate_id      uuid        NOT NULL UNIQUE REFERENCES certificates(id) ON DELETE CASCADE,
          user_id             uuid        NOT NULL REFERENCES users(id),
          organization_id     uuid        NULL REFERENCES organizations(id),
          status              text        NOT NULL DEFAULT 'awaiting'
                                CHECK (status IN ('awaiting','pending','sent','failed','cancelled')),
          origin              text        NOT NULL DEFAULT 'rule' CHECK (origin IN ('rule','manual','batch_end','backfill')),
          attempts            smallint    NOT NULL DEFAULT 0 CHECK (attempts >= 0),
          last_error          text        NULL CHECK (last_error IS NULL OR char_length(last_error) <= 500),
          provider_message_id text        NULL,
          approved_by         uuid        NULL REFERENCES users(id),
          approved_at         timestamptz NULL,
          cancelled_by        uuid        NULL REFERENCES users(id),
          cancelled_at        timestamptz NULL,
          sent_at             timestamptz NULL,
          created_at          timestamptz NOT NULL DEFAULT now(),
          updated_at          timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_cob_sent CHECK ((status = 'sent') = (sent_at IS NOT NULL))
        );
        CREATE INDEX ix_cob_status ON certificate_outbox (status, created_at);
        CREATE INDEX ix_cob_user ON certificate_outbox (user_id);
        COMMENT ON TABLE certificate_outbox IS 'Owner: learning | RLS: US | Retention: R-LEARN | PII: P1';

        INSERT INTO feature_flags (id, flag_key, description) VALUES
          (gen_random_uuid(), 'certificates.auto_send',
           'Email automatically issued certificates at once (off: they wait for approval in Admin > Certificates)')
        ON CONFLICT (flag_key) DO NOTHING;
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON certificate_outbox TO td_app")
    op.execute("GRANT SELECT ON certificate_outbox TO td_readonly")
    enable_rls("certificate_outbox", "US")
    add_updated_at_trigger("certificate_outbox")


def downgrade() -> None:
    op.execute("DELETE FROM feature_flags WHERE flag_key = 'certificates.auto_send'")
    op.execute("DROP TABLE IF EXISTS certificate_outbox")
