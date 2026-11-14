"""admissions: course registration status (open / coming soon / closed) + login-email timestamp

Revision ID: admissions_0003
Revises: admissions_0002
Create Date: 2026-11-12

Owner requirement 2026-11-12: Admin sets each website course to *Open for registration*, *Coming
soon* or *Closed* in the LMS; the company website and every course list read it from
``GET /public/courses/status``, and registrations are accepted only while a course is open.

* ``course_status`` — one row per website course slug (the slugs of ``admission_fee_plans`` and
  of the ``web-<slug>`` batches). Platform only under RLS, like the other admissions tables (the
  public map is read under a named system context). Seeded from the current state so nothing
  changes for live courses: a slug whose fee plan is active (fee > 0) starts ``open``, every
  other known slug ``coming_soon``.
* ``admission_registrations.login_email_sent_at`` — when the LMS login email (username +
  temporary password) last reached the email provider for this registration.

No ``depends_on`` on other branch heads (see admissions_0001); ``batches`` / ``users`` exist since
``orgs_0001`` / ``identity_0001``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger

revision: str = "admissions_0003"
down_revision: str | Sequence[str] | None = "admissions_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES = "td_app, td_readonly"


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE course_status (
          course_slug  text        PRIMARY KEY CHECK (course_slug ~ '^[a-z0-9][a-z0-9-]{0,79}$'),
          status       text        NOT NULL DEFAULT 'coming_soon' CHECK (status IN ('open','coming_soon','closed')),
          updated_at   timestamptz NOT NULL DEFAULT now(),
          updated_by   uuid        NULL REFERENCES users(id)
        );
        COMMENT ON TABLE course_status IS 'Owner: admissions | RLS: platform only | Retention: config | PII: none';

        ALTER TABLE admission_registrations ADD COLUMN login_email_sent_at timestamptz NULL;
        """
    )
    op.execute("ALTER TABLE course_status ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE course_status FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS p_platform ON course_status")
    op.execute(
        f"CREATE POLICY p_platform ON course_status FOR ALL TO {_ROLES} "
        "USING (app.is_platform()) WITH CHECK (app.is_platform())"
    )
    op.execute("GRANT SELECT ON course_status TO td_readonly")
    op.execute("GRANT SELECT, INSERT, UPDATE ON course_status TO td_app")
    op.execute("REVOKE DELETE, TRUNCATE ON course_status FROM td_app")
    add_updated_at_trigger("course_status")

    # Seed from the current state (live courses keep taking registrations).
    op.execute(
        r"""
        INSERT INTO course_status (course_slug, status)
        SELECT course_slug, CASE WHEN active AND fee_paise > 0 THEN 'open' ELSE 'coming_soon' END
          FROM admission_fee_plans
        ON CONFLICT (course_slug) DO NOTHING;

        INSERT INTO course_status (course_slug, status)
        SELECT DISTINCT s, 'coming_soon' FROM (
          SELECT website_course_slug AS s FROM batches WHERE website_course_slug IS NOT NULL
          UNION
          SELECT substr(code, 5) AS s FROM batches WHERE code LIKE 'web-%'
        ) k
         WHERE s ~ '^[a-z0-9][a-z0-9-]{0,79}$'
        ON CONFLICT (course_slug) DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE admission_registrations DROP COLUMN IF EXISTS login_email_sent_at")
    op.execute("DROP TABLE IF EXISTS course_status CASCADE")
