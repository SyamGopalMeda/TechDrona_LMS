"""analytics: raw events, heartbeats, engagement intervals, aggregates, mastery, security feed

Revision ID: analytics_0001
Revises: (branch root)
Create Date: 2026-11-03

database-schema §12 / analytics-event-schema §4.2. Deviations (owner = analytics, documented in
app/modules/analytics/README.md):

* Partitioned tables get a DEFAULT partition only (pg_partman / ``maint.*`` premake is not
  available yet); retention uses batched DELETE until ``maint.drop_expired_partitions`` exists.
* ``activity_heartbeats.sample_interval_ms`` + ``editor_focused`` (hidden-playback credit and the
  coding evidence rule need them); ``engagement_intervals.last_sample_at`` (attribution
  tie-break) and close reasons ``blur``/``mode_change``/``gap``; mode ``interactive|mixed|media``.
* ``daily_learning_aggregates.entity_kind`` adds ``organization`` (per-org rollup source, so a
  D2C purchase never rolls up to a college) and ``lesson_asset``.
* ``topic_mastery``: ``topic_id`` is a soft reference (catalog ``topics`` not migrated yet);
  extra decayed-sum columns for weighted accuracy; band adds ``insufficient_data``.
* ``question_item_stats.question_version_id`` soft reference; ``video_watch_coverage.duration_s``
  nullable until the catalog exposes asset durations.
* Ops tables: ``analytics_job_state`` (builder watermarks) and ``analytics_consumed_events``
  (idempotent outbox consumption).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import enable_rls

revision: str = "analytics_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("analytics",)
depends_on: str | Sequence[str] | None = ("core_base_0001", "identity_0001", "orgs_0001")

PARTITIONED = ("analytics_events", "activity_heartbeats", "engagement_intervals")
U_TABLES = (
    "analytics_events",
    "activity_heartbeats",
    "engagement_intervals",
    "daily_learning_aggregates",
    "weekly_learning_aggregates",
    "video_watch_coverage",
    "topic_mastery",
)
ALL_TABLES = (
    *U_TABLES,
    "cohort_learning_aggregates",
    "route_daily_aggregates",
    "question_item_stats",
    "security_activity_feed_daily",
    "analytics_dirty_days",
    "analytics_ingest_rejections",
    "analytics_job_state",
    "analytics_consumed_events",
)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE analytics_events (
          event_id          uuid        NOT NULL,
          event_ts          timestamptz NOT NULL,
          event_type        text        NOT NULL,
          schema_version    smallint    NOT NULL,
          source            text        NOT NULL CHECK (source IN ('client','server')),
          purpose           text        NOT NULL CHECK (purpose IN ('learning','product')),
          user_id           uuid        NOT NULL,
          organization_id   uuid        NULL,
          auth_session_id   uuid        NULL,
          device_id         uuid        NULL,
          tab_id            uuid        NULL,
          page_instance_id  uuid        NULL,
          seq               int         NULL CHECK (seq >= 0),
          route             text        NULL,
          surface           text        NULL,
          course_id         uuid        NULL,
          lesson_id         uuid        NULL,
          lesson_asset_id   uuid        NULL,
          topic_id          uuid        NULL,
          question_id       uuid        NULL,
          test_attempt_id   uuid        NULL,
          coding_problem_id uuid        NULL,
          occurred_at       timestamptz NOT NULL,
          received_at       timestamptz NOT NULL DEFAULT now(),
          effective_at      timestamptz NOT NULL,
          skew_ms           integer     NOT NULL,
          privacy_tier      text        NOT NULL CHECK (privacy_tier IN ('adult','minor')),
          ingest_flags      text[]      NOT NULL DEFAULT '{}' CHECK (ingest_flags <@
              ARRAY['large_skew','clock_jump','late','seq_gap',
                                           'rate_capped','implausible_clamped']::text[]),
          measurement_version text      NOT NULL DEFAULT 'tm-1.0',
          payload           jsonb       NOT NULL DEFAULT '{}' CHECK (octet_length(payload::text) <= 4096),
          PRIMARY KEY (event_id, event_ts),
          CONSTRAINT ck_aev_minor_purpose CHECK (privacy_tier = 'adult' OR purpose = 'learning')
        ) PARTITION BY RANGE (event_ts);
        CREATE TABLE analytics_events_default PARTITION OF analytics_events DEFAULT;
        CREATE INDEX ix_aev_user_time ON analytics_events (user_id, event_ts);
        CREATE INDEX ix_aev_user_eff ON analytics_events (user_id, effective_at);
        CREATE INDEX ix_aev_page_seq ON analytics_events (page_instance_id, seq);
        CREATE INDEX brin_aev_received ON analytics_events USING brin (received_at);
        COMMENT ON TABLE analytics_events IS 'Owner: analytics | RLS: U | partitioned (event_ts) |
            Retention: R-AN-RAW 90 d | PII: P1';

        CREATE TABLE activity_heartbeats (
          event_id          uuid        NOT NULL,
          event_ts          timestamptz NOT NULL,
          user_id           uuid        NOT NULL,
          organization_id   uuid        NULL,
          auth_session_id   uuid        NULL,
          device_id         uuid        NULL,
          tab_id            uuid        NOT NULL,
          page_instance_id  uuid        NOT NULL,
          seq               int         NOT NULL CHECK (seq >= 0),
          effective_at      timestamptz NOT NULL,
          received_at       timestamptz NOT NULL DEFAULT now(),
          kind              text        NOT NULL CHECK (kind IN ('engaged','keepalive')),
          active_ms         int         NOT NULL CHECK (active_ms BETWEEN 0 AND 20000),
          sample_interval_ms int        NULL CHECK (sample_interval_ms IS NULL
              OR sample_interval_ms BETWEEN 1000 AND 330000),
          state_bits        smallint    NOT NULL,
          surface           text        NOT NULL,
          route             text        NULL,
          privacy_tier      text        NOT NULL DEFAULT 'minor' CHECK (privacy_tier IN ('adult','minor')),
          course_id         uuid        NULL,
          lesson_id         uuid        NULL,
          lesson_asset_id   uuid        NULL,
          topic_id          uuid        NULL,
          question_id       uuid        NULL,
          test_attempt_id   uuid        NULL,
          coding_problem_id uuid        NULL,
          media_position_s  numeric(9,2) NULL,
          media_rate        numeric(3,2) NULL CHECK (media_rate IS NULL OR media_rate BETWEEN 0.25 AND 2.0),
          played_ranges     int4range[] NULL,
          edit_ops          int         NULL CHECK (edit_ops IS NULL OR edit_ops BETWEEN 0 AND 5000),
          editor_focused    boolean     NULL,
          scroll_depth_pct  smallint    NULL CHECK (scroll_depth_pct IS NULL
              OR scroll_depth_pct BETWEEN 0 AND 100),
          input_events      int         NULL CHECK (input_events IS NULL OR input_events BETWEEN 0 AND 1000),
          ingest_flags      text[]      NOT NULL DEFAULT '{}',
          PRIMARY KEY (event_id, event_ts)
        ) PARTITION BY RANGE (event_ts);
        CREATE TABLE activity_heartbeats_default PARTITION OF activity_heartbeats DEFAULT;
        CREATE INDEX ix_hb_user_time ON activity_heartbeats (user_id, event_ts);
        CREATE INDEX ix_hb_page_seq ON activity_heartbeats (page_instance_id, seq);
        CREATE INDEX ix_hb_user_device_eff ON activity_heartbeats (user_id, device_id,
            effective_at) WHERE kind = 'engaged';
        CREATE INDEX ix_hb_user_eff ON activity_heartbeats (user_id, effective_at);
        CREATE INDEX brin_hb_received ON activity_heartbeats USING brin (received_at);
        COMMENT ON TABLE activity_heartbeats IS 'Owner: analytics | RLS: U | partitioned (event_ts) |
            Retention: R-AN-HB 35 d | PII: P1';

        CREATE TABLE engagement_intervals (
          id                uuid        NOT NULL,
          started_at        timestamptz NOT NULL,
          ended_at          timestamptz NULL,
          last_sample_at    timestamptz NOT NULL,
          provisional_end   timestamptz NOT NULL,
          user_id           uuid        NOT NULL,
          organization_id   uuid        NULL,
          auth_session_id   uuid        NULL,
          device_id         uuid        NULL,
          tab_id            uuid        NOT NULL,
          page_instance_id  uuid        NOT NULL,
          surface           text        NOT NULL,
          mode              text        NOT NULL CHECK (mode IN ('interactive','mixed','media')),
          course_id         uuid        NULL,
          lesson_id         uuid        NULL,
          lesson_asset_id   uuid        NULL,
          topic_id          uuid        NULL,
          question_id       uuid        NULL,
          test_attempt_id   uuid        NULL,
          coding_problem_id uuid        NULL,
          active_s          numeric(10,3) NOT NULL DEFAULT 0 CHECK (active_s >= 0),
          heartbeat_count   int         NOT NULL DEFAULT 0,
          close_reason      text        NULL CHECK (close_reason IN
              ('idle','hidden','blur','pagehide','navigate','grace_timeout',
                                           'session_ended','mode_change','gap')),
          flags             text[]      NOT NULL DEFAULT '{}' CHECK (flags <@
              ARRAY['hidden_playback','clock_jump','seq_gap','late']::text[]),
          is_open           boolean     NOT NULL DEFAULT true,
          privacy_tier      text        NOT NULL CHECK (privacy_tier IN ('adult','minor')),
          measurement_version text      NOT NULL,
          built_at          timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (id, started_at),
          CONSTRAINT ck_ei_open CHECK (is_open = (ended_at IS NULL)),
          CONSTRAINT ck_ei_order CHECK (ended_at IS NULL OR ended_at >= started_at)
        ) PARTITION BY RANGE (started_at);
        CREATE TABLE engagement_intervals_default PARTITION OF engagement_intervals DEFAULT;
        CREATE INDEX ix_ei_user_time ON engagement_intervals (user_id, started_at);
        CREATE INDEX ix_ei_page ON engagement_intervals (page_instance_id);
        CREATE INDEX ix_ei_open ON engagement_intervals (page_instance_id) WHERE is_open;
        COMMENT ON TABLE engagement_intervals IS 'Owner: analytics | RLS: U | partitioned (started_at) |
            Retention: R-AN-INT 13 months | PII: P1';

        CREATE TABLE daily_learning_aggregates (
          user_id               uuid        NOT NULL,
          activity_date         date        NOT NULL,
          entity_kind           text        NOT NULL CHECK (entity_kind IN
              ('_total','course','lesson','topic','test_attempt',
                                               'coding_problem','organization','lesson_asset')),
          entity_id             uuid        NOT NULL,
          organization_id       uuid        NULL,
          course_id             uuid        NULL,
          topic_id              uuid        NULL,
          category_topic_id     uuid        NULL,
          m1_session_elapsed_s  int         NULL CHECK (entity_kind = '_total'
              OR m1_session_elapsed_s IS NULL),
          m2_active_s           int         NOT NULL DEFAULT 0,
          m3_video_playback_s   int         NOT NULL DEFAULT 0,
          m4_assessment_s       int         NOT NULL DEFAULT 0,
          m5_learning_s         int         NOT NULL DEFAULT 0,
          assessment_active_s   int         NOT NULL DEFAULT 0,
          questions_attempted   int         NOT NULL DEFAULT 0,
          questions_correct     int         NOT NULL DEFAULT 0,
          first_attempt_correct int         NOT NULL DEFAULT 0,
          code_runs             int         NOT NULL DEFAULT 0,
          code_submissions      int         NOT NULL DEFAULT 0,
          code_accepted         int         NOT NULL DEFAULT 0,
          lessons_completed     int         NOT NULL DEFAULT 0,
          video_coverage_gain_s int         NOT NULL DEFAULT 0,
          implausible_day       boolean     NOT NULL DEFAULT false,
          privacy_tier          text        NOT NULL CHECK (privacy_tier IN ('adult','minor')),
          measurement_version   text        NOT NULL,
          is_frozen             boolean     NOT NULL DEFAULT false,
          computed_at           timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (user_id, activity_date, entity_kind, entity_id),
          CONSTRAINT ck_dla_order CHECK (m5_learning_s <= m2_active_s OR entity_kind <> '_total')
        );
        CREATE INDEX ix_dla_org_date ON daily_learning_aggregates (organization_id, activity_date)
            WHERE organization_id IS NOT NULL;
        CREATE INDEX ix_dla_course_date ON daily_learning_aggregates (course_id, activity_date)
            WHERE course_id IS NOT NULL;
        CREATE INDEX ix_dla_kind_date ON daily_learning_aggregates (entity_kind, activity_date);
        COMMENT ON TABLE daily_learning_aggregates IS 'Owner: analytics | RLS: U | Retention: R-AN-AGG 24
            months | PII: P1';

        CREATE TABLE weekly_learning_aggregates (
          user_id              uuid        NOT NULL,
          iso_week_start       date        NOT NULL CHECK (extract(isodow FROM iso_week_start) = 1),
          entity_kind          text        NOT NULL CHECK (entity_kind IN
              ('_total','course','topic','organization')),
          entity_id            uuid        NOT NULL,
          organization_id      uuid        NULL,
          m2_active_s          int         NOT NULL DEFAULT 0,
          m3_video_playback_s  int         NOT NULL DEFAULT 0,
          m4_assessment_s      int         NOT NULL DEFAULT 0,
          m5_learning_s        int         NOT NULL DEFAULT 0,
          active_days          smallint    NOT NULL DEFAULT 0 CHECK (active_days BETWEEN 0 AND 7),
          privacy_tier         text        NOT NULL CHECK (privacy_tier IN ('adult','minor')),
          measurement_version  text        NOT NULL,
          computed_at          timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (user_id, iso_week_start, entity_kind, entity_id)
        );
        CREATE INDEX ix_wla_org_week ON weekly_learning_aggregates (organization_id,
            iso_week_start) WHERE organization_id IS NOT NULL;
        COMMENT ON TABLE weekly_learning_aggregates IS 'Owner: analytics | RLS: U | Retention: R-AN-AGG |
            PII: P1';

        CREATE TABLE cohort_learning_aggregates (
          id                   uuid PRIMARY KEY,
          organization_id      uuid        NULL,
          batch_id             uuid        NULL,
          period_kind          text        NOT NULL CHECK (period_kind IN ('day','week')),
          period_start         date        NOT NULL,
          entity_kind          text        NOT NULL CHECK (entity_kind IN
              ('_total','course','topic','category','test')),
          entity_id            uuid        NULL,
          learners_enrolled    int         NULL,
          learners_active      int         NULL,
          m5_sum_s             bigint      NULL,
          m5_p50_s             int         NULL,
          m5_p90_s             int         NULL,
          completions          int         NULL,
          accuracy             numeric(5,4) NULL,
          score_deciles        numeric(7,2)[] NULL,
          suppressed           boolean     NOT NULL DEFAULT false,
          measurement_version  text        NOT NULL,
          computed_at          timestamptz NOT NULL DEFAULT now(),
          UNIQUE NULLS NOT DISTINCT (organization_id, batch_id, period_kind, period_start, entity_kind,
              entity_id),
          CONSTRAINT ck_cla_suppressed CHECK (NOT suppressed OR (learners_active IS NULL AND m5_sum_s IS NULL
                                              AND m5_p50_s IS NULL AND m5_p90_s IS NULL AND accuracy IS NULL))
        );
        CREATE INDEX ix_cla_org_period ON cohort_learning_aggregates (organization_id, period_start);
        COMMENT ON TABLE cohort_learning_aggregates IS 'Owner: analytics | RLS: T (NULL org = platform) |
            Retention: R-AN-COHORT | PII: P0';

        CREATE TABLE route_daily_aggregates (
          route                text        NOT NULL,
          activity_date        date        NOT NULL,
          views                int         NOT NULL DEFAULT 0,
          unique_users_hll     bytea       NULL,
          unique_users_est     int         NULL,
          m2_p50_s             int         NULL,
          bounce_count         int         NOT NULL DEFAULT 0,
          buffering_events     int         NOT NULL DEFAULT 0,
          computed_at          timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (route, activity_date)
        );
        COMMENT ON TABLE route_daily_aggregates IS 'Owner: analytics | RLS: NONE (no user ids; adults
            with analytics_product only) | PII: P0';

        CREATE TABLE video_watch_coverage (
          user_id              uuid        NOT NULL,
          lesson_asset_id      uuid        NOT NULL,
          organization_id      uuid        NULL,
          lesson_id            uuid        NULL,
          covered_ranges       int4range[] NOT NULL DEFAULT '{}',
          covered_s            numeric(10,1) NOT NULL DEFAULT 0,
          coverage_pct         numeric(5,2) NOT NULL DEFAULT 0 CHECK (coverage_pct BETWEEN 0 AND 100),
          duration_s           int         NULL CHECK (duration_s IS NULL OR duration_s > 0),
          last_position_s      int         NULL,
          updated_at           timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (user_id, lesson_asset_id)
        );
        COMMENT ON TABLE video_watch_coverage IS 'Owner: analytics | RLS: U | Retention: R-AN-AGG | PII: P1';

        CREATE TABLE topic_mastery (
          user_id              uuid        NOT NULL REFERENCES users(id),
          topic_id             uuid        NOT NULL,
          organization_id      uuid        NULL REFERENCES organizations(id),
          theta                numeric(6,3) NOT NULL DEFAULT 0,
          n_eff                numeric(8,2) NOT NULL DEFAULT 0,
          attempts             int         NOT NULL DEFAULT 0,
          correct              int         NOT NULL DEFAULT 0,
          weighted_accuracy    numeric(5,4) NOT NULL DEFAULT 0 CHECK (weighted_accuracy BETWEEN 0 AND 1),
          wa_num               double precision NOT NULL DEFAULT 0,
          wa_den               double precision NOT NULL DEFAULT 0,
          band                 text        NOT NULL DEFAULT 'not_started' CHECK (band IN
              ('not_started','insufficient_data','weak',
                                              'developing','proficient','strong')),
          avg_time_ms          int         NULL,
          last_practiced_at    timestamptz NULL,
          model_version        text        NOT NULL,
          updated_at           timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (user_id, topic_id)
        );
        CREATE INDEX ix_tm_user_band ON topic_mastery (user_id, band);
        CREATE INDEX ix_tm_topic ON topic_mastery (topic_id);
        COMMENT ON TABLE topic_mastery IS 'Owner: analytics (single writer) | RLS: U | Retention:
            R-AN-AGG | PII: P1';

        CREATE TABLE question_item_stats (
          question_version_id  uuid PRIMARY KEY,
          n_first              int         NOT NULL DEFAULT 0,
          p_value              numeric(5,4) NULL,
          median_time_s        int         NULL,
          skip_rate            numeric(5,4) NULL,
          option_dist          jsonb       NULL,
          point_biserial       numeric(5,4) NULL,
          difficulty_b         numeric(6,3) NULL,
          n_updates            int         NOT NULL DEFAULT 0,
          review_flag          boolean     NOT NULL DEFAULT false,
          computed_at          timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE question_item_stats IS 'Owner: analytics | RLS: NONE (aggregate; k_min.item) |
            PII: P0';

        CREATE TABLE security_activity_feed_daily (
          user_id                       uuid        NOT NULL,
          activity_date                 date        NOT NULL,
          privacy_tier                  text        NOT NULL CHECK (privacy_tier = 'adult'),
          active_devices                smallint    NOT NULL DEFAULT 0,
          multi_device_overlap_s        int         NOT NULL DEFAULT 0,
          max_concurrent_active_page_instances smallint NOT NULL DEFAULT 0,
          active_hours_bitmap           int         NOT NULL DEFAULT 0 CHECK (active_hours_bitmap BETWEEN
              0 AND 16777215),
          implausible_day               boolean     NOT NULL DEFAULT false,
          plausibility_violations       jsonb       NOT NULL DEFAULT '{}',
          clock_jump_count              int         NOT NULL DEFAULT 0,
          large_skew_count              int         NOT NULL DEFAULT 0,
          feed_version                  text        NOT NULL,
          computed_at                   timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (user_id, activity_date)
        );
        COMMENT ON TABLE security_activity_feed_daily IS 'Owner: analytics | RLS: O | adults +
            security_monitoring only | Retention: R-AN-FEED 180 d | PII: P1';

        CREATE TABLE analytics_dirty_days (
          user_id              uuid        NOT NULL,
          activity_date        date        NOT NULL,
          reason               text        NOT NULL CHECK (reason IN
              ('late_event','backfill','tm_version_change','erasure',
                                              'interval_rebuild','server_event')),
          marked_at            timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (user_id, activity_date)
        );
        COMMENT ON TABLE analytics_dirty_days IS 'Owner: analytics | RLS: O | ops | PII: P1';

        CREATE TABLE analytics_ingest_rejections (
          hour_start           timestamptz NOT NULL,
          code                 text        NOT NULL CHECK (code IN
              ('unknown_event_type','unsupported_schema_version','server_only_event',
                                  'purpose_not_permitted','event_too_old','event_in_future','invalid_payload','payload_too_large'
                                      ,
                                  'entity_not_entitled','rate_capped','uuid_time_mismatch')),
          event_type           text        NOT NULL DEFAULT '_unknown',
          count                bigint      NOT NULL DEFAULT 0,
          PRIMARY KEY (hour_start, code, event_type)
        );
        COMMENT ON TABLE analytics_ingest_rejections IS 'Owner: analytics | RLS: NONE | counters only |
            Retention: 90 d | PII: P0';

        CREATE TABLE analytics_job_state (
          job                  text        PRIMARY KEY,
          watermark            timestamptz NULL,
          last_run_at          timestamptz NULL,
          last_duration_ms     int         NULL,
          last_result          jsonb       NOT NULL DEFAULT '{}'
        );
        COMMENT ON TABLE analytics_job_state IS 'Owner: analytics | RLS: NONE | ops | PII: P0';

        CREATE TABLE analytics_consumed_events (
          outbox_event_id      uuid        PRIMARY KEY,
          event_type           text        NOT NULL,
          consumed_at          timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE analytics_consumed_events IS 'Owner: analytics | RLS: NONE | outbox consumer
            idempotency | PII: P0';
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(ALL_TABLES)} TO td_app")
    op.execute(f"GRANT SELECT ON {', '.join(ALL_TABLES)} TO td_readonly")
    defaults = ", ".join(f"{t}_default" for t in PARTITIONED)
    op.execute(f"REVOKE ALL ON {defaults} FROM td_app, td_readonly")
    for t in U_TABLES:
        enable_rls(t, "U")
    for t in PARTITIONED:
        enable_rls(f"{t}_default", "U")
    enable_rls("cohort_learning_aggregates", "T")
    enable_rls("security_activity_feed_daily", "O")
    enable_rls("analytics_dirty_days", "O")


def downgrade() -> None:
    for t in reversed(ALL_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
