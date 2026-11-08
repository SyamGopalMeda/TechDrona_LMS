"""placement: named question banks, new question types, question settings, question images

Revision ID: placement_0005
Revises: placement_0004
Create Date: 2026-11-06

WISEMAN-FEATURES build (qbank):

* ``questions.question_type`` additionally allows ``essay``, ``poll``, ``survey`` and
  ``word_cloud`` (poll/survey/word_cloud are ungraded; ``descriptive`` stays for compatibility).
* ``question_versions.settings`` (jsonb, non-key per-type configuration delivered to learners,
  e.g. poll ``allow_multiple``, survey scale, word-cloud limits). Covered by the immutability
  trigger like the other content columns.
* ``question_banks`` (TN): named collections of questions with a subject and an owner org.
  ``question_bank_items`` (TN): membership (a question may be in several banks; the global
  bank, topics, company paths, practice and tests keep using ``questions`` unchanged).
* ``question_media`` (TN): images on question stems/options uploaded straight to the content
  bucket (presigned POST, same pattern as media MED-02) and malware-scanned before they are
  served.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "placement_0005"
down_revision: str | Sequence[str] | None = "placement_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TYPES_OLD = "'mcq_single','mcq_multi','numeric','fill_blank','coding','descriptive'"
TYPES_NEW = TYPES_OLD + ",'essay','poll','survey','word_cloud'"

_IMMUTABLE_FN = """
CREATE OR REPLACE FUNCTION placement_qv_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status IN ('published','retired') AND (
       NEW.stem IS DISTINCT FROM OLD.stem OR NEW.answer_key IS DISTINCT FROM OLD.answer_key
    OR NEW.explanation IS DISTINCT FROM OLD.explanation OR NEW.difficulty IS DISTINCT FROM OLD.difficulty
    OR NEW.default_marks IS DISTINCT FROM OLD.default_marks
    OR NEW.default_negative IS DISTINCT FROM OLD.default_negative
    OR NEW.content_hash IS DISTINCT FROM OLD.content_hash OR NEW.question_id IS DISTINCT FROM OLD.question_id
    OR NEW.version_no IS DISTINCT FROM OLD.version_no{extra}) THEN
    RAISE EXCEPTION 'published question versions are immutable' USING ERRCODE = 'check_violation';
  END IF;
  IF OLD.status IN ('published','retired') AND NEW.status NOT IN ('published','retired') THEN
    RAISE EXCEPTION 'published question versions cannot return to draft' USING ERRCODE = 'check_violation';
  END IF;
  RETURN NEW;
END $$;
"""

TN_TABLES = ("question_banks", "question_bank_items", "question_media")


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE questions DROP CONSTRAINT IF EXISTS questions_question_type_check;
        ALTER TABLE questions ADD CONSTRAINT ck_q_type CHECK (question_type IN ({TYPES_NEW}));

        ALTER TABLE question_versions ADD COLUMN settings jsonb NOT NULL DEFAULT '{{}}'::jsonb
          CONSTRAINT ck_qv_settings CHECK (jsonb_typeof(settings) = 'object' AND pg_column_size(settings) <= 8192);
        """
    )
    op.execute(_IMMUTABLE_FN.format(extra="\n    OR NEW.settings IS DISTINCT FROM OLD.settings"))
    op.execute(
        r"""
        CREATE TABLE question_banks (
          id               uuid PRIMARY KEY,
          organization_id  uuid        NULL REFERENCES organizations(id),
          name             text        NOT NULL CHECK (char_length(name) BETWEEN 1 AND 120),
          subject          text        NULL CHECK (subject IS NULL OR char_length(subject) BETWEEN 1 AND 120),
          description      text        NULL CHECK (description IS NULL OR char_length(description) <= 2000),
          default_topic_id uuid        NULL REFERENCES topics(id),
          created_by       uuid        NOT NULL REFERENCES users(id),
          last_added_at    timestamptz NULL,
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now(),
          deleted_at       timestamptz NULL
        );
        CREATE INDEX ix_qb_org ON question_banks (organization_id, created_at DESC) WHERE deleted_at IS NULL;
        COMMENT ON TABLE question_banks IS 'Owner: placement | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE question_bank_items (
          id               uuid PRIMARY KEY,
          bank_id          uuid        NOT NULL REFERENCES question_banks(id) ON DELETE CASCADE,
          question_id      uuid        NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
          organization_id  uuid        NULL REFERENCES organizations(id),
          added_by         uuid        NOT NULL REFERENCES users(id),
          added_at         timestamptz NOT NULL DEFAULT now(),
          UNIQUE (bank_id, question_id)
        );
        CREATE INDEX ix_qbi_question ON question_bank_items (question_id);
        COMMENT ON TABLE question_bank_items IS 'Owner: placement | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE question_media (
          id               uuid PRIMARY KEY,
          organization_id  uuid        NULL REFERENCES organizations(id),
          s3_key           text        NOT NULL UNIQUE,
          content_type     text        NOT NULL CHECK (content_type IN ('image/png','image/jpeg','image/webp','image/gif')),
          size_bytes       int         NOT NULL CHECK (size_bytes > 0 AND size_bytes <= 5242880),
          status           text        NOT NULL DEFAULT 'uploading' CHECK (status IN ('uploading','ready','failed')),
          scan_status      text        NOT NULL DEFAULT 'pending' CHECK (scan_status IN ('pending','clean','infected')),
          created_by       uuid        NOT NULL REFERENCES users(id),
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_qm_pending ON question_media (created_at) WHERE scan_status = 'pending';
        COMMENT ON TABLE question_media IS 'Owner: placement | RLS: TN | Retention: R-CONTENT | PII: P0';
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TN_TABLES)} TO td_app")
    op.execute(f"GRANT SELECT ON {', '.join(TN_TABLES)} TO td_readonly")
    for t in TN_TABLES:
        enable_rls(t, "TN")
    add_updated_at_trigger("question_banks")
    add_updated_at_trigger("question_media")


def downgrade() -> None:
    for t in reversed(TN_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t}")
    op.execute(_IMMUTABLE_FN.format(extra=""))
    op.execute(
        f"""
        ALTER TABLE question_versions DROP COLUMN IF EXISTS settings;
        ALTER TABLE questions DROP CONSTRAINT IF EXISTS ck_q_type;
        ALTER TABLE questions ADD CONSTRAINT questions_question_type_check CHECK (question_type IN ({TYPES_OLD}));
        """
    )
