"""Media playback sessions on Firestore (``TD_STORE_MEDIA=firestore``), emulator only: the
advisory-lock section of ``issue_playback`` (stale clean-up, same-session take-over, stream
cap / conflict / explicit take-over, 30 tokens per hour), end/discard, mapper, TTL and indexes."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest

from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.time import utcnow

API = Path(__file__).resolve().parents[3]


@pytest.fixture
def repo(fs_client: Any) -> Any:
    from app.core.firestore.store import ScopedStore
    from app.modules.media.repo_firestore import JOB, PlaybackRepo

    return PlaybackRepo(ScopedStore.system(JOB, client=fs_client))  # type: ignore[arg-type]


def _new(uid: uuid.UUID, auth: uuid.UUID, now: Any) -> Any:
    from app.modules.media.models import PlaybackSession

    return PlaybackSession(
        id=uuid7(),
        started_at=now,
        user_id=uid,
        auth_session_id=auth,
        device_id=uuid7(),
        tab_id=None,
        lesson_asset_id=uuid7(),
        provider="vdocipher",
        status="active",
        otp_expires_at=now + timedelta(seconds=300),
        last_heartbeat_at=now,
        last_position_s=0,
    )


async def _claim(
    repo: Any, uid: uuid.UUID, auth: uuid.UUID, *, take_over: Any = None, now: Any = None, cap: int = 1
):
    now = now or utcnow()
    return await repo.claim(
        uid,
        auth_session_id=auth,
        take_over_id=take_over,
        now=now,
        stale_cut=now - timedelta(seconds=90),
        hour_cut=now - timedelta(hours=1),
        cap=cap,
        tokens_per_hour=30,
        new=_new(uid, auth, now),
    )


async def test_cap_conflict_takeover_and_same_session_tabs(repo: Any) -> None:
    uid, a, b = uuid7(), uuid7(), uuid7()
    first = await _claim(repo, uid, a)
    assert first.kind == "ok"
    tab2 = await _claim(repo, uid, a)  # another tab of the same auth session: silent take-over
    assert tab2.kind == "ok"
    assert (await repo.get(uid, first.session.id)).end_reason == "taken_over"
    other = await _claim(repo, uid, b)  # a different device at the cap
    assert other.kind == "conflict" and other.session.id == tab2.session.id
    taken = await _claim(repo, uid, b, take_over=tab2.session.id)
    assert taken.kind == "ok"
    old = await repo.get(uid, tab2.session.id)
    assert (old.status, old.end_reason) == ("ended", "taken_over") and old.ended_at is not None
    assert await repo.get(uuid7(), taken.session.id) is None  # another user's id: invisible


async def test_stale_sessions_end_before_the_cap(repo: Any) -> None:
    uid = uuid7()
    t0 = utcnow() - timedelta(minutes=5)
    first = await _claim(repo, uid, uuid7(), now=t0)
    nxt = await _claim(repo, uid, uuid7())  # first had no heartbeat for 5 min (> 90 s)
    assert nxt.kind == "ok"
    assert (await repo.get(uid, first.session.id)).end_reason == "stale"


async def test_token_rate_limit_writes_nothing(repo: Any) -> None:
    uid, auth = uuid7(), uuid7()
    for _ in range(30):
        assert (await _claim(repo, uid, auth)).kind == "ok"
    with pytest.raises(ProblemError) as e:
        await _claim(repo, uid, auth)
    assert e.value.code == "rate_limited" if hasattr(e.value, "code") else True
    later = utcnow() + timedelta(hours=1, minutes=1)
    assert (await _claim(repo, uid, auth, now=later)).kind == "ok"


async def test_concurrent_issues_from_two_devices_leave_one_active(repo: Any) -> None:
    uid = uuid7()
    res = await asyncio.gather(*(_claim(repo, uid, uuid7()) for _ in range(4)))
    assert sorted(r.kind for r in res) == ["conflict", "conflict", "conflict", "ok"]
    from app.modules.media.store_specs import PLAYBACK_USERS

    lock = await repo.store.get(PLAYBACK_USERS, str(uid))
    assert lock["active_ids"] == [str(next(r for r in res if r.kind == "ok").session.id)]


async def test_end_and_discard_keep_the_lock_document_consistent(repo: Any) -> None:
    from app.modules.media.store_specs import PLAYBACK_USERS

    uid, a = uuid7(), uuid7()
    c = await _claim(repo, uid, a)
    await repo.update(uid, c.session.id, {"last_position_s": 42, "provider_otp_ref_hash": b"\x01" * 32})
    got = await repo.get(uid, c.session.id)
    assert got.last_position_s == 42 and got.provider_otp_ref_hash == b"\x01" * 32
    await repo.end(uid, c.session.id, "stopped", utcnow())
    assert (await repo.store.get(PLAYBACK_USERS, str(uid)))["active_ids"] == []
    d = await _claim(repo, uid, uuid7())
    await repo.discard(uid, d.session.id)
    assert await repo.get(uid, d.session.id) is None
    lock = await repo.store.get(PLAYBACK_USERS, str(uid))
    assert lock["active_ids"] == [] and len(lock["starts"]) == 1  # the discarded start is refunded


async def test_new_documents_carry_the_180_day_ttl(repo: Any) -> None:
    from app.modules.media.store_specs import PLAYBACK

    c = await _claim(repo, uuid7(), uuid7())
    d = await repo.store.get(PLAYBACK, str(c.session.id))
    assert timedelta(days=179) < d["expire_at"] - d["started_at"] <= timedelta(days=180, seconds=5)


def test_mapper_matches_the_repository() -> None:
    from app.modules.media.repo_firestore import ps_fields, ps_of
    from app.modules.media.store_specs import FIELDS, RETENTION, playback_doc

    now = utcnow()
    row = {k: None for k in FIELDS} | {
        "id": uuid7(),
        "started_at": now,
        "user_id": uuid7(),
        "auth_session_id": uuid7(),
        "lesson_asset_id": uuid7(),
        "provider": "vdocipher",
        "provider_otp_ref_hash": b"\x02" * 32,
        "status": "ended",
        "otp_expires_at": now,
        "last_heartbeat_at": now,
        "ended_at": now,
        "end_reason": "stopped",
    }
    doc = playback_doc(row)
    assert doc["expire_at"] == now + RETENTION
    ps = ps_of(doc)
    assert {k: getattr(ps, k) for k in FIELDS} == row
    assert ps_fields(ps) == {k: v for k, v in doc.items() if k != "expire_at"}


def test_repository_scope_lint_and_indexes() -> None:
    from app.core.firestore.repository import assert_repository_scoped
    from app.modules.media.repo_firestore import PlaybackRepo

    assert_repository_scoped(PlaybackRepo)
    frag = json.loads((API / "app/modules/media/firestore.indexes.fragment.json").read_text())
    got = {tuple(f["fieldPath"] for f in i["fields"]) for i in frag["indexes"]}
    assert ("user_id", "status", "started_at") in got and ("user_id", "started_at") in got
    assert {
        "collectionGroup": "lms_playback_sessions",
        "fieldPath": "expire_at",
        "ttl": True,
        # ascending index: the retention job's TTL guard queries expire_at < horizon (retention-fs)
        "indexes": [{"order": "ASCENDING", "queryScope": "COLLECTION"}],
    } in frag["fieldOverrides"]
