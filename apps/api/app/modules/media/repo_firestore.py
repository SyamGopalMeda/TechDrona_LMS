"""Firestore repository of media playback sessions (``TD_STORE_MEDIA=firestore``).

``service.py`` dispatches here; the Postgres path is unchanged. Data model and the per-user lock
document: ``store_specs.py``. Return values are transient ``PlaybackSession`` instances.

``claim`` is the advisory-lock section of ``issue_playback`` as one transaction on
``playback_users/{uid}``: end stale sessions, silently take over other tabs of the same auth
session, apply the stream cap (conflict or explicit take-over), the 30-tokens-per-hour limit, and
insert the new session. A conflict commits the clean-up and returns the other session (Postgres
returns the problem without raising, so its clean-up commits too); the rate limit raises, so
nothing is written (Postgres rolls back).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from app.core.errors import ProblemError
from app.core.firestore.codec import to_store
from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.repository import FirestoreRepository
from app.core.firestore.store import Doc, ScopedStore, ScopedTransaction
from app.modules.media.models import PlaybackSession
from app.modules.media.store_specs import FIELDS, PLAYBACK, PLAYBACK_USERS

JOB = "media.playback"
_PAGE = 100


def _dt(v: Any) -> datetime | None:
    if v is None:
        return None
    v = v.astimezone(UTC)
    return datetime(v.year, v.month, v.day, v.hour, v.minute, v.second, v.microsecond, tzinfo=UTC)


_UUIDS = ("id", "user_id", "auth_session_id", "device_id", "tab_id", "lesson_asset_id")
_TIMES = ("started_at", "otp_expires_at", "last_heartbeat_at", "ended_at")


def ps_of(d: dict[str, Any]) -> PlaybackSession:
    kw: dict[str, Any] = {}
    for k in FIELDS:
        v = d.get(k)
        if k in _UUIDS:
            v = uuid.UUID(str(v)) if v else None
        elif k in _TIMES:
            v = _dt(v)
        elif k == "provider_otp_ref_hash":
            v = bytes.fromhex(v) if v else None
        kw[k] = v
    return PlaybackSession(**kw)


def ps_fields(ps: PlaybackSession) -> dict[str, Any]:
    out = {k: to_store(getattr(ps, k)) for k in FIELDS}
    h = ps.provider_otp_ref_hash
    out["provider_otp_ref_hash"] = h.hex() if h else None
    return out


@dataclass(frozen=True, slots=True)
class Claim:
    kind: Literal["ok", "conflict"]
    session: PlaybackSession  # the new session ("ok") or the other device's ("conflict")


class _NeedSeed(Exception):
    pass


class PlaybackRepo(FirestoreRepository):
    """Always on the named system job ``media.playback``; every method is per ``user_id``."""

    async def _query(self, user_id: uuid.UUID, filters: Sequence[Any], order: Any) -> list[Doc]:
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                PLAYBACK, user_id=user_id, filters=filters, order_by=order, limit=_PAGE, cursor=cursor
            )
            out.extend(page.items)
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    async def get(self, user_id: uuid.UUID, ps_id: uuid.UUID) -> PlaybackSession | None:
        d = await self.store.get(PLAYBACK, str(ps_id))
        if d is None or d.get("user_id") != str(user_id):
            return None
        return ps_of(d.data)

    async def _seed(self, user_id: uuid.UUID, hour_cut: datetime) -> dict[str, Any]:
        active = await self._query(user_id, [("status", "==", "active")], (("started_at", "asc"),))
        recent = await self._query(user_id, [("started_at", ">", hour_cut)], (("started_at", "asc"),))
        return {
            "user_id": str(user_id),
            "active_ids": [d.id for d in active],
            "starts": [d["started_at"] for d in recent],
        }

    async def claim(
        self,
        user_id: uuid.UUID,
        *,
        auth_session_id: uuid.UUID,
        take_over_id: uuid.UUID | None,
        now: datetime,
        stale_cut: datetime,
        hour_cut: datetime,
        cap: int,
        tokens_per_hour: int,
        new: PlaybackSession,
    ) -> Claim:
        seed: dict[str, Any] | None = None
        for _ in range(3):
            try:
                return await self.store.run_transaction(
                    lambda tx, seed=seed: self._claim_tx(  # type: ignore[misc]
                        tx,
                        user_id,
                        seed,
                        auth_session_id,
                        take_over_id,
                        now,
                        stale_cut,
                        hour_cut,
                        cap,
                        tokens_per_hour,
                        new,
                    )
                )
            except _NeedSeed:
                seed = await self._seed(user_id, hour_cut)
            except UniqueViolationError:  # a concurrent first issue created the lock document
                seed = None
        raise ProblemError("conflict")

    async def _claim_tx(
        self,
        tx: ScopedTransaction,
        user_id: uuid.UUID,
        seed: dict[str, Any] | None,
        auth_session_id: uuid.UUID,
        take_over_id: uuid.UUID | None,
        now: datetime,
        stale_cut: datetime,
        hour_cut: datetime,
        cap: int,
        tokens_per_hour: int,
        new: PlaybackSession,
    ) -> Claim:
        # ---- reads
        lock = await tx.get(PLAYBACK_USERS, str(user_id))
        fresh = lock is None
        if lock is None:
            if seed is None:
                raise _NeedSeed
            state = dict(seed)
        else:
            state = dict(lock.data)
        docs = await tx.get_many(PLAYBACK, state.get("active_ids") or [])
        # ---- decide (same order as the Postgres path)
        ending: list[tuple[Doc, str]] = []
        active: list[PlaybackSession] = []
        for i in state.get("active_ids") or []:
            d = docs.get(i)
            if d is None or d.get("status") != "active":
                continue
            ps = ps_of(d.data)
            if ps.last_heartbeat_at <= stale_cut:
                ending.append((d, "stale"))
            else:
                active.append(ps)
        active.sort(key=lambda p: p.started_at)
        others: list[PlaybackSession] = []
        for ps in active:
            if ps.auth_session_id == auth_session_id:
                ending.append((docs[str(ps.id)], "taken_over"))
            else:
                others.append(ps)
        result: Claim | None = None
        if len(others) >= cap:
            target = next((o for o in others if o.id == take_over_id), None) if take_over_id else None
            if target is None:
                result = Claim("conflict", others[-1])
            else:
                ending.append((docs[str(target.id)], "taken_over"))
                others.remove(target)
                if len(others) >= cap:  # pragma: no cover - cap > 1 with several others
                    raise ProblemError("playback_conflict", takeover_allowed=True)
        starts = [s for s in state.get("starts") or [] if s > hour_cut]
        if result is None and len(starts) >= tokens_per_hour:
            raise ProblemError("rate_limited", headers={"Retry-After": "600"})
        # ---- writes
        for d, reason in ending:
            await tx.update_read(PLAYBACK, d, {"status": "ended", "ended_at": now, "end_reason": reason})
        keep = [str(o.id) for o in others]
        if result is None:
            row = ps_fields(new)
            await tx.create(PLAYBACK, row, doc_id=str(new.id))
            keep.append(str(new.id))
            starts.append(now)
            result = Claim("ok", new)
        lock_doc = {"user_id": str(user_id), "active_ids": keep, "starts": starts}
        if fresh:
            await tx.create(PLAYBACK_USERS, lock_doc, doc_id=str(user_id))
        else:
            created = {"created_at": state["created_at"]} if state.get("created_at") else {}
            await tx.put(PLAYBACK_USERS, str(user_id), {**lock_doc, **created})
        return result

    async def update(self, user_id: uuid.UUID, ps_id: uuid.UUID, changes: dict[str, Any]) -> None:
        """Field update (heartbeat position, OTP hash). Ending goes through ``end``."""
        c = dict(changes)
        if "provider_otp_ref_hash" in c and c["provider_otp_ref_hash"] is not None:
            c["provider_otp_ref_hash"] = bytes(c["provider_otp_ref_hash"]).hex()
        await self.store.update(PLAYBACK, str(ps_id), c)

    async def end(self, user_id: uuid.UUID, ps_id: uuid.UUID, reason: str, now: datetime) -> None:
        """End a session and drop it from the user's active list (one transaction)."""

        async def body(tx: ScopedTransaction) -> None:
            lock = await tx.get(PLAYBACK_USERS, str(user_id))
            cur = await tx.get(PLAYBACK, str(ps_id))
            if cur is None:
                return
            await tx.update_read(PLAYBACK, cur, {"status": "ended", "ended_at": now, "end_reason": reason})
            if lock is not None and str(ps_id) in (lock.get("active_ids") or []):
                ids = [i for i in lock["active_ids"] if i != str(ps_id)]
                await tx.put(PLAYBACK_USERS, str(user_id), {**lock.data, "active_ids": ids})

        await self.store.run_transaction(body)

    async def discard(self, user_id: uuid.UUID, ps_id: uuid.UUID) -> None:
        """Undo a claim whose OTP could not be issued (Postgres rolls the insert back)."""

        async def body(tx: ScopedTransaction) -> None:
            lock = await tx.get(PLAYBACK_USERS, str(user_id))
            cur = await tx.get(PLAYBACK, str(ps_id))
            if cur is not None:
                await tx.delete_read(PLAYBACK, str(ps_id), cur.data)
            if lock is not None:
                ids = [i for i in lock.get("active_ids") or [] if i != str(ps_id)]
                started = cur.get("started_at") if cur is not None else None
                starts = list(lock.get("starts") or [])
                if started in starts:
                    starts.remove(started)
                await tx.put(PLAYBACK_USERS, str(user_id), {**lock.data, "active_ids": ids, "starts": starts})

        await self.store.run_transaction(body)


def repo() -> PlaybackRepo:
    return PlaybackRepo(ScopedStore.system(JOB))
