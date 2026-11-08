"""identity: users, profiles, credentials, MFA factors, verification/reset tokens, consents

Revision ID: identity_0001
Revises:
Create Date: 2026-11-03

database-schema §3. RLS: users (custom on id; org visibility added in identity_0002),
user_profiles/user_credentials/mfa_factors/consents O, guardian_consents custom (child),
verification_tokens/password_reset_tokens NONE (pre-auth, accessed by hash only).
Deviations: ``mfa_factors.totp_confirmed_at`` (pending vs confirmed TOTP enrolment);
``guardian_consents.verification_method`` also allows ``guardian_otp_declaration``
(privacy doc §4 branch J: guardian OTP + declaration, counsel question P-6).
``consents.organization_id`` FK is added in identity_0002 (organizations is in the orgs branch).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger, enable_rls, revoke_app_writes

revision: str = "identity_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("identity",)
depends_on: str | Sequence[str] | None = ("core_base",)

TABLES = (
    "users",
    "user_profiles",
    "user_credentials",
    "mfa_factors",
    "verification_tokens",
    "password_reset_tokens",
    "guardian_consents",
    "consents",
)


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE users (
          id                 uuid PRIMARY KEY,
          email              citext      NULL,
          email_verified_at  timestamptz NULL,
          phone_e164         text        NULL CHECK (phone_e164 ~ '^\+[1-9][0-9]{7,14}$'),
          phone_verified_at  timestamptz NULL,
          status             text        NOT NULL DEFAULT 'pending_verification'
                             CHECK (status IN ('pending_verification','pending_guardian_consent','active','deactivated','deleted')),
          is_minor           boolean     NOT NULL DEFAULT true,
          age_verified_at    timestamptz NULL,
          age_verification_method text   NULL CHECK (age_verification_method IN ('self_declared','roster','digilocker','guardian_attested')),
          privacy_tier       text        GENERATED ALWAYS AS (CASE WHEN is_minor THEN 'minor' ELSE 'adult' END) STORED,
          restriction_level  smallint    NOT NULL DEFAULT 0 CHECK (restriction_level BETWEEN 0 AND 4),
          sessions_valid_after timestamptz NULL,
          must_change_password boolean   NOT NULL DEFAULT false,
          is_synthetic       boolean     NOT NULL DEFAULT false,
          account_origin     text        NOT NULL DEFAULT 'self_signup'
                             CHECK (account_origin IN ('self_signup','roster_import','staff_created','sso')),
          locale             text        NOT NULL DEFAULT 'en-IN',
          last_login_at      timestamptz NULL,
          created_at         timestamptz NOT NULL DEFAULT now(),
          updated_at         timestamptz NOT NULL DEFAULT now(),
          deleted_at         timestamptz NULL,
          CONSTRAINT ck_users_contact CHECK (email IS NOT NULL OR phone_e164 IS NOT NULL OR status = 'deleted'),
          CONSTRAINT ck_users_adult_verified CHECK (is_minor OR age_verified_at IS NOT NULL),
          CONSTRAINT ck_users_age_method CHECK ((age_verified_at IS NULL) = (age_verification_method IS NULL))
        );
        CREATE UNIQUE INDEX ux_users_email ON users (email) WHERE email IS NOT NULL AND deleted_at IS NULL;
        CREATE UNIQUE INDEX ux_users_phone ON users (phone_e164) WHERE phone_e164 IS NOT NULL AND deleted_at IS NULL;
        CREATE INDEX ix_users_status ON users (status);
        COMMENT ON TABLE users IS 'Owner: identity | RLS: custom (id/platform/org visibility) | Retention: R-ACCT | PII: P2/P3';

        CREATE TABLE user_profiles (
          user_id             uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          full_name           text        NOT NULL CHECK (char_length(full_name) BETWEEN 1 AND 200),
          display_name        text        NULL,
          date_of_birth       date        NULL,
          college_name_text   text        NULL,
          degree              text        NULL,
          branch              text        NULL,
          graduation_year     smallint    NULL CHECK (graduation_year BETWEEN 1990 AND 2100),
          city                text        NULL,
          state_code          char(2)     NULL,
          target_role         text        NULL,
          target_company_ids  uuid[]      NOT NULL DEFAULT '{}',
          target_date         date        NULL,
          avatar_s3_key       text        NULL,
          timezone            text        NOT NULL DEFAULT 'Asia/Kolkata',
          created_at          timestamptz NOT NULL DEFAULT now(),
          updated_at          timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE user_profiles IS 'Owner: identity | RLS: O + org visibility | Retention: R-ACCT | PII: P2/P3';

        CREATE TABLE user_credentials (
          user_id              uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
          password_hash        text        NOT NULL,
          hash_params_version  smallint    NOT NULL DEFAULT 1,
          password_set_at      timestamptz NOT NULL DEFAULT now(),
          breach_checked_at    timestamptz NULL,
          consecutive_failures int         NOT NULL DEFAULT 0 CHECK (consecutive_failures >= 0),
          hard_locked_at       timestamptz NULL,
          created_at           timestamptz NOT NULL DEFAULT now(),
          updated_at           timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE user_credentials IS 'Owner: identity | RLS: O | Retention: R-ACCT | PII: P4';

        CREATE TABLE mfa_factors (
          id                     uuid PRIMARY KEY,
          user_id                uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          factor_type            text        NOT NULL CHECK (factor_type IN ('webauthn','totp','sms','recovery_codes')),
          label                  text        NULL,
          totp_secret_encrypted  bytea       NULL,
          totp_wrapped_key       bytea       NULL,
          totp_last_used_step    bigint      NULL,
          totp_confirmed_at      timestamptz NULL,
          webauthn_credential_id bytea       NULL,
          webauthn_public_key    bytea       NULL,
          webauthn_sign_count    bigint      NULL,
          webauthn_aaguid        uuid        NULL,
          webauthn_transports    text[]      NULL,
          webauthn_uv_required   boolean     NOT NULL DEFAULT true,
          sms_phone_e164         text        NULL,
          recovery_code_hashes   bytea[]     NULL,
          is_primary             boolean     NOT NULL DEFAULT false,
          last_used_at           timestamptz NULL,
          created_at             timestamptz NOT NULL DEFAULT now(),
          revoked_at             timestamptz NULL,
          CONSTRAINT ck_mfa_payload CHECK (
            (factor_type = 'totp'     AND totp_secret_encrypted IS NOT NULL) OR
            (factor_type = 'webauthn' AND webauthn_credential_id IS NOT NULL AND webauthn_public_key IS NOT NULL) OR
            (factor_type = 'sms'      AND sms_phone_e164 IS NOT NULL) OR
            (factor_type = 'recovery_codes' AND recovery_code_hashes IS NOT NULL))
        );
        CREATE INDEX ix_mfa_user ON mfa_factors (user_id) WHERE revoked_at IS NULL;
        CREATE UNIQUE INDEX ux_mfa_webauthn_cred ON mfa_factors (webauthn_credential_id) WHERE webauthn_credential_id IS NOT NULL;
        COMMENT ON TABLE mfa_factors IS 'Owner: identity | RLS: O | Retention: R-ACCT | PII: P4/P2';

        CREATE TABLE verification_tokens (
          id                uuid PRIMARY KEY,
          user_id           uuid        NULL REFERENCES users(id) ON DELETE CASCADE,
          purpose           text        NOT NULL CHECK (purpose IN ('email_verify','phone_verify','login_otp','new_device_otp',
                                                                    'step_up_otp','contact_change','guardian_verify')),
          channel           text        NOT NULL CHECK (channel IN ('email','sms')),
          destination_hmac  bytea       NOT NULL CHECK (octet_length(destination_hmac) = 32),
          token_hash        bytea       NOT NULL CHECK (octet_length(token_hash) = 32),
          auth_session_id   uuid        NULL,
          device_id         uuid        NULL,
          attempts          smallint    NOT NULL DEFAULT 0,
          max_attempts      smallint    NOT NULL DEFAULT 5,
          expires_at        timestamptz NOT NULL,
          consumed_at       timestamptz NULL,
          created_ip        inet        NULL,
          created_at        timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_vt_attempts CHECK (attempts <= max_attempts)
        );
        CREATE UNIQUE INDEX ux_vt_token_hash ON verification_tokens (token_hash);
        CREATE INDEX ix_vt_user_purpose ON verification_tokens (user_id, purpose, created_at DESC);
        CREATE INDEX ix_vt_dest_recent ON verification_tokens (destination_hmac, created_at DESC);
        CREATE INDEX ix_vt_expires ON verification_tokens (expires_at);
        COMMENT ON TABLE verification_tokens IS 'Owner: identity | RLS: NONE (by hash) | Retention: R-TOKEN | PII: P4/P3';

        CREATE TABLE password_reset_tokens (
          id             uuid PRIMARY KEY,
          user_id        uuid        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          token_hash     bytea       NOT NULL CHECK (octet_length(token_hash) = 32),
          expires_at     timestamptz NOT NULL,
          consumed_at    timestamptz NULL,
          requested_ip   inet        NULL,
          created_at     timestamptz NOT NULL DEFAULT now()
        );
        CREATE UNIQUE INDEX ux_prt_hash ON password_reset_tokens (token_hash);
        CREATE INDEX ix_prt_user ON password_reset_tokens (user_id, created_at DESC);
        COMMENT ON TABLE password_reset_tokens IS 'Owner: identity | RLS: NONE (by hash) | Retention: R-TOKEN | PII: P4';

        CREATE TABLE guardian_consents (
          id                   uuid PRIMARY KEY,
          child_user_id        uuid        NOT NULL REFERENCES users(id),
          guardian_user_id     uuid        NULL REFERENCES users(id),
          guardian_name        text        NOT NULL,
          guardian_email       citext      NULL,
          guardian_phone_e164  text        NULL,
          relationship         text        NOT NULL CHECK (relationship IN ('parent','legal_guardian')),
          verification_method  text        NOT NULL CHECK (verification_method IN ('existing_adult_account','digilocker_token',
                                                                                   'institution_attested','guardian_otp_declaration')),
          verification_ref     text        NULL,
          evidence_hash        bytea       NULL,
          status               text        NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','verified','rejected','revoked','expired')),
          verified_at          timestamptz NULL,
          revoked_at           timestamptz NULL,
          expires_at           timestamptz NULL,
          created_at           timestamptz NOT NULL DEFAULT now(),
          updated_at           timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_gc_contact CHECK (guardian_email IS NOT NULL OR guardian_phone_e164 IS NOT NULL OR guardian_user_id IS NOT NULL)
        );
        CREATE INDEX ix_gc_child ON guardian_consents (child_user_id, status);
        COMMENT ON TABLE guardian_consents IS 'Owner: identity | RLS: custom (child) | Retention: R-CONSENT | PII: P3';

        CREATE TABLE consents (
          id                  uuid PRIMARY KEY,
          user_id             uuid        NOT NULL REFERENCES users(id),
          purpose             text        NOT NULL CHECK (purpose IN ('terms','privacy_notice','core_service','security_monitoring',
                                             'analytics_personalisation','college_data_sharing','device_fingerprint',
                                             'marketing_email','marketing_sms','assessment_integrity','analytics_product')),
          action              text        NOT NULL CHECK (action IN ('granted','withdrawn')),
          context_ref         uuid        NULL,
          notice_version      text        NOT NULL,
          notice_locale       text        NOT NULL DEFAULT 'en-IN',
          channel             text        NOT NULL CHECK (channel IN ('web','android','ios','roster_import','support')),
          guardian_consent_id uuid        NULL REFERENCES guardian_consents(id),
          organization_id     uuid        NULL,
          ip                  inet        NULL,
          user_agent          text        NULL,
          created_at          timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_consents_user_purpose ON consents (user_id, purpose, created_at DESC);
        COMMENT ON TABLE consents IS 'Owner: identity | RLS: O | append-only | Retention: R-CONSENT | PII: P3';
        """
    )
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TABLES)} TO td_app")
    op.execute(f"GRANT SELECT ON {', '.join(TABLES)} TO td_readonly")
    for t in ("users", "user_profiles", "user_credentials", "guardian_consents"):
        add_updated_at_trigger(t)

    # users: own row or platform (org visibility added in identity_0002)
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE users FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY p_users ON users FOR ALL TO td_app, td_readonly "
        "USING (id = app.user_id() OR app.is_platform()) WITH CHECK (id = app.user_id() OR app.is_platform())"
    )
    for t in ("user_profiles", "user_credentials", "mfa_factors", "consents"):
        enable_rls(t, "O")
    op.execute("ALTER TABLE guardian_consents ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE guardian_consents FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY p_gc ON guardian_consents FOR ALL TO td_app, td_readonly "
        "USING (child_user_id = app.user_id() OR app.is_platform()) "
        "WITH CHECK (child_user_id = app.user_id() OR app.is_platform())"
    )
    revoke_app_writes("consents")  # append-only ledger


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
