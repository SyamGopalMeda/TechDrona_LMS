"""GCP demo: retire the PUBLIC dev credentials after the demo seeds ran, and create the owner Admin.

The dev seeds (app/seeds/dev_users.py) give every synthetic account the published password
``DEV_PASSWORD`` and staff the published ``DEV_TOTP_SECRETS``. On a hosted demo both must be
replaced. This script, run once inside the td-api image (``docker compose run``), uses the app's
own service functions where they exist:

* ``identity.service.set_password``        -> new random password for every synthetic account
* ``sessions.service.revoke_all_sessions``  -> ends any session opened with the old values
* staff TOTP: active factors revoked (as ADM-05 ``_execute_mfa_reset`` does) and a NEW random
  factor enrolled (as the seed does, ``identity.crypto.encrypt_secret``)
* ``RETIRE`` admin accounts are deactivated (grants revoked) — fewer live admin logins
* the owner Admin (``--owner-email``) is created WITHOUT an MFA factor: TOTP enrolment is
  forced at first sign-in by the app (Admin role has ``mfa_required``).

Writes the new credentials as JSON to STDOUT only (capture it straight into the local secrets
file; nothing is stored on the VM). Re-running rotates again (and leaves the owner's password
untouched unless ``--reset-owner`` is given).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import secrets
import sys

from sqlalchemy import select, update

from app.core.company import COMPANY_ORG_ID
from app.core.config import get_settings
from app.core.db import make_engine, system_context
from app.core.ids import uuid7
from app.core.models_registry import import_all_models
from app.core.time import utcnow

import_all_models()

from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.modules.identity import service as idsvc  # noqa: E402
from app.modules.identity.crypto import encrypt_secret  # noqa: E402
from app.modules.identity.models import Consent, MfaFactor, User, UserProfile  # noqa: E402
from app.modules.rbac.models import Role, RoleGrant  # noqa: E402
from app.modules.sessions import service as ss  # noqa: E402

DOMAIN = "dev.techdrona.local"
RETIRE = ("security", "security2", "finance")


def new_password() -> str:
    return "Td-" + secrets.token_urlsafe(18)


def new_totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


async def rotate(session, out: list[dict]) -> None:
    now = utcnow()
    users = (
        await session.execute(
            select(User).where(User.email.like(f"%@{DOMAIN}"), User.is_synthetic.is_(True)).order_by(User.email)
        )
    ).scalars().all()
    for u in users:
        local = u.email.split("@", 1)[0]
        rec: dict = {"email": u.email}
        if local in RETIRE:
            await session.execute(
                update(RoleGrant)
                .where(RoleGrant.user_id == u.id, RoleGrant.revoked_at.is_(None))
                .values(revoked_at=now, reason="gcp demo: unused admin account retired")
            )
            u.status = "deactivated"
            rec["status"] = "deactivated"
        pw = new_password()
        await idsvc.set_password(session, u.id, pw)
        res = await session.execute(
            update(MfaFactor)
            .where(MfaFactor.user_id == u.id, MfaFactor.revoked_at.is_(None))
            .values(revoked_at=now)
            .execution_options(synchronize_session=False)
        )
        had_mfa = int(getattr(res, "rowcount", 0) or 0) > 0
        if had_mfa and local not in RETIRE:
            secret = new_totp_secret()
            ct, wrapped = encrypt_secret(secret)
            session.add(
                MfaFactor(
                    id=uuid7(),
                    user_id=u.id,
                    factor_type="totp",
                    label="demo",
                    totp_secret_encrypted=ct,
                    totp_wrapped_key=wrapped,
                    totp_confirmed_at=now,
                    is_primary=True,
                )
            )
            rec["totp_secret"] = secret
        await ss.revoke_all_sessions(session, u.id, "password_changed")
        if local not in RETIRE:
            rec["password"] = pw
            rec.setdefault("status", u.status)
        out.append(rec)
    await session.flush()


async def ensure_owner(session, email: str, reset: bool, out: list[dict]) -> None:
    now = utcnow()
    u = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    pw = new_password()
    if u is None:
        uid = uuid7()
        session.add(
            User(
                id=uid,
                email=email,
                email_verified_at=now,
                status="active",
                is_minor=False,
                age_verified_at=now,
                age_verification_method="self_declared",
                is_synthetic=False,
                account_origin="staff_created",
            )
        )
        await session.flush()
        session.add(UserProfile(user_id=uid, full_name="Tech Drona Owner"))
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
        await idsvc.set_password(session, uid, pw)
        role_id = (await session.execute(select(Role.id).where(Role.role_key == "super_admin"))).scalar_one()
        granter = (
            await session.execute(select(User.id).where(User.email == f"admin@{DOMAIN}"))
        ).scalar_one_or_none() or uid
        session.add(
            RoleGrant(
                id=uuid7(),
                user_id=uid,
                role_id=role_id,
                scope_type="platform",
                scope_id=None,
                organization_id=None,
                granted_by=granter,
                reason="gcp demo: owner Admin account",
            )
        )
        out.append({"email": email, "password": pw, "role": "super_admin", "note": "new; TOTP enrolment at first sign-in"})
    elif reset:
        await idsvc.set_password(session, u.id, pw)
        await ss.revoke_all_sessions(session, u.id, "password_changed")
        out.append({"email": email, "password": pw, "note": "password reset"})
    else:
        out.append({"email": email, "note": "exists; unchanged"})
    await session.flush()


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--owner-email", required=True)
    ap.add_argument("--reset-owner", action="store_true")
    ap.add_argument("--skip-rotate", action="store_true")
    a = ap.parse_args()
    _ = COMPANY_ORG_ID
    engine = make_engine(get_settings().DATABASE_URL)
    out: list[dict] = []
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
            await system_context(session, "gcp_demo.rotate_accounts")
            if not a.skip_rotate:
                await rotate(session, out)
            await ensure_owner(session, a.owner_email, a.reset_owner, out)
    finally:
        await engine.dispose()
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
