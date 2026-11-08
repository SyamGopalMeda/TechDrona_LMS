"""security (on the support branch): purge_closed_cases retention (privacy D8, §7; core request 6, secadmin request 9)

Revision ID: support_0003
Revises: support_0002
Create Date: 2026-11-03

Branch placement (w3be): this security-owned revision lives on the ``support`` branch because it
needs ``support_tickets`` (``support_0001``) and ``retention_policies``/``policy_settings``
(``admin_0001``, a dependency of ``support_0001``); the ``maint`` schema comes from the single
``depends_on`` ``core_base_0002``. As ``security_0003`` it needed cross-branch ``depends_on`` entries back to
revisions that themselves depend on ``security_0001``, which made alembic's head bookkeeping fail
nondeterministically on a fresh database (``KeyError: 'security_0001'``, hash-seed dependent).

``docs/privacy-and-data-retention.md`` D8 / §7 ``purge_closed_cases`` (weekly):

* attachments (``unblock_requests.attachments``, ``case_notes.attachments``; objects in the
  private uploads bucket) are deleted **90 days after case closure**;
* case data (``security_cases`` with its ``case_notes``, ``case_decisions``,
  ``unblock_requests`` and case-linked ``account_restrictions``) is deleted **1 year after
  closure, 3 years if disputed**. A case on ``legal_hold`` is never purged.

"Disputed" = the student used the second-level appeal on the case (an unblock request with
``is_second_level_appeal`` or ``appeal_used``). A case is also kept while a restriction linked
to it is still in force, while an unblock request on it is still open, while one of its
attachments has not been purged yet (objects first, then rows: no orphaned objects), or while a
``policy_settings`` user exception cites one of its decisions (``ck_ps_user_exception`` needs
that reference).

Functions follow the ``core_base_0002`` pattern (owned by td_owner, ``SECURITY DEFINER``,
``search_path`` pinned, EXECUTE only for ``td_maintenance``):

* ``maint.closed_case_attachments(limit)`` — attachment keys due for deletion (whole rows, so a
  row is never half-listed);
* ``maint.clear_closed_case_attachments(source, ids)`` — empties those attachment lists after the
  application deleted the objects through the storage abstraction (rows re-checked);
* ``maint.purge_closed_cases(batch)`` — deletes eligible case data; detaches
  ``support_tickets`` links (support tickets have their own 3-year retention).

Each writes an ``audit_outbox`` summary. The existing ``retention_policies`` row for
``unblock_requests`` (job ``purge_cases``, category D9) is renamed to job
``purge_closed_cases`` / category D8, and the other D8 tables are registered.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "support_0003"
down_revision: str | Sequence[str] | None = "support_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = ("core_base_0002",)

ATTACHMENT_AGE = "90 days"
DISPUTED_AGE = "3 years"

# Tables with FORCE RLS that the functions touch and core_base_0002 did not cover
# (security_cases already has p_maint).
MAINT_POLICY_TABLES = ("account_restrictions", "unblock_requests", "support_tickets")
MAINT_GUC = "current_setting('app.maint', true) = 'on'"

NEW_POLICIES = (
    ("security_cases", "Security cases: closure + 1 year; 3 years if disputed or legal hold (privacy D8)"),
    ("case_notes", "Reviewer notes: with their case (privacy D8)"),
    ("case_decisions", "Case decisions: with their case (privacy D8)"),
    ("account_restrictions", "Case-linked restrictions: with their case (privacy D8)"),
)

_ELIGIBLE_ATTACHMENTS = f"""c.status = 'closed' AND NOT c.legal_hold
                       AND c.closed_at < now() - interval '{ATTACHMENT_AGE}'"""

LIST_ATTACHMENTS = rf"""
CREATE OR REPLACE FUNCTION maint.closed_case_attachments(p_limit integer DEFAULT 500)
RETURNS TABLE (source text, row_id uuid, s3_key text)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, maint, pg_temp
AS $fn$
DECLARE
  v_prev text := current_setting('app.maint', true);
BEGIN
  IF p_limit < 1 THEN
    RAISE EXCEPTION 'maint.closed_case_attachments: limit must be positive';
  END IF;
  -- FORCE RLS binds the owner too; the p_maint policies admit td_owner only while app.maint=on.
  PERFORM set_config('app.maint', 'on', true);
  RETURN QUERY
    WITH rows_due AS (
      (SELECT 'unblock_requests'::text AS src, ur.id, ur.attachments
         FROM public.unblock_requests ur JOIN public.security_cases c ON c.id = ur.case_id
        WHERE {_ELIGIBLE_ATTACHMENTS} AND jsonb_array_length(ur.attachments) > 0
        ORDER BY c.closed_at LIMIT p_limit)
      UNION ALL
      (SELECT 'case_notes'::text, n.id, n.attachments
         FROM public.case_notes n JOIN public.security_cases c ON c.id = n.case_id
        WHERE {_ELIGIBLE_ATTACHMENTS} AND jsonb_array_length(n.attachments) > 0
        ORDER BY c.closed_at LIMIT p_limit)
    )
    SELECT r.src, r.id, a.value->>'s3_key'
      FROM rows_due r CROSS JOIN LATERAL jsonb_array_elements(r.attachments) a(value);
  PERFORM set_config('app.maint', coalesce(v_prev, ''), true);
END
$fn$;
"""

CLEAR_ATTACHMENTS = rf"""
CREATE OR REPLACE FUNCTION maint.clear_closed_case_attachments(p_source text, p_ids uuid[])
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, maint, pg_temp
AS $fn$
DECLARE
  v_n    integer := 0;
  v_prev text := current_setting('app.maint', true);
BEGIN
  PERFORM set_config('app.maint', 'on', true);
  IF p_source = 'unblock_requests' THEN
    UPDATE public.unblock_requests ur SET attachments = '[]'::jsonb
      FROM public.security_cases c
     WHERE ur.id = ANY (p_ids) AND c.id = ur.case_id AND {_ELIGIBLE_ATTACHMENTS}
       AND jsonb_array_length(ur.attachments) > 0;
  ELSIF p_source = 'case_notes' THEN
    UPDATE public.case_notes n SET attachments = '[]'::jsonb
      FROM public.security_cases c
     WHERE n.id = ANY (p_ids) AND c.id = n.case_id AND {_ELIGIBLE_ATTACHMENTS}
       AND jsonb_array_length(n.attachments) > 0;
  ELSE
    RAISE EXCEPTION 'maint.clear_closed_case_attachments: unknown source %', p_source;
  END IF;
  GET DIAGNOSTICS v_n = ROW_COUNT;
  IF v_n > 0 THEN
    INSERT INTO public.audit_outbox (id, record) VALUES (gen_random_uuid(), jsonb_build_object(
      'actor_type', 'system', 'actor_roles', jsonb_build_array('system:security.purge_closed_cases'),
      'action', 'security.case_attachments.purged', 'target_type', p_source,
      'after_state', jsonb_build_object('rows', v_n)));
  END IF;
  PERFORM set_config('app.maint', coalesce(v_prev, ''), true);
  RETURN v_n;
END
$fn$;
"""

PURGE_CASES = rf"""
CREATE OR REPLACE FUNCTION maint.purge_closed_cases(p_batch integer DEFAULT 500)
RETURNS TABLE (table_name text, rows_deleted bigint)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, maint, pg_temp
AS $fn$
DECLARE
  v_interval interval;
  v_cases    uuid[];
  v_requests uuid[];
  v_decisions uuid[];
  v_n        bigint;
  v_summary  jsonb := '{{}}'::jsonb;
  v_prev     text := current_setting('app.maint', true);
  t          text;
BEGIN
  IF p_batch < 1 THEN
    RAISE EXCEPTION 'maint.purge_closed_cases: batch must be positive';
  END IF;
  SELECT min(rp.retention_interval) INTO v_interval
    FROM public.retention_policies rp WHERE rp.table_name = 'security_cases' AND rp.is_active;
  IF v_interval IS NULL THEN
    RAISE EXCEPTION 'maint.purge_closed_cases: security_cases has no active retention policy';
  END IF;
  PERFORM set_config('app.maint', 'on', true);

  SELECT coalesce(array_agg(x.id), '{{}}') INTO v_cases FROM (
    SELECT c.id FROM public.security_cases c
     WHERE c.status = 'closed' AND c.closed_at IS NOT NULL AND NOT c.legal_hold
       AND c.closed_at < now() - CASE WHEN EXISTS (
             SELECT 1 FROM public.unblock_requests u
              WHERE u.case_id = c.id AND (u.is_second_level_appeal OR u.appeal_used))
           THEN GREATEST(v_interval, interval '{DISPUTED_AGE}') ELSE v_interval END
       AND NOT EXISTS (SELECT 1 FROM public.account_restrictions r
                        WHERE r.case_id = c.id AND r.ended_at IS NULL)
       AND NOT EXISTS (SELECT 1 FROM public.unblock_requests u
                        WHERE u.case_id = c.id
                          AND (u.state IN ('draft','submitted','under_review','info_requested','escalated')
                               OR jsonb_array_length(u.attachments) > 0))
       AND NOT EXISTS (SELECT 1 FROM public.case_notes n
                        WHERE n.case_id = c.id AND jsonb_array_length(n.attachments) > 0)
       AND NOT EXISTS (SELECT 1 FROM public.policy_settings ps
                         JOIN public.case_decisions d ON d.id = ps.case_decision_id
                        WHERE d.case_id = c.id)
     ORDER BY c.closed_at
     LIMIT p_batch) x;

  v_requests := ARRAY(SELECT u.id FROM public.unblock_requests u WHERE u.case_id = ANY (v_cases));
  v_decisions := ARRAY(SELECT d.id FROM public.case_decisions d WHERE d.case_id = ANY (v_cases));

  -- Detach references that outlive the case (support tickets: 3 years, privacy D13).
  UPDATE public.support_tickets s SET related_case_id = NULL WHERE s.related_case_id = ANY (v_cases);
  UPDATE public.support_tickets s SET related_unblock_request_id = NULL
   WHERE s.related_unblock_request_id = ANY (v_requests);
  UPDATE public.account_restrictions r SET decision_id = NULL WHERE r.decision_id = ANY (v_decisions);
  UPDATE public.unblock_requests u SET restriction_id = NULL
   WHERE NOT (u.case_id = ANY (v_cases))
     AND u.restriction_id IN (SELECT r.id FROM public.account_restrictions r WHERE r.case_id = ANY (v_cases));

  FOREACH t IN ARRAY ARRAY['case_notes','case_decisions','unblock_requests','account_restrictions',
                           'security_cases'] LOOP
    IF t = 'security_cases' THEN
      DELETE FROM public.security_cases c WHERE c.id = ANY (v_cases);
    ELSE
      EXECUTE format('DELETE FROM public.%I x WHERE x.case_id = ANY ($1)', t) USING v_cases;
    END IF;
    GET DIAGNOSTICS v_n = ROW_COUNT;
    table_name := t; rows_deleted := v_n;
    v_summary := v_summary || jsonb_build_object(t, v_n);
    RETURN NEXT;
  END LOOP;

  INSERT INTO public.audit_outbox (id, record) VALUES (gen_random_uuid(), jsonb_build_object(
    'actor_type', 'system', 'actor_roles', jsonb_build_array('system:security.purge_closed_cases'),
    'action', 'security.closed_cases.purged', 'target_type', 'security_case',
    'after_state', v_summary));
  PERFORM set_config('app.maint', coalesce(v_prev, ''), true);
END
$fn$;
"""

SIGNATURES = (
    "maint.closed_case_attachments(integer)",
    "maint.clear_closed_case_attachments(text, uuid[])",
    "maint.purge_closed_cases(integer)",
)


def upgrade() -> None:
    for t in MAINT_POLICY_TABLES:
        op.execute(
            f"CREATE POLICY p_maint ON {t} FOR ALL TO td_owner USING ({MAINT_GUC}) WITH CHECK ({MAINT_GUC})"
        )
    for sql in (LIST_ATTACHMENTS, CLEAR_ATTACHMENTS, PURGE_CASES):
        op.execute(sql)
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
    op.execute(
        "UPDATE retention_policies SET job_name = 'purge_closed_cases', data_category = 'D8', "
        "basis = 'Case closure + 1 year; 3 years if disputed or legal hold (privacy D8)' "
        "WHERE table_name = 'unblock_requests' AND job_name = 'purge_cases'"
    )
    values = ",\n".join(
        f"(gen_random_uuid(), 'D8', '{table}', 'R-RISK', interval '1 year', '{basis}', 'row_delete', "
        "'purge_closed_cases', 'security')"
        for table, basis in NEW_POLICIES
    )
    op.execute(
        "INSERT INTO retention_policies (id, data_category, table_name, retention_class, retention_interval, "
        "basis, deletion_method, job_name, owner_module) VALUES\n"
        + values
        + "\nON CONFLICT (table_name, data_category) DO NOTHING"
    )


def downgrade() -> None:
    for table, _basis in NEW_POLICIES:
        op.execute(
            f"DELETE FROM retention_policies WHERE table_name = '{table}' AND data_category = 'D8' "
            "AND job_name = 'purge_closed_cases'"
        )
    op.execute(
        "UPDATE retention_policies SET job_name = 'purge_cases', data_category = 'D9', "
        "basis = 'Case closure + 1 year (UNB §9)' "
        "WHERE table_name = 'unblock_requests' AND job_name = 'purge_closed_cases'"
    )
    for sig in reversed(SIGNATURES):
        op.execute(f"DROP FUNCTION IF EXISTS {sig}")
    for t in MAINT_POLICY_TABLES:
        op.execute(f"DROP POLICY IF EXISTS p_maint ON {t}")
