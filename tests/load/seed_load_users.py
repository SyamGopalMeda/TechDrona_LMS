"""DEV / LOAD-TEST DATA ONLY: N synthetic adult students for the k6 smoke (tests/load).

Creates ``load001..loadNNN@load.techdrona.local`` (``is_synthetic = true``) with the dev seed
password (``app.seeds.dev_users.DEV_PASSWORD``), verified email and the core consents. No device
history, so each account's first sign-in trusts its device without an OTP (one k6 VU = one
device). Idempotent; refuses when ``APP_ENV`` is production.

Run from apps/api with its venv (after ``scripts/seed-dev.*``):
    .venv/Scripts/python ../../tests/load/seed_load_users.py 200
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import make_engine, system_context
from app.core.ids import uuid7
from app.core.models_registry import import_all_models
from app.core.security import hash_password
from app.core.time import utcnow
from app.modules.identity.models import Consent, User, UserCredential, UserProfile
from app.seeds.dev_users import DEV_PASSWORD

import_all_models()

DOMAIN = "load.techdrona.local"


async def main(n: int) -> int:
    if get_settings().is_production:
        print("REFUSED: APP_ENV is production")
        return 3
    from sqlalchemy.ext.asyncio import async_sessionmaker

    engine = make_engine(get_settings().DATABASE_URL)
    pw_hash = hash_password(DEV_PASSWORD)
    made = 0
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session, session.begin():
            await system_context(session, "seed.load_users")
            now = utcnow()
            for i in range(1, n + 1):
                email = f"load{i:03d}@{DOMAIN}"
                if (await session.execute(select(User.id).where(User.email == email))).scalar_one_or_none():
                    continue
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
                        is_synthetic=True,
                        account_origin="self_signup",
                    )
                )
                await session.flush()
                session.add(UserProfile(user_id=uid, full_name=f"Load Student {i:03d}", date_of_birth=date(2002, 6, 1)))
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
                made += 1
    finally:
        await engine.dispose()
    print(f"load users ready: {made} created, {n} total requested (@{DOMAIN})")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 200)))
