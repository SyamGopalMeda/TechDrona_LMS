"""Unit-of-work savers of the identity tables (``fs_uow``)."""

from __future__ import annotations

from typing import Any

from app.modules.identity.fs_uow import SaverSpec, register_saver
from app.modules.identity.models import (
    Consent,
    GuardianConsent,
    MfaFactor,
    PasswordResetToken,
    User,
    UserCredential,
    UserProfile,
    VerificationToken,
)


def _r() -> Any:
    from app.modules.identity.repo_firestore import system_repo

    return system_repo()


async def _no_update(obj: Any) -> Any:
    raise RuntimeError(f"{type(obj).__name__} rows are append-only")


def _reg(model: type, load: Any, save: Any, insert: Any) -> None:
    register_saver(model, SaverSpec("identity", load, save, insert))


_reg(User, lambda o: _r().get_user(o.id), lambda o: _r().save_user(o), lambda o: _r().create_user(o))
_reg(
    UserProfile,
    lambda o: _r().get_profile(o.user_id),
    lambda o: _r().save_profile(o),
    lambda o: _r().save_profile(o),
)
_reg(
    UserCredential,
    lambda o: _r().get_credential(o.user_id),
    lambda o: _r().save_credential(o),
    lambda o: _r().save_credential(o),
)
_reg(MfaFactor, lambda o: _r().get_factor(o.id), lambda o: _r().save_factor(o), lambda o: _r().save_factor(o))
_reg(Consent, lambda o: _r().get_consent(o.id), _no_update, lambda o: _r().add_consent(o))
_reg(
    GuardianConsent,
    lambda o: _r().get_guardian_consent(o.id),
    lambda o: _r().save_guardian_consent(o),
    lambda o: _r().save_guardian_consent(o),
)
_reg(
    VerificationToken,
    lambda o: _r().get_token(o.id),
    lambda o: _r().save_token(o),
    lambda o: _r().add_token(o),
)
_reg(
    PasswordResetToken,
    lambda o: _r().get_reset_token(o.id),
    lambda o: _r().save_reset_token(o),
    lambda o: _r().add_reset_token(o),
)
