"""GCP demo: free an account's trusted-device slots ("Device limit reached" at sign-in).

Run on the VM:  sudo bash vm.sh reset-devices --email <email> [--keep 0]

Uses ``sessions.service.remove_user_device`` (the same code as "Remove device" in the app): each
trusted browser of the account is marked removed (reason ``support_reset``, as an admin reset), its remember-me token is
dropped and its sessions end. ``--keep N`` keeps the N most recently used browsers. The next sign-in
from any browser trusts it again after the normal checks. Output: JSON counts, no secrets.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import make_engine, system_context
from app.core.models_registry import import_all_models

import_all_models()

from sqlalchemy.ext.asyncio import async_sessionmaker  # noqa: E402

from app.modules.identity.models import User  # noqa: E402
from app.modules.sessions import service as ss  # noqa: E402


async def run(session, email: str, keep: int) -> dict:
    u = (await session.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if u is None:
        raise SystemExit(f"{email} not found; nothing changed")
    trusted = await ss.trusted_devices(session, u.id)  # oldest first
    to_remove = trusted[: max(0, len(trusted) - keep)]
    ended = 0
    for ud in to_remove:
        ended += await ss.remove_user_device(session, ud, "support_reset", removed_by=None)
    await session.flush()
    return {"email": email, "trusted_before": len(trusted), "removed": len(to_remove), "sessions_ended": ended}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--keep", type=int, default=0, help="keep the N most recently used trusted browsers")
    a = ap.parse_args()
    engine = make_engine(get_settings().DATABASE_URL)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
            await system_context(session, "gcp_demo.reset_devices")
            out = await run(session, a.email.strip().lower(), a.keep)
    finally:
        await engine.dispose()
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
