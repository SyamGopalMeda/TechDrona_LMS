"""core_base: maint.* partition maintenance and retention purge (DB-02, DB-04)

Revision ID: core_base_0002
Revises: core_base_0001
Create Date: 2026-11-03

Functions (owned by td_owner, ``SECURITY DEFINER``, ``search_path`` pinned, EXECUTE only for
``td_maintenance``; database-schema §1.2):

* ``maint.ensure_partitions(parent, months_ahead)`` — premakes monthly RANGE partitions for
  the 10 partitioned parents. Each new child is hardened exactly like the parent's
  ``*_default`` partition (DB-04): every privilege granted by the default privileges
  (``td_app``/``td_readonly``...) is revoked, the default partition's ACL is re-applied, RLS is
  enabled + forced and the default partition's policies are copied. If the DEFAULT partition
  already holds rows of the new month, they are moved under an ACCESS EXCLUSIVE lock
  (detach DEFAULT → create child → copy rows → delete from DEFAULT → re-attach). Parents with a
  DELETE-blocking trigger (``audit_log`` is immutable) are never moved: that month is skipped
  and reported as ``skipped_default_rows``.
* ``maint.drop_expired_partitions(parent)`` — detaches and drops monthly children whose upper
  bound is older than the parent's ``retention_policies`` interval.
* ``maint.purge_expired_rows(table, batch, max_batches)`` — batched row deletes of rows past
  the ``retention_policies`` interval (rules per table below; risk rows referenced by an open
  or legal-hold case are kept, privacy §7).
* ``maint.run_partition_maintenance(months_ahead)`` / ``maint.run_retention()`` — the two
  entry points the Celery ``maintenance`` queue calls; each writes one ``audit_outbox`` summary.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "core_base_0002"
down_revision: str | Sequence[str] | None = "core_base_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = (
    "admin_0001",
    "sessions_0002",
    "security_0001",
    "media_0001",
    "assessments_0001",
    "analytics_0001",
    "audit_0001",
    "identity_0001",
    "notifications_0001",
)

PARENTS = (
    "login_attempts",
    "session_network_observations",
    "security_signals",
    "risk_evaluations",
    "attempt_events",
    "analytics_events",
    "activity_heartbeats",
    "engagement_intervals",
    "playback_sessions",
    "audit_log",
)

# Retention rows the privacy doc (§2, §7) requires and admin_0001 did not seed.
NEW_POLICIES = (
    # table, category, class, interval, basis, method, job, owner
    (
        "auth_sessions",
        "D5",
        "R-SEC",
        "395 days",
        "Ended sessions: CERT-In logs >= 1 year (privacy §7)",
        "row_delete",
        "purge_auth_logs",
        "sessions",
    ),
    (
        "playback_sessions",
        "D11",
        "R-PLAY",
        "180 days",
        "Video playback (privacy D11)",
        "partition_drop",
        "purge_playback",
        "media",
    ),
    (
        "attempt_events",
        "D15",
        "R-ASSESS-EVT",
        "24 months",
        "Attempt events (schema R-ASSESS-EVT)",
        "partition_drop",
        "purge_attempt_events",
        "assessments",
    ),
    (
        "verification_tokens",
        "TOKEN",
        "R-TOKEN",
        "7 days",
        "7 days after expiry/consumption (schema R-TOKEN)",
        "row_delete",
        "purge_tokens",
        "identity",
    ),
    (
        "password_reset_tokens",
        "TOKEN",
        "R-TOKEN",
        "7 days",
        "7 days after expiry/consumption (schema R-TOKEN)",
        "row_delete",
        "purge_tokens",
        "identity",
    ),
    (
        "outbox_events",
        "OPS",
        "R-OPS",
        "7 days",
        "Dispatched or dead-lettered domain events (schema §17)",
        "row_delete",
        "purge_outbox",
        "core",
    ),
    (
        "idempotency_keys",
        "OPS",
        "R-OPS",
        "0 days",
        "Removed once expires_at (24 h / 7 d money) passes",
        "row_delete",
        "purge_idempotency",
        "core",
    ),
    (
        "notifications",
        "D13",
        "R-NOTIF",
        "1 year",
        "Notification logs 1 year (privacy D13)",
        "row_delete",
        "purge_notifications",
        "notifications",
    ),
)

ENSURE_PARTITIONS = r"""
CREATE OR REPLACE FUNCTION maint.ensure_partitions(p_parent regclass, p_months_ahead integer DEFAULT 3)
RETURNS TABLE (partition_name text, action text, moved_rows bigint)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, maint, pg_temp
AS $fn$
DECLARE
  v_parent  text;
  v_schema  text;
  v_owner   oid;
  v_key     text;
  v_default oid;
  v_month   date;
  v_from    timestamptz;
  v_to      timestamptz;
  v_child   text;
  v_qchild  text;
  v_cols    text;
  v_n       bigint;
  v_movable boolean;
  v_prev    text := current_setting('app.maint', true);
  r         record;
  i         integer;
BEGIN
  -- FORCE RLS binds the owner too; the p_maint policies admit td_owner only while app.maint=on.
  PERFORM set_config('app.maint', 'on', true);
  SELECT c.relname, n.nspname, c.relowner INTO v_parent, v_schema, v_owner
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE c.oid = p_parent AND c.relkind = 'p';
  IF v_parent IS NULL OR v_schema <> 'public' OR v_parent <> ALL (ARRAY[__PARENTS__]) THEN
    RAISE EXCEPTION 'maint.ensure_partitions: % is not a registered partitioned parent', p_parent;
  END IF;
  IF p_months_ahead < 0 OR p_months_ahead > 24 THEN
    RAISE EXCEPTION 'maint.ensure_partitions: months_ahead must be 0..24';
  END IF;
  SELECT a.attname, pt.partdefid INTO v_key, v_default
    FROM pg_partitioned_table pt
    JOIN pg_attribute a ON a.attrelid = pt.partrelid AND a.attnum = pt.partattrs[0]
   WHERE pt.partrelid = p_parent AND pt.partstrat = 'r' AND pt.partnatts = 1;
  IF v_key IS NULL THEN
    RAISE EXCEPTION 'maint.ensure_partitions: % is not RANGE-partitioned on one column', p_parent;
  END IF;
  -- Rows can be moved only where nothing forbids deleting them from DEFAULT.
  v_movable := NOT EXISTS (
    SELECT 1 FROM pg_trigger t
     WHERE t.tgrelid = p_parent AND NOT t.tgisinternal AND (t.tgtype & 8) <> 0  -- DELETE
  );
  SELECT string_agg(quote_ident(a.attname), ', ' ORDER BY a.attnum) INTO v_cols
    FROM pg_attribute a WHERE a.attrelid = p_parent AND a.attnum > 0 AND NOT a.attisdropped;

  FOR i IN 0 .. p_months_ahead LOOP
    v_month := (date_trunc('month', now() AT TIME ZONE 'UTC') + make_interval(months => i))::date;
    v_from  := v_month::timestamp AT TIME ZONE 'UTC';
    v_to    := (v_month + interval '1 month')::timestamp AT TIME ZONE 'UTC';
    v_child := v_parent || '_' || to_char(v_month, 'YYYY_MM');
    v_qchild := format('%I.%I', v_schema, v_child);
    IF to_regclass(v_qchild) IS NOT NULL THEN
      partition_name := v_child; action := 'exists'; moved_rows := 0; RETURN NEXT; CONTINUE;
    END IF;
    v_n := 0;
    IF v_default <> 0 THEN
      EXECUTE format('SELECT count(*) FROM %s WHERE %I >= $1 AND %I < $2', v_default::regclass, v_key, v_key)
        INTO v_n USING v_from, v_to;
    END IF;
    IF v_n > 0 AND NOT v_movable THEN
      partition_name := v_child; action := 'skipped_default_rows'; moved_rows := v_n; RETURN NEXT; CONTINUE;
    END IF;
    IF v_n > 0 THEN
      EXECUTE format('ALTER TABLE %s DETACH PARTITION %s', p_parent, v_default::regclass);
    END IF;
    EXECUTE format('CREATE TABLE %s PARTITION OF %s FOR VALUES FROM (%L) TO (%L)', v_qchild, p_parent, v_from, v_to);
    IF v_n > 0 THEN
      EXECUTE format('INSERT INTO %s (%s) SELECT %s FROM %s WHERE %I >= $1 AND %I < $2',
                     v_qchild, v_cols, v_cols, v_default::regclass, v_key, v_key) USING v_from, v_to;
      EXECUTE format('DELETE FROM %s WHERE %I >= $1 AND %I < $2', v_default::regclass, v_key, v_key)
        USING v_from, v_to;
      EXECUTE format('ALTER TABLE %s ATTACH PARTITION %s DEFAULT', p_parent, v_default::regclass);
    END IF;

    -- Harden the child like the DEFAULT partition (DB-04): no default-privilege grants.
    EXECUTE format('REVOKE ALL ON %s FROM PUBLIC', v_qchild);
    FOR r IN SELECT rolname FROM pg_roles WHERE rolname IN ('td_app','td_readonly','td_audit_sealer','td_maintenance') LOOP
      EXECUTE format('REVOKE ALL ON %s FROM %I', v_qchild, r.rolname);
    END LOOP;
    IF v_default <> 0 THEN
      FOR r IN SELECT x.grantee, x.privilege_type
                 FROM pg_class c, aclexplode(c.relacl) x
                WHERE c.oid = v_default AND x.grantee <> v_owner LOOP
        EXECUTE format('GRANT %s ON %s TO %s', r.privilege_type, v_qchild,
                       CASE WHEN r.grantee = 0 THEN 'PUBLIC' ELSE quote_ident(pg_get_userbyid(r.grantee)) END);
      END LOOP;
      FOR r IN SELECT p.policyname, p.permissive, p.cmd, p.roles, p.qual, p.with_check
                 FROM pg_policies p
                 JOIN pg_class c ON c.relname = p.tablename
                 JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = p.schemaname
                WHERE c.oid = v_default LOOP
        EXECUTE format('CREATE POLICY %I ON %s AS %s FOR %s TO %s%s%s', r.policyname, v_qchild, r.permissive, r.cmd,
                       (SELECT string_agg(CASE WHEN x = 'public' THEN 'PUBLIC' ELSE quote_ident(x) END, ', ')
                          FROM unnest(r.roles) x),
                       CASE WHEN r.qual IS NULL THEN '' ELSE ' USING (' || r.qual || ')' END,
                       CASE WHEN r.with_check IS NULL THEN '' ELSE ' WITH CHECK (' || r.with_check || ')' END);
      END LOOP;
    END IF;
    EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', v_qchild);
    EXECUTE format('ALTER TABLE %s FORCE ROW LEVEL SECURITY', v_qchild);
    partition_name := v_child;
    action := CASE WHEN v_n > 0 THEN 'created_moved' ELSE 'created' END;
    moved_rows := v_n;
    RETURN NEXT;
  END LOOP;
  PERFORM set_config('app.maint', coalesce(v_prev, ''), true);
END
$fn$;
"""

DROP_EXPIRED = r"""
CREATE OR REPLACE FUNCTION maint.drop_expired_partitions(p_parent regclass)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, maint, pg_temp
AS $fn$
DECLARE
  v_parent   text;
  v_interval interval;
  v_cutoff   timestamptz;
  v_upper    timestamptz;
  v_n        integer := 0;
  r          record;
BEGIN
  SELECT c.relname INTO v_parent FROM pg_class c WHERE c.oid = p_parent AND c.relkind = 'p';
  SELECT min(rp.retention_interval) INTO v_interval
    FROM public.retention_policies rp
   WHERE rp.table_name = v_parent AND rp.is_active AND rp.deletion_method = 'partition_drop';
  IF v_parent IS NULL OR v_interval IS NULL OR v_parent = 'audit_log' THEN
    RAISE EXCEPTION 'maint.drop_expired_partitions: % has no partition_drop retention policy', p_parent;
  END IF;
  v_cutoff := now() - v_interval;
  FOR r IN SELECT i.inhrelid::regclass AS child, pg_get_expr(c.relpartbound, c.oid) AS bound
             FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
            WHERE i.inhparent = p_parent LOOP
    CONTINUE WHEN r.bound = 'DEFAULT';
    v_upper := substring(r.bound FROM 'TO \(''([^'']+)''\)')::timestamptz;
    CONTINUE WHEN v_upper IS NULL OR v_upper > v_cutoff;
    EXECUTE format('ALTER TABLE %s DETACH PARTITION %s', p_parent, r.child);
    EXECUTE format('DROP TABLE %s', r.child);
    v_n := v_n + 1;
  END LOOP;
  RETURN v_n;
END
$fn$;
"""

PURGE_ROWS = r"""
CREATE OR REPLACE FUNCTION maint.purge_expired_rows(p_table text, p_batch integer DEFAULT 5000,
                                                    p_max_batches integer DEFAULT 200)
RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, maint, pg_temp
AS $fn$
DECLARE
  v_interval interval;
  v_pred     text;
  v_cutoff   timestamptz;
  v_total    bigint := 0;
  v_n        bigint;
  v_prev     text := current_setting('app.maint', true);
  v_kept_case text := 'NOT EXISTS (SELECT 1 FROM public.security_cases sc WHERE sc.user_id = s.user_id '
                      'AND (sc.status <> ''closed'' OR sc.legal_hold))';
  i          integer := 0;
BEGIN
  SELECT min(rp.retention_interval) INTO v_interval
    FROM public.retention_policies rp WHERE rp.table_name = p_table AND rp.is_active;
  IF v_interval IS NULL THEN
    RAISE EXCEPTION 'maint.purge_expired_rows: % has no active retention policy', p_table;
  END IF;
  v_pred := CASE p_table
    WHEN 'login_attempts' THEN 's.attempted_at < $1'
    WHEN 'session_network_observations' THEN 'coalesce(s.last_seen_at, s.first_seen_at) < $1'
    WHEN 'auth_sessions' THEN 'coalesce(s.ended_at, s.absolute_expires_at) < $1'
    WHEN 'security_signals' THEN 's.occurred_at < $1 AND ' || v_kept_case
    WHEN 'risk_evaluations' THEN 's.evaluated_at < $1 AND ' || v_kept_case ||
         ' AND NOT EXISTS (SELECT 1 FROM public.security_cases c2 WHERE c2.id = s.case_id'
         ' AND (c2.status <> ''closed'' OR c2.legal_hold))'
    WHEN 'playback_sessions' THEN 's.started_at < $1'
    WHEN 'attempt_events' THEN 's.occurred_at < $1'
    WHEN 'verification_tokens' THEN 'coalesce(s.consumed_at, s.expires_at) < $1'
    WHEN 'password_reset_tokens' THEN 'coalesce(s.consumed_at, s.expires_at) < $1'
    WHEN 'outbox_events' THEN '((s.dispatched_at IS NOT NULL AND s.dispatched_at < $1) OR '
                              '(s.dispatched_at IS NULL AND s.attempts >= 10 AND s.occurred_at < $1))'
    WHEN 'idempotency_keys' THEN 's.expires_at < $1'
    WHEN 'notifications' THEN 's.created_at < $1'
  END;
  IF v_pred IS NULL THEN
    RAISE EXCEPTION 'maint.purge_expired_rows: no purge rule for %', p_table;
  END IF;
  IF p_batch < 1 OR p_max_batches < 1 THEN
    RAISE EXCEPTION 'maint.purge_expired_rows: batch sizes must be positive';
  END IF;
  v_cutoff := now() - v_interval;
  -- FORCE RLS binds the owner too; the p_maint policies admit td_owner only while app.maint=on.
  PERFORM set_config('app.maint', 'on', true);
  LOOP
    i := i + 1;
    EXECUTE format('DELETE FROM public.%I t WHERE (t.tableoid, t.ctid) IN '
                   '(SELECT s.tableoid, s.ctid FROM public.%I s WHERE %s LIMIT %s)',
                   p_table, p_table, v_pred, p_batch) USING v_cutoff;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    v_total := v_total + v_n;
    EXIT WHEN v_n < p_batch OR i >= p_max_batches;
  END LOOP;
  PERFORM set_config('app.maint', coalesce(v_prev, ''), true);
  RETURN v_total;
END
$fn$;
"""

RUN_PARTITIONS = r"""
CREATE OR REPLACE FUNCTION maint.run_partition_maintenance(p_months_ahead integer DEFAULT 3)
RETURNS TABLE (parent text, partition_name text, action text, moved_rows bigint)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, maint, pg_temp
AS $fn$
DECLARE
  v_parent text;
  v_summary jsonb := '[]'::jsonb;
  r record;
BEGIN
  FOREACH v_parent IN ARRAY ARRAY[__PARENTS__] LOOP
    CONTINUE WHEN to_regclass('public.' || v_parent) IS NULL;
    FOR r IN SELECT * FROM maint.ensure_partitions(('public.' || v_parent)::regclass, p_months_ahead) LOOP
      parent := v_parent; partition_name := r.partition_name; action := r.action; moved_rows := r.moved_rows;
      IF r.action <> 'exists' THEN
        v_summary := v_summary || jsonb_build_object('partition', r.partition_name, 'action', r.action,
                                                     'moved_rows', r.moved_rows);
      END IF;
      RETURN NEXT;
    END LOOP;
  END LOOP;
  IF jsonb_array_length(v_summary) > 0 THEN
    INSERT INTO public.audit_outbox (id, record) VALUES (gen_random_uuid(), jsonb_build_object(
      'actor_type', 'system', 'actor_roles', jsonb_build_array('system:maint.partitions'),
      'action', 'maint.partitions.premade', 'target_type', 'partition', 'after_state',
      jsonb_build_object('months_ahead', p_months_ahead, 'changes', v_summary)));
  END IF;
END
$fn$;
"""

RUN_RETENTION = r"""
CREATE OR REPLACE FUNCTION maint.run_retention(p_batch integer DEFAULT 5000, p_max_batches integer DEFAULT 200)
RETURNS TABLE (table_name text, partitions_dropped integer, rows_deleted bigint)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, maint, pg_temp
AS $fn$
DECLARE
  v_summary jsonb := '{}'::jsonb;
  v_drop integer;
  v_rows bigint;
  t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['login_attempts','session_network_observations','auth_sessions',
                           'security_signals','risk_evaluations','playback_sessions','attempt_events',
                           'verification_tokens','password_reset_tokens','outbox_events',
                           'idempotency_keys','notifications'] LOOP
    CONTINUE WHEN to_regclass('public.' || t) IS NULL
      OR NOT EXISTS (SELECT 1 FROM public.retention_policies rp WHERE rp.table_name = t AND rp.is_active);
    v_drop := 0;
    -- Case-referenced risk rows must survive, so those two tables are purged row by row only.
    IF t IN ('login_attempts','session_network_observations','playback_sessions','attempt_events') THEN
      v_drop := maint.drop_expired_partitions(('public.' || t)::regclass);
    END IF;
    v_rows := maint.purge_expired_rows(t, p_batch, p_max_batches);
    table_name := t; partitions_dropped := v_drop; rows_deleted := v_rows;
    v_summary := v_summary || jsonb_build_object(t, jsonb_build_object('partitions_dropped', v_drop,
                                                                       'rows_deleted', v_rows));
    RETURN NEXT;
  END LOOP;
  INSERT INTO public.audit_outbox (id, record) VALUES (gen_random_uuid(), jsonb_build_object(
    'actor_type', 'system', 'actor_roles', jsonb_build_array('system:maint.retention'),
    'action', 'maint.retention.purged', 'target_type', 'retention_policy', 'after_state', v_summary));
END
$fn$;
"""

# Tables the functions read or delete as td_owner. Policies on the parents cover queries through
# them; the DEFAULT partitions are read directly while moving rows (and their policies are
# copied onto every new child).
MAINT_POLICY_TABLES = (
    *PARENTS,
    *(f"{p}_default" for p in PARENTS),
    "auth_sessions",
    "verification_tokens",
    "password_reset_tokens",
    "outbox_events",
    "idempotency_keys",
    "notifications",
    "security_cases",
)
MAINT_GUC = "current_setting('app.maint', true) = 'on'"

SIGNATURES = (
    "maint.ensure_partitions(regclass, integer)",
    "maint.drop_expired_partitions(regclass)",
    "maint.purge_expired_rows(text, integer, integer)",
    "maint.run_partition_maintenance(integer)",
    "maint.run_retention(integer, integer)",
)


def upgrade() -> None:
    parents = ", ".join(f"'{p}'" for p in PARENTS)
    for t in MAINT_POLICY_TABLES:
        op.execute(
            f"CREATE POLICY p_maint ON {t} FOR ALL TO td_owner USING ({MAINT_GUC}) WITH CHECK ({MAINT_GUC})"
        )
    for sql in (ENSURE_PARTITIONS, DROP_EXPIRED, PURGE_ROWS, RUN_PARTITIONS, RUN_RETENTION):
        op.execute(sql.replace("__PARENTS__", parents))
    for sig in SIGNATURES:
        op.execute(f"REVOKE ALL ON FUNCTION {sig} FROM PUBLIC")
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'td_maintenance') THEN
            GRANT USAGE ON SCHEMA maint TO td_maintenance;
            GRANT EXECUTE ON FUNCTION {", ".join(SIGNATURES)} TO td_maintenance;
          END IF;
        END $$;
        """
    )
    values = ",\n".join(
        "(gen_random_uuid(), '{1}', '{0}', '{2}', interval '{3}', '{4}', '{5}', '{6}', '{7}')".format(
            *(v.replace("'", "''") for v in row)
        )
        for row in NEW_POLICIES
    )
    op.execute(
        "INSERT INTO retention_policies (id, data_category, table_name, retention_class, retention_interval, "
        "basis, deletion_method, job_name, owner_module) VALUES\n"
        + values
        + "\nON CONFLICT (table_name, data_category) DO NOTHING"
    )
    # privacy §7 names the security purge job ``purge_security_signals``.
    op.execute(
        "UPDATE retention_policies SET job_name = 'purge_security_signals' WHERE job_name = 'purge_risk'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE retention_policies SET job_name = 'purge_risk' WHERE job_name = 'purge_security_signals'"
    )
    for row in NEW_POLICIES:
        op.execute(
            f"DELETE FROM retention_policies WHERE table_name = '{row[0]}' AND data_category = '{row[1]}'"
        )
    for sig in reversed(SIGNATURES):
        op.execute(f"DROP FUNCTION IF EXISTS {sig}")
    for t in MAINT_POLICY_TABLES:
        op.execute(f"DROP POLICY IF EXISTS p_maint ON {t}")
