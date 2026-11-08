"""analytics: single company — drop organization rollups and org exports, staff-only org rows

Revision ID: analytics_0003
Revises: analytics_0002
Create Date: 2026-11-07

REMOVAL-PLAN §1.2 (analytics), §1.3, §5 step 8.

* Organization rollups go: ``daily_learning_aggregates`` / ``weekly_learning_aggregates`` rows
  with ``entity_kind='organization'`` and org-level ``cohort_learning_aggregates`` cells
  (``organization_id`` set, ``batch_id`` NULL) are deleted, and the ``entity_kind`` CHECKs no
  longer allow ``organization``. Batch cohort cells stay (batch reports).
* Org-scoped export jobs (``scope_type='organization'`` and the removed coordinator reports
  ``coordinator.org_overview`` / ``coordinator.org_learners``) are deleted; the export
  ``scope_type`` CHECK drops ``organization``. ``coordinator.batch_progress`` jobs are renamed
  ``batch.progress``.
* RLS hardening (same reason as identity_0005 / §2.4): with one company organization every
  batch student is a member of the org, so the generic ``U`` predicate
  (``organization_id = ANY(app.org_ids())``) would let any batch student read every other
  student's org-attributed analytics rows (events, heartbeats, intervals, aggregates, mastery)
  and org export jobs. The organization branch now also requires the caller to be **staff** of
  that organization (``app.analytics_staff_org_ids()``: an active staff membership or a live
  non-student role grant carrying the organization). Own rows and platform access are
  unchanged.

Data steps run as the table owner; FORCE RLS is lifted for the statements and restored.
``downgrade()`` restores the schema (CHECKs, policies) only; restore data from the backup dump.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "analytics_0003"
down_revision: str | Sequence[str] | None = "analytics_0002"
branch_labels: str | Sequence[str] | None = None
# No cross-branch depends_on: analytics_0001/0002 already depend on orgs_0001 and rbac_0001
# (and see docs/single-company/ws1.md, Alembic pitfall).
depends_on: str | Sequence[str] | None = None

_ROLES = "td_app, td_readonly"
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
_POLICY_TABLES = (*U_TABLES, *(f"{t}_default" for t in PARTITIONED))

_U_NEW = (
    "user_id = app.user_id() OR (organization_id IS NOT NULL AND "
    "organization_id = ANY (app.analytics_staff_org_ids())) OR app.is_platform()"
)
_U_OLD = (
    "user_id = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) "
    "OR app.is_platform()"
)
_EJ_NEW = (
    "requested_by = app.user_id() OR (organization_id IS NOT NULL AND "
    "organization_id = ANY (app.analytics_staff_org_ids())) OR app.is_platform()"
)
_EJ_OLD = (
    "requested_by = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) "
    "OR app.is_platform()"
)

_DLA_KINDS = "'_total','course','lesson','topic','test_attempt','coding_problem','lesson_asset'"
_DLA_KINDS_OLD = (
    "'_total','course','lesson','topic','test_attempt','coding_problem','organization','lesson_asset'"
)
_WLA_KINDS = "'_total','course','topic'"
_WLA_KINDS_OLD = "'_total','course','topic','organization'"
_EJ_SCOPES = "'platform','batch','course','self'"
_EJ_SCOPES_OLD = "'platform','organization','batch','course','self'"

_FORCED = (
    "daily_learning_aggregates",
    "weekly_learning_aggregates",
    "cohort_learning_aggregates",
    "export_jobs",
)


def _check(table: str, name: str, column: str, values: str) -> None:
    op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")
    op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({column} IN ({values}))")


def _policies(u_pred: str, ej_pred: str) -> None:
    for t in _POLICY_TABLES:
        op.execute(f"DROP POLICY IF EXISTS p_u ON {t}")
        op.execute(f"CREATE POLICY p_u ON {t} FOR ALL TO {_ROLES} USING ({u_pred}) WITH CHECK ({u_pred})")
    op.execute("DROP POLICY IF EXISTS p_ej ON export_jobs")
    op.execute(
        f"CREATE POLICY p_ej ON export_jobs FOR ALL TO {_ROLES} USING ({ej_pred}) WITH CHECK ({ej_pred})"
    )


def upgrade() -> None:
    # 1. Data: organization rollups and org-scoped exports.
    for t in _FORCED:
        op.execute(f"ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY")
    op.execute("DELETE FROM daily_learning_aggregates WHERE entity_kind = 'organization'")
    op.execute("DELETE FROM weekly_learning_aggregates WHERE entity_kind = 'organization'")
    op.execute(
        "DELETE FROM cohort_learning_aggregates WHERE organization_id IS NOT NULL AND batch_id IS NULL"
    )
    op.execute(
        "DELETE FROM export_jobs WHERE scope_type = 'organization' "
        "OR report_key IN ('coordinator.org_overview', 'coordinator.org_learners')"
    )
    op.execute(
        "UPDATE export_jobs SET report_key = 'batch.progress' WHERE report_key = 'coordinator.batch_progress'"
    )
    for t in _FORCED:
        op.execute(f"ALTER TABLE {t} FORCE ROW LEVEL SECURITY")

    # 2. Tightened CHECKs.
    _check(
        "daily_learning_aggregates", "daily_learning_aggregates_entity_kind_check", "entity_kind", _DLA_KINDS
    )
    _check(
        "weekly_learning_aggregates",
        "weekly_learning_aggregates_entity_kind_check",
        "entity_kind",
        _WLA_KINDS,
    )
    _check("export_jobs", "export_jobs_scope_type_check", "scope_type", _EJ_SCOPES)

    # 3. Staff-only organization branch in RLS.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.analytics_staff_org_ids() RETURNS uuid[]
        LANGUAGE sql STABLE SECURITY INVOKER AS
        $$
          SELECT coalesce(array_agg(DISTINCT s.o), '{}'::uuid[]) FROM (
            SELECT m.organization_id AS o FROM org_memberships m
             WHERE m.user_id = app.user_id() AND m.organization_id = ANY (app.org_ids())
               AND m.member_type = 'staff' AND m.status = 'active'
            UNION
            SELECT g.organization_id FROM role_grants g JOIN roles r ON r.id = g.role_id
             WHERE g.user_id = app.user_id() AND g.organization_id = ANY (app.org_ids())
               AND g.revoked_at IS NULL AND (g.expires_at IS NULL OR g.expires_at > now())
               AND r.role_key <> 'student'
          ) s
        $$;
        GRANT EXECUTE ON FUNCTION app.analytics_staff_org_ids() TO td_app, td_readonly;
        """
    )
    _policies(_U_NEW, _EJ_NEW)


def downgrade() -> None:
    _policies(_U_OLD, _EJ_OLD)
    op.execute("DROP FUNCTION IF EXISTS app.analytics_staff_org_ids()")
    _check("export_jobs", "export_jobs_scope_type_check", "scope_type", _EJ_SCOPES_OLD)
    _check(
        "weekly_learning_aggregates",
        "weekly_learning_aggregates_entity_kind_check",
        "entity_kind",
        _WLA_KINDS_OLD,
    )
    _check(
        "daily_learning_aggregates",
        "daily_learning_aggregates_entity_kind_check",
        "entity_kind",
        _DLA_KINDS_OLD,
    )
