"""sessions: devices, user_devices, auth_sessions, login_attempts, session_network_observations

Revision ID: sessions_0001
Revises:
Create Date: 2026-11-03

database-schema §4. Partitioned tables get a DEFAULT partition here (pg_partman premake and
395-day drops are registered by the maintenance job later, like audit_log).
``playback_sessions`` is created with the media module (Planned).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls, revoke_app_writes

revision: str = "sessions_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("sessions",)
depends_on: str | Sequence[str] | None = ("core_base", "identity_0001", "orgs_0001")

TABLES = ("devices", "user_devices", "auth_sessions", "login_attempts", "session_network_observations")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE devices (
          id                   uuid PRIMARY KEY,
          device_key_hash      bytea       NOT NULL CHECK (octet_length(device_key_hash) = 32),
          key_version          smallint    NOT NULL DEFAULT 1 CHECK (key_version >= 1),
          client_type          text        NOT NULL CHECK (client_type IN ('web','android','ios')),
          ua_family            text        NULL,
          os_family            text        NULL,
          device_class         text        NULL CHECK (device_class IN ('desktop','mobile','tablet','unknown')),
          fp_hash              bytea       NULL CHECK (fp_hash IS NULL OR octet_length(fp_hash) = 32),
          fp_epoch             int         NULL,
          shared_organization_id uuid      NULL REFERENCES organizations(id),
          shared_registered_by uuid        NULL REFERENCES users(id),
          shared_registered_at timestamptz NULL,
          label_hint           text        NULL,
          first_seen_at        timestamptz NOT NULL DEFAULT now(),
          last_seen_at         timestamptz NOT NULL DEFAULT now(),
          created_at           timestamptz NOT NULL DEFAULT now(),
          updated_at           timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_dev_fp CHECK ((fp_hash IS NULL) = (fp_epoch IS NULL)),
          CONSTRAINT ck_dev_shared CHECK ((shared_organization_id IS NULL) = (shared_registered_by IS NULL))
        );
        CREATE UNIQUE INDEX ux_devices_key ON devices (device_key_hash);
        CREATE INDEX ix_devices_fp ON devices (fp_hash, fp_epoch) WHERE fp_hash IS NOT NULL;
        CREATE INDEX ix_devices_last_seen ON devices (last_seen_at);
        COMMENT ON TABLE devices IS 'Owner: sessions | RLS: NONE | Retention: R-DEV | PII: P1/P3';

        CREATE TABLE user_devices (
          id                 uuid PRIMARY KEY,
          user_id            uuid        NOT NULL REFERENCES users(id),
          device_id          uuid        NOT NULL REFERENCES devices(id),
          trust_status       text        NOT NULL DEFAULT 'pending_otp'
                             CHECK (trust_status IN ('pending_otp','trusted','removed','expired')),
          trusted_at         timestamptz NULL,
          owner_verified_at  timestamptz NULL,
          verification_method text       NULL CHECK (verification_method IN ('email_otp','sms_otp','passkey','totp','support')),
          counts_toward_cap  boolean     NOT NULL DEFAULT true,
          remember_until     timestamptz NULL,
          remember_token_hash bytea      NULL CHECK (remember_token_hash IS NULL OR octet_length(remember_token_hash) = 32),
          remember_issued_at timestamptz NULL,
          user_label         text        NULL CHECK (user_label IS NULL OR char_length(user_label) <= 60),
          last_used_at       timestamptz NULL,
          removed_at         timestamptz NULL,
          removed_by         uuid        NULL REFERENCES users(id),
          removed_reason     text        NULL CHECK (removed_reason IN ('self_service_replacement','self_service_signout',
                                                 'support_reset','security_action','unblock_reset','inactivity_expiry')),
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_ud_removed CHECK ((trust_status = 'removed') = (removed_at IS NOT NULL)),
          CONSTRAINT ck_ud_trusted CHECK (trust_status <> 'trusted' OR trusted_at IS NOT NULL),
          CONSTRAINT ck_ud_remember CHECK ((remember_token_hash IS NULL) = (remember_until IS NULL))
        );
        CREATE UNIQUE INDEX ux_ud_user_device ON user_devices (user_id, device_id) WHERE trust_status <> 'removed';
        CREATE UNIQUE INDEX ux_ud_remember ON user_devices (remember_token_hash) WHERE remember_token_hash IS NOT NULL;
        CREATE INDEX ix_ud_trusted ON user_devices (user_id) WHERE trust_status = 'trusted' AND counts_toward_cap;
        CREATE INDEX ix_ud_replacements ON user_devices (user_id, removed_at) WHERE removed_reason = 'self_service_replacement';
        CREATE INDEX ix_ud_device ON user_devices (device_id);
        COMMENT ON TABLE user_devices IS 'Owner: sessions | RLS: O | Retention: R-DEV | PII: P1/P2';

        CREATE TABLE auth_sessions (
          id                   uuid PRIMARY KEY,
          token_hash           bytea       NOT NULL CHECK (octet_length(token_hash) = 32),
          user_id              uuid        NOT NULL REFERENCES users(id),
          organization_id      uuid        NULL REFERENCES organizations(id),
          device_id            uuid        NULL REFERENCES devices(id),
          user_device_id       uuid        NULL REFERENCES user_devices(id),
          client_type          text        NOT NULL CHECK (client_type IN ('web','android','ios')),
          session_tier         text        NOT NULL CHECK (session_tier IN ('student','staff','privileged')),
          scope                text        NOT NULL DEFAULT 'full' CHECK (scope IN ('full','restricted','status_only')),
          status               text        NOT NULL DEFAULT 'active'
                               CHECK (status IN ('pending_mfa','pending_device_otp','pending_session_choice','active','expired','revoked','blocked')),
          aal                  smallint    NOT NULL DEFAULT 1 CHECK (aal BETWEEN 1 AND 3),
          amr                  text[]      NOT NULL DEFAULT '{}',
          created_via          text        NOT NULL CHECK (created_via IN ('password','otp_login','passkey','sso','recovery','unblock_reauth',
                                  'remember_device')),
          auth_time            timestamptz NOT NULL DEFAULT now(),
          last_step_up_at      timestamptz NULL,
          remember_device      boolean     NOT NULL DEFAULT false,
          restriction_level_at_issue smallint NOT NULL DEFAULT 0 CHECK (restriction_level_at_issue BETWEEN 0 AND 4),
          created_at           timestamptz NOT NULL DEFAULT now(),
          last_seen_at         timestamptz NOT NULL DEFAULT now(),
          idle_expires_at      timestamptz NOT NULL,
          absolute_expires_at  timestamptz NOT NULL,
          idle_hold_until      timestamptz NULL,
          ip_first             inet        NULL,
          ip_last              inet        NULL,
          net_cluster_first    text        NULL,
          net_cluster_last     text        NULL,
          asn                  integer     NULL,
          network_type         text        NULL CHECK (network_type IN ('mobile','broadband','hosting','vpn_proxy','tor','education','unknown')),
          geo_country          char(2)     NULL,
          geo_region           text        NULL,
          ua_family            text        NULL,
          ua_major             text        NULL,
          os_family            text        NULL,
          device_class         text        NULL CHECK (device_class IN ('desktop','mobile','tablet','unknown')),
          ua_hash              bytea       NULL CHECK (ua_hash IS NULL OR octet_length(ua_hash) = 32),
          app_version          text        NULL,
          risk_evaluation_id   uuid        NULL,
          ended_at             timestamptz NULL,
          end_reason           text        NULL CHECK (end_reason IN ('user_logout','user_revoked_other','session_cap_evicted',
                                  'idle_timeout','absolute_timeout','password_changed','mfa_changed','device_removed',
                                  'device_mismatch','risk_L2_overflow','risk_L3','admin_L4','takeover_protect','admin_kill',
                                  'unblock_reset','privilege_change','account_deleted','replaced_same_device')),
          ended_by             uuid        NULL REFERENCES users(id),
          updated_at           timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_as_expiry CHECK (idle_expires_at <= absolute_expires_at),
          CONSTRAINT ck_as_ended CHECK ((status IN ('expired','revoked','blocked')) = (ended_at IS NOT NULL AND end_reason IS NOT NULL)),
          CONSTRAINT ck_as_blocked CHECK (status <> 'blocked' OR end_reason IN ('risk_L3','admin_L4','takeover_protect','device_mismatch'))
        );
        CREATE UNIQUE INDEX ux_as_token ON auth_sessions (token_hash);
        CREATE INDEX ix_as_user_active ON auth_sessions (user_id, created_at) WHERE status = 'active';
        CREATE INDEX ix_as_user_ended ON auth_sessions (user_id, ended_at DESC);
        CREATE INDEX ix_as_expiry ON auth_sessions (absolute_expires_at) WHERE status = 'active';
        CREATE INDEX ix_as_device ON auth_sessions (device_id, created_at DESC);
        COMMENT ON TABLE auth_sessions IS 'Owner: sessions | RLS: O | Retention: R-SEC | PII: P4/P3';

        CREATE TABLE session_network_observations (
          id                uuid        NOT NULL,
          first_seen_at     timestamptz NOT NULL DEFAULT now(),
          last_seen_at      timestamptz NOT NULL DEFAULT now(),
          auth_session_id   uuid        NOT NULL,
          user_id           uuid        NOT NULL,
          net_cluster       text        NOT NULL,
          asn               integer     NULL,
          network_type      text        NULL CHECK (network_type IN ('mobile','broadband','hosting','vpn_proxy','tor','education','unknown')),
          geo_region        text        NULL,
          PRIMARY KEY (id, first_seen_at)
        ) PARTITION BY RANGE (first_seen_at);
        CREATE TABLE session_network_observations_default PARTITION OF session_network_observations DEFAULT;
        CREATE INDEX ix_sno_session ON session_network_observations (auth_session_id, first_seen_at);
        CREATE INDEX ix_sno_user_time ON session_network_observations (user_id, first_seen_at DESC);
        COMMENT ON TABLE session_network_observations IS 'Owner: sessions | RLS: O | partitioned | Retention: R-SEC | PII: P3';

        CREATE TABLE login_attempts (
          id                  uuid        NOT NULL,
          attempted_at        timestamptz NOT NULL DEFAULT now(),
          user_id             uuid        NULL,
          identifier_hash     bytea       NOT NULL CHECK (octet_length(identifier_hash) = 32),
          key_version         smallint    NOT NULL DEFAULT 1 CHECK (key_version >= 1),
          method              text        NOT NULL CHECK (method IN ('password','otp','passkey','sso','recovery')),
          mfa_method          text        NULL CHECK (mfa_method IN ('totp','passkey','sms_otp','email_otp','recovery_code')),
          outcome             text        NOT NULL CHECK (outcome IN ('success','bad_credentials','unknown_identifier','throttled',
                                  'mfa_required','mfa_failed','device_otp_required','restricted','locked','error')),
          failure_reason      text        NULL,
          pre_auth_blocked    boolean     NOT NULL DEFAULT false,
          ip                  inet        NULL,
          asn                 integer     NULL,
          network_type        text        NULL CHECK (network_type IN ('mobile','broadband','hosting','vpn_proxy','tor','education','unknown')),
          geo_country         char(2)     NULL,
          geo_region          text        NULL,
          ua_hash             bytea       NULL CHECK (ua_hash IS NULL OR octet_length(ua_hash) = 32),
          device_id           uuid        NULL,
          auth_session_id     uuid        NULL,
          risk_evaluation_id  uuid        NULL,
          PRIMARY KEY (id, attempted_at)
        ) PARTITION BY RANGE (attempted_at);
        CREATE TABLE login_attempts_default PARTITION OF login_attempts DEFAULT;
        CREATE INDEX ix_la_user_time ON login_attempts (user_id, attempted_at DESC);
        CREATE INDEX ix_la_ident_time ON login_attempts (identifier_hash, attempted_at DESC);
        CREATE INDEX ix_la_ip_time ON login_attempts (ip, attempted_at DESC);
        CREATE INDEX ix_la_asn_time ON login_attempts (asn, attempted_at DESC) WHERE outcome <> 'success';
        CREATE INDEX brin_la_time ON login_attempts USING brin (attempted_at);
        COMMENT ON TABLE login_attempts IS 'Owner: sessions | RLS: O (NULL user rows platform-only) | append-only | partitioned | Retention: R-SEC | PII: P3';
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO td_app")
    op.execute(f"GRANT SELECT ON {', '.join(TABLES)} TO td_readonly")
    # Partitions are reached only through their RLS-protected parent.
    op.execute(
        "REVOKE ALL ON login_attempts_default, session_network_observations_default FROM td_app, td_readonly"
    )
    for t in ("devices", "user_devices", "auth_sessions"):
        add_updated_at_trigger(t)
    for t in ("user_devices", "auth_sessions", "login_attempts", "session_network_observations"):
        enable_rls(t, "O")
    revoke_app_writes("login_attempts")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
