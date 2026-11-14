"""Unit-of-work savers of the orgs tables (``fs_uow``)."""

from __future__ import annotations

from typing import Any

from app.modules.identity.fs_uow import SaverSpec, register_saver
from app.modules.orgs.models import (
    Batch,
    BatchMember,
    BatchPlan,
    ClassAttendance,
    ClassSession,
    Organization,
    OrgMembership,
)


def _r() -> Any:
    from app.modules.orgs.repo_firestore import system_repo

    return system_repo()


def _reg(model: type, load: Any, save: Any, insert: Any) -> None:
    register_saver(model, SaverSpec("orgs", load, save, insert))


_reg(Organization, lambda o: _r().get_org(o.id), lambda o: _r().save_org(o), lambda o: _r().save_org(o))
_reg(Batch, lambda o: _r().get_batch(o.id), lambda o: _r().save_batch(o), lambda o: _r().insert_batch(o))
_reg(
    BatchMember,
    lambda o: _r().get_batch_member(o.id),
    lambda o: _r().save_batch_member(o),
    lambda o: _r().add_batch_member(o),
)
_reg(
    OrgMembership,
    lambda o: _r().get_membership(o.id),
    lambda o: _r().save_membership(o),
    lambda o: _r().insert_membership(o),
)
_reg(
    BatchPlan, lambda o: _r().batch_plan(o.batch_id), lambda o: _r().save_plan(o), lambda o: _r().save_plan(o)
)
_reg(
    ClassSession,
    lambda o: _r().get_class(o.id),
    lambda o: _r().save_class(o),
    lambda o: _r().insert_class(o),
)
_reg(
    ClassAttendance,
    lambda o: _r().get_attendance(o.session_id, o.user_id),
    lambda o: _r().save_attendance(o),
    lambda o: _r().save_attendance(o),
)
