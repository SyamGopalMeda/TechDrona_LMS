"""Pass-2 requests 9/10: a detector that fails after ``apply_restriction`` leaves nothing behind
on Firestore -- no restriction, no family head, no user-state change and no relayable
``account.restricted`` outbox event (emitted through ``core.outbox`` and buffered to the commit
point; restriction/state writes go through ``JournalingStore``)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from app.core.audit import AuditActor
from app.core.db import NO_POSTGRES
from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.identity import clock
from app.modules.identity import public as idp
from app.modules.identity.models import User
from app.modules.security import restrictions as rx
from app.modules.security.repo_fs_engine import detector_scope

FS_MODULES = ("security", "identity", "sessions", "audit", "core")
pytestmark = pytest.mark.usefixtures("fs_env")
ACTOR = AuditActor.system("test.detector")


async def _user() -> Any:
    uid = uuid7()
    now = clock.now()
    return await idp.create_user(
        NO_POSTGRES,
        User(
            id=uid,
            email=f"d{uid.hex[-8:]}@example.com",
            email_verified_at=now,
            status="active",
            is_minor=False,
            age_verified_at=now,
            age_verification_method="self_declared",
        ),
    )


async def _events(event_type: str) -> list[Any]:
    from app.core.firestore.core_store import OUTBOX

    return [d for d in await ScopedStore.system("t").scan(OUTBOX) if d.get("event_type") == event_type]


class Boom(Exception):
    pass


async def test_failed_detector_leaves_no_restriction_and_no_event() -> None:
    u = await _user()
    with pytest.raises(Boom):
        async with detector_scope():
            await rx.apply_restriction(
                NO_POSTGRES, user_id=u.id, level=3, family="sharing", source="engine", actor=ACTOR
            )
            await rx.get_state(NO_POSTGRES, u.id)
            raise Boom
    st = ScopedStore.system("t")
    assert await st.scan("account_restrictions") == []
    heads = [h for h in await st.scan("restriction_heads") if h.get("active_id")]
    assert heads == []
    assert await st.get("security_user_state", str(u.id)) is None
    assert await _events("account.restricted") == []
    assert (await idp.get_user(NO_POSTGRES, u.id)).restriction_level == 0


async def test_successful_detector_commits_restriction_and_event() -> None:
    u = await _user()
    async with detector_scope():
        await rx.apply_restriction(
            NO_POSTGRES, user_id=u.id, level=3, family="sharing", source="engine", actor=ACTOR
        )
    assert len(await rx.active_restrictions(NO_POSTGRES, u.id)) == 1
    ev = await _events("account.restricted")
    assert len(ev) == 1 and json.loads(ev[0]["payload_json"])["user_id"] == str(u.id)
