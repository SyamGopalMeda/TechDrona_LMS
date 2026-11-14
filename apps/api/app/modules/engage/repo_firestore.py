"""Firestore repository of ``engage`` (``TD_STORE_ENGAGE=firestore``; data model in ``store_specs.py``).

Rows come back as transient ORM instances (``EngageActivity`` / ``EngageRun`` / ...), so the
serializers in ``service.py`` are shared and every response keeps its shape.

Authorization: the service performs the same checks as on Postgres (``can_manage`` /
``_may_join`` / participant presence) before calling the repository; the repository itself runs
as named system jobs (Postgres also read runs/activities in ``system_context``), and every method
either takes the ``user_id`` it acts for or is ``@platform_only(engage.activity.manage)``.

Invariants (Postgres constraint -> Firestore):

* one join code per run: ``engage_join_codes/{code}`` created in the launch transaction;
* run numbers: ``max(run_no)+1`` read in the launch transaction, ``engage_run_keys`` guards it;
* ``FOR UPDATE`` on a run (control, join) -> the read-modify-write runs in one transaction;
* one participant per user and run: deterministic id ``{run}:{user}``; ``seq`` from the
  ``engage_seq/{run}`` counter in the same transaction (no seq collision, unlike count+1);
* one response per participant and question: deterministic id ``{participant}:{question}``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from app.core.firestore.errors import UniqueViolationError
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.rows import doc_of, orm_of
from app.core.firestore.store import Doc, ScopedStore, ScopedTransaction
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.engage import store_specs as ss
from app.modules.engage.models import (
    EngageActivity,
    EngageParticipant,
    EngageQuestion,
    EngageResponse,
    EngageRun,
)

PERM = ss.PERM
LIVE_STATUSES = ("scheduled", "open")
_MANAGED = ("created_at", "updated_at", "schema_version")


class JoinRefused(Exception):
    """Raised inside the join transaction; ``reason`` is ``closed`` or ``full``."""

    def __init__(self, reason: str, status: str = "", limit: int | None = None) -> None:
        super().__init__(reason)
        self.reason, self.status, self.limit = reason, status, limit


def _changes(obj: Any, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    d = {k: v for k, v in doc_of(obj).items() if k not in _MANAGED}
    if extra:
        d.update(extra)
    return d


def _new(obj: Any, now: datetime, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    d = doc_of(obj)
    d["created_at"] = d.get("created_at") or now
    d.pop("updated_at", None)
    if extra:
        d.update(extra)
    return d


def activity_of(d: Doc | dict[str, Any]) -> EngageActivity:
    return orm_of(EngageActivity, d.data if isinstance(d, Doc) else d)


def run_of(d: Doc | dict[str, Any]) -> EngageRun:
    return orm_of(EngageRun, d.data if isinstance(d, Doc) else d)


def refresh(r: EngageRun, now: datetime) -> bool:
    """``service.refresh_status`` without the flush (pure; applied inside a transaction)."""
    changed = False
    if (
        r.status == "scheduled"
        and (r.settings or {}).get("run_mode") == "scheduled"
        and r.opens_at
        and r.opens_at <= now
    ):
        r.status, r.opened_at, changed = "open", r.opens_at, True
    if r.status in LIVE_STATUSES and r.closes_at and r.closes_at <= now:
        r.status, r.closed_at, changed = "closed", r.closes_at, True
    if changed:
        r.state_version = int(r.state_version or 1) + 1
    return changed


class EngageRepo(FirestoreRepository):
    async def _all(
        self, coll: str, *, filters: Any = (), order_by: Any = (), user_id: Any = None
    ) -> list[Doc]:
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                coll, user_id=user_id, filters=filters, order_by=order_by, limit=500, cursor=cursor
            )
            out += page.items
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    # ------------------------------------------------------------------ activities

    @platform_only(PERM)
    async def get_activity(self, activity_id: uuid.UUID) -> EngageActivity | None:
        d = await self.store.get(ss.ACTIVITIES, str(activity_id))
        return activity_of(d) if d else None

    @platform_only(PERM)
    async def questions_of(self, activity_id: uuid.UUID) -> list[EngageQuestion]:
        docs = await self._all(
            ss.QUESTIONS, filters=(("activity_id", "==", str(activity_id)),), order_by=(("position", "asc"),)
        )
        return [orm_of(EngageQuestion, d.data) for d in docs]

    @platform_only(PERM)
    async def list_activities(
        self, *, activity_type: str | None, title_like: str | None, limit: int
    ) -> list[EngageActivity]:
        """Not deleted, newest first; ``title_like`` is a case-insensitive substring (ILIKE)."""
        filters: list[Any] = [("deleted", "==", False)]
        if activity_type:
            filters.append(("activity_type", "==", activity_type))
        needle = title_like.lower() if title_like else None
        out: list[EngageActivity] = []
        cursor: str | None = None
        while len(out) < limit:
            page = await self.store.query(
                ss.ACTIVITIES, filters=filters, order_by=(("created_at", "desc"),), limit=200, cursor=cursor
            )
            for d in page.items:
                if needle is None or needle in str(d.get("title") or "").lower():
                    out.append(activity_of(d))
                    if len(out) >= limit:
                        break
            if not page.next_cursor:
                break
            cursor = page.next_cursor
        return out

    @platform_only(PERM)
    async def question_counts(self, activity_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
        out: dict[uuid.UUID, int] = {}
        for aid in activity_ids:
            n = await self.store.count(ss.QUESTIONS, filters=(("activity_id", "==", str(aid)),))
            if n:
                out[aid] = n
        return out

    @platform_only(PERM)
    async def latest_runs(self, activity_ids: list[uuid.UUID]) -> dict[uuid.UUID, EngageRun]:
        out: dict[uuid.UUID, EngageRun] = {}
        for aid in activity_ids:
            page = await self.store.query(
                ss.RUNS, filters=(("activity_id", "==", str(aid)),), order_by=(("run_no", "desc"),), limit=1
            )
            if page.items:
                out[aid] = run_of(page.items[0])
        return out

    @platform_only(PERM)
    async def create_activity(self, a: EngageActivity, questions: list[EngageQuestion]) -> EngageActivity:
        now = utcnow()

        async def fn(tx: ScopedTransaction) -> EngageActivity:
            d = await tx.create(
                ss.ACTIVITIES, _new(a, now, {"deleted": a.deleted_at is not None}), doc_id=str(a.id)
            )
            for q in questions:
                await tx.create(ss.QUESTIONS, _new(q, now), doc_id=str(q.id))
            return activity_of(d)

        return await self.store.run_transaction(fn)

    @platform_only(PERM)
    async def replace_activity(self, a: EngageActivity, questions: list[EngageQuestion]) -> EngageActivity:
        """Update the activity's settings and replace its questions (delete + insert), atomically."""
        now = utcnow()

        async def fn(tx: ScopedTransaction) -> EngageActivity:
            cur = await tx.get(ss.ACTIVITIES, str(a.id))
            if cur is None:
                from app.core.errors import ProblemError

                raise ProblemError("not_found")
            old = await tx.query(ss.QUESTIONS, filters=(("activity_id", "==", str(a.id)),))
            d = await tx.update_read(ss.ACTIVITIES, cur, _changes(a, {"deleted": a.deleted_at is not None}))
            for od in old:
                await tx.delete_read(ss.QUESTIONS, od.id, od.data)
            for q in questions:
                await tx.create(ss.QUESTIONS, _new(q, now), doc_id=str(q.id))
            return activity_of(d)

        return await self.store.run_transaction(fn)

    @platform_only(PERM)
    async def delete_activity(self, activity_id: uuid.UUID, now: datetime) -> None:
        """Soft-delete and close every live run (state_version + 1), atomically."""

        async def fn(tx: ScopedTransaction) -> None:
            cur = await tx.get(ss.ACTIVITIES, str(activity_id))
            runs = await tx.query(
                ss.RUNS,
                filters=(("activity_id", "==", str(activity_id)), ("status", "in", list(LIVE_STATUSES))),
            )
            if cur is not None:
                await tx.update_read(ss.ACTIVITIES, cur, {"deleted_at": now, "deleted": True})
            for r in runs:
                await tx.update_read(
                    ss.RUNS,
                    r,
                    {"status": "closed", "closed_at": now, "state_version": int(r["state_version"]) + 1},
                )

        await self.store.run_transaction(fn)

    # ------------------------------------------------------------------ runs

    @platform_only(PERM)
    async def runs_of(self, activity_id: uuid.UUID) -> list[EngageRun]:
        docs = await self._all(
            ss.RUNS, filters=(("activity_id", "==", str(activity_id)),), order_by=(("run_no", "desc"),)
        )
        return [run_of(d) for d in docs]

    @platform_only(PERM)
    async def get_run(self, run_id: uuid.UUID) -> EngageRun | None:
        d = await self.store.get(ss.RUNS, str(run_id))
        return run_of(d) if d else None

    @platform_only(PERM)
    async def run_id_by_code(self, code: str) -> uuid.UUID | None:
        d = await self.store.get(ss.JOIN_CODES, code)
        return uuid.UUID(d["run_id"]) if d else None

    @platform_only(PERM)
    async def launch(
        self, a: EngageActivity, build: Callable[[int], EngageRun], codes: Callable[[], str], now: datetime
    ) -> EngageRun:
        """Close the activity's live runs and insert run ``max(run_no)+1`` with a fresh join code."""

        async def fn(tx: ScopedTransaction) -> EngageRun:
            runs = await tx.query(ss.RUNS, filters=(("activity_id", "==", str(a.id)),))
            run_no = max((int(r["run_no"]) for r in runs), default=0) + 1
            r = build(run_no)
            code = ""
            for _ in range(5):
                cand = codes()
                if await tx.raw_get(ss.JOIN_CODES, cand) is None:
                    code = cand
                    break
            if not code:  # pragma: no cover - 31^8 codes
                from app.core.errors import ProblemError

                raise ProblemError("conflict")
            r.join_code = code
            for x in runs:
                if x["status"] in LIVE_STATUSES:
                    await tx.update_read(
                        ss.RUNS,
                        x,
                        {"status": "closed", "closed_at": now, "state_version": int(x["state_version"]) + 1},
                    )
            tx.raw_create(ss.JOIN_CODES, code, {"run_id": str(r.id), "created_at": now})
            tx.raw_create(ss.RUN_KEYS, ss.run_key(a.id, run_no), {"run_id": str(r.id), "created_at": now})
            d = await tx.create(ss.RUNS, _new(r, now), doc_id=str(r.id))
            return run_of(d)

        return await self.store.run_transaction(fn)

    @platform_only(PERM)
    async def mutate_run(self, run_id: uuid.UUID, fn: Callable[[EngageRun], Any] | None = None) -> EngageRun:
        """``SELECT ... FOR UPDATE`` + refresh_status + ``fn(run)`` + flush, as one transaction.

        ``fn`` may raise (nothing is written). With ``fn=None`` only the timer refresh applies,
        and nothing is written when it changes nothing."""

        async def body(tx: ScopedTransaction) -> EngageRun:
            cur = await tx.get(ss.RUNS, str(run_id))
            if cur is None:
                from app.core.errors import ProblemError

                raise ProblemError("not_found")
            r = run_of(cur)
            before = _changes(r)
            refresh(r, utcnow())
            if fn is not None:
                fn(r)
            after = _changes(r)
            diff = {k: v for k, v in after.items() if before.get(k) != v}
            if not diff:
                return r
            d = await tx.update_read(ss.RUNS, cur, diff)
            return run_of(d)

        return await self.store.run_transaction(body)

    @platform_only(PERM)
    async def refresh_run(self, r: EngageRun) -> EngageRun:
        """Apply a scheduled run's timer; writes only when the status changes."""
        probe = run_of(doc_of(r))
        if not refresh(probe, utcnow()):
            return r
        return await self.mutate_run(r.id)

    # ------------------------------------------------------------------ participants / responses

    async def participant(self, run_id: uuid.UUID, user_id: uuid.UUID) -> EngageParticipant | None:
        d = await self.store.get(ss.PARTICIPANTS, ss.participant_id(run_id, user_id))
        return orm_of(EngageParticipant, d.data) if d else None

    async def join(
        self, run_id: uuid.UUID, user_id: uuid.UUID, display_name: str | None, organization_id: Any
    ) -> tuple[EngageParticipant, bool]:
        """(participant, created). Re-checks the run's status and the participant limit inside
        the transaction (the Postgres path holds the run's row lock)."""
        pid = ss.participant_id(run_id, user_id)
        now = utcnow()

        async def fn(tx: ScopedTransaction) -> tuple[EngageParticipant, bool]:
            existing = await tx.get(ss.PARTICIPANTS, pid)
            if existing is not None:
                return orm_of(EngageParticipant, existing.data), False
            run = await tx.get(ss.RUNS, str(run_id))
            if run is None:
                from app.core.errors import ProblemError

                raise ProblemError("not_found")
            r = run_of(run)
            refresh(r, now)
            if r.status not in LIVE_STATUSES:
                raise JoinRefused("closed", r.status)
            seq_doc = await tx.raw_get(ss.SEQ, str(run_id))
            count = int((seq_doc or {}).get("value", 0))
            limit = (r.settings or {}).get("participant_limit")
            if limit is not None and count >= int(limit):
                raise JoinRefused("full", r.status, int(limit))
            tx.raw_set(ss.SEQ, str(run_id), {"value": count + 1, "updated_at": now})
            p = EngageParticipant(
                id=uuid7(),
                run_id=run_id,
                organization_id=organization_id,
                user_id=user_id,
                display_name=display_name,
                seq=count + 1,
                joined_at=now,
            )
            d = await tx.create(ss.PARTICIPANTS, _new(p, now), doc_id=pid)
            return orm_of(EngageParticipant, d.data), True

        return await self.store.run_transaction(fn)

    @platform_only(PERM)
    async def participant_count(self, run_id: uuid.UUID) -> int:
        return await self.store.count(ss.PARTICIPANTS, filters=(("run_id", "==", str(run_id)),))

    @platform_only(PERM)
    async def participants_map(self, run_id: uuid.UUID) -> dict[uuid.UUID, EngageParticipant]:
        docs = await self._all(ss.PARTICIPANTS, filters=(("run_id", "==", str(run_id)),))
        ps = [orm_of(EngageParticipant, d.data) for d in docs]
        return {p.id: p for p in ps}

    async def answer(self, user_id: uuid.UUID, response: EngageResponse) -> datetime | None:
        """Insert the response; ``None`` when this participant already answered the question."""
        now = utcnow()
        response.answered_at = now
        rid = ss.response_id(response.participant_id, response.question_id)
        try:
            await self.store.create(ss.RESPONSES, _new(response, now), doc_id=rid)
        except UniqueViolationError:
            return None
        return now

    @platform_only(PERM)
    async def responses(self, run_id: uuid.UUID) -> list[EngageResponse]:
        docs = await self._all(ss.RESPONSES, filters=(("run_id", "==", str(run_id)),))
        return [orm_of(EngageResponse, d.data) for d in docs]

    async def my_responses(self, user_id: uuid.UUID, participant_id: uuid.UUID) -> list[EngageResponse]:
        docs = await self._all(
            ss.RESPONSES, user_id=user_id, filters=(("participant_id", "==", str(participant_id)),)
        )
        return [orm_of(EngageResponse, d.data) for d in docs]

    async def my_participations(self, user_id: uuid.UUID, limit: int = 50) -> list[EngageParticipant]:
        page = await self.store.query(
            ss.PARTICIPANTS, user_id=user_id, order_by=(("joined_at", "desc"),), limit=limit
        )
        return [orm_of(EngageParticipant, d.data) for d in page.items]

    # ------------------------------------------------------------------ erasure (DB-01)

    async def erase_user(self, user_id: uuid.UUID) -> dict[str, int]:
        names = texts = 0
        for d in await self._all(ss.PARTICIPANTS, user_id=user_id):
            if d.get("display_name") is not None:
                await self.store.update(ss.PARTICIPANTS, d.id, {"display_name": None})
                names += 1
        for d in await self._all(ss.RESPONSES, user_id=user_id):
            ans = d.get("answer") or {}
            if isinstance(ans, dict) and "text" in ans:
                await self.store.update(ss.RESPONSES, d.id, {"answer": {"erased": True}, "terms": []})
                texts += 1
        return {"participant_names_cleared": names, "text_answers_erased": texts}


def repo(job: str = "engage.service") -> EngageRepo:
    return EngageRepo(ScopedStore.system(job))
