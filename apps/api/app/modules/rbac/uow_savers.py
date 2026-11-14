"""Unit-of-work savers of the rbac tables (``fs_uow``)."""

from __future__ import annotations

from typing import Any

from app.modules.identity.fs_uow import SaverSpec, register_saver
from app.modules.rbac.models import ApprovalRequest, Role, RoleGrant


def _r() -> Any:
    from app.modules.rbac.repo_firestore import system_repo

    return system_repo()


async def _grant(o: Any) -> Any:
    got = await _r().get_grant(o.id)
    return got[0] if got else None


async def _save_grant(o: Any) -> Any:
    return await _r().save_grant(o)


async def _insert_grant(o: Any) -> Any:
    from app.modules.rbac.store_specs import ROLES

    role = await _r()._get_obj(Role, ROLES, str(o.role_id))
    return await _r().create_grant(o, role.role_key if role else "")


def _reg(model: type, load: Any, save: Any, insert: Any) -> None:
    register_saver(model, SaverSpec("rbac", load, save, insert))


_reg(RoleGrant, _grant, _save_grant, _insert_grant)
_reg(
    ApprovalRequest,
    lambda o: _r().get_approval(o.id),
    lambda o: _r().save_approval(o),
    lambda o: _r().add_approval(o),
)
