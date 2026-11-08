"""audit: audit_outbox + append-only hash-chained audit_log

Revision ID: audit_0001
Revises:
Create Date: 2026-11-03

* audit_outbox: td_app INSERT only; td_audit_sealer SELECT/DELETE. RLS NONE.
* audit_log: partitioned by RANGE(occurred_at). A DEFAULT partition is created here so the
  table works without pg_partman; monthly partition premake/retention is registered by the
  maintenance job (Planned, maint.run_partition_maintenance()).
* UPDATE/DELETE/TRUNCATE revoked from every app role and blocked by trigger.
* RLS (FORCE): td_app/td_readonly read only with app.is_platform(); sealer reads/inserts.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "audit_0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = ("audit",)
depends_on: str | Sequence[str] | None = ("core_base",)


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE audit_outbox (
          id          uuid PRIMARY KEY,
          occurred_at timestamptz NOT NULL DEFAULT clock_timestamp(),
          record      jsonb       NOT NULL
        );
        CREATE INDEX ix_audit_outbox_time ON audit_outbox (occurred_at, id);
        COMMENT ON TABLE audit_outbox IS 'Owner: audit | RLS: NONE (insert-only for td_app) | Retention: minutes | PII: P1/P2';

        CREATE TABLE audit_log (
          seq               bigint      NOT NULL,
          occurred_at       timestamptz NOT NULL,
          id                uuid        NOT NULL,
          actor_type        text        NOT NULL,
          actor_user_id     uuid        NULL,
          actor_session_id  uuid        NULL,
          actor_roles       text[]      NOT NULL DEFAULT '{}',
          action            text        NOT NULL,
          target_type       text        NOT NULL,
          target_id         uuid        NULL,
          organization_id   uuid        NULL,
          subject_user_id   uuid        NULL,
          reason_code       text        NULL,
          reason            text        NULL,
          before_state      jsonb       NULL,
          after_state       jsonb       NULL,
          request_id        text        NULL,
          ip                inet        NULL,
          prev_hash         bytea       NOT NULL,
          row_hash          bytea       NOT NULL,
          CONSTRAINT ck_audit_log_actor_type CHECK (actor_type IN ('user','system','gateway','support_impersonation')),
          CONSTRAINT ck_audit_log_prev_hash_len CHECK (octet_length(prev_hash) = 32),
          CONSTRAINT ck_audit_log_row_hash_len CHECK (octet_length(row_hash) = 32),
          CONSTRAINT pk_audit_log PRIMARY KEY (seq, occurred_at)
        ) PARTITION BY RANGE (occurred_at);
        CREATE INDEX ix_audit_target ON audit_log (target_type, target_id, occurred_at);
        CREATE INDEX ix_audit_actor ON audit_log (actor_user_id, occurred_at);
        CREATE INDEX ix_audit_subject ON audit_log (subject_user_id, occurred_at);
        CREATE INDEX ix_audit_seq ON audit_log (seq);
        CREATE TABLE audit_log_default PARTITION OF audit_log DEFAULT;
        COMMENT ON TABLE audit_log IS 'Owner: audit | RLS: platform-only read | Retention: R-AUDIT | PII: P1/P2 | append-only, hash-chained';

        CREATE OR REPLACE FUNCTION app.audit_log_immutable() RETURNS trigger LANGUAGE plpgsql AS
        $$ BEGIN
             RAISE EXCEPTION 'audit_log is append-only (% blocked)', TG_OP USING ERRCODE = 'insufficient_privilege';
           END $$;
        CREATE TRIGGER trg_audit_log_immutable BEFORE UPDATE OR DELETE ON audit_log
          FOR EACH ROW EXECUTE FUNCTION app.audit_log_immutable();
        CREATE TRIGGER trg_audit_log_no_truncate BEFORE TRUNCATE ON audit_log
          FOR EACH STATEMENT EXECUTE FUNCTION app.audit_log_immutable();
        CREATE TRIGGER trg_audit_log_default_no_truncate BEFORE TRUNCATE ON audit_log_default
          FOR EACH STATEMENT EXECUTE FUNCTION app.audit_log_immutable();
        """
    )

    # ---- privileges (override the core_base default privileges)
    for t in ("audit_outbox", "audit_log", "audit_log_default"):
        op.execute(f"REVOKE ALL ON {t} FROM PUBLIC, td_app, td_readonly, td_audit_sealer, td_maintenance")
    op.execute("GRANT INSERT ON audit_outbox TO td_app")
    op.execute("GRANT SELECT, DELETE ON audit_outbox TO td_audit_sealer")
    op.execute("GRANT SELECT ON audit_log TO td_app, td_readonly")
    op.execute("GRANT SELECT, INSERT ON audit_log TO td_audit_sealer")
    # Partitions are reached only through the parent (privileges + RLS are checked there).

    op.execute(
        """
        ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
        ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
        CREATE POLICY p_platform_read ON audit_log FOR SELECT TO td_app, td_readonly
          USING (app.is_platform());
        CREATE POLICY p_sealer_read ON audit_log FOR SELECT TO td_audit_sealer USING (true);
        CREATE POLICY p_sealer_insert ON audit_log FOR INSERT TO td_audit_sealer WITH CHECK (true);
        ALTER TABLE audit_log_default ENABLE ROW LEVEL SECURITY;
        ALTER TABLE audit_log_default FORCE ROW LEVEL SECURITY;
        """
    )


def downgrade() -> None:
    # Dropping the audit log is only acceptable on an empty development database.
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS audit_outbox")
    op.execute("DROP FUNCTION IF EXISTS app.audit_log_immutable()")
