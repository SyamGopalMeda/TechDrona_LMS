"""admissions: fee plans, registrations, manual payment claims, event trail (website fees -> LMS)

Revision ID: admissions_0001
Revises:
Create Date: 2026-11-11

Course registration, instalment fees and manual UPI payment verification move from the company
website (Firestore ``web_fee_*``) into the LMS (owner decision 2026-11-11: the website admin keeps
website content and form submissions only).

Tables (all ``Owner: admissions``, RLS forced, **platform only** like ``corporate_enquiries``:
the public routes write under a named system context, staff with a platform grant read/decide):

* ``admission_pay_settings`` — single row (id 1): where students pay (number / UPI ID / payee).
* ``admission_fee_plans`` — one per website course slug: fee, instalment schedule, access
  threshold, optional LMS ``course_id`` / ``batch_id``, optional course-specific UPI / bank details.
* ``admission_registrations`` — one student's registration for one course (reg_no TDR-XXXXXXXX),
  money terms snapshotted from the plan, ``verified_total_paise`` and ``balance_paise``.
* ``admission_payment_claims`` — a student's claim (screenshot + UTR) or a staff entry.
* ``admission_events`` — append-only trail (td_app: INSERT + SELECT only).

Invariants enforced by the database (the website's firestore.rules, server-side now):

* ``balance = fee - verified_total``, ``0 <= verified_total <= fee`` (CHECK);
* one live registration per email per course (partial UNIQUE; rejected/cancelled free the slot);
* a UTR, a proof file (sha256 of the stored bytes) and the original screenshot hash can each be
  claimed once (partial UNIQUE, unless staff released the claim's locks);
* at most 3 claims waiting for review per registration (CHECK on ``open_claims``);
* the ledger: ``verified_total`` always equals the sum of ``verified_amount`` of the claims in
  status ``verified`` (deferred constraint trigger, checked at commit), so the total can only
  move together with a claim's verification or reversal in the same transaction.

RBAC (reference rows owned by this module, inserted like ``paths_0001``): ``payment.verify``
(verify / request correction / reject / record / registration changes) and ``payment.reverse``
(undo a verification, change a student's fee), both for ``super_admin``. Reading reuses
``payment.read``; fee plans reuse ``price.manage``.

No ``depends_on`` on other branch heads (a cross-branch head dependency breaks
``alembic upgrade heads``, see learning_0005); the referenced tables (users, batches) exist since
``identity_0001`` / ``orgs_0001``, which are long applied.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from app.core.migration_helpers import add_updated_at_trigger

revision: str = "admissions_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("admissions",)
depends_on: str | Sequence[str] | None = ("core_base_0001", "identity_0001", "orgs_0001")

_ROLES = "td_app, td_readonly"
TABLES = (
    "admission_pay_settings",
    "admission_fee_plans",
    "admission_registrations",
    "admission_payment_claims",
    "admission_events",
)
PERMS = {
    "payment.verify": "Verify, correct or reject manual payment claims and manage admissions registrations",
    "payment.reverse": "Reverse a verified manual payment or change a registration's fee",
}
GRANTEES = ("super_admin",)


def _platform_only(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"DROP POLICY IF EXISTS p_platform ON {table}")
    op.execute(
        f"CREATE POLICY p_platform ON {table} FOR ALL TO {_ROLES} "
        "USING (app.is_platform()) WITH CHECK (app.is_platform())"
    )
    op.execute(f"GRANT SELECT ON {table} TO td_readonly")


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE admission_pay_settings (
          id             smallint PRIMARY KEY CHECK (id = 1),
          phone          text        NULL CHECK (phone ~ '^[6-9][0-9]{9}$'),
          preferred_app  text        NOT NULL DEFAULT 'PhonePe' CHECK (char_length(preferred_app) <= 40),
          upi_id         text        NULL CHECK (upi_id ~ '^[a-zA-Z0-9._-]{2,256}@[a-zA-Z][a-zA-Z0-9.-]{1,64}$'),
          payee_name     text        NULL CHECK (char_length(payee_name) <= 80),
          instructions   text        NULL CHECK (char_length(instructions) <= 800),
          updated_by     uuid        NULL REFERENCES users(id),
          updated_at     timestamptz NOT NULL DEFAULT now()
        );
        COMMENT ON TABLE admission_pay_settings IS 'Owner: admissions | single row | RLS: platform only | Retention: config | PII: none';

        CREATE TABLE admission_fee_plans (
          id                uuid PRIMARY KEY,
          course_slug       text        NOT NULL UNIQUE CHECK (course_slug ~ '^[a-z0-9][a-z0-9-]{0,79}$'),
          title             text        NOT NULL CHECK (char_length(title) BETWEEN 1 AND 160),
          course_id         uuid        NULL,
          batch_id          uuid        NULL REFERENCES batches(id),
          fee_paise         bigint      NOT NULL CHECK (fee_paise BETWEEN 0 AND 100000000),
          allow_instalments boolean     NOT NULL DEFAULT false,
          schedule          jsonb       NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(schedule) = 'array'),
          policy            text        NOT NULL DEFAULT 'full' CHECK (policy IN ('full','instalments')),
          min_first_paise   bigint      NOT NULL CHECK (min_first_paise >= 0),
          access_min_paise  bigint      NOT NULL CHECK (access_min_paise >= 0),
          upi_id            text        NULL CHECK (upi_id ~ '^[a-zA-Z0-9._-]{2,256}@[a-zA-Z][a-zA-Z0-9.-]{1,64}$'),
          payee_name        text        NULL CHECK (char_length(payee_name) <= 80),
          bank_details      text        NULL CHECK (char_length(bank_details) <= 600),
          instructions      text        NULL CHECK (char_length(instructions) <= 800),
          active            boolean     NOT NULL DEFAULT false,
          updated_by        uuid        NULL REFERENCES users(id),
          created_at        timestamptz NOT NULL DEFAULT now(),
          updated_at        timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_afp_terms CHECK (access_min_paise <= fee_paise AND min_first_paise <= fee_paise)
        );
        COMMENT ON TABLE admission_fee_plans IS 'Owner: admissions | RLS: platform only | Retention: config | PII: P0 (payee details)';

        CREATE TABLE admission_registrations (
          id                   uuid PRIMARY KEY,
          reg_no               text        NOT NULL UNIQUE CHECK (reg_no ~ '^TDR-[A-Z0-9]{8}$'),
          fee_plan_id          uuid        NOT NULL REFERENCES admission_fee_plans(id),
          course_slug          text        NOT NULL,
          course_title         text        NOT NULL CHECK (char_length(course_title) <= 160),
          name                 text        NOT NULL CHECK (char_length(name) BETWEEN 2 AND 120),
          email                text        NOT NULL CHECK (email = lower(email) AND char_length(email) <= 160 AND position('@' in email) > 1),
          phone                text        NOT NULL CHECK (phone ~ '^\+91[6-9][0-9]{9}$'),
          college              text        NOT NULL CHECK (char_length(college) BETWEEN 1 AND 160),
          branch               text        NOT NULL CHECK (char_length(branch) BETWEEN 1 AND 60),
          year                 text        NOT NULL CHECK (char_length(year) BETWEEN 1 AND 30),
          current_status       text        NULL CHECK (char_length(current_status) <= 60),
          preferred_mode       text        NULL CHECK (char_length(preferred_mode) <= 30),
          message              text        NULL CHECK (char_length(message) <= 2000),
          fee_paise            bigint      NOT NULL CHECK (fee_paise BETWEEN 0 AND 100000000),
          access_min_paise     bigint      NOT NULL CHECK (access_min_paise >= 0),
          policy               text        NOT NULL CHECK (policy IN ('full','instalments')),
          allow_instalments    boolean     NOT NULL,
          min_first_paise      bigint      NOT NULL CHECK (min_first_paise >= 0),
          schedule             jsonb       NOT NULL DEFAULT '[]' CHECK (jsonb_typeof(schedule) = 'array'),
          verified_total_paise bigint      NOT NULL DEFAULT 0,
          balance_paise        bigint      NOT NULL,
          status               text        NOT NULL DEFAULT 'registered'
                                 CHECK (status IN ('registered','pending_verification','partially_paid','payment_verified',
                                                   'enrolled','rejected','cancelled','completed')),
          status_note          text        NULL CHECK (char_length(status_note) <= 500),
          open_claims          smallint    NOT NULL DEFAULT 0 CHECK (open_claims BETWEEN 0 AND 3),
          resume_key           text        NULL,
          resume_name          text        NULL,
          resume_type          text        NULL,
          resume_size          integer     NULL CHECK (resume_size BETWEEN 1 AND 2097152),
          consent_text         text        NOT NULL,
          consent_at           timestamptz NOT NULL,
          show_public          boolean     NOT NULL DEFAULT false,
          marketing_consent_at timestamptz NULL,
          source               text        NOT NULL DEFAULT 'website' CHECK (source IN ('website','import','staff')),
          user_id              uuid        NULL REFERENCES users(id),
          entitlement_id       uuid        NULL,
          enrolment_id         uuid        NULL,
          batch_member_id      uuid        NULL,
          enrolled_course_id   uuid        NULL,
          enrolled_batch_id    uuid        NULL,
          enrolled_at          timestamptz NULL,
          created_at           timestamptz NOT NULL DEFAULT now(),
          updated_at           timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT ck_areg_ledger CHECK (verified_total_paise BETWEEN 0 AND fee_paise
                                           AND balance_paise = fee_paise - verified_total_paise),
          CONSTRAINT ck_areg_access CHECK (access_min_paise <= fee_paise),
          CONSTRAINT ck_areg_enrolled CHECK (status <> 'enrolled' OR enrolled_at IS NOT NULL)
        );
        -- one live registration per email per course (rejected / cancelled free the slot)
        CREATE UNIQUE INDEX ux_areg_email_course ON admission_registrations (course_slug, email)
          WHERE status NOT IN ('rejected','cancelled');
        CREATE INDEX ix_areg_status_created ON admission_registrations (status, created_at DESC, id DESC);
        CREATE INDEX ix_areg_created ON admission_registrations (created_at DESC, id DESC);
        CREATE INDEX ix_areg_email ON admission_registrations (email);
        COMMENT ON TABLE admission_registrations IS 'Owner: admissions | RLS: platform only | Retention: R-FIN (8 years) | PII: P2';

        CREATE TABLE admission_payment_claims (
          id                    uuid PRIMARY KEY,
          registration_id       uuid        NOT NULL REFERENCES admission_registrations(id),
          provider              text        NOT NULL CHECK (provider IN ('manual_upi','admin_entry')),
          method                text        NOT NULL CHECK (method IN ('upi','bank','cash','other')),
          amount_paise          bigint      NOT NULL CHECK (amount_paise > 0 AND amount_paise <= 100000000),
          utr                   text        NULL CHECK (utr ~ '^[A-Z0-9]{4,22}$'),
          paid_on               date        NOT NULL,
          note                  text        NULL CHECK (char_length(note) <= 500),
          proof_key             text        NULL,
          proof_name            text        NULL,
          proof_type            text        NULL CHECK (proof_type IN ('image/jpeg','image/png','image/webp','application/pdf')),
          proof_size            integer     NULL CHECK (proof_size BETWEEN 1 AND 2097152),
          proof_sha256          text        NULL CHECK (proof_sha256 ~ '^[0-9a-f]{64}$'),
          proof_original_sha256 text        NULL CHECK (proof_original_sha256 ~ '^[0-9a-f]{64}$'),
          status                text        NOT NULL DEFAULT 'pending'
                                  CHECK (status IN ('pending','needs_info','verified','rejected','reversed')),
          verified_amount_paise bigint      NOT NULL DEFAULT 0 CHECK (verified_amount_paise >= 0),
          locks_released        boolean     NOT NULL DEFAULT false,
          reviewed_by           uuid        NULL REFERENCES users(id),
          reviewed_at           timestamptz NULL,
          review_note           text        NULL CHECK (char_length(review_note) <= 500),
          submitted_at          timestamptz NOT NULL DEFAULT now(),
          updated_at            timestamptz NOT NULL DEFAULT now(),
          -- a student claim always carries a reference and a proof; a staff entry may not
          CONSTRAINT ck_apc_student CHECK (provider <> 'manual_upi'
                                           OR (utr IS NOT NULL AND proof_key IS NOT NULL AND proof_sha256 IS NOT NULL)),
          CONSTRAINT ck_apc_verified CHECK ((status IN ('verified','reversed')) = (verified_amount_paise > 0)),
          CONSTRAINT ck_apc_reviewed CHECK (status IN ('pending') OR provider = 'admin_entry' OR reviewed_at IS NOT NULL)
        );
        CREATE UNIQUE INDEX ux_apc_utr ON admission_payment_claims (utr)
          WHERE utr IS NOT NULL AND NOT locks_released;
        CREATE UNIQUE INDEX ux_apc_proof ON admission_payment_claims (proof_sha256)
          WHERE proof_sha256 IS NOT NULL AND NOT locks_released;
        CREATE UNIQUE INDEX ux_apc_proof_original ON admission_payment_claims (proof_original_sha256)
          WHERE proof_original_sha256 IS NOT NULL AND NOT locks_released;
        CREATE INDEX ix_apc_reg ON admission_payment_claims (registration_id, submitted_at);
        CREATE INDEX ix_apc_queue ON admission_payment_claims (status, submitted_at)
          WHERE status IN ('pending','needs_info');
        COMMENT ON TABLE admission_payment_claims IS 'Owner: admissions | RLS: platform only | Retention: R-FIN (8 years) | PII: P1';

        CREATE TABLE admission_events (
          id               uuid PRIMARY KEY,
          registration_id  uuid        NULL REFERENCES admission_registrations(id),
          claim_id         uuid        NULL REFERENCES admission_payment_claims(id),
          action           text        NOT NULL CHECK (action ~ '^[a-z_]+\.[a-z_]+$'),
          amount_paise     bigint      NOT NULL DEFAULT 0,
          actor_user_id    uuid        NULL REFERENCES users(id),
          actor_label      text        NOT NULL CHECK (char_length(actor_label) <= 160),
          detail           text        NULL CHECK (char_length(detail) <= 400),
          at               timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_aev_reg ON admission_events (registration_id, at DESC);
        CREATE INDEX ix_aev_at ON admission_events (at DESC, id DESC);
        COMMENT ON TABLE admission_events IS 'Owner: admissions | RLS: platform only | Retention: R-FIN | PII: P1 | append-only';

        -- Ledger invariant: verified_total = sum(verified_amount) of the verified claims. Deferred to
        -- commit so a verification moves the claim and the total in one transaction.
        CREATE FUNCTION admissions_check_ledger() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE
          rid uuid;
          total bigint;
          expected bigint;
        BEGIN
          IF TG_TABLE_NAME = 'admission_registrations' THEN rid := NEW.id; ELSE rid := NEW.registration_id; END IF;
          SELECT verified_total_paise INTO total FROM admission_registrations WHERE id = rid;
          SELECT coalesce(sum(verified_amount_paise), 0) INTO expected
            FROM admission_payment_claims WHERE registration_id = rid AND status = 'verified';
          IF total IS DISTINCT FROM expected THEN
            RAISE EXCEPTION 'admissions ledger mismatch for registration %: total % <> verified claims %',
              rid, total, expected USING ERRCODE = '23514', CONSTRAINT = 'ck_areg_ledger_sum';
          END IF;
          RETURN NULL;
        END $$;
        CREATE CONSTRAINT TRIGGER trg_areg_ledger AFTER INSERT OR UPDATE ON admission_registrations
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION admissions_check_ledger();
        CREATE CONSTRAINT TRIGGER trg_apc_ledger AFTER INSERT OR UPDATE ON admission_payment_claims
          DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION admissions_check_ledger();
        """
    )
    for t in TABLES:
        _platform_only(t)
    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON admission_pay_settings, admission_fee_plans, "
        "admission_registrations, admission_payment_claims TO td_app"
    )
    op.execute("GRANT SELECT, INSERT ON admission_events TO td_app")
    for t in TABLES:
        op.execute(f"REVOKE DELETE, TRUNCATE ON {t} FROM td_app")
    op.execute("REVOKE UPDATE ON admission_events FROM td_app")
    op.execute("GRANT EXECUTE ON FUNCTION admissions_check_ledger() TO td_app")
    for t in ("admission_fee_plans", "admission_registrations", "admission_payment_claims"):
        add_updated_at_trigger(t)

    # RBAC reference rows (td_app cannot write them; migrations run as the owner).
    from sqlalchemy import text

    from app.seeds.rbac_seed import permission_id

    conn = op.get_bind()
    for key, desc in PERMS.items():
        conn.execute(
            text(
                "INSERT INTO permissions (id, permission_key, module, description, is_sensitive) "
                "VALUES (:id, :k, 'commerce', :d, :s) ON CONFLICT (permission_key) DO NOTHING"
            ),
            {"id": permission_id(key), "k": key, "d": desc, "s": key == "payment.reverse"},
        )
        for role in GRANTEES:
            conn.execute(
                text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT r.id, p.id FROM roles r, permissions p "
                    "WHERE r.role_key = :r AND p.permission_key = :k ON CONFLICT DO NOTHING"
                ),
                {"r": role, "k": key},
            )


def downgrade() -> None:
    op.execute(
        "DELETE FROM role_permissions WHERE permission_id IN "
        "(SELECT id FROM permissions WHERE permission_key IN ('payment.verify','payment.reverse'))"
    )
    op.execute("DELETE FROM permissions WHERE permission_key IN ('payment.verify','payment.reverse')")
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    op.execute("DROP FUNCTION IF EXISTS admissions_check_ledger()")
