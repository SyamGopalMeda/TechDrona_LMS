"""cost-media: MED-05 looks up only ``playback.stale_after_seconds`` (the one policy a heartbeat
uses) instead of all four playback policies, with the same value and the same stale decision."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any, cast

import pytest

from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.time import utcnow


@pytest.fixture
def policies(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    from app.modules.media import service as svc

    asked: list[str] = []
    values = {"playback.stale_after_seconds": 120, "playback.heartbeat_seconds": 45}

    async def fake(session: Any, key: str, default: int, user_id: uuid.UUID, lo: int, hi: int) -> int:
        asked.append(key)
        v = values.get(key, default)
        return v if lo <= v <= hi else default

    monkeypatch.setattr(svc, "_int_policy", fake)
    return asked


async def test_stale_after_policy_equals_the_full_policy_value(policies: list[str]) -> None:
    from app.modules.media import service as svc

    uid, session = uuid7(), cast(Any, None)
    assert (
        await svc.stale_after_policy(session, uid)
        == (await svc.playback_policy(session, uid)).stale_after_seconds
        == 120
    )


@pytest.mark.parametrize(("silent_s", "reason"), [(100, "revoked"), (130, "stale")])
async def test_heartbeat_reads_one_policy_and_decides_stale_as_before(
    policies: list[str], monkeypatch: pytest.MonkeyPatch, silent_s: int, reason: str
) -> None:
    from app.core.principal import Principal
    from app.modules.media import service as svc
    from app.modules.media.models import PlaybackSession

    now = utcnow()
    p = Principal(user_id=uuid7(), session_id=uuid7(), is_minor=False)
    ps = PlaybackSession(
        id=uuid7(),
        started_at=now - timedelta(minutes=5),
        user_id=p.user_id,
        auth_session_id=p.session_id,
        lesson_asset_id=uuid7(),
        provider="vdocipher",
        status="active",
        otp_expires_at=now,
        last_heartbeat_at=now - timedelta(seconds=silent_s),
        last_position_s=0,
    )
    ended: list[str] = []

    async def own(session: Any, principal: Any, ps_id: uuid.UUID) -> Any:
        return ps

    async def end(session: Any, s: Any, why: str) -> None:
        ended.append(why)

    async def gone(session: Any, asset_id: uuid.UUID) -> Any:
        raise ProblemError("not_found")  # entitlement re-check fails -> "revoked" (BE-19)

    monkeypatch.setattr(svc, "own_playback", own)
    monkeypatch.setattr(svc, "_end", end)
    monkeypatch.setattr(svc, "student_asset", gone)
    problem, credited = await svc.heartbeat(cast(Any, None), p, ps.id, position_s=10, playing=True)
    assert problem is not None and problem.code == "playback_revoked" and not credited
    # 120 s policy: 100 s of silence is not stale (re-check runs), 130 s is
    assert ended == [reason]
    assert policies == ["playback.stale_after_seconds"]
