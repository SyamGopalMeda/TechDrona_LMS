"""DEV / DEMO DATA ONLY — synthetic users, the company's demo batches and role grants for local
development and demos. Never run against production: the script refuses outside ``APP_ENV``
local/dev/test (``app.seeds.seeds_allowed``) and marks every user ``is_synthetic = true``.

Run (after ``alembic upgrade heads``):  ``python -m app.seeds.dev_users``

Single company (REMOVAL-PLAN §8 D2/D7). Creates (password for all: the shared ``DEV_PASSWORD``
below, printed by ``main``; staff get a TOTP factor with a FIXED, DEV-ONLY base32 secret from
``DEV_TOTP_SECRETS`` so a database reset is reproducible and the E2E env file can carry it —
these secrets are public and must never protect a real account):

* student@dev.techdrona.local            student, the CLEAN learner fixture (never restricted)
* restricted.student@dev.techdrona.local student, L3-restricted by ``security_demo`` (no request)
* reverify.student@dev.techdrona.local   student, L3 decided as false positive → lift pending
* suspended.student@dev.techdrona.local  student, L4 high-risk case + submitted unblock request
* minor.student@dev.techdrona.local      under-18 student (guardian consent verified)
* asha.student@dev.techdrona.local       student whose structured-assignment submission waits for
                                         the evaluator (``company_demo``)
* ravi.student@dev.techdrona.local       student of the second batch ``DEMO-FS-26``
* trainer@dev.techdrona.local            Trainer @ batch DEMO-CSE-27
* evaluator@dev.techdrona.local          Evaluator @ batch DEMO-CSE-27 (grades and releases results)
* content@dev.techdrona.local            Content manager @ platform
* admin@dev.techdrona.local              Admin (``super_admin``) @ platform
* admin2@dev.techdrona.local             second Admin (dual control: maker != checker)
* security@ / security2@ / finance@      further Admin accounts. D2 folded the Security reviewer
                                         and Finance admin roles into Admin; the addresses stay
                                         because the security, commerce and E2E fixtures use them
                                         (E2E_REVIEWER_A/B, E2E_FINANCE: two different admins).

Everything lives in the single company organization (``app.core.company.COMPANY_ORG_ID``,
inserted by migration orgs_0002; upserted here as well) and its batches ``DEMO-CSE-27`` and
``DEMO-FS-26``. Students join through ``orgs.service.ensure_org_membership`` (company
membership) plus an active ``batch_members`` row; trainer/evaluator get a ``staff`` membership.

Legacy purge (D7): demo accounts of the old college seed that no longer exist here
(``LEGACY_LOCALS``: the college coordinator and the support agent) are deactivated: live grants
revoked, sessions ended, company/batch memberships closed. Only synthetic accounts on the dev
domain are touched; re-running changes nothing.

Students' ``email_verified_at`` is backdated by ``EMAIL_VERIFIED_DAYS_AGO`` so security
fixtures restricted "now" pass the AUTH-21 contact-age rule (contact verified > 7 days before
the restriction).

Idempotent: existing users (by email) keep their credentials; missing users, memberships and
grants are added.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import date, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.company import COMPANY_ORG_ID, COMPANY_ORG_NAME, COMPANY_ORG_SLUG, COMPANY_ORG_TYPE
from app.core.config import get_settings
from app.core.db import make_engine, system_context
from app.core.ids import uuid7
from app.core.models_registry import import_all_models
from app.core.security import hash_password
from app.core.time import utcnow
from app.modules.identity.crypto import encrypt_secret
from app.modules.identity.models import Consent, MfaFactor, User, UserCredential, UserProfile
from app.modules.orgs.models import Batch, BatchMember, Organization, OrgMembership
from app.modules.orgs.service import ensure_org_membership
from app.modules.rbac.models import Role, RoleGrant
from app.modules.sessions.models import AuthSession
from app.seeds import seeds_allowed

# Seeds run standalone: register every module's tables so cross-module FKs resolve.
import_all_models()

DEV_PASSWORD = "dev-only-lantern-harbour-2026"  # noqa: S105 - dev/demo seed, refused in production
DOMAIN = "dev.techdrona.local"
ORG_SLUG = COMPANY_ORG_SLUG
BATCH_CODE = "DEMO-CSE-27"
SECOND_BATCH_CODE = "DEMO-FS-26"
# code -> (name, graduation year)
BATCHES: dict[str, tuple[str, int]] = {
    BATCH_CODE: ("CSE 2027 (demo)", 2027),
    SECOND_BATCH_CODE: ("Full-stack 2026 (demo)", 2026),
}
EMAIL_VERIFIED_DAYS_AGO = 45

# DEV/DEMO ONLY — fixed TOTP secrets (base32, 160 bit) for the synthetic staff accounts. They are
# published in the repo on purpose (reproducible resets, Playwright E2E); never reuse them.
DEV_TOTP_SECRETS: dict[str, str] = {
    "trainer": "KA2PKEZOIRDDNMOPL2PJ5GJUZW44EC5R",
    "evaluator": "HVNXMW4RJCMBYNNSGG5CWHP4EBLWUH6E",
    "security": "IKBBJ4HXXN7XH5FQPBCRHXTCPQIZLDAY",
    "security2": "WAEKTMCNTNWMCXFCNKRAK2OO4X53BIER",
    "finance": "5IWC76OSXS47HSHGPPHGYGR5R5TMY3LZ",
    "content": "6BLD7TM27IYROCA7NI5PT4PR2EY66AQP",
    "admin": "334SDLG2HT25N3YTC36RU2ZBOWFQT22R",
    "admin2": "4M7K6EV24W5HPAPHG3SRX77NQFX43ZUX",
}

PEOPLE: list[tuple[str, str, str | None, str | None]] = [
    # local part, full name, role, scope ("platform" | "batch" | None)
    ("student", "Demo Student", None, None),
    ("restricted.student", "Demo Restricted Student", None, None),
    ("reverify.student", "Demo Reverify Student", None, None),
    ("suspended.student", "Demo Suspended Student", None, None),
    ("minor.student", "Demo Minor", None, None),
    ("asha.student", "Asha Demo", None, None),
    ("ravi.student", "Ravi Demo", None, None),
    ("trainer", "Demo Trainer", "trainer", "batch"),
    ("evaluator", "Demo Evaluator", "evaluator", "batch"),
    ("security", "Demo Admin (security desk)", "super_admin", "platform"),
    ("security2", "Demo Admin (security desk two)", "super_admin", "platform"),
    ("finance", "Demo Admin (finance desk)", "super_admin", "platform"),
    ("content", "Demo Content", "content_manager", "platform"),
    ("admin", "Demo Admin", "super_admin", "platform"),
    ("admin2", "Demo Admin Two", "super_admin", "platform"),
]
# Students outside the default batch (everyone else ending in ``student`` joins BATCH_CODE).
STUDENT_BATCH: dict[str, str] = {"ravi.student": SECOND_BATCH_CODE}
# Batch-scoped staff are granted on this batch.
STAFF_BATCH = BATCH_CODE

# D7: accounts the old multi-college seed created that the single-company seed no longer has.
LEGACY_LOCALS: tuple[str, ...] = ("coordinator", "support")
LEGACY_REASON = "dev seed: legacy college-era demo account retired (single company, D7)"


class ProductionRefused(RuntimeError):
    pass


def guard() -> None:
    if not seeds_allowed():
        raise ProductionRefused("dev_users seed refuses to run outside APP_ENV local/dev/test")


def students() -> list[str]:
    return [p[0] for p in PEOPLE if p[2] is None]


async def _ensure_batches(session: AsyncSession, created_by: uuid.UUID) -> dict[str, Batch]:
    out: dict[str, Batch] = {}
    for code, (name, year) in BATCHES.items():
        b = (
            await session.execute(
                select(Batch).where(Batch.organization_id == COMPANY_ORG_ID, Batch.code == code)
            )
        ).scalar_one_or_none()
        if b is None:
            b = Batch(
                id=uuid7(),
                organization_id=COMPANY_ORG_ID,
                name=name,
                code=code,
                graduation_year=year,
                created_by=created_by,
            )
            session.add(b)
            await session.flush()
        out[code] = b
    return out


async def _ensure_batch_student(
    session: AsyncSession, batch: Batch, user_id: uuid.UUID, added_by: uuid.UUID
) -> None:
    await ensure_org_membership(session, COMPANY_ORG_ID, user_id, member_type="student", added_by=added_by)
    live = (
        await session.execute(
            select(BatchMember.id).where(
                BatchMember.batch_id == batch.id,
                BatchMember.user_id == user_id,
                BatchMember.member_role == "student",
                BatchMember.status == "active",
            )
        )
    ).first()
    if live is None:
        session.add(
            BatchMember(
                id=uuid7(),
                batch_id=batch.id,
                organization_id=COMPANY_ORG_ID,
                user_id=user_id,
                member_role="student",
                added_by=added_by,
            )
        )
        await session.flush()


async def purge_legacy(session: AsyncSession, actor: uuid.UUID | None = None) -> int:
    """D7: deactivate the college-era demo accounts (``LEGACY_LOCALS``) a database migrated from
    an old dev dump may still hold. Revokes their live grants, ends their sessions and closes
    their company/batch memberships. Synthetic dev-domain accounts only; returns how many
    accounts changed (0 on a re-run)."""
    guard()
    emails = [f"{local}@{DOMAIN}" for local in LEGACY_LOCALS]
    users = list(
        (
            await session.execute(select(User).where(User.email.in_(emails), User.is_synthetic.is_(True)))
        ).scalars()
    )
    now = utcnow()
    changed = 0
    for u in users:
        touched = False
        grants = (
            await session.execute(
                update(RoleGrant)
                .where(RoleGrant.user_id == u.id, RoleGrant.revoked_at.is_(None))
                .values(revoked_at=now, revoked_by=actor, reason=LEGACY_REASON)
                .returning(RoleGrant.id)
            )
        ).all()
        touched |= bool(grants)
        ended = (
            await session.execute(
                update(AuthSession)
                .where(
                    AuthSession.user_id == u.id,
                    AuthSession.status.notin_(("expired", "revoked", "blocked")),
                )
                .values(status="revoked", end_reason="privilege_change", ended_at=now)
                .returning(AuthSession.id)
            )
        ).all()
        touched |= bool(ended)
        left = (
            await session.execute(
                update(OrgMembership)
                .where(OrgMembership.user_id == u.id, OrgMembership.status == "active")
                .values(status="left", left_at=now)
                .returning(OrgMembership.id)
            )
        ).all()
        touched |= bool(left)
        removed = (
            await session.execute(
                update(BatchMember)
                .where(BatchMember.user_id == u.id, BatchMember.status == "active")
                .values(status="removed", removed_at=now)
                .returning(BatchMember.id)
            )
        ).all()
        touched |= bool(removed)
        if u.status != "deactivated":
            u.status = "deactivated"
            u.sessions_valid_after = now
            touched = True
        changed += int(touched)
    await session.flush()
    return changed


async def seed(session: AsyncSession) -> dict[str, str]:
    """Returns the TOTP secrets of staff accounts created by THIS run (``{}`` on a re-run)."""
    guard()
    await system_context(session, "seed.dev_users")
    now = utcnow()
    org = await session.get(Organization, COMPANY_ORG_ID)
    if org is None:  # normally inserted by migration orgs_0002
        org = Organization(
            id=COMPANY_ORG_ID, name=COMPANY_ORG_NAME, slug=COMPANY_ORG_SLUG, org_type=COMPANY_ORG_TYPE
        )
        session.add(org)
        await session.flush()
    pw_hash = hash_password(DEV_PASSWORD)
    secrets: dict[str, str] = {}
    created: dict[str, uuid.UUID] = {}
    roles = {r.role_key: r.id for r in (await session.execute(select(Role))).scalars()}
    for local, name, role, _scope in PEOPLE:
        email = f"{local}@{DOMAIN}"
        existing = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
        if existing is not None:
            created[local] = existing.id
            continue
        uid = uuid7()
        minor = local == "minor.student"
        verified_at = now - timedelta(days=EMAIL_VERIFIED_DAYS_AGO) if role is None else now
        session.add(
            User(
                id=uid,
                email=email,
                email_verified_at=verified_at,
                status="active",
                is_minor=minor,
                age_verified_at=now,
                age_verification_method="self_declared",
                is_synthetic=True,
                account_origin="staff_created" if role else "self_signup",
            )
        )
        await session.flush()
        session.add(
            UserProfile(
                user_id=uid, full_name=name, date_of_birth=date(2010, 6, 1) if minor else date(2002, 6, 1)
            )
        )
        session.add(UserCredential(user_id=uid, password_hash=pw_hash))
        for purpose in ("terms", "privacy_notice", "core_service"):
            session.add(
                Consent(
                    id=uuid7(),
                    user_id=uid,
                    purpose=purpose,
                    action="granted",
                    notice_version="2026-11-01",
                    channel="support",
                )
            )
        if role:
            secret = DEV_TOTP_SECRETS[local]
            ct, wrapped = encrypt_secret(secret)
            session.add(
                MfaFactor(
                    id=uuid7(),
                    user_id=uid,
                    factor_type="totp",
                    label="dev",
                    totp_secret_encrypted=ct,
                    totp_wrapped_key=wrapped,
                    totp_confirmed_at=now,
                    is_primary=True,
                )
            )
            secrets[email] = secret
        created[local] = uid
    await session.flush()

    admin = created["admin"]
    batches = await _ensure_batches(session, admin)
    for local in students():
        batch = batches[STUDENT_BATCH.get(local, BATCH_CODE)]
        await _ensure_batch_student(session, batch, created[local], admin)
    for local, _name, _role, scope in PEOPLE:
        if scope == "batch":
            await ensure_org_membership(
                session, COMPANY_ORG_ID, created[local], member_type="staff", added_by=admin
            )

    granter = created["admin2"]
    for local, _name, role, scope in PEOPLE:
        if not role:
            continue
        uid = created[local]
        scope_id = batches[STAFF_BATCH].id if scope == "batch" else None
        live = (
            await session.execute(
                select(RoleGrant.id).where(
                    RoleGrant.user_id == uid,
                    RoleGrant.role_id == roles[role],
                    RoleGrant.scope_type == (scope or "platform"),
                    RoleGrant.scope_id.is_(None) if scope_id is None else RoleGrant.scope_id == scope_id,
                    RoleGrant.revoked_at.is_(None),
                )
            )
        ).first()
        if live is None:
            session.add(
                RoleGrant(
                    id=uuid7(),
                    user_id=uid,
                    role_id=roles[role],
                    scope_type=scope or "platform",
                    scope_id=scope_id,
                    organization_id=COMPANY_ORG_ID if scope == "batch" else None,
                    granted_by=granter if uid != granter else admin,
                    reason="dev seed (synthetic)",
                )
            )
    await session.flush()
    await purge_legacy(session, admin)
    return secrets


async def main() -> int:
    guard()
    engine = make_engine(get_settings().DATABASE_URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
            secrets = await seed(session)
    finally:
        await engine.dispose()
    print("DEV/DEMO users ready. Password for all:", DEV_PASSWORD)
    print(f"  {len(secrets)} new account(s) enrolled with the fixed DEV-ONLY TOTP secrets:")
    for local, secret in DEV_TOTP_SECRETS.items():
        print(f"  TOTP secret for {local}@{DOMAIN}: {secret}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(asyncio.run(main()))
