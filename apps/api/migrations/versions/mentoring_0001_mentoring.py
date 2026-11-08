"""mentoring: mentor_slots, mentor_bookings, interview_feedback, mentor_notes, resumes, resume_reviews

Revision ID: mentoring_0001
Revises:
Create Date: 2026-11-03

database-schema §8 (PRD CCP-02, CCP-06; api-spec PLC-36..52). Implementation additions to the
contract DDL (reported to the schema owner):

* ``interview_feedback.scores`` holds five 1-5 criteria (``overall`` added to the four PRD ones);
* ``mentor_notes`` (new): private mentor notes on a student. RLS policy ``p_author``:
  ``author_id = app.user_id() OR app.is_platform()`` — students never match; staff reads go
  through the API (assignment check, SoD-11) under a system context;
* ``resumes``: ``pdf_pending_key`` / ``pdf_uploaded_at`` (presigned S3 upload metadata);
* ``resume_reviews``: ``note`` (student request note), ``summary`` (reviewer summary).

RLS: mentor_slots TN; mentor_bookings, interview_feedback U; resumes, resume_reviews O.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "mentoring_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("mentoring",)
depends_on: str | Sequence[str] | None = (
    "core_base",
    "identity_0001",
    "orgs_0001",
    "placement_0001",
    "entitlements_0001",
)


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE mentor_slots (
          id               uuid PRIMARY KEY,
          mentor_id        uuid        NOT NULL REFERENCES users(id),
          organization_id  uuid        NULL REFERENCES organizations(id),
          starts_at        timestamptz NOT NULL,
          duration_minutes smallint    NOT NULL CHECK (duration_minutes IN (30,45,60)),
          session_kind     text        NOT NULL CHECK (session_kind IN ('mock_interview','resume_review','career_guidance')),
          company_id       uuid        NULL REFERENCES companies(id),
          status           text        NOT NULL DEFAULT 'open' CHECK (status IN ('open','booked','cancelled','completed')),
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_ms_open ON mentor_slots (starts_at) WHERE status = 'open';
        CREATE UNIQUE INDEX ux_ms_mentor_time ON mentor_slots (mentor_id, starts_at) WHERE status <> 'cancelled';
        CREATE INDEX ix_ms_mentor ON mentor_slots (mentor_id, starts_at);
        COMMENT ON TABLE mentor_slots IS 'Owner: mentoring | RLS: TN | Retention: R-LEARN | PII: P1';

        CREATE TABLE mentor_bookings (
          id                 uuid PRIMARY KEY,
          mentor_slot_id     uuid        NOT NULL REFERENCES mentor_slots(id),
          user_id            uuid        NOT NULL REFERENCES users(id),
          organization_id    uuid        NULL REFERENCES organizations(id),
          entitlement_id     uuid        NULL REFERENCES entitlements(id),
          meeting_url        text        NULL CHECK (meeting_url IS NULL OR (meeting_url LIKE 'https://%' AND char_length(meeting_url) <= 2048)),
          status             text        NOT NULL DEFAULT 'booked' CHECK (status IN ('booked','rescheduled','cancelled_by_student',
                                             'cancelled_by_mentor','completed','student_no_show','mentor_no_show')),
          quota_consumed     boolean     NOT NULL DEFAULT true,
          cancelled_at       timestamptz NULL,
          idempotency_key    text        NOT NULL,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          UNIQUE (user_id, idempotency_key)
        );
        CREATE UNIQUE INDEX ux_mb_slot_live ON mentor_bookings (mentor_slot_id) WHERE status IN ('booked','rescheduled','completed');
        CREATE INDEX ix_mb_user ON mentor_bookings (user_id, created_at DESC);
        CREATE INDEX ix_mb_slot ON mentor_bookings (mentor_slot_id);
        COMMENT ON TABLE mentor_bookings IS 'Owner: mentoring | RLS: U (+ mentor via API) | Retention: R-LEARN | PII: P1/P2';

        CREATE TABLE interview_feedback (
          id                  uuid PRIMARY KEY,
          mentor_booking_id   uuid        NOT NULL UNIQUE REFERENCES mentor_bookings(id),
          user_id             uuid        NOT NULL REFERENCES users(id),
          organization_id     uuid        NULL REFERENCES organizations(id),
          mentor_id           uuid        NOT NULL REFERENCES users(id),
          scores              jsonb       NOT NULL,
          comments            text        NULL CHECK (comments IS NULL OR char_length(comments) <= 5000),
          released_at         timestamptz NULL,
          created_at          timestamptz NOT NULL DEFAULT now(),
          updated_at          timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_if_user ON interview_feedback (user_id, created_at DESC);
        COMMENT ON TABLE interview_feedback IS 'Owner: mentoring | RLS: U | Retention: R-LEARN | PII: P2';

        CREATE TABLE mentor_notes (
          id                 uuid PRIMARY KEY,
          student_id         uuid        NOT NULL REFERENCES users(id),
          author_id          uuid        NOT NULL REFERENCES users(id),
          organization_id    uuid        NULL REFERENCES organizations(id),
          mentor_booking_id  uuid        NULL REFERENCES mentor_bookings(id),
          body               text        NOT NULL CHECK (char_length(body) BETWEEN 1 AND 5000),
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_mn_student ON mentor_notes (student_id, created_at DESC);
        COMMENT ON TABLE mentor_notes IS 'Owner: mentoring | RLS: author or platform (never the student) | Retention: R-LEARN | PII: P2';

        CREATE TABLE resumes (
          id               uuid PRIMARY KEY,
          user_id          uuid        NOT NULL REFERENCES users(id),
          template_key     text        NOT NULL CHECK (template_key IN ('ats_classic','ats_modern')),
          version_no       int         NOT NULL DEFAULT 1 CHECK (version_no >= 1),
          content          jsonb       NOT NULL,
          checklist_score  smallint    NULL CHECK (checklist_score BETWEEN 0 AND 100),
          pdf_s3_key       text        NULL,
          pdf_pending_key  text        NULL,
          pdf_uploaded_at  timestamptz NULL,
          is_current       boolean     NOT NULL DEFAULT true,
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now(),
          UNIQUE (user_id, version_no)
        );
        CREATE UNIQUE INDEX ux_resume_current ON resumes (user_id) WHERE is_current;
        COMMENT ON TABLE resumes IS 'Owner: mentoring | RLS: O (+ reviewer via API) | Retention: R-ACCT | PII: P2';

        CREATE TABLE resume_reviews (
          id               uuid PRIMARY KEY,
          resume_id        uuid        NOT NULL REFERENCES resumes(id),
          user_id          uuid        NOT NULL REFERENCES users(id),
          reviewer_id      uuid        NULL REFERENCES users(id),
          entitlement_id   uuid        NULL REFERENCES entitlements(id),
          status           text        NOT NULL DEFAULT 'requested' CHECK (status IN ('requested','in_review','completed','cancelled')),
          note             text        NULL CHECK (note IS NULL OR char_length(note) <= 1000),
          comments         jsonb       NOT NULL DEFAULT '[]',
          summary          text        NULL CHECK (summary IS NULL OR char_length(summary) <= 5000),
          requested_at     timestamptz NOT NULL DEFAULT now(),
          completed_at     timestamptz NULL,
          updated_at       timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_rr_queue ON resume_reviews (status, requested_at) WHERE status IN ('requested','in_review');
        CREATE INDEX ix_rr_resume ON resume_reviews (resume_id);
        CREATE UNIQUE INDEX ux_rr_open ON resume_reviews (resume_id) WHERE status IN ('requested','in_review');
        COMMENT ON TABLE resume_reviews IS 'Owner: mentoring | RLS: O (+ reviewer via API) | Retention: R-ACCT | PII: P2';
        """
    )
    enable_rls("mentor_slots", "TN")
    enable_rls("mentor_bookings", "U")
    enable_rls("interview_feedback", "U")
    enable_rls("resumes", "O")
    enable_rls("resume_reviews", "O")
    op.execute("ALTER TABLE mentor_notes ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE mentor_notes FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY p_author ON mentor_notes FOR ALL TO td_app, td_readonly "
        "USING (author_id = app.user_id() OR app.is_platform()) "
        "WITH CHECK (author_id = app.user_id() OR app.is_platform())"
    )
    for t in (
        "mentor_slots",
        "mentor_bookings",
        "interview_feedback",
        "mentor_notes",
        "resumes",
        "resume_reviews",
    ):
        add_updated_at_trigger(t)


def downgrade() -> None:
    for t in (
        "resume_reviews",
        "resumes",
        "mentor_notes",
        "interview_feedback",
        "mentor_bookings",
        "mentor_slots",
    ):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
