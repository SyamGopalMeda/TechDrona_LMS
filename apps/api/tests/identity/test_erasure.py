"""DB-01: the identity erasure provider tombstones the account and removes its personal data."""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.db import system_context
from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.identity.erasure import ERASED_NAME, erase_user
from app.modules.identity.models import (
    Consent,
    MfaFactor,
    PasswordResetToken,
    User,
    UserCredential,
    UserProfile,
)
from tests.identity.factory import make_user


async def test_db01_identity_erasure_tombstones_user_and_is_idempotent(db) -> None:
    u = await make_user(db, with_totp=True, phone="+919812300001")
    await system_context(db, "test.erasure")
    db.add(
        PasswordResetToken(
            id=uuid7(), user_id=u.id, token_hash=b"x" * 32, expires_at=clock.now(), created_at=clock.now()
        )
    )
    await db.flush()

    out = await erase_user(db, u.id)
    assert out["users_tombstoned"] == 1 and out["profiles_scrubbed"] == 1
    assert out["deleted"]["user_credentials"] == 1 and out["deleted"]["mfa_factors"] == 1
    assert out["deleted"]["password_reset_tokens"] == 1

    db.expire_all()
    user = await db.get(User, u.id)
    assert user is not None and user.status == "deleted" and user.deleted_at is not None
    assert user.email is None and user.phone_e164 is None
    prof = await db.get(UserProfile, u.id)
    assert prof is not None and prof.full_name == ERASED_NAME and prof.date_of_birth is None
    assert await db.get(UserCredential, u.id) is None
    n_factors = (await db.execute(select(func.count()).where(MfaFactor.user_id == u.id))).scalar_one()
    assert n_factors == 0
    # legal hold: the consent proof ledger is kept (append-only, account + 3 years)
    n_consents = (await db.execute(select(func.count()).where(Consent.user_id == u.id))).scalar_one()
    assert n_consents == 3

    again = await erase_user(db, u.id)
    assert again["users_tombstoned"] == 0 and again["profiles_scrubbed"] == 0
    assert set(again["deleted"].values()) == {0}


async def test_db01_identity_and_notifications_providers_registered_and_run(db) -> None:
    from app.modules.admin.privacy import REQUIRED_ERASURE_MODULES, erasure_providers, execute_erasure
    from app.wiring import _register_erasure_providers

    _register_erasure_providers()
    providers = erasure_providers()
    assert {"identity", "notifications"} <= set(providers)
    u = await make_user(db)
    await system_context(db, "test.erasure")
    result = await execute_erasure(db, u.id)
    assert "identity" in result.ran and "notifications" in result.ran
    assert "identity" not in result.missing and "notifications" not in result.missing
    assert set(result.missing) <= set(REQUIRED_ERASURE_MODULES)
    db.expire_all()
    user = await db.get(User, u.id)
    assert user is not None and user.status == "deleted" and user.email is None
