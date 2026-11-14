"""Security slice 1 on Firestore (restrictions, user state, the sessions restriction hook) with
identity/sessions also on Firestore and no Postgres (session = NO_POSTGRES)."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

import pytest

from app.core.audit import AuditActor
from app.core.db import NO_POSTGRES
from app.core.firestore.repository import assert_repository_scoped
from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.identity import public as idp
from app.modules.identity.models import User
from app.modules.security import public as secp
from app.modules.security import restrictions as rx
from app.modules.security.repo_firestore import SecurityRepo, system_repo

FS_MODULES = ("security", "identity", "sessions", "audit", "core")
pytestmark = pytest.mark.usefixtures("fs_env")
ACTOR = AuditActor.system("test.security")


async def _user() -> Any:
    uid = uuid7()
    now = clock.now()
    u = User(
        id=uid,
        email=f"u{uid.hex[-10:]}@example.com",
        email_verified_at=now,
        status="active",
        is_minor=False,
        age_verified_at=now,
        age_verification_method="self_declared",
    )
    return await idp.create_user(NO_POSTGRES, u)


def test_scope_lint() -> None:
    assert_repository_scoped(SecurityRepo)


async def test_apply_supersede_state_and_lift() -> None:
    u = await _user()
    st0 = await rx.restriction_state(NO_POSTGRES, u.id)
    assert st0.level == 0 and not st0.restrictions
    r1, _ = await rx.apply_restriction(
        NO_POSTGRES,
        user_id=u.id,
        level=1,
        family="sharing",
        source="engine",
        actor=ACTOR,
        rule_keys=["SH-01"],
    )
    dev = uuid7()
    r2, _ = await rx.apply_restriction(
        NO_POSTGRES,
        user_id=u.id,
        level=2,
        family="sharing",
        source="engine",
        actor=ACTOR,
        reverify_device_ids=[dev],
    )
    active = await rx.active_restrictions(NO_POSTGRES, u.id)
    assert [r.id for r in active] == [r2.id]  # r1 superseded: one active per family
    old = await system_repo().restrictions_for_user(u.id)
    assert {r.id: r.end_reason for r in old}[r1.id] == "superseded"
    st = await rx.restriction_state(NO_POSTGRES, u.id)
    assert st.level == 2 and "device_verification_required" in st.restrictions
    assert f"reverify:{dev}" in st.restrictions
    assert (await idp.get_user(NO_POSTGRES, u.id)).restriction_level == 2  # users cache kept in sync
    assert (await secp.restricted_users_by_level(NO_POSTGRES)) == {2: 1}
    out = rx.restriction_out(r2)
    assert out["state"] == "active" and out["level"] == 2
    await rx.end_restriction(NO_POSTGRES, r2, "lifted_by_reviewer", ended_by=uuid7())
    assert await rx.active_restrictions(NO_POSTGRES, u.id) == []
    assert (await rx.restriction_state(NO_POSTGRES, u.id)).level == 0
    assert (await idp.get_user(NO_POSTGRES, u.id)).restriction_level == 0
    assert len(await secp.user_restrictions(NO_POSTGRES, u.id)) == 2
    assert await secp.user_restrictions(NO_POSTGRES, u.id, active_only=True) == []


async def test_concurrent_apply_keeps_one_active_per_family() -> None:
    u = await _user()

    async def apply(level: int) -> Any:
        return await rx.apply_restriction(
            NO_POSTGRES, user_id=u.id, level=level, family="sharing", source="engine", actor=ACTOR
        )

    await asyncio.gather(*(apply(lv) for lv in (1, 2)))
    assert len(await rx.active_restrictions(NO_POSTGRES, u.id)) == 1


async def test_l3_locks_takeover_protect_and_recovery() -> None:
    u = await _user()
    await rx.apply_restriction(
        NO_POSTGRES, user_id=u.id, level=3, family="sharing", source="manual", actor=ACTOR
    )
    st = await rx.restriction_state(NO_POSTGRES, u.id)
    assert st.level == 3 and {"video_locked", "attempt_locked"} <= st.restrictions
    _t, _ = await rx.apply_restriction(
        NO_POSTGRES, user_id=u.id, level=4, family="takeover", source="engine", actor=ACTOR
    )
    assert (await idp.get_user(NO_POSTGRES, u.id)).must_change_password is True
    st = await rx.restriction_state(NO_POSTGRES, u.id)
    assert st.takeover_lock is True and st.level == 3  # protect-lock does not raise the sharing level


async def test_step_up_state_and_case_lookups() -> None:
    u = await _user()
    st = await rx.get_state(NO_POSTGRES, u.id)
    assert st.sharing_level == 0 and str(st.sharing_score) == "0.00"
    st.step_up_required_since = clock.now() - timedelta(minutes=5)
    await system_repo().save_state(u.id, st)
    assert (await rx.restriction_state(NO_POSTGRES, u.id)).step_up_required is True
    assert await secp.open_case_count(NO_POSTGRES) == 0
    assert await secp.user_unblock_requests(NO_POSTGRES, u.id) == []
