"""Firestore repository of the sessions module (``TD_STORE_SESSIONS=firestore``).

``service.py`` / ``resolver.py`` dispatch here when the switch is on. Objects are transient ORM
instances; the service's mutators (``activate_session``, ``end_session``, ``trust_device``, ...)
persist them through ``save_*`` after mutating, which replaces the Postgres session flush.

Authorization: sessions are resolved before a principal exists, so Postgres runs these reads in
``system_context("sessions.*")``; the repository uses the named job ``sessions.store`` and every
method is ``@platform_only``.

Replaced Postgres mechanisms:

* ``ux_as_token`` / ``ux_devices_key``: random 256-bit / HMAC values, looked up by equality.
* ``ux_ud_user_device``: ``user_devices_live`` lookup document, same transaction as the row.
* ``SELECT ... FOR UPDATE`` on the session row: every session write is a transaction that
  re-reads the document; ``end_session`` never resurrects an already-ended session.
* ``pg_advisory_xact_lock('sess:'||user)`` (``lock_user``): ``locks/sess:{user}`` lease.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import structlog
from google.api_core import exceptions as gexc

from app.core.firestore.repository import platform_only
from app.core.firestore.store import Doc, ScopedTransaction
from app.modules.identity import clock
from app.modules.identity.fs_base import AccessRepo
from app.modules.identity.fs_codec import doc_obj, obj_doc
from app.modules.sessions.models import (
    AuthSession,
    Device,
    LoginAttempt,
    SessionNetworkObservation,
    UserDevice,
)
from app.modules.sessions.store_specs import (
    ATTEMPTS,
    DEVICES,
    OBSERVATIONS,
    SESSIONS,
    UD_LIVE,
    USER_DEVICES,
    live_id,
)

PERM = "session.read"
log = structlog.get_logger("sessions.store")
JOB = "sessions.store"
ENDED = frozenset({"expired", "revoked", "blocked"})
# migrations sessions_0001: CHECK (status IN (pending_mfa, pending_device_otp,
# pending_session_choice, active, expired, revoked, blocked)) -- the not-ended ones:
OPEN = ("active", "pending_mfa", "pending_device_otp", "pending_session_choice")


class SessionsRepo(AccessRepo):
    # ------------------------------------------------------------------ devices

    @platform_only(PERM)
    async def devices_by_hashes(self, digests: list[bytes]) -> list[Device]:
        if not digests:
            return []
        return await self._objs(
            Device, DEVICES, filters=(("device_key_hash", "in", [d.hex() for d in digests]),)
        )

    @platform_only(PERM)
    async def get_device(self, device_id: uuid.UUID) -> Device | None:
        return await self._get_obj(Device, DEVICES, str(device_id))

    @platform_only(PERM)
    async def get_devices(self, device_ids: list[uuid.UUID]) -> dict[uuid.UUID, Device]:
        docs = await self.store.get_many(DEVICES, [str(d) for d in device_ids])
        return {uuid.UUID(k): doc_obj(Device, d.data) for k, d in docs.items()}

    @platform_only(PERM)
    async def save_device(self, dev: Device) -> Device:
        return await self._upsert(DEVICES, str(dev.id), dev)

    # ------------------------------------------------------------------ user devices

    @platform_only(PERM)
    async def user_devices(self, user_id: uuid.UUID) -> list[UserDevice]:
        return await self._objs(UserDevice, USER_DEVICES, user_id=user_id)

    @platform_only(PERM)
    async def get_user_device_by_id(self, ud_id: uuid.UUID) -> UserDevice | None:
        return await self._get_obj(UserDevice, USER_DEVICES, str(ud_id))

    @platform_only(PERM)
    async def live_user_device(self, user_id: uuid.UUID, device_id: uuid.UUID) -> UserDevice | None:
        ref = await self.store.get(UD_LIVE, live_id(user_id, device_id))
        if ref is None:
            return None
        ud = await self._get_obj(UserDevice, USER_DEVICES, ref["user_device_id"])
        return ud if ud is not None and ud.trust_status != "removed" else None

    @platform_only(PERM)
    async def ensure_user_device(self, user_id: uuid.UUID, device_id: uuid.UUID) -> tuple[UserDevice, bool]:
        """The live (user, device) row, created if absent: ``(row, created)``. Concurrent callers
        converge on one row (the lookup document is created in the same transaction)."""
        lid = live_id(user_id, device_id)

        async def fn(tx: ScopedTransaction) -> tuple[Doc, bool]:
            ref = await tx.get(UD_LIVE, lid)
            if ref is not None:
                cur = await tx.get(USER_DEVICES, ref["user_device_id"])
                if cur is not None and cur.get("trust_status") != "removed":
                    return cur, False
            from app.core.ids import uuid7

            ud = UserDevice(
                id=uuid7(),
                user_id=user_id,
                device_id=device_id,
                trust_status="pending_otp",
                counts_toward_cap=True,
            )
            d = await tx.create(USER_DEVICES, self.new_doc(ud), doc_id=str(ud.id))
            await tx.put(UD_LIVE, lid, {"user_device_id": str(ud.id)})
            return d, True

        d, created = await self.store.run_transaction(fn)
        return doc_obj(UserDevice, d.data), created

    @platform_only(PERM)
    async def save_user_device(self, ud: UserDevice) -> UserDevice:
        """Overwrite ``ud``; a removed row frees its ``user_devices_live`` slot."""
        lid = live_id(ud.user_id, ud.device_id)

        async def fn(tx: ScopedTransaction) -> Doc:
            cur = await tx.get(USER_DEVICES, str(ud.id))
            ref = await tx.get(UD_LIVE, lid)
            d = await self._tx_upsert(tx, USER_DEVICES, str(ud.id), ud, cur)
            if ud.trust_status == "removed" and ref is not None and ref["user_device_id"] == str(ud.id):
                await tx.delete_read(UD_LIVE, lid, ref.data)
            elif ud.trust_status != "removed" and ref is None:
                await tx.put(UD_LIVE, lid, {"user_device_id": str(ud.id)})
            return d

        return doc_obj(UserDevice, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def clear_remember(self, user_id: uuid.UUID) -> int:
        n = 0
        for ud in await self.user_devices(user_id):
            if ud.remember_token_hash is not None:
                ud.remember_token_hash = None
                ud.remember_until = None
                await self.save_user_device(ud)
                n += 1
        return n

    @platform_only(PERM)
    async def user_device_by_remember(self, token_hash: bytes) -> UserDevice | None:
        rows = await self._objs(
            UserDevice, USER_DEVICES, filters=(("remember_token_hash", "==", token_hash.hex()),)
        )
        return rows[0] if rows else None

    # ------------------------------------------------------------------ auth sessions

    @platform_only(PERM)
    async def add_session(self, s: AuthSession) -> AuthSession:
        d = await self.store.create(SESSIONS, self.new_doc(s), doc_id=str(s.id))
        return doc_obj(AuthSession, d.data)

    @platform_only(PERM)
    async def get_session(self, session_id: uuid.UUID) -> AuthSession | None:
        return await self._get_obj(AuthSession, SESSIONS, str(session_id))

    @platform_only(PERM)
    async def session_by_token(self, token_hash: bytes) -> AuthSession | None:
        """Per-request lookup: one equality query on ``token_hash``."""
        page = await self.store.query(
            SESSIONS, filters=(("token_hash", "==", token_hash.hex()),), order_by=(), limit=1
        )
        return doc_obj(AuthSession, page.items[0].data) if page.items else None

    @platform_only(PERM)
    async def save_session(self, s: AuthSession) -> AuthSession:
        """Overwrite ``s``. A session another request ended meanwhile stays ended (the
        Postgres row lock gave the same result: the second writer saw the ended row)."""

        async def fn(tx: ScopedTransaction) -> Doc:
            cur = await tx.get(SESSIONS, str(s.id))
            if cur is not None and cur.get("status") in ENDED and s.status not in ENDED:
                return cur
            return await self._tx_upsert(tx, SESSIONS, str(s.id), s, cur)

        return doc_obj(AuthSession, (await self.store.run_transaction(fn)).data)

    @platform_only(PERM)
    async def sessions_for(self, user_id: uuid.UUID) -> list[AuthSession]:
        rows = await self._objs(AuthSession, SESSIONS, user_id=user_id)
        return sorted(rows, key=lambda s: (s.created_at, str(s.id)))

    async def _open_sessions(self, user_id: uuid.UUID) -> list[AuthSession]:
        """The user's sessions that are not ended (``OPEN``: every other status the
        ``auth_sessions`` CHECK constraint allows), instead of every session the user ever had
        (billed per document; the history grows with every sign-in). Falls back to the whole
        history if the project refuses the query, so the result never changes."""
        try:
            rows = await self._objs(
                AuthSession, SESSIONS, user_id=user_id, filters=(("status", "in", list(OPEN)),)
            )
        except gexc.FailedPrecondition:
            log.warning("open_sessions_query_unavailable")
            return await self.sessions_for(user_id)
        return sorted(rows, key=lambda s: (s.created_at, str(s.id)))

    @platform_only(PERM)
    async def active_sessions(
        self, user_id: uuid.UUID, *, exclude: uuid.UUID | None = None
    ) -> list[AuthSession]:
        now = clock.now()
        rows = await self._objs(AuthSession, SESSIONS, user_id=user_id, filters=(("status", "==", "active"),))
        out = [
            s
            for s in rows
            if s.absolute_expires_at > now
            and (s.idle_expires_at > now or (s.idle_hold_until is not None and s.idle_hold_until > now))
            and s.id != exclude
        ]
        return sorted(out, key=lambda s: (s.created_at, str(s.id)))

    @platform_only(PERM)
    async def end_sessions(
        self,
        user_id: uuid.UUID,
        *,
        status: str,
        reason: str,
        ended_by: uuid.UUID | None = None,
        where: Callable[[AuthSession], bool] = lambda _s: True,
    ) -> int:
        """``end_sessions_where`` for one user's sessions: every not-ended session matching
        ``where`` ends (one transaction per 300 sessions)."""
        rows = [s for s in await self._open_sessions(user_id) if s.status not in ENDED and where(s)]
        now = clock.now()
        n = 0
        for i in range(0, len(rows), 300):
            ids = [str(s.id) for s in rows[i : i + 300]]

            async def fn(tx: ScopedTransaction, ids: list[str] = ids) -> int:
                docs = await tx.get_many(SESSIONS, ids)
                k = 0
                for d in docs.values():
                    if d.get("status") not in ENDED:
                        changes = {
                            "status": status,
                            "end_reason": reason,
                            "ended_at": now,
                            "ended_by": ended_by,
                        }
                        await tx.update_read(SESSIONS, d, changes)
                        k += 1
                return k

            n += await self.store.run_transaction(fn)
        return n

    # ------------------------------------------------------------------ login attempts / observations

    @platform_only(PERM)
    async def add_attempt(self, a: LoginAttempt) -> LoginAttempt:
        from app.modules.sessions.store_specs import ip_prefix

        doc = {**self.new_doc(a), "ip_prefix": ip_prefix(a.ip)}
        d = await self.store.create(ATTEMPTS, doc, doc_id=str(a.id))
        return doc_obj(LoginAttempt, d.data)

    @platform_only(PERM)
    async def attempts_for_identifiers(self, digests: list[bytes], since: datetime) -> list[LoginAttempt]:
        if not digests:
            return []
        return await self._objs(
            LoginAttempt,
            ATTEMPTS,
            filters=(("identifier_hash", "in", [d.hex() for d in digests]), ("attempted_at", ">", since)),
            order_by=(("attempted_at", "asc"),),
        )

    @platform_only(PERM)
    async def count_attempts(
        self,
        *,
        since: datetime,
        user_id: uuid.UUID | None = None,
        ip: str | None = None,
        outcome: str | None = None,
        outcomes: tuple[str, ...] = (),
    ) -> int:
        field, value = ("user_id", str(user_id)) if user_id is not None else ("ip", ip)
        want = set(outcomes) | ({outcome} if outcome else set())
        # Aggregation count (1 billed read per 1000 matches) instead of reading every attempt of
        # the IP / user in the window (a whole campus behind one NAT IP logs in within minutes).
        # Same number; if the project lacks the composite index for the outcome filter, the old
        # full read answers (logged) -- never a different result.
        filters: tuple[Any, ...] = ((field, "==", value), ("attempted_at", ">", since))
        if want:
            filters += (("outcome", "in", sorted(want)),)
        try:
            return await self.store.count(ATTEMPTS, filters=filters)
        except gexc.FailedPrecondition:
            log.warning("login_attempt_count_index_missing", field=field)
        rows = await self._all(
            ATTEMPTS,
            filters=((field, "==", value), ("attempted_at", ">", since)),
            order_by=(("attempted_at", "asc"),),
        )
        return sum(1 for d in rows if not want or d.get("outcome") in want)

    @platform_only(PERM)
    async def add_observation(self, o: SessionNetworkObservation) -> None:
        await self.store.create(OBSERVATIONS, self.new_doc(o), doc_id=str(o.id))

    @platform_only(PERM)
    async def get_attempt(self, attempt_id: uuid.UUID) -> LoginAttempt | None:
        return await self._get_obj(LoginAttempt, ATTEMPTS, str(attempt_id))

    @platform_only(PERM)
    async def get_observation(self, obs_id: uuid.UUID) -> SessionNetworkObservation | None:
        return await self._get_obj(SessionNetworkObservation, OBSERVATIONS, str(obs_id))

    # ------------------------------------------------------------------ per-user serialisation

    @platform_only(PERM)
    async def lock_user(
        self, user_id: uuid.UUID, holder: str, ttl: timedelta = timedelta(seconds=30)
    ) -> bool:
        return await self.store.claim_lease(f"sess:{user_id}", holder, ttl)

    @platform_only(PERM)
    async def unlock_user(self, user_id: uuid.UUID, holder: str) -> bool:
        return await self.store.release_lease(f"sess:{user_id}", holder)

    @staticmethod
    def doc_of(obj: Any) -> dict[str, Any]:
        return obj_doc(obj)


def system_repo(job: str = JOB) -> SessionsRepo:
    from app.modules.identity.fs_journal import JournalingStore

    return SessionsRepo(JournalingStore.system(job))
