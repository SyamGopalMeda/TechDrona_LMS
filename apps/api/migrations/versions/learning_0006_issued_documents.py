"""learning: issued documents (letters + extra certificate types), wording overrides, document
settings; the certificate email outbox carries documents too

Revision ID: learning_0006
Revises: learning_0005
Create Date: 2026-11-11

Moves the company website's documents engine (offer / admission / recommendation letters,
internship / appreciation / participation certificates) into the LMS, beside the course
certificates (which stay in ``certificates``).

* ``issued_documents`` (RLS ``US``): one row per issued document. ``ref_no`` is
  ``TD-<prefix>-<year>-<6>`` and its prefix must match ``doc_type``. ``content`` freezes the
  issued wording (paragraphs, sections, subject, letterhead and signatory snapshot) so a
  re-render is identical. Status ``valid -> revoked`` or ``valid -> superseded`` (a corrected
  re-issue; ``replaces_id`` / ``superseded_by_id``, at most one correction per document).
  ``content_hash`` = SHA-256 of the stored PDF; ``file_hashes`` = hex SHA-256 of every copy
  handed out (public "check a PDF"). ``origin='enrolment'`` rows are unique per
  (enrolment, type): the automatic admission letter is created once.
* ``document_templates`` (platform only): paragraph / section / email overrides.
* ``document_settings`` (platform only, singleton): letterhead, signatory, image keys in S3.
* ``certificate_outbox``: ``certificate_id`` / ``user_id`` become nullable; new ``document_id``
  (exactly one of the two targets), ``to_email`` / ``subject`` / ``body`` (documents may go to
  people without an account; the approver may edit the text), origins ``enrolment`` /
  ``reissue`` / ``resend``. One automatic (``enrolment``) email per document.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "learning_0006"
down_revision: str | Sequence[str] | None = "learning_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None  # see learning_0005: no cross-branch depends_on

DOC_TYPES = (
    ("offer_internship", "OL"),
    ("offer_employment", "EO"),
    ("offer_course", "AL"),
    ("cert_completion", "CC"),
    ("cert_internship", "IC"),
    ("cert_appreciation", "CA"),
    ("cert_participation", "CP"),
    ("lor", "LR"),
)


def upgrade() -> None:
    types = ",".join(f"'{t}'" for t, _ in DOC_TYPES)
    prefix_case = " ".join(f"WHEN '{t}' THEN '{p}'" for t, p in DOC_TYPES)
    op.execute(
        f"""
        CREATE TABLE issued_documents (
          id                   uuid PRIMARY KEY,
          doc_type             text        NOT NULL CHECK (doc_type IN ({types})),
          ref_no               text        NOT NULL UNIQUE
                                 CHECK (ref_no ~ '^TD-(OL|EO|AL|CC|IC|CA|CP|LR)-[0-9]{{4}}-[A-HJ-NP-Z2-9]{{6}}$'),
          recipient_name       text        NOT NULL CHECK (char_length(recipient_name) BETWEEN 1 AND 160),
          recipient_email      text        NOT NULL CHECK (char_length(recipient_email) BETWEEN 3 AND 254),
          recipient            jsonb       NOT NULL DEFAULT '{{}}',
          user_id              uuid        NULL REFERENCES users(id),
          organization_id      uuid        NULL REFERENCES organizations(id),
          enrolment_id         uuid        NULL REFERENCES enrolments(id),
          batch_id             uuid        NULL REFERENCES batches(id),
          course_id            uuid        NULL,
          certificate_id       uuid        NULL REFERENCES certificates(id),
          fields               jsonb       NOT NULL DEFAULT '{{}}',
          content              jsonb       NOT NULL DEFAULT '{{}}',
          issue_date           date        NOT NULL,
          status               text        NOT NULL DEFAULT 'valid' CHECK (status IN ('valid','revoked','superseded')),
          origin               text        NOT NULL DEFAULT 'manual' CHECK (origin IN ('manual','enrolment','reissue')),
          replaces_id          uuid        NULL REFERENCES issued_documents(id),
          superseded_by_id     uuid        NULL REFERENCES issued_documents(id),
          superseded_at        timestamptz NULL,
          revoked_at           timestamptz NULL,
          revoked_by           uuid        NULL REFERENCES users(id),
          revoke_reason        text        NULL CHECK (revoke_reason IS NULL OR char_length(revoke_reason) <= 300),
          revoke_reason_public boolean     NOT NULL DEFAULT false,
          template_version     text        NOT NULL,
          pdf_s3_key           text        NULL,
          content_hash         bytea       NULL CHECK (content_hash IS NULL OR length(content_hash) = 32),
          file_hashes          text[]      NOT NULL DEFAULT '{{}}' CHECK (cardinality(file_hashes) <= 20),
          issued_by            uuid        NULL REFERENCES users(id),
          created_at           timestamptz NOT NULL DEFAULT now(),
          updated_at           timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_idoc_prefix CHECK (split_part(ref_no, '-', 2) = CASE doc_type {prefix_case} END),
          CONSTRAINT ck_idoc_revoked CHECK ((status = 'revoked') = (revoked_at IS NOT NULL)),
          CONSTRAINT ck_idoc_superseded CHECK ((status = 'superseded') = (superseded_by_id IS NOT NULL)),
          CONSTRAINT ck_idoc_not_self CHECK (replaces_id IS NULL OR replaces_id <> id)
        );
        CREATE UNIQUE INDEX ux_idoc_replaces ON issued_documents (replaces_id) WHERE replaces_id IS NOT NULL;
        CREATE UNIQUE INDEX ux_idoc_enrolment_auto ON issued_documents (enrolment_id, doc_type)
          WHERE origin = 'enrolment';
        CREATE INDEX ix_idoc_email ON issued_documents (lower(recipient_email));
        CREATE INDEX ix_idoc_user ON issued_documents (user_id) WHERE user_id IS NOT NULL;
        CREATE INDEX ix_idoc_type_status ON issued_documents (doc_type, status, created_at);
        COMMENT ON TABLE issued_documents IS 'Owner: learning | RLS: US | Retention: R-LEARN | PII: P1';

        CREATE TABLE document_templates (
          kind         text        NOT NULL CHECK (kind IN ('document','email')),
          template_key text        NOT NULL CHECK (template_key ~ '^[a-z_]{{2,40}}$'),
          content      jsonb       NOT NULL,
          updated_by   uuid        NULL REFERENCES users(id),
          created_at   timestamptz NOT NULL DEFAULT now(),
          updated_at   timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (kind, template_key)
        );
        COMMENT ON TABLE document_templates IS 'Owner: learning | RLS: platform only | wording overrides | no PII';
        CREATE POLICY p_document_templates ON document_templates FOR ALL TO td_app, td_readonly
          USING (app.is_platform()) WITH CHECK (app.is_platform());
        GRANT SELECT, INSERT, UPDATE, DELETE ON document_templates TO td_app;
        GRANT SELECT ON document_templates TO td_readonly;

        CREATE TABLE document_settings (
          id         smallint    PRIMARY KEY DEFAULT 1 CHECK (id = 1),
          data       jsonb       NOT NULL DEFAULT '{{}}',
          updated_by uuid        NULL REFERENCES users(id),
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE document_settings IS 'Owner: learning | RLS: platform only | singleton | company contact details, no secrets';
        CREATE POLICY p_document_settings ON document_settings FOR ALL TO td_app, td_readonly
          USING (app.is_platform()) WITH CHECK (app.is_platform());
        GRANT SELECT, INSERT, UPDATE ON document_settings TO td_app;
        GRANT SELECT ON document_settings TO td_readonly;
        REVOKE DELETE, TRUNCATE ON document_settings FROM td_app;
        INSERT INTO document_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

        ALTER TABLE document_templates ENABLE ROW LEVEL SECURITY;
        ALTER TABLE document_templates FORCE ROW LEVEL SECURITY;
        ALTER TABLE document_settings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE document_settings FORCE ROW LEVEL SECURITY;
        """
    )
    op.execute("GRANT SELECT, INSERT, UPDATE ON issued_documents TO td_app")
    op.execute("GRANT SELECT ON issued_documents TO td_readonly")
    enable_rls("issued_documents", "US")
    add_updated_at_trigger("issued_documents")
    add_updated_at_trigger("document_templates")
    add_updated_at_trigger("document_settings")

    # certificate_outbox -> certificates and documents
    op.execute(
        """
        ALTER TABLE certificate_outbox
          ALTER COLUMN certificate_id DROP NOT NULL,
          ALTER COLUMN user_id DROP NOT NULL,
          ADD COLUMN document_id uuid NULL REFERENCES issued_documents(id) ON DELETE CASCADE,
          ADD COLUMN to_email text NULL CHECK (to_email IS NULL OR char_length(to_email) BETWEEN 3 AND 254),
          ADD COLUMN subject text NULL CHECK (subject IS NULL OR char_length(subject) <= 300),
          ADD COLUMN body text NULL CHECK (body IS NULL OR char_length(body) <= 20000),
          ADD CONSTRAINT ck_cob_target CHECK (num_nonnulls(certificate_id, document_id) = 1);
        ALTER TABLE certificate_outbox DROP CONSTRAINT IF EXISTS certificate_outbox_origin_check;
        ALTER TABLE certificate_outbox ADD CONSTRAINT certificate_outbox_origin_check
          CHECK (origin IN ('rule','manual','batch_end','backfill','enrolment','reissue','resend'));
        CREATE INDEX ix_cob_document ON certificate_outbox (document_id) WHERE document_id IS NOT NULL;
        CREATE UNIQUE INDEX ux_cob_document_auto ON certificate_outbox (document_id)
          WHERE document_id IS NOT NULL AND origin = 'enrolment';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM certificate_outbox WHERE document_id IS NOT NULL;
        DROP INDEX IF EXISTS ux_cob_document_auto;
        DROP INDEX IF EXISTS ix_cob_document;
        ALTER TABLE certificate_outbox DROP CONSTRAINT IF EXISTS certificate_outbox_origin_check;
        UPDATE certificate_outbox SET origin = 'manual' WHERE origin IN ('enrolment','reissue','resend');
        ALTER TABLE certificate_outbox ADD CONSTRAINT certificate_outbox_origin_check
          CHECK (origin IN ('rule','manual','batch_end','backfill'));
        ALTER TABLE certificate_outbox
          DROP CONSTRAINT IF EXISTS ck_cob_target,
          DROP COLUMN IF EXISTS body,
          DROP COLUMN IF EXISTS subject,
          DROP COLUMN IF EXISTS to_email,
          DROP COLUMN IF EXISTS document_id,
          ALTER COLUMN certificate_id SET NOT NULL,
          ALTER COLUMN user_id SET NOT NULL;
        DROP TABLE IF EXISTS document_settings;
        DROP TABLE IF EXISTS document_templates;
        DROP TABLE IF EXISTS issued_documents;
        """
    )
