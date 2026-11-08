"""learning: enrolments, lesson_progress, assignments, assignment_submissions, certificates

Revision ID: learning_0001
Revises:
Create Date: 2026-11-03

database-schema §7 (learning half). RLS: enrolments / lesson_progress / assignment_submissions /
certificates family U (own rows, or rows of the principal's organizations, or platform);
assignments family TN.

Deviations from database-schema §7 (reported to the Integration Lead):

* ``enrolments.entitlement_id``, ``assignment_submissions.code_submission_id`` and
  ``certificates.final_attempt_id`` are soft references until the entitlements / coding /
  assessments tables exist.
* ``lesson_progress``: + ``watched_intervals`` (merged, server-plausibility-checked
  ``[start, end]`` second ranges from playback heartbeats — the evidence behind
  ``watched_seconds``), + ``evidence`` (jsonb: completion evidence kind and markers).
* ``assignments``: + ``lesson_id`` (soft; the lesson that embeds it), + ``late_penalty_pct``,
  + ``allowed_file_types``, + ``grades_released_at``, + ``status``.
* ``assignment_submissions``: + ``rubric_scores``, + ``returned_reason``.
* ``certificates``: public verification is served by the API in a named system context that
  selects only the safe fields (no SECURITY DEFINER function is needed).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "learning_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("learning",)
depends_on: str | Sequence[str] | None = ("core_base", "identity_0001", "orgs_0001", "catalog_0001")

TABLES = ("enrolments", "lesson_progress", "assignments", "assignment_submissions", "certificates")


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE enrolments (
          id                 uuid PRIMARY KEY,
          user_id            uuid        NOT NULL REFERENCES users(id),
          course_id          uuid        NOT NULL REFERENCES courses(id),
          course_version_id  uuid        NOT NULL REFERENCES course_versions(id),
          organization_id    uuid        NULL REFERENCES organizations(id),
          batch_id           uuid        NULL REFERENCES batches(id),
          source             text        NOT NULL CHECK (source IN ('entitlement','batch_sync','manual','free')),
          entitlement_id     uuid        NULL,
          status             text        NOT NULL DEFAULT 'active'
                               CHECK (status IN ('active','completed','suspended','expired','withdrawn')),
          enrolled_at        timestamptz NOT NULL DEFAULT now(),
          completed_at       timestamptz NULL,
          expires_at         timestamptz NULL,
          progress_pct       numeric(5,2) NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
          last_activity_at   timestamptz NULL,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          UNIQUE (user_id, course_id),
          CONSTRAINT ck_enr_source CHECK (source <> 'entitlement' OR entitlement_id IS NOT NULL)
        );
        CREATE INDEX ix_enr_course ON enrolments (course_id, status);
        CREATE INDEX ix_enr_batch ON enrolments (batch_id) WHERE batch_id IS NOT NULL;
        CREATE INDEX ix_enr_user_activity ON enrolments (user_id, last_activity_at DESC);
        COMMENT ON TABLE enrolments IS 'Owner: learning | RLS: U | Retention: R-LEARN | PII: P1';

        CREATE TABLE lesson_progress (
          enrolment_id       uuid        NOT NULL REFERENCES enrolments(id) ON DELETE CASCADE,
          lesson_key         uuid        NOT NULL,
          user_id            uuid        NOT NULL REFERENCES users(id),
          organization_id    uuid        NULL REFERENCES organizations(id),
          status             text        NOT NULL DEFAULT 'not_started'
                               CHECK (status IN ('not_started','in_progress','completed')),
          progress_pct       numeric(5,2) NOT NULL DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
          video_position_s   int         NULL,
          watched_seconds    int         NOT NULL DEFAULT 0 CHECK (watched_seconds >= 0),
          watched_intervals  jsonb       NOT NULL DEFAULT '[]',
          evidence           jsonb       NULL,
          first_opened_at    timestamptz NULL,
          completed_at       timestamptz NULL,
          updated_at         timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (enrolment_id, lesson_key),
          CONSTRAINT ck_lp_completed CHECK ((status = 'completed') = (completed_at IS NOT NULL))
        );
        CREATE INDEX ix_lp_user ON lesson_progress (user_id, updated_at DESC);
        COMMENT ON TABLE lesson_progress IS 'Owner: learning | RLS: U | Retention: R-LEARN | PII: P1';

        CREATE TABLE assignments (
          id                 uuid PRIMARY KEY,
          organization_id    uuid        NULL REFERENCES organizations(id),
          course_id          uuid        NULL REFERENCES courses(id),
          batch_id           uuid        NULL REFERENCES batches(id),
          lesson_id          uuid        NULL,
          title              text        NOT NULL,
          instructions_md    text        NOT NULL,
          submission_type    text        NOT NULL CHECK (submission_type IN ('file','text','link','code')),
          max_score          numeric(7,2) NOT NULL CHECK (max_score > 0),
          rubric             jsonb       NULL,
          allowed_file_types text[]      NOT NULL DEFAULT '{pdf,zip,docx,txt}',
          available_from     timestamptz NULL,
          due_at             timestamptz NULL,
          late_until         timestamptz NULL,
          late_penalty_pct   numeric(5,2) NOT NULL DEFAULT 0 CHECK (late_penalty_pct BETWEEN 0 AND 100),
          max_attempts       smallint    NOT NULL DEFAULT 1 CHECK (max_attempts BETWEEN 1 AND 20),
          status             text        NOT NULL DEFAULT 'active' CHECK (status IN ('active','archived')),
          grades_released_at timestamptz NULL,
          created_by         uuid        NOT NULL REFERENCES users(id),
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_asg_dates CHECK (late_until IS NULL OR due_at IS NULL OR late_until >= due_at),
          CONSTRAINT ck_asg_target CHECK (num_nonnulls(course_id, batch_id) >= 1)
        );
        CREATE INDEX ix_asg_batch ON assignments (batch_id) WHERE batch_id IS NOT NULL;
        CREATE INDEX ix_asg_course ON assignments (course_id) WHERE course_id IS NOT NULL;
        COMMENT ON TABLE assignments IS 'Owner: learning | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE assignment_submissions (
          id                 uuid PRIMARY KEY,
          assignment_id      uuid        NOT NULL REFERENCES assignments(id),
          user_id            uuid        NOT NULL REFERENCES users(id),
          organization_id    uuid        NULL REFERENCES organizations(id),
          attempt_no         smallint    NOT NULL DEFAULT 1 CHECK (attempt_no >= 1),
          body_text          text        NULL,
          link_url           text        NULL CHECK (link_url IS NULL OR link_url ~ '^https?://'),
          file_s3_keys       text[]      NOT NULL DEFAULT '{}',
          code_submission_id uuid        NULL,
          status             text        NOT NULL DEFAULT 'submitted'
                               CHECK (status IN ('draft','submitted','late','graded','returned')),
          submitted_at       timestamptz NULL,
          score              numeric(7,2) NULL CHECK (score IS NULL OR score >= 0),
          rubric_scores      jsonb       NULL,
          feedback_md        text        NULL,
          returned_reason    text        NULL,
          graded_by          uuid        NULL REFERENCES users(id),
          graded_at          timestamptz NULL,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          UNIQUE (assignment_id, user_id, attempt_no)
        );
        CREATE INDEX ix_as_assignment ON assignment_submissions (assignment_id, status);
        CREATE INDEX ix_as_user ON assignment_submissions (user_id, created_at DESC);
        COMMENT ON TABLE assignment_submissions IS 'Owner: learning | RLS: U | Retention: R-LEARN | PII: P2';

        CREATE TABLE certificates (
          id                  uuid PRIMARY KEY,
          public_code         text        NOT NULL UNIQUE CHECK (public_code ~ '^[A-Z0-9]{10,16}$'),
          user_id             uuid        NOT NULL REFERENCES users(id),
          organization_id     uuid        NULL REFERENCES organizations(id),
          course_id           uuid        NOT NULL REFERENCES courses(id),
          course_version_id   uuid        NOT NULL REFERENCES course_versions(id),
          enrolment_id        uuid        NOT NULL REFERENCES enrolments(id),
          name_on_certificate text        NOT NULL,
          identity_verified   boolean     NOT NULL DEFAULT false,
          final_attempt_id    uuid        NULL,
          issue_source        text        NOT NULL DEFAULT 'rule' CHECK (issue_source IN ('rule','manual')),
          template_version    text        NOT NULL,
          pdf_s3_key          text        NULL,
          content_hash        bytea       NOT NULL CHECK (octet_length(content_hash) = 32),
          issued_at           timestamptz NOT NULL DEFAULT now(),
          revoked_at          timestamptz NULL,
          revoke_reason       text        NULL,
          created_at          timestamptz NOT NULL DEFAULT now(),
          UNIQUE (enrolment_id),
          CONSTRAINT ck_cert_revoke CHECK ((revoked_at IS NULL) = (revoke_reason IS NULL))
        );
        CREATE INDEX ix_cert_user ON certificates (user_id, issued_at DESC);
        COMMENT ON TABLE certificates IS 'Owner: learning | RLS: U | Retention: R-LEARN | PII: P2';
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO td_app")
    op.execute(f"GRANT SELECT ON {', '.join(TABLES)} TO td_readonly")
    # Certificates are never deleted by the app (revocation keeps the row for verification).
    op.execute("REVOKE DELETE, TRUNCATE ON certificates FROM td_app")
    for t in TABLES:
        if t != "certificates":
            add_updated_at_trigger(t)
    for t in ("enrolments", "lesson_progress", "assignment_submissions", "certificates"):
        enable_rls(t, "U")
    enable_rls("assignments", "TN")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
