"""GCP demo: create one extra Admin (``super_admin`` @ platform) with a password AND a TOTP factor.

Run on the VM:  sudo bash vm.sh create-admin --email <email> --name "<full name>"
(the JSON with the credentials goes to STDOUT only; capture it straight into the PC secrets file).

Unlike the owner account of ``rotate_demo_accounts.py`` (no MFA, enrolment forced at first sign-in),
this account gets a confirmed TOTP factor, so it can sign in immediately with password + authenticator
code (no e-mail code needed: mail never leaves the VM). ``is_synthetic`` is False, so ``vm.sh rotate``
never touches it. Refuses if the e-mail already exists.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import secrets
import sys
from urllib.parse import quote

from sqlalchemy import select

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

GRANTER = "admin@dev.techdrona.local"


async def create(session, email: str, name: str) -> dict:
    now = utcnow()
    if (await session.execute(select(User.id).where(User.email == email))).first():
        raise SystemExit(f"{email} already exists; nothing changed")
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
    session.add(UserProfile(user_id=uid, full_name=name))
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
    pw = "Td-" + secrets.token_urlsafe(18)
    await idsvc.set_password(session, uid, pw)
    totp = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    ct, wrapped = encrypt_secret(totp)
    session.add(
        MfaFactor(
            id=uuid7(),
            user_id=uid,
            factor_type="totp",
            label="authenticator",
            totp_secret_encrypted=ct,
            totp_wrapped_key=wrapped,
            totp_confirmed_at=now,
            is_primary=True,
        )
    )
    role_id = (await session.execute(select(Role.id).where(Role.role_key == "super_admin"))).scalar_one()
    granter = (await session.execute(select(User.id).where(User.email == GRANTER))).scalar_one_or_none() or uid
    session.add(
        RoleGrant(
            id=uuid7(),
            user_id=uid,
            role_id=role_id,
            scope_type="platform",
            scope_id=None,
            organization_id=None,
            granted_by=granter,
            reason="gcp demo: additional Admin account (owner request)",
        )
    )
    await session.flush()
    issuer = "Tech Drona"
    return {
        "email": email,
        "name": name,
        "role": "super_admin",
        "password": pw,
        "totp_secret": totp,
        "otpauth_uri": f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={totp}&issuer={quote(issuer)}",
    }


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--name", required=True)
    a = ap.parse_args()
    engine = make_engine(get_settings().DATABASE_URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
            await system_context(session, "gcp_demo.create_admin")
            out = await create(session, a.email.strip().lower(), a.name.strip())
    finally:
        await engine.dispose()
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
