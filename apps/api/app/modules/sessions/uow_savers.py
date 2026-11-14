"""Unit-of-work savers of the sessions tables (``fs_uow``)."""

from __future__ import annotations

from typing import Any

from app.modules.identity.fs_uow import SaverSpec, register_saver
from app.modules.sessions.models import (
    AuthSession,
    Device,
    LoginAttempt,
    SessionNetworkObservation,
    UserDevice,
)


def _r() -> Any:
    from app.modules.sessions.repo_firestore import system_repo

    return system_repo()


async def _no_update(obj: Any) -> Any:
    raise RuntimeError(f"{type(obj).__name__} rows are append-only")


def _reg(model: type, load: Any, save: Any, insert: Any) -> None:
    register_saver(model, SaverSpec("sessions", load, save, insert))


_reg(
    AuthSession,
    lambda o: _r().get_session(o.id),
    lambda o: _r().save_session(o),
    lambda o: _r().add_session(o),
)
_reg(Device, lambda o: _r().get_device(o.id), lambda o: _r().save_device(o), lambda o: _r().save_device(o))
_reg(
    UserDevice,
    lambda o: _r().get_user_device_by_id(o.id),
    lambda o: _r().save_user_device(o),
    lambda o: _r().save_user_device(o),
)
_reg(LoginAttempt, lambda o: _r().get_attempt(o.id), _no_update, lambda o: _r().add_attempt(o))
_reg(
    SessionNetworkObservation,
    lambda o: _r().get_observation(o.id),
    _no_update,
    lambda o: _r().add_observation(o),
)
