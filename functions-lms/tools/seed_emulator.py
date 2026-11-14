"""Seed the Firestore EMULATOR for the Firebase stack (no Postgres): role catalogue + demo users.

    (env from emulate.ps1) apps/api/.venv/Scripts/python functions-lms/tools/seed_emulator.py

* The RBAC catalogue (``app.modules.rbac.catalogue``) -> ``lms_roles`` / ``lms_permissions`` /
  ``lms_role_permissions`` through the rbac backfill mappings (same documents a Postgres
  backfill writes; deterministic ids from ``app.seeds.rbac_seed``).
* Two synthetic accounts through the identity / rbac public APIs on Firestore
  (``identity.public.create_user``, ``identity.service.record_consent``, ``rbac.public.add_grant``):
  ``admin@dev.techdrona.local`` (super_admin @ platform) and ``student@dev.techdrona.local``,
  password ``app.seeds.dev_users.DEV_PASSWORD`` -- the same demo identities as the VM seed.

DEMO ONLY: refuses unless ``FIRESTORE_EMULATOR_HOST`` is set and the project id starts with
``demo-``. Idempotent (existing users are kept).
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta
from pathlib import Path

API = Path(__file__).resolve().parents[2] / "apps" / "api"
sys.path.insert(0, str(API))


def _guard() -> None:
    if not os.environ.get("FIRESTORE_EMULATOR_HOST") or not os.environ.get(
        "FIREBASE_PROJECT_ID", ""
    ).startswith("demo-"):
        sys.exit("seed_emulator: refusing (needs FIRESTORE_EMULATOR_HOST and a demo-* FIREBASE_PROJECT_ID)")
    from app.core.firestore.backend import MODULES

    for m in MODULES:
        os.environ.setdefault(f"TD_STORE_{m.upper()}", "firestore")
    os.environ.setdefault("TD_RUNTIME", "firebase")
    os.environ["DATABASE_URL"] = ""


async def seed_catalogue() -> dict[str, int]:
    from app.core.firestore.backfill import mappings
    from app.core.firestore.store import ScopedStore
    from app.core.time import utcnow
    from app.modules.rbac.catalogue import PERMISSIONS, ROLES, role_permission_pairs
    from app.seeds.rbac_seed import permission_id, role_id

    now = utcnow()
    rows = {
        "roles": [
            {
                "id": role_id(r.key),
                "role_key": r.key,
                "name": r.name,
                "session_tier": r.session_tier,
                "mfa_required": r.mfa_required,
                "allowed_scope_types": list(r.allowed_scope_types),
                "is_system": True,
                "created_at": now,
                "updated_at": now,
            }
            for r in ROLES.values()
        ],
        "permissions": [
            {
                "id": permission_id(p.key),
                "permission_key": p.key,
                "module": p.module,
                "description": p.description,
                "is_sensitive": p.is_sensitive,
                "created_at": now,
            }
            for p in PERMISSIONS.values()
        ],
        "role_permissions": [
            {"role_id": role_id(r), "permission_id": permission_id(p), "created_at": now}
            for r, p in role_permission_pairs()
        ],
    }
    store = ScopedStore.system("firestore.backfill")
    out: dict[str, int] = {}
    for m in mappings("rbac"):
        if m.table in rows:
            docs = [(m.doc_id(r), m.transform(r)) for r in rows[m.table]]
            out[m.table] = await store.import_documents(m.collection, docs)
    return out


async def seed_users() -> list[str]:
    from app.core.db import NO_POSTGRES
    from app.core.ids import uuid7
    from app.core.security import hash_password
    from app.core.time import utcnow
    from app.modules.identity import public as identity
    from app.modules.identity import service as identity_service
    from app.modules.identity.models import User, UserCredential, UserProfile
    from app.seeds.dev_users import DEV_PASSWORD, DOMAIN

    people = [("admin", "Demo Admin", "super_admin"), ("student", "Demo Student", None)]
    done: list[str] = []
    now = utcnow()
    for local, name, role in people:
        email = f"{local}@{DOMAIN}"
        existing = await identity.find_user(NO_POSTGRES, "email", email)
        if existing is not None:
            if role and not await _has_role(existing.id, role):
                await _grant(existing.id, role, now)
                done.append(f"{email} (exists; {role} granted)")
            else:
                done.append(f"{email} (exists)")
            continue
        uid = uuid7()
        user = User(
            id=uid,
            email=email,
            email_verified_at=now - timedelta(days=45),
            status="active",
            is_minor=False,
            age_verified_at=now,
            age_verification_method="self_declared",
            is_synthetic=True,
            account_origin="staff_created" if role else "self_signup",
            must_change_password=False,
            created_at=now,
            updated_at=now,
        )
        profile = UserProfile(
            user_id=uid, full_name=name, date_of_birth=date(2002, 6, 1), created_at=now, updated_at=now
        )
        cred = UserCredential(
            user_id=uid, password_hash=hash_password(DEV_PASSWORD), created_at=now, updated_at=now
        )
        await identity.create_user(NO_POSTGRES, user, profile, cred)
        for purpose in ("terms", "privacy_notice", "core_service"):
            await identity_service.record_consent(
                NO_POSTGRES, uid, purpose, "granted", "2026-11-01", channel="support"
            )
        if role:
            await _grant(uid, role, now)
        done.append(email)
    return done


async def _has_role(user_id: object, role: str) -> bool:
    from app.modules.rbac.repo_firestore import system_repo

    return any(key == role and g.revoked_at is None for g, key in await system_repo().grants_for(user_id))  # type: ignore[arg-type]


async def _grant(user_id: object, role: str, now: object) -> None:
    from app.core.db import NO_POSTGRES
    from app.core.ids import uuid7
    from app.modules.rbac import public as rbac
    from app.modules.rbac.models import RoleGrant
    from app.seeds.rbac_seed import role_id

    grant = RoleGrant(
        id=uuid7(),
        user_id=user_id,
        role_id=role_id(role),
        scope_type="platform",
        scope_id=None,
        organization_id=None,
        granted_by=user_id,
        reason="emulator seed (synthetic)",
        granted_at=now,
    )
    await rbac.add_grant(NO_POSTGRES, grant, role)


async def main() -> None:
    _guard()
    from app.core.config import reset_settings_cache

    reset_settings_cache()
    from app.core.models_registry import import_all_models

    import_all_models()
    print("catalogue:", await seed_catalogue())
    print("users:", await seed_users())
    from app.seeds.dev_users import DEV_PASSWORD

    print("password for both:", DEV_PASSWORD)


if __name__ == "__main__":
    asyncio.run(main())
