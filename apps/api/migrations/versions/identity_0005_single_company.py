"""identity: single-company RLS hardening (students cannot read other students)

Revision ID: identity_0005
Revises: identity_0004
Create Date: 2026-11-06

docs/single-company/REMOVAL-PLAN.md §2.4 and §5 step 3. With one company organization every
batch student shares the organization with every other batch student, so the old
``app.user_visible_in_orgs(target)`` ("target has a membership in one of my orgs") would let
any batch student read every other student's ``users`` / ``user_profiles`` row.

``app.user_visible_in_orgs(target)`` now returns true only when

* (a) the caller is **staff** of a shared organization the target belongs to (an active
  ``org_memberships`` row with ``member_type='staff'``, or a live non-student role grant
  carrying that ``organization_id``), or
* (b) the target is **staff** of one of the caller's organizations (so students still see
  their trainers' names).

Platform principals keep their ``app.is_platform()`` bypass in the policies themselves. The
function stays SECURITY INVOKER: the caller's own RLS on ``org_memberships`` / ``role_grants``
applies inside it.

Also: the consent purpose ``college_data_sharing`` is no longer accepted for **new** rows
(``NOT VALID`` CHECK: historic rows are legal evidence and stay). ``college_name_text`` is kept
as the optional "Institution" profile field (owner decision D6): no change.

Downgrade restores the previous function and CHECK.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "identity_0005"
down_revision: str | Sequence[str] | None = "identity_0004"
branch_labels: str | Sequence[str] | None = None
# Not orgs_0002 on purpose: a cross-branch dependent would make Alembic drop orgs_0002 from
# alembic_version, and the later merge step orgs_0003 would then fail (KeyError in update_to_step).
depends_on: str | Sequence[str] | None = ("orgs_0001", "rbac_0001")

_LIVE_STAFF_GRANT = """
    SELECT 1 FROM role_grants g JOIN roles r ON r.id = g.role_id
     WHERE g.user_id = {who} AND g.organization_id = {org}
       AND g.revoked_at IS NULL AND (g.expires_at IS NULL OR g.expires_at > now())
       AND r.role_key <> 'student'
"""

_PURPOSES_NEW = (
    "'terms','privacy_notice','core_service','security_monitoring','analytics_personalisation',"
    "'device_fingerprint','marketing_email','marketing_sms','assessment_integrity','analytics_product'"
)
_PURPOSES_OLD = _PURPOSES_NEW.replace(
    "'analytics_personalisation',", "'analytics_personalisation','college_data_sharing',"
)


def upgrade() -> None:
    caller_staff_grant = _LIVE_STAFF_GRANT.format(who="app.user_id()", org="m.organization_id")
    target_staff_grant = _LIVE_STAFF_GRANT.format(who="target", org="ANY (app.org_ids())")
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION app.user_visible_in_orgs(target uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY INVOKER AS
        $$
          SELECT
            -- (b) the target is staff of one of the caller's organizations
            EXISTS (SELECT 1 FROM org_memberships m
                     WHERE m.user_id = target AND m.organization_id = ANY (app.org_ids())
                       AND m.member_type = 'staff' AND m.status = 'active')
            OR EXISTS ({target_staff_grant})
            -- (a) the caller is staff of a shared organization the target belongs to
            OR EXISTS (SELECT 1 FROM org_memberships m
                        WHERE m.user_id = target AND m.organization_id = ANY (app.org_ids())
                          AND m.status <> 'removed'
                          AND (EXISTS (SELECT 1 FROM org_memberships c
                                        WHERE c.user_id = app.user_id()
                                          AND c.organization_id = m.organization_id
                                          AND c.member_type = 'staff' AND c.status = 'active')
                               OR EXISTS ({caller_staff_grant})))
        $$;
        GRANT EXECUTE ON FUNCTION app.user_visible_in_orgs(uuid) TO td_app, td_readonly;
        """
    )
    op.execute("ALTER TABLE consents DROP CONSTRAINT IF EXISTS consents_purpose_check")
    op.execute(
        "ALTER TABLE consents ADD CONSTRAINT consents_purpose_check "
        f"CHECK (purpose IN ({_PURPOSES_NEW})) NOT VALID"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE consents DROP CONSTRAINT IF EXISTS consents_purpose_check")
    op.execute(
        f"ALTER TABLE consents ADD CONSTRAINT consents_purpose_check CHECK (purpose IN ({_PURPOSES_OLD}))"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION app.user_visible_in_orgs(target uuid) RETURNS boolean
        LANGUAGE sql STABLE SECURITY INVOKER AS
        $$ SELECT EXISTS (SELECT 1 FROM org_memberships m
                          WHERE m.user_id = target AND m.organization_id = ANY (app.org_ids())
                            AND m.status <> 'removed') $$;
        """
    )
