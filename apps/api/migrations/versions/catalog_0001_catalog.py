"""catalog: courses, course_versions, course_modules, lessons, lesson_topics, lesson_assets, resources

Revision ID: catalog_0001
Revises:
Create Date: 2026-11-03

database-schema §7 (catalog half). RLS family TN everywhere (organization_id NULL = platform
catalogue, readable by everyone; writable only in a platform context).

Deviations from database-schema §7 (reported to the Integration Lead):

* ``courses``: + ``is_free`` (price type "free"; paid access is decided by entitlements).
* ``course_versions``: + ``level``, ``language``, ``category``, ``tags``, ``certificate_rule``,
  ``completeness_plan``, ``change_type``, ``created_by``, ``submitted_by``, ``submitted_at``
  (draft metadata of CAT-11 and SoD-04 author != publisher).
* ``lessons.test_id`` / ``coding_problem_id`` / ``assignment_id`` and ``lesson_topics.topic_id``
  and ``resources.company_id`` are soft references until the assessments / coding / placement
  tables exist (assignments live in the learning branch, which depends on this one).
* ``lesson_assets``: VdoCipher uniqueness is per lesson (``ux_la_vdo`` on (lesson_id,
  provider_asset_id)) because each new draft version clones the asset rows of the published
  version.
* ``resources``: + ``access_level`` (public / signed_in / entitled, CAT-21); ``is_public`` kept
  and derived.
* Position uniques are ``DEFERRABLE INITIALLY DEFERRED`` so an outline (CAT-12) can be
  re-ordered inside one transaction.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls

revision: str = "catalog_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("catalog",)
depends_on: str | Sequence[str] | None = ("core_base", "identity_0001", "orgs_0001")

TABLES = (
    "courses",
    "course_versions",
    "course_modules",
    "lessons",
    "lesson_topics",
    "lesson_assets",
    "resources",
)


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE courses (
          id                  uuid PRIMARY KEY,
          organization_id     uuid        NULL REFERENCES organizations(id),
          slug                citext      NOT NULL CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,118}$'),
          title               text        NOT NULL,
          course_kind         text        NOT NULL DEFAULT 'self_paced'
                                CHECK (course_kind IN ('self_paced','cohort','crash_course','company_prep','bootcamp')),
          visibility          text        NOT NULL DEFAULT 'private'
                                CHECK (visibility IN ('public','unlisted','private','org_only')),
          status              text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','published','archived')),
          is_free             boolean     NOT NULL DEFAULT false,
          current_version_id  uuid        NULL,
          primary_topic_id    uuid        NULL,
          completeness_pct    numeric(5,2) NOT NULL DEFAULT 0 CHECK (completeness_pct BETWEEN 0 AND 100),
          created_by          uuid        NOT NULL REFERENCES users(id),
          created_at          timestamptz NOT NULL DEFAULT now(),
          updated_at          timestamptz NOT NULL DEFAULT now(),
          deleted_at          timestamptz NULL
        );
        CREATE UNIQUE INDEX ux_courses_slug
          ON courses (coalesce(organization_id, '00000000-0000-0000-0000-000000000000'::uuid), slug)
          WHERE deleted_at IS NULL;
        CREATE INDEX ix_courses_public ON courses (status, visibility) WHERE deleted_at IS NULL;
        CREATE INDEX ix_courses_org ON courses (organization_id) WHERE organization_id IS NOT NULL;
        COMMENT ON TABLE courses IS 'Owner: catalog | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE course_versions (
          id                uuid PRIMARY KEY,
          course_id         uuid        NOT NULL REFERENCES courses(id),
          organization_id   uuid        NULL REFERENCES organizations(id),
          version_no        int         NOT NULL CHECK (version_no >= 1),
          title             text        NOT NULL,
          summary           text        NULL,
          description_md    text        NULL,
          outcomes          text[]      NOT NULL DEFAULT '{}',
          level             text        NULL CHECK (level IN ('beginner','intermediate','advanced')),
          language          text        NOT NULL DEFAULT 'en',
          category          text        NULL CHECK (category IN
                              ('aptitude','programming','dsa','cs_fundamentals','company','interview','other')),
          tags              text[]      NOT NULL DEFAULT '{}',
          certificate_rule  jsonb       NULL,
          completeness_plan jsonb       NULL,
          status            text        NOT NULL DEFAULT 'draft'
                              CHECK (status IN ('draft','in_review','published','superseded')),
          change_type       text        NULL CHECK (change_type IN ('minor','major')),
          created_by        uuid        NOT NULL REFERENCES users(id),
          submitted_by      uuid        NULL REFERENCES users(id),
          submitted_at      timestamptz NULL,
          published_at      timestamptz NULL,
          published_by      uuid        NULL REFERENCES users(id),
          changelog         text        NULL,
          created_at        timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now(),
          UNIQUE (course_id, version_no),
          CONSTRAINT ck_cv_published CHECK (status NOT IN ('published','superseded')
                                            OR (published_at IS NOT NULL AND published_by IS NOT NULL))
        );
        -- at most one editable (draft / in_review) version per course
        CREATE UNIQUE INDEX ux_cv_one_draft ON course_versions (course_id) WHERE status IN ('draft','in_review');
        ALTER TABLE courses ADD CONSTRAINT fk_courses_current_version
          FOREIGN KEY (current_version_id) REFERENCES course_versions(id);
        COMMENT ON TABLE course_versions IS 'Owner: catalog | RLS: TN | immutable once published | Retention: R-CONTENT | PII: P0';

        CREATE TABLE course_modules (
          id                 uuid PRIMARY KEY,
          course_version_id  uuid        NOT NULL REFERENCES course_versions(id) ON DELETE CASCADE,
          organization_id    uuid        NULL REFERENCES organizations(id),
          module_key         uuid        NOT NULL,
          title              text        NOT NULL,
          position           int         NOT NULL CHECK (position >= 0),
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_cm_position UNIQUE (course_version_id, position) DEFERRABLE INITIALLY DEFERRED,
          CONSTRAINT uq_cm_key UNIQUE (course_version_id, module_key)
        );
        COMMENT ON TABLE course_modules IS 'Owner: catalog | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE lessons (
          id                  uuid PRIMARY KEY,
          course_module_id    uuid        NOT NULL REFERENCES course_modules(id) ON DELETE CASCADE,
          course_version_id   uuid        NOT NULL REFERENCES course_versions(id),
          organization_id     uuid        NULL REFERENCES organizations(id),
          lesson_key          uuid        NOT NULL,
          title               text        NOT NULL,
          lesson_type         text        NOT NULL
                                CHECK (lesson_type IN ('video','article','quiz','coding','assignment','live_link')),
          position            int         NOT NULL CHECK (position >= 0),
          is_required         boolean     NOT NULL DEFAULT true,
          is_free_preview     boolean     NOT NULL DEFAULT false,
          duration_seconds    int         NULL CHECK (duration_seconds >= 0),
          article_body        jsonb       NULL,
          test_id             uuid        NULL,
          coding_problem_id   uuid        NULL,
          assignment_id       uuid        NULL,
          live_url            text        NULL CHECK (live_url IS NULL OR live_url ~ '^https://'),
          est_reading_minutes smallint    NULL CHECK (est_reading_minutes >= 0),
          created_at          timestamptz NOT NULL DEFAULT now(),
          updated_at          timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT uq_lessons_position UNIQUE (course_module_id, position) DEFERRABLE INITIALLY DEFERRED,
          CONSTRAINT uq_lessons_key UNIQUE (course_version_id, lesson_key),
          CONSTRAINT ck_lesson_ref CHECK (
            (lesson_type = 'quiz'       AND test_id IS NOT NULL) OR
            (lesson_type = 'coding'     AND coding_problem_id IS NOT NULL) OR
            (lesson_type = 'assignment' AND assignment_id IS NOT NULL) OR
            (lesson_type = 'live_link'  AND live_url IS NOT NULL) OR
            (lesson_type IN ('video','article')))
        );
        CREATE INDEX ix_lessons_key ON lessons (lesson_key);
        CREATE INDEX ix_lessons_version ON lessons (course_version_id);
        CREATE INDEX ix_lessons_assignment ON lessons (assignment_id) WHERE assignment_id IS NOT NULL;
        COMMENT ON TABLE lessons IS 'Owner: catalog | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE lesson_topics (
          lesson_id        uuid        NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
          topic_id         uuid        NOT NULL,
          organization_id  uuid        NULL REFERENCES organizations(id),
          is_primary       boolean     NOT NULL DEFAULT false,
          created_at       timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (lesson_id, topic_id)
        );
        CREATE UNIQUE INDEX ux_lt_primary ON lesson_topics (lesson_id) WHERE is_primary;
        CREATE INDEX ix_lt_topic ON lesson_topics (topic_id);
        COMMENT ON TABLE lesson_topics IS 'Owner: catalog | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE lesson_assets (
          id                 uuid PRIMARY KEY,
          lesson_id          uuid        NOT NULL REFERENCES lessons(id) ON DELETE CASCADE,
          organization_id    uuid        NULL REFERENCES organizations(id),
          asset_type         text        NOT NULL CHECK (asset_type IN ('video','pdf','image','attachment','captions')),
          provider           text        NOT NULL CHECK (provider IN ('vdocipher','s3')),
          provider_asset_id  text        NULL,
          s3_key             text        NULL,
          mime_type          text        NULL,
          size_bytes         bigint      NULL CHECK (size_bytes >= 0),
          duration_seconds   int         NULL,
          status             text        NOT NULL DEFAULT 'processing'
                               CHECK (status IN ('uploading','processing','available','failed','retired')),
          scan_status        text        NOT NULL DEFAULT 'pending'
                               CHECK (scan_status IN ('pending','clean','infected','not_required')),
          position           int         NOT NULL DEFAULT 0,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_la_provider CHECK ((provider = 'vdocipher' AND provider_asset_id IS NOT NULL)
                                           OR (provider = 's3' AND s3_key IS NOT NULL))
        );
        CREATE UNIQUE INDEX ux_la_vdo ON lesson_assets (lesson_id, provider_asset_id) WHERE provider = 'vdocipher';
        CREATE INDEX ix_la_lesson ON lesson_assets (lesson_id);
        CREATE INDEX ix_la_provider_asset ON lesson_assets (provider_asset_id) WHERE provider_asset_id IS NOT NULL;
        COMMENT ON TABLE lesson_assets IS 'Owner: catalog (status maintained by media) | RLS: TN | Retention: R-CONTENT | PII: P0';

        CREATE TABLE resources (
          id               uuid PRIMARY KEY,
          organization_id  uuid        NULL REFERENCES organizations(id),
          course_id        uuid        NULL REFERENCES courses(id),
          lesson_id        uuid        NULL REFERENCES lessons(id) ON DELETE SET NULL,
          company_id       uuid        NULL,
          title            text        NOT NULL,
          resource_type    text        NOT NULL CHECK (resource_type IN ('file','link','cheatsheet','interview_experience')),
          access_level     text        NOT NULL DEFAULT 'entitled' CHECK (access_level IN ('public','signed_in','entitled')),
          s3_key           text        NULL,
          url              text        NULL CHECK (url IS NULL OR url ~ '^https://'),
          is_public        boolean     NOT NULL DEFAULT false,
          created_by       uuid        NOT NULL REFERENCES users(id),
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_res_target CHECK (num_nonnulls(course_id, lesson_id, company_id) >= 1),
          CONSTRAINT ck_res_payload CHECK (s3_key IS NOT NULL OR url IS NOT NULL),
          CONSTRAINT ck_res_public CHECK (is_public = (access_level = 'public'))
        );
        CREATE INDEX ix_res_course ON resources (course_id) WHERE course_id IS NOT NULL;
        COMMENT ON TABLE resources IS 'Owner: catalog | RLS: TN | Retention: R-CONTENT | PII: P0';
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO td_app")
    op.execute(f"GRANT SELECT ON {', '.join(TABLES)} TO td_readonly")
    for t in TABLES:
        if t != "lesson_topics":
            add_updated_at_trigger(t)
        enable_rls(t, "TN")


def downgrade() -> None:
    op.execute("ALTER TABLE courses DROP CONSTRAINT IF EXISTS fk_courses_current_version")
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
