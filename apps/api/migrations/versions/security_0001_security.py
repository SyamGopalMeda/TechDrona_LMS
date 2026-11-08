"""security: signals, rules, evaluations, restrictions, cases, unblock requests, decisions,
trusted networks, incidents, per-user engine state, exports and bulk lifts

Revision ID: security_0001
Revises:
Create Date: 2026-11-03

database-schema §5 (all security tables RLS family O or NONE). Additions owned by security:
``security_user_state`` (T-step-up / L2 bookkeeping), ``security_counters`` (DB sliding-window
counters for AB-*), ``security_notices`` (event refs for "This wasn't me", SEC-46),
``security_report_exports`` (SEC-32), ``security_bulk_lifts`` (SEC-44/45), plus ``version``
(ETag) columns on cases and unblock requests and lift bookkeeping on restrictions.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls, revoke_app_writes

revision: str = "security_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("security",)
depends_on: str | Sequence[str] | None = ("core_base", "identity_0001", "orgs_0001", "rbac_0001")

TABLES = (
    "security_signals",
    "risk_rules",
    "risk_rule_versions",
    "risk_evaluations",
    "security_cases",
    "account_restrictions",
    "unblock_requests",
    "case_notes",
    "case_decisions",
    "org_trusted_networks",
    "security_incidents",
    "security_user_state",
    "security_counters",
    "security_notices",
    "security_report_exports",
    "security_bulk_lifts",
)

_FAM = "'sharing','takeover','cap','abuse','integrity'"
_REF = "[0-9A-HJKMNP-TV-Z]{6}"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE security_signals (
          id               uuid        NOT NULL,
          occurred_at      timestamptz NOT NULL DEFAULT now(),
          user_id          uuid        NULL,
          family           text        NOT NULL CHECK (family IN ({_FAM})),
          rule_key         text        NOT NULL,
          rule_version     text        NULL,
          category         text        NULL CHECK (category IN ('C','D','N')),
          base_points      numeric(5,2) NOT NULL DEFAULT 0,
          multipliers      jsonb       NOT NULL DEFAULT '{{}}',
          evidence         jsonb       NOT NULL DEFAULT '{{}}',
          source           text        NOT NULL CHECK (source IN ('login','heartbeat_batch','playback','attempt','nightly','system')),
          auth_session_id  uuid        NULL,
          device_id        uuid        NULL,
          is_minor_at_time boolean     NOT NULL,
          suppressed_by_decision_id uuid NULL,
          PRIMARY KEY (id, occurred_at),
          CONSTRAINT ck_sig_minor CHECK (family <> 'sharing' OR NOT is_minor_at_time),
          CONSTRAINT ck_sig_cat CHECK ((family = 'sharing') = (category IS NOT NULL) OR rule_key IN ('SH-M1','HC-01','HC-02'))
        ) PARTITION BY RANGE (occurred_at);
        CREATE TABLE security_signals_default PARTITION OF security_signals DEFAULT;
        CREATE INDEX ix_sig_user_time ON security_signals (user_id, occurred_at DESC);
        CREATE INDEX ix_sig_rule_time ON security_signals (rule_key, occurred_at DESC);
        COMMENT ON TABLE security_signals IS 'Owner: security | RLS: O | append-only (suppression flag only) | partitioned | Retention: R-RISK | PII: P3';

        CREATE TABLE risk_rules (
          id                 uuid PRIMARY KEY,
          key                text        NOT NULL UNIQUE,
          family             text        NOT NULL CHECK (family IN ({_FAM})),
          category           text        NULL CHECK (category IN ('C','D','N')),
          description        text        NOT NULL,
          explanation_key    text        NOT NULL,
          active_version_id  uuid        NULL,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE risk_rules IS 'Owner: security | RLS: NONE | Retention: R-CONTENT | PII: P0';

        CREATE TABLE risk_rule_versions (
          id               uuid PRIMARY KEY,
          rule_id          uuid        NULL REFERENCES risk_rules(id),
          family           text        NOT NULL CHECK (family IN ({_FAM})),
          ruleset_version  text        NOT NULL,
          semver           text        NOT NULL CHECK (semver ~ '^[0-9]+\\.[0-9]+\\.[0-9]+$'),
          definition       jsonb       NOT NULL,
          status           text        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','shadow','active','retired')),
          effective_from   timestamptz NULL,
          shadow_started_at timestamptz NULL,
          shadow_report    jsonb       NULL,
          proposed_by      uuid        NOT NULL REFERENCES users(id),
          approved_by      uuid        NULL REFERENCES users(id),
          approved_at      timestamptz NULL,
          approval_request_id uuid     NULL REFERENCES approval_requests(id),
          status_changed_at timestamptz NULL,
          status_changed_by uuid       NULL REFERENCES users(id),
          status_change_reason text    NULL CHECK (status_change_reason IN ('activation','rollback','retire','circuit_breaker','kill_switch','shadow_start')),
          created_at       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_rrv_approval CHECK (status IN ('draft','shadow') OR status = 'retired' OR (approved_by IS NOT NULL AND approved_by <> proposed_by))
        );
        CREATE UNIQUE INDEX ux_rrv_rule_semver ON risk_rule_versions (coalesce(rule_id, '00000000-0000-0000-0000-000000000000'::uuid), family, semver);
        CREATE UNIQUE INDEX ux_rrv_active_ruleset ON risk_rule_versions (family) WHERE rule_id IS NULL AND status = 'active';
        CREATE UNIQUE INDEX ux_rrv_active_rule ON risk_rule_versions (rule_id) WHERE rule_id IS NOT NULL AND status = 'active';
        ALTER TABLE risk_rules ADD CONSTRAINT fk_rr_active FOREIGN KEY (active_version_id) REFERENCES risk_rule_versions(id);
        COMMENT ON TABLE risk_rule_versions IS 'Owner: security | RLS: NONE | immutable definition | Retention: R-CONTENT | PII: P0';

        CREATE TABLE risk_evaluations (
          id                uuid        NOT NULL,
          evaluated_at      timestamptz NOT NULL DEFAULT now(),
          user_id           uuid        NOT NULL,
          organization_id   uuid        NULL,
          family            text        NOT NULL CHECK (family IN ('sharing','takeover')),
          mode              text        NOT NULL CHECK (mode IN ('enforce','shadow')),
          ruleset_version   text        NOT NULL,
          feed_version      text        NULL,
          trigger           text        NOT NULL CHECK (trigger IN ('login','playback','attempt','rebind','heartbeat_batch',
                                'nightly','policy_shadow','manual_review','verification')),
          "window"          jsonb       NOT NULL,
          signals           jsonb       NOT NULL,
          subtotals         jsonb       NOT NULL,
          repeat_multiplier numeric(3,2) NOT NULL DEFAULT 1.00,
          score             numeric(5,2) NOT NULL CHECK (score BETWEEN 0 AND 100),
          previous_score    numeric(5,2) NULL,
          level_before      smallint    NOT NULL CHECK (level_before BETWEEN 0 AND 4),
          level_after       smallint    NOT NULL CHECK (level_after BETWEEN 0 AND 4),
          gates             jsonb       NOT NULL DEFAULT '{{}}',
          action            text        NOT NULL CHECK (action IN ('none','notice_L1','require_otp_L2','restrict_L3','recommend_L4',
                                'step_up','protect_lock','deescalate')),
          restriction_id    uuid        NULL,
          case_id           uuid        NULL,
          explanation_keys  text[]      NOT NULL DEFAULT '{{}}',
          auth_session_id   uuid        NULL,
          latency_ms        integer     NULL,
          is_minor_at_time  boolean     NOT NULL DEFAULT false,
          PRIMARY KEY (id, evaluated_at),
          CONSTRAINT ck_re_no_auto_l4 CHECK (level_after <= 3 OR level_before = 4),
          CONSTRAINT ck_re_no_minor CHECK (NOT is_minor_at_time)
        ) PARTITION BY RANGE (evaluated_at);
        CREATE TABLE risk_evaluations_default PARTITION OF risk_evaluations DEFAULT;
        CREATE INDEX ix_re_user_time ON risk_evaluations (user_id, family, evaluated_at DESC);
        CREATE INDEX ix_re_level ON risk_evaluations (evaluated_at, level_after) WHERE level_after >= 2;
        COMMENT ON TABLE risk_evaluations IS 'Owner: security | RLS: O | append-only | partitioned | Retention: R-RISK | PII: P3';

        CREATE TABLE security_cases (
          id                     uuid PRIMARY KEY,
          case_ref               text        NOT NULL UNIQUE CHECK (case_ref ~ '^SEC-[0-9]{{4}}-{_REF}$'),
          user_id                uuid        NOT NULL REFERENCES users(id),
          organization_id        uuid        NULL REFERENCES organizations(id),
          family                 text        NOT NULL CHECK (family IN ('sharing','takeover')),
          level                  smallint    NOT NULL CHECK (level BETWEEN 0 AND 4),
          recommended_level      smallint    NULL CHECK (recommended_level BETWEEN 0 AND 4),
          priority               text        NOT NULL DEFAULT 'medium' CHECK (priority IN ('low','medium','high','urgent')),
          status                 text        NOT NULL DEFAULT 'open' CHECK (status IN ('open','under_review','awaiting_user','escalated',
                                     'decided','closed')),
          opened_reason          text        NOT NULL CHECK (opened_reason IN ('engine_L3','engine_recommend_L4','takeover_recovery_failed',
                                     'unblock_request','support_escalation','manual','integrity_referral','engine_hc_L3')),
          assignee_id            uuid        NULL REFERENCES users(id),
          is_high_risk           boolean     NOT NULL DEFAULT false,
          high_risk_reasons      text[]      NOT NULL DEFAULT '{{}}',
          repeat_count           smallint    NOT NULL DEFAULT 0,
          hc_rule                text        NULL,
          sla_first_response_due timestamptz NULL,
          sla_decision_due       timestamptz NULL,
          first_response_at      timestamptz NULL,
          sla_alerted_at         timestamptz NULL,
          escalated_at           timestamptz NULL,
          panel_views            jsonb       NOT NULL DEFAULT '{{}}',
          legal_hold             boolean     NOT NULL DEFAULT false,
          version                integer     NOT NULL DEFAULT 1,
          closed_at              timestamptz NULL,
          created_at             timestamptz NOT NULL DEFAULT now(),
          updated_at             timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_sc_closed CHECK ((status = 'closed') = (closed_at IS NOT NULL))
        );
        CREATE INDEX ix_sc_queue ON security_cases (status, priority, sla_decision_due) WHERE status <> 'closed';
        CREATE INDEX ix_sc_user ON security_cases (user_id, created_at DESC);
        COMMENT ON TABLE security_cases IS 'Owner: security | RLS: O | Retention: R-RISK | PII: P3';

        CREATE TABLE account_restrictions (
          id                  uuid PRIMARY KEY,
          user_id             uuid        NOT NULL REFERENCES users(id),
          level               smallint    NOT NULL CHECK (level BETWEEN 1 AND 4),
          family              text        NOT NULL CHECK (family IN ('sharing','takeover')),
          scope               text        NOT NULL CHECK (scope IN ('learning_access','status_only','protect_lock')),
          source              text        NOT NULL CHECK (source IN ('engine','reviewer')),
          starts_at           timestamptz NOT NULL DEFAULT now(),
          ends_at             timestamptz NULL,
          deferred_until      timestamptz NULL,
          evaluation_id       uuid        NULL,
          case_id             uuid        NULL REFERENCES security_cases(id),
          applied_by          uuid        NULL REFERENCES users(id),
          hc_rule             text        NULL,
          ruleset_version     text        NULL,
          rule_keys           text[]      NOT NULL DEFAULT '{{}}',
          reverify_device_ids uuid[]      NOT NULL DEFAULT '{{}}',
          lift_pending_at     timestamptz NULL,
          ended_at            timestamptz NULL,
          ended_by            uuid        NULL REFERENCES users(id),
          end_reason          text        NULL CHECK (end_reason IN ('expired_reverified','case_decision','superseded','takeover_recovered','deescalated')),
          decision_id         uuid        NULL,
          created_at          timestamptz NOT NULL DEFAULT now(),
          updated_at          timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_ar_l4_human CHECK (level < 4 OR (source = 'reviewer' AND applied_by IS NOT NULL)),
          CONSTRAINT ck_ar_ended CHECK ((ended_at IS NULL) = (end_reason IS NULL)),
          CONSTRAINT ck_ar_l4_lift CHECK (level < 4 OR ended_at IS NULL OR end_reason IN ('case_decision','superseded'))
        );
        CREATE UNIQUE INDEX ux_ar_active_family ON account_restrictions (user_id, family) WHERE ended_at IS NULL;
        CREATE INDEX ix_ar_ends ON account_restrictions (ends_at) WHERE ended_at IS NULL AND ends_at IS NOT NULL;
        CREATE INDEX ix_ar_level_active ON account_restrictions (level, starts_at) WHERE ended_at IS NULL;
        COMMENT ON TABLE account_restrictions IS 'Owner: security | RLS: O | Retention: R-RISK | PII: P3';

        CREATE TABLE unblock_requests (
          id                      uuid PRIMARY KEY,
          reference               text        NOT NULL UNIQUE CHECK (reference ~ '^APL-[0-9]{{4}}-{_REF}$'),
          case_id                 uuid        NOT NULL REFERENCES security_cases(id),
          user_id                 uuid        NOT NULL REFERENCES users(id),
          restriction_id          uuid        NULL REFERENCES account_restrictions(id),
          state                   text        NOT NULL DEFAULT 'draft' CHECK (state IN ('draft','submitted','under_review',
                                      'info_requested','escalated','approved','rejected','closed')),
          closure_reason          text        NULL CHECK (closure_reason IN ('completed','rejected_final','withdrawn','no_response','moot')),
          state_changed_at        timestamptz NOT NULL DEFAULT now(),
          what_happened           text[]      NOT NULL DEFAULT '{{}}',
          explanation             text        NULL CHECK (explanation IS NULL OR char_length(explanation) BETWEEN 30 AND 2000),
          recognised_device_ids   uuid[]      NOT NULL DEFAULT '{{}}',
          unrecognised_device_ids uuid[]      NOT NULL DEFAULT '{{}}',
          lab_location_text       text        NULL CHECK (lab_location_text IS NULL OR char_length(lab_location_text) <= 200),
          attachments             jsonb       NOT NULL DEFAULT '[]',
          preferred_contact       text        NULL CHECK (preferred_contact IN ('in_app','email','sms')),
          declaration_at          timestamptz NULL,
          guardian_assisted       boolean     NOT NULL DEFAULT false,
          is_second_level_appeal  boolean     NOT NULL DEFAULT false,
          appeal_used             boolean     NOT NULL DEFAULT false,
          submitted_at            timestamptz NULL,
          assigned_to             uuid        NULL REFERENCES users(id),
          info_requested_at       timestamptz NULL,
          info_requested_due      timestamptz NULL,
          escalated_at            timestamptz NULL,
          requires_second_approval boolean    NOT NULL DEFAULT false,
          decided_at              timestamptz NULL,
          rejected_by             uuid        NULL REFERENCES users(id),
          timeline                jsonb       NOT NULL DEFAULT '[]',
          idempotency_key         text        NULL,
          version                 integer     NOT NULL DEFAULT 1,
          created_at              timestamptz NOT NULL DEFAULT now(),
          updated_at              timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_ur_submitted CHECK (state = 'draft' OR (submitted_at IS NOT NULL AND explanation IS NOT NULL AND declaration_at IS NOT NULL)),
          CONSTRAINT ck_ur_closed CHECK ((state = 'closed') = (closure_reason IS NOT NULL)),
          UNIQUE (user_id, idempotency_key)
        );
        CREATE UNIQUE INDEX ux_ur_open_per_case ON unblock_requests (case_id)
          WHERE state IN ('draft','submitted','under_review','info_requested','escalated');
        CREATE INDEX ix_ur_user ON unblock_requests (user_id, submitted_at DESC);
        CREATE INDEX ix_ur_queue ON unblock_requests (state, submitted_at) WHERE state IN ('submitted','under_review','info_requested','escalated');
        COMMENT ON TABLE unblock_requests IS 'Owner: security | RLS: O | Retention: R-RISK | PII: P3';

        CREATE TABLE case_notes (
          id                uuid PRIMARY KEY,
          case_id           uuid        NOT NULL REFERENCES security_cases(id),
          author_id         uuid        NULL REFERENCES users(id),
          visibility        text        NOT NULL DEFAULT 'internal' CHECK (visibility IN ('internal','student')),
          body              text        NOT NULL CHECK (char_length(body) BETWEEN 1 AND 4000),
          attachments       jsonb       NOT NULL DEFAULT '[]',
          created_at        timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_cn_case ON case_notes (case_id, created_at);
        COMMENT ON TABLE case_notes IS 'Owner: security | RLS: NONE (API projection) | append-only | Retention: R-RISK | PII: P3';

        CREATE TABLE case_decisions (
          id                     uuid PRIMARY KEY,
          case_id                uuid        NOT NULL REFERENCES security_cases(id),
          unblock_request_id     uuid        NULL REFERENCES unblock_requests(id),
          outcome                text        NOT NULL CHECK (outcome IN ('lift_false_positive','lift_with_warning','lift_conditions',
                                     'uphold','convert_L4','reduce_level')),
          resulting_level        smallint    NULL CHECK (resulting_level BETWEEN 0 AND 4),
          rationale              text        NOT NULL,
          student_summary        text        NULL CHECK (student_summary IS NULL OR char_length(student_summary) >= 50),
          conditions             jsonb       NOT NULL DEFAULT '{{}}',
          extension_days         smallint    NOT NULL DEFAULT 0 CHECK (extension_days >= 0),
          false_positive_rule_keys text[]    NOT NULL DEFAULT '{{}}',
          decided_by             uuid        NOT NULL REFERENCES users(id),
          requires_second_approval boolean   NOT NULL DEFAULT false,
          approved_by            uuid        NULL REFERENCES users(id),
          approved_at            timestamptz NULL,
          approval_request_id    uuid        NULL REFERENCES approval_requests(id),
          created_at             timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_cd_approval_link CHECK (NOT requires_second_approval OR approval_request_id IS NOT NULL),
          CONSTRAINT ck_cd_second CHECK (approved_by IS NULL OR approved_by <> decided_by),
          CONSTRAINT ck_cd_needs CHECK (NOT requires_second_approval OR (approved_by IS NOT NULL AND approved_at IS NOT NULL)),
          CONSTRAINT ck_cd_reject_summary CHECK (outcome <> 'uphold' OR student_summary IS NOT NULL)
        );
        CREATE INDEX ix_cd_case ON case_decisions (case_id, created_at);
        CREATE INDEX ix_cd_outcome ON case_decisions (outcome, created_at);
        ALTER TABLE account_restrictions ADD CONSTRAINT fk_ar_decision FOREIGN KEY (decision_id) REFERENCES case_decisions(id);
        COMMENT ON TABLE case_decisions IS 'Owner: security | RLS: NONE (API projection) | append-only | Retention: R-RISK | PII: P3';

        CREATE TABLE org_trusted_networks (
          id               uuid PRIMARY KEY,
          organization_id  uuid        NOT NULL REFERENCES organizations(id),
          cidr             cidr        NULL CHECK (cidr IS NULL OR (family(cidr) = 4 AND masklen(cidr) >= 16) OR family(cidr) = 6),
          asn              integer     NULL,
          status           text        NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed','verified','rejected','expired')),
          proposed_by      uuid        NOT NULL REFERENCES users(id),
          verified_by      uuid        NULL REFERENCES users(id),
          verified_at      timestamptz NULL,
          evidence_ref     text        NULL,
          decision_note    text        NULL,
          expires_at       timestamptz NULL,
          created_at       timestamptz NOT NULL DEFAULT now(),
          updated_at       timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_otn_target CHECK (num_nonnulls(cidr, asn) = 1),
          CONSTRAINT ck_otn_verify CHECK (status <> 'verified' OR (verified_by IS NOT NULL AND verified_by <> proposed_by))
        );
        CREATE INDEX ix_otn_org ON org_trusted_networks (organization_id) WHERE status = 'verified';
        CREATE INDEX gist_otn_cidr ON org_trusted_networks USING gist (cidr inet_ops) WHERE status = 'verified';
        COMMENT ON TABLE org_trusted_networks IS 'Owner: security | RLS: T | Retention: R-ORG | PII: P0/P1';

        CREATE TABLE security_incidents (
          id                   uuid PRIMARY KEY,
          incident_ref         text        NOT NULL UNIQUE CHECK (incident_ref ~ '^INC-[0-9]{{4}}-{_REF}$'),
          title                text        NOT NULL,
          severity             text        NOT NULL CHECK (severity IN ('low','medium','high','critical')),
          status               text        NOT NULL DEFAULT 'detected' CHECK (status IN ('detected','triaged','contained','notified',
                                   'remediated','closed')),
          detected_at          timestamptz NOT NULL,
          is_personal_data_breach boolean  NOT NULL DEFAULT false,
          certin_reportable    boolean     NOT NULL DEFAULT false,
          certin_due_at        timestamptz NULL,
          certin_reported_at   timestamptz NULL,
          dpb_intimation_due_at timestamptz NULL,
          dpb_intimated_at     timestamptz NULL,
          dpb_report_due_at    timestamptz NULL,
          dpb_reported_at      timestamptz NULL,
          principals_notified_at timestamptz NULL,
          affected_data        jsonb       NOT NULL DEFAULT '{{}}',
          timeline             jsonb       NOT NULL DEFAULT '[]',
          owner_id             uuid        NOT NULL REFERENCES users(id),
          legal_hold           boolean     NOT NULL DEFAULT true,
          version              integer     NOT NULL DEFAULT 1,
          closed_at            timestamptz NULL,
          created_at           timestamptz NOT NULL DEFAULT now(),
          updated_at           timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_si_certin CHECK (NOT certin_reportable OR certin_due_at IS NOT NULL)
        );
        CREATE INDEX ix_si_open ON security_incidents (status, certin_due_at) WHERE status <> 'closed';
        COMMENT ON TABLE security_incidents IS 'Owner: security | RLS: NONE (API: security_reviewer/super_admin) | Retention: R-PRIV | PII: P2/P3';

        CREATE TABLE security_user_state (
          user_id                   uuid PRIMARY KEY REFERENCES users(id),
          sharing_score             numeric(5,2) NOT NULL DEFAULT 0,
          takeover_score            numeric(5,2) NOT NULL DEFAULT 0,
          sharing_level             smallint    NOT NULL DEFAULT 0 CHECK (sharing_level BETWEEN 0 AND 4),
          l2_issued_at              timestamptz NULL,
          l2_passed_at              timestamptz NULL,
          step_up_required_since    timestamptz NULL,
          step_up_cleared_at        timestamptz NULL,
          last_evaluated_at         timestamptz NULL,
          created_at                timestamptz NOT NULL DEFAULT now(),
          updated_at                timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE security_user_state IS 'Owner: security | RLS: O | Retention: R-RISK | PII: P3';

        CREATE TABLE security_counters (
          counter_key   text        NOT NULL,
          bucket_start  timestamptz NOT NULL,
          count         integer     NOT NULL DEFAULT 0,
          PRIMARY KEY (counter_key, bucket_start)
        );
        COMMENT ON TABLE security_counters IS 'Owner: security | RLS: NONE (hashed source keys only) | Retention: 2 days | PII: P1';

        CREATE TABLE security_notices (
          id               uuid PRIMARY KEY,
          event_ref        text        NOT NULL UNIQUE CHECK (event_ref ~ '^ACC-[0-9]{{4}}-{_REF}$'),
          user_id          uuid        NOT NULL REFERENCES users(id),
          kind             text        NOT NULL CHECK (kind IN ('replay','new_sign_in','new_country')),
          rule_key         text        NOT NULL,
          auth_session_id  uuid        NULL,
          created_at       timestamptz NOT NULL DEFAULT now(),
          acknowledged_at  timestamptz NULL,
          disowned_at      timestamptz NULL
        );
        CREATE INDEX ix_sn_user ON security_notices (user_id, created_at DESC);
        COMMENT ON TABLE security_notices IS 'Owner: security | RLS: O | Retention: R-SEC | PII: P1';

        CREATE TABLE security_report_exports (
          id                  uuid PRIMARY KEY,
          report_key          text        NOT NULL,
          requested_by        uuid        NOT NULL REFERENCES users(id),
          filters             jsonb       NOT NULL DEFAULT '{{}}',
          include_per_user_rows boolean   NOT NULL DEFAULT false,
          contains_pii        boolean     NOT NULL DEFAULT false,
          reason_code         text        NULL,
          reason              text        NULL,
          status              text        NOT NULL CHECK (status IN ('awaiting_approval','running','completed','rejected','expired','failed')),
          approval_request_id uuid        NULL REFERENCES approval_requests(id),
          approved_by         uuid        NULL REFERENCES users(id),
          row_count           integer     NULL,
          content             text        NULL,
          watermark           text        NULL,
          download_expires_at timestamptz NULL,
          created_at          timestamptz NOT NULL DEFAULT now(),
          completed_at        timestamptz NULL,
          updated_at          timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE security_report_exports IS 'Owner: security | RLS: NONE (requester only via API) | Retention: 30 days | PII: P3';

        CREATE TABLE security_bulk_lifts (
          id                  uuid PRIMARY KEY,
          selector            jsonb       NOT NULL,
          reason              text        NOT NULL,
          extension_credit    boolean     NOT NULL DEFAULT true,
          requested_by        uuid        NOT NULL REFERENCES users(id),
          approval_request_id uuid        NULL REFERENCES approval_requests(id),
          matched_restriction_ids uuid[]  NOT NULL DEFAULT '{{}}',
          status              text        NOT NULL CHECK (status IN ('awaiting_approval','running','completed','rejected','expired')),
          progress            jsonb       NOT NULL DEFAULT '{{}}',
          created_at          timestamptz NOT NULL DEFAULT now(),
          completed_at        timestamptz NULL,
          updated_at          timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE security_bulk_lifts IS 'Owner: security | RLS: NONE (API) | Retention: R-AUDIT | PII: P0';
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO td_app")
    op.execute(f"GRANT SELECT ON {', '.join(TABLES)} TO td_readonly")
    op.execute("REVOKE ALL ON security_signals_default, risk_evaluations_default FROM td_app, td_readonly")
    op.execute("REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON risk_rules FROM td_app")
    op.execute("GRANT UPDATE (active_version_id, updated_at) ON risk_rules TO td_app")
    # Append-only: evaluations, notes, decisions. Signals allow UPDATE only for suppression.
    revoke_app_writes("risk_evaluations")
    revoke_app_writes("case_notes")
    revoke_app_writes("case_decisions")
    op.execute("REVOKE UPDATE, DELETE, TRUNCATE ON security_signals FROM td_app")
    op.execute("GRANT UPDATE (suppressed_by_decision_id) ON security_signals TO td_app")
    for t in (
        "risk_rules",
        "security_cases",
        "account_restrictions",
        "unblock_requests",
        "org_trusted_networks",
        "security_incidents",
        "security_user_state",
        "security_report_exports",
        "security_bulk_lifts",
    ):
        add_updated_at_trigger(t)
    for t in (
        "security_signals",
        "security_signals_default",
        "risk_evaluations",
        "risk_evaluations_default",
        "security_cases",
        "account_restrictions",
        "unblock_requests",
        "security_user_state",
        "security_notices",
    ):
        enable_rls(t, "O")
    enable_rls("org_trusted_networks", "T")
    _seed_rules()


def _seed_rules() -> None:
    from app.core.ids import uuid7
    from app.modules.security.catalogue import RULES

    rows = ",\n".join(
        "('{id}', '{key}', '{fam}', {cat}, '{desc}', '{expl}')".format(
            id=uuid7(),
            key=r.key,
            fam=r.family,
            cat=f"'{r.category}'" if r.category else "NULL",
            desc=r.description.replace("'", "''"),
            expl=r.explanation_key,
        )
        for r in RULES
    )
    op.execute(
        f"INSERT INTO risk_rules (id, key, family, category, description, explanation_key) VALUES {rows} "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE IF EXISTS risk_rules DROP CONSTRAINT IF EXISTS fk_rr_active")
    op.execute("ALTER TABLE IF EXISTS account_restrictions DROP CONSTRAINT IF EXISTS fk_ar_decision")
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
