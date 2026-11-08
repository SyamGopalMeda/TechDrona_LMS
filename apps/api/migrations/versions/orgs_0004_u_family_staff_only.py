"""orgs: RLS family U — the organization path is for company STAFF only

Revision ID: orgs_0004
Revises: orgs_0003
Create Date: 2026-11-08

docs/single-company/ws1-close.md §4 (WS5 note "review RLS family U"). Family ``U`` was

    user_id = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids()))
    OR app.is_platform()

With one company organization every batch student is a member of the same organization, so
the organization branch let any batch student read (at the database level) every other
student's org-attributed attempts, submissions, grades, progress, heartbeats, certificates
... (≈50 policies incl. partitions). The application layer always filtered by user / batch,
so this is defence in depth, the same hole ``identity_0005`` closed for ``users``.

Now the organization branch also requires ``app.caller_is_org_staff()``: the caller holds an
active ``member_type='staff'`` membership in one of ``app.org_ids()``, or a live non-student
role grant carrying one of those organization ids (trainer / evaluator batch grants do).
The function has no row argument, so Postgres evaluates it once per statement (InitPlan).
Own rows (``user_id = app.user_id()``) and the platform bypass are unchanged.

Every policy named ``p_u`` is altered in place (parents and existing partitions);
``maint.ensure_partitions`` copies the parent's policy to new partitions, and
``app.core.migration_helpers`` uses the new predicate for future tables.
Downgrade restores the previous predicate and drops the function.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "orgs_0004"
down_revision: str | Sequence[str] | None = "orgs_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "user_id = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids())) "
    "OR app.is_platform()"
)
_NEW = (
    "user_id = app.user_id() OR (organization_id IS NOT NULL AND organization_id = ANY (app.org_ids()) "
    "AND app.caller_is_org_staff()) OR app.is_platform()"
)


def _alter_all(predicate: str) -> None:
    op.execute(
        f"""
        DO $$
        DECLARE r record;
        BEGIN
          FOR r IN SELECT schemaname, tablename FROM pg_policies
                    WHERE policyname = 'p_u' AND schemaname = 'public'
          LOOP
            EXECUTE format('ALTER POLICY p_u ON %I.%I USING ({predicate}) WITH CHECK ({predicate})',
                           r.schemaname, r.tablename);
          END LOOP;
        END $$;
        """
    )


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.caller_is_org_staff() RETURNS boolean
        LANGUAGE sql STABLE SECURITY INVOKER AS
        $$
          SELECT EXISTS (SELECT 1 FROM org_memberships m
                          WHERE m.user_id = app.user_id() AND m.organization_id = ANY (app.org_ids())
                            AND m.member_type = 'staff' AND m.status = 'active')
              OR EXISTS (SELECT 1 FROM role_grants g JOIN roles r ON r.id = g.role_id
                          WHERE g.user_id = app.user_id() AND g.organization_id = ANY (app.org_ids())
                            AND g.revoked_at IS NULL AND (g.expires_at IS NULL OR g.expires_at > now())
                            AND r.role_key <> 'student')
        $$;
        GRANT EXECUTE ON FUNCTION app.caller_is_org_staff() TO td_app, td_readonly;
        """
    )
    _alter_all(_NEW.replace("'", "''"))


def downgrade() -> None:
    _alter_all(_OLD.replace("'", "''"))
    op.execute("DROP FUNCTION IF EXISTS app.caller_is_org_staff()")
