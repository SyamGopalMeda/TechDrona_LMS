"""GCP demo: set an existing account's password (read from STDIN, never from argv) and make sure it
has a confirmed TOTP factor.

Run on the VM:  printf '%s' '<password>' | sudo bash vm.sh set-login --email <email>

* The password is written with ``identity.service.set_password`` directly, so the app's password
  policy (length / breached-password list) is NOT applied: this is an owner-requested override.
* ``--no-totp``: revoke every MFA factor instead (password-only sign-in; the account must be in
  ``TD_MFA_EXEMPT_EMAILS``, otherwise the app demands MFA enrolment).
* If the account already has an active TOTP factor it is kept (no new secret is printed); otherwise
  a new random factor is enrolled and its secret is printed, so the password alone never lets the
  first person to sign in enrol their own authenticator.
* All sessions of the account are revoked. Output (JSON on STDOUT) never contains the password.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import secrets
import sys
from urllib.parse import quote

from sqlalchemy import select, update

from app.core.config import get_settings
from app.core.db import make_engine, system_context
from app.core.ids import uuid7
from app.core.models_registry import import_all_models
from app.core.time import utcnow

import_all_models()

from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.modules.identity import service as idsvc  # noqa: E402
from app.modules.identity.crypto import encrypt_secret  # noqa: E402
from app.modules.identity.models import MfaFactor, User  # noqa: E402
from app.modules.rbac.models import Role, RoleGrant  # noqa: E402
from app.modules.sessions import service as ss  # noqa: E402


async def run(session, email: str, password: str, no_totp: bool = False) -> dict:
    now = utcnow()
    u = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if u is None:
        raise SystemExit(f"{email} not found; nothing changed")
    await idsvc.set_password(session, u.id, password)
    out: dict = {"email": email, "status": u.status, "password": "set (as requested)"}
    has_totp = (
        await session.execute(
            select(MfaFactor.id).where(
                MfaFactor.user_id == u.id,
                MfaFactor.factor_type == "totp",
                MfaFactor.revoked_at.is_(None),
                MfaFactor.totp_confirmed_at.is_not(None),
            )
        )
    ).first()
    if no_totp:
        # Owner override (only meaningful with TD_MFA_EXEMPT_EMAILS listing this account).
        res = await session.execute(
            update(MfaFactor)
            .where(MfaFactor.user_id == u.id, MfaFactor.revoked_at.is_(None))
            .values(revoked_at=now)
            .execution_options(synchronize_session=False)
        )
        out["totp"] = f"removed ({int(getattr(res, 'rowcount', 0) or 0)} factor(s) revoked)"
    elif has_totp:
        out["totp"] = "existing authenticator kept"
    else:
        totp = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        ct, wrapped = encrypt_secret(totp)
        session.add(
            MfaFactor(
                id=uuid7(),
                user_id=u.id,
                factor_type="totp",
                label="authenticator",
                totp_secret_encrypted=ct,
                totp_wrapped_key=wrapped,
                totp_confirmed_at=now,
                is_primary=True,
            )
        )
        out["totp_secret"] = totp
        out["otpauth_uri"] = (
            f"otpauth://totp/{quote('Tech Drona')}:{quote(email)}?secret={totp}&issuer={quote('Tech Drona')}"
        )
    out["sessions_revoked"] = await ss.revoke_all_sessions(session, u.id, "password_changed")
    out["roles"] = [
        r
        for (r,) in (
            await session.execute(
                select(Role.role_key)
                .join(RoleGrant, RoleGrant.role_id == Role.id)
                .where(RoleGrant.user_id == u.id, RoleGrant.revoked_at.is_(None))
            )
        ).all()
    ]
    await session.flush()
    return out


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--no-totp", action="store_true", help="revoke all MFA factors instead of ensuring one")
    a = ap.parse_args()
    password = sys.stdin.read()
    if not password:
        raise SystemExit("no password on STDIN")
    engine = make_engine(get_settings().DATABASE_URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
            await system_context(session, "gcp_demo.set_login")
            out = await run(session, a.email.strip().lower(), password, a.no_totp)
    finally:
        await engine.dispose()
    json.dump(out, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
