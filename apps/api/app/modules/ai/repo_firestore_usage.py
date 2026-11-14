"""Firestore AI usage ledger, tutor quota and tutor history (``TD_STORE_AI=firestore``).

``ai.store`` dispatches here. Same guarantees as the Postgres ledger (SEC-14 / SEC-15, D10):

* ``reserve`` is one transaction: it reads the month rollup (every reservation of the month
  conflicts on it, which replaces the ``ai.caps`` advisory lock) and, for the tutor, the
  ``ai_quota`` document (replaces the per-activity advisory lock), checks the caps counting
  in-flight reservations, then writes the ``reserved`` usage row, the rollup and the quota. N
  concurrent requests against a limit L get exactly L reservations (Firestore retries losers,
  which then see the new counts).
* ``finalize`` is one transaction and changes a row only while it is ``reserved`` (the
  ``ai_usage_finalize_guard`` trigger becomes this state check); the rollup moves by the delta.
* Nothing here calls the provider; ``store`` calls it between the two transactions.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import Doc, ScopedStore, ScopedTransaction
from app.core.ids import uuid7
from app.core.time import utcnow
from app.modules.ai.store_specs_usage import (
    QUOTA,
    TUTOR_THREADS,
    TUTOR_TURNS,
    USAGE,
    USAGE_MONTHS,
    add_to_month,
    day_key,
    empty_month,
    from_micros,
    micros,
    month_key,
    quota_id,
    thread_id,
    turn_id,
)

METERING = "ai.metering"
_PAGE = 100


class CapHit(Exception):
    def __init__(self, kind: str, used: int, limit: int) -> None:
        super().__init__(kind)
        self.kind, self.used, self.limit = kind, used, limit


def _tutor_count(q: dict[str, Any] | None, now: datetime, ttl: timedelta) -> int:
    if not q:
        return 0
    live = sum(1 for ts in (q.get("reserved") or {}).values() if ts > now - ttl)
    return int(q.get("ok") or 0) + live


def _month(d: Doc | None) -> dict[str, Any]:
    if d is None:
        return empty_month()
    m = empty_month()
    m.update({k: d.get(k) for k in m if d.get(k) is not None})
    m["by_feature"] = {k: dict(v) for k, v in (d.get("by_feature") or {}).items()}
    m["by_day"] = {k: dict(v) for k, v in (d.get("by_day") or {}).items()}
    return m


class AIUsageRepo(FirestoreRepository):
    @platform_only("ai.usage.read")
    async def reserve(
        self,
        *,
        caps: tuple[int, int],
        row: dict[str, Any],
        tutor_limit: int | None,
        reservation_ttl: timedelta,
    ) -> tuple[uuid.UUID, int]:
        """``caps = (monthly_call_cap, monthly_token_cap)``; ``row``: the usage fields
        (``user_id``, ``feature``, ``context_*``, ``provider``, ``model``, ``tokens_in``,
        ``tokens_out``, ``cost_estimate``). Returns (usage id, tutor replies before this one)."""
        call_cap, token_cap = caps
        rid = uuid7()
        tutor = (
            row["feature"] == "tutor"
            and row.get("user_id")
            and row.get("context_type")
            and row.get("context_id")
        )
        qid = quota_id(row["user_id"], row["context_type"], row["context_id"]) if tutor else None

        async def fn(tx: ScopedTransaction) -> int:
            now = utcnow()
            mk = month_key(now)
            q = await tx.get(QUOTA, qid) if qid else None
            md = await tx.get(USAGE_MONTHS, mk)
            used = 0
            if tutor_limit is not None and qid:
                used = _tutor_count(q.data if q else None, now, reservation_ttl)
                if used >= tutor_limit:
                    raise CapHit("tutor", used, tutor_limit)
            m = _month(md)
            if m["calls"] >= call_cap:
                raise CapHit("calls", m["calls"], call_cap)
            if m["tokens_in"] + m["tokens_out"] >= token_cap:
                raise CapHit("tokens", m["tokens_in"] + m["tokens_out"], token_cap)
            cost = Decimal(str(row["cost_estimate"]))
            doc = {
                "id": str(rid),
                "organization_id": None,
                "user_id": None if row.get("user_id") is None else str(row["user_id"]),
                "feature": row["feature"],
                "context_type": row.get("context_type"),
                "context_id": None if row.get("context_id") is None else str(row["context_id"]),
                "provider": row["provider"],
                "model": row["model"],
                "tokens_in": int(row["tokens_in"]),
                "tokens_out": int(row["tokens_out"]),
                "cost_estimate": str(cost.quantize(Decimal("0.000001"))),
                "cost_micros": micros(cost),
                "outcome": "reserved",
                "month": mk,
                "day": day_key(now),
                "created_at": now,
            }
            add_to_month(m, doc)
            await tx.create(USAGE, doc, doc_id=str(rid))
            await tx.put(USAGE_MONTHS, mk, {**m, **({"created_at": md["created_at"]} if md else {})})
            if qid:
                live = {
                    k: v
                    for k, v in ((q.get("reserved") if q else None) or {}).items()
                    if v > now - reservation_ttl
                }
                live[str(rid)] = now
                await tx.put(
                    QUOTA,
                    qid,
                    {
                        "user_id": str(row["user_id"]),
                        "context_type": row["context_type"],
                        "context_id": str(row["context_id"]),
                        "ok": int((q.get("ok") if q else 0) or 0),
                        "reserved": live,
                        **({"created_at": q["created_at"]} if q and q.get("created_at") else {}),
                    },
                )
            return used

        used = await self.store.run_transaction(fn)
        return rid, used

    @platform_only("ai.usage.read")
    async def finalize(self, reservation_id: uuid.UUID, changes: dict[str, Any]) -> bool:
        """``changes``: outcome, model, tokens_in, tokens_out, cost_estimate. False when the row is
        not ``reserved`` any more (the finalise guard: a reservation changes exactly once)."""

        async def fn(tx: ScopedTransaction) -> bool:
            cur = await tx.get(USAGE, str(reservation_id))
            if cur is None or cur.get("outcome") != "reserved":
                return False
            md = await tx.get(USAGE_MONTHS, cur["month"])
            u = cur.data
            tutor = (
                u["feature"] == "tutor" and u.get("user_id") and u.get("context_type") and u.get("context_id")
            )
            qid = quota_id(u["user_id"], u["context_type"], u["context_id"]) if tutor else None
            q = await tx.get(QUOTA, qid) if qid else None
            cost = Decimal(str(changes["cost_estimate"]))
            new = {
                **u,
                "outcome": changes["outcome"],
                "model": changes["model"],
                "tokens_in": int(changes["tokens_in"]),
                "tokens_out": int(changes["tokens_out"]),
                "cost_estimate": str(cost.quantize(Decimal("0.000001"))),
                "cost_micros": micros(cost),
            }
            m = _month(md)
            add_to_month(m, u, -1)
            add_to_month(m, new)
            await tx.update_read(
                USAGE,
                cur,
                {
                    k: new[k]
                    for k in ("outcome", "model", "tokens_in", "tokens_out", "cost_estimate", "cost_micros")
                },
            )
            await tx.put(
                USAGE_MONTHS, cur["month"], {**m, **({"created_at": md["created_at"]} if md else {})}
            )
            if qid and q is not None:
                reserved = dict(q.get("reserved") or {})
                reserved.pop(str(reservation_id), None)
                ok = int(q.get("ok") or 0) + (1 if new["outcome"] == "ok" else 0)
                await tx.put(QUOTA, qid, {**q.data, "reserved": reserved, "ok": ok})
            elif qid and new["outcome"] == "ok":
                await tx.put(
                    QUOTA,
                    qid,
                    {
                        "user_id": u["user_id"],
                        "context_type": u["context_type"],
                        "context_id": u["context_id"],
                        "ok": 1,
                        "reserved": {},
                    },
                )
            return True

        return await self.store.run_transaction(fn)

    @platform_only("ai.usage.read")
    async def tutor_used(
        self, user_id: uuid.UUID, ctx: str, ctx_id: uuid.UUID, reservation_ttl: timedelta
    ) -> int:
        q = await self.store.get(QUOTA, quota_id(user_id, ctx, ctx_id))
        return _tutor_count(q.data if q else None, utcnow(), reservation_ttl)

    @platform_only("ai.usage.read")
    async def month_totals(self, month: str) -> tuple[int, int, int, Decimal]:
        m = _month(await self.store.get(USAGE_MONTHS, month))
        cost = from_micros(m["cost_micros"]) if m["calls"] else Decimal(0)
        return m["calls"], m["tokens_in"], m["tokens_out"], cost

    @platform_only("ai.usage.read")
    async def month_rollup(self, month: str) -> dict[str, Any]:
        return _month(await self.store.get(USAGE_MONTHS, month))

    @platform_only("ai.usage.read")
    async def get_usage(self, usage_id: uuid.UUID) -> dict[str, Any] | None:
        d = await self.store.get(USAGE, str(usage_id))
        return d.data if d else None

    # ------------------------------------------------------------------ tutor history

    async def history(
        self, user_id: uuid.UUID, ctx: str, ctx_id: uuid.UUID, item_id: uuid.UUID | None, limit: int
    ) -> list[dict[str, Any]]:
        """The last ``limit`` turns of one thread, oldest first."""
        page = await self.store.query(
            TUTOR_TURNS,
            user_id=user_id,
            filters=(("thread", "==", thread_id(user_id, ctx, ctx_id, item_id)),),
            order_by=(("seq", "desc"),),
            limit=limit,
        )
        return [d.data for d in reversed(page.items)]

    async def append_turns(
        self,
        user_id: uuid.UUID,
        ctx: str,
        ctx_id: uuid.UUID,
        item_id: uuid.UUID | None,
        bodies: list[tuple[str, str]],
    ) -> None:
        if not bodies:
            return
        tid = thread_id(user_id, ctx, ctx_id, item_id)

        async def fn(tx: ScopedTransaction) -> None:
            th = await tx.get(TUTOR_THREADS, tid)
            n = int(th["next"]) if th else 0
            now = utcnow()
            for role, body in bodies:
                n += 1
                await tx.create(
                    TUTOR_TURNS,
                    {
                        "seq": n,
                        "thread": tid,
                        "user_id": str(user_id),
                        "context_type": ctx,
                        "context_id": str(ctx_id),
                        "item_id": None if item_id is None else str(item_id),
                        "role": role,
                        "content": body,
                        "created_at": now,
                    },
                    doc_id=turn_id(tid, n),
                )
            await tx.put(TUTOR_THREADS, tid, {"next": n, **({"created_at": th["created_at"]} if th else {})})

        await self.store.run_transaction(fn)

    # ------------------------------------------------------------------ erasure (DB-01)

    async def erase_user(self, user_id: uuid.UUID) -> tuple[int, int]:
        """Pseudonymise the ledger rows, delete tutor turns, threads and quota counters.
        Returns (usage rows pseudonymised, turns deleted)."""
        uid = str(user_id)
        usage = [d async for d in _stream(self.store, USAGE, ("user_id", "==", uid))]
        turns = [d async for d in _stream(self.store, TUTOR_TURNS, ("user_id", "==", uid), owned=uid)]
        quotas = [d async for d in _stream(self.store, QUOTA, ("user_id", "==", uid))]
        threads = {t["thread"] for t in turns}
        for i in range(0, len(usage), 300):
            chunk = usage[i : i + 300]

            async def upd(tx: ScopedTransaction, chunk: list[Doc] = chunk) -> None:
                for d in chunk:
                    await tx.update_read(USAGE, d, {"user_id": None})

            await self.store.run_transaction(upd)
        dels = [(TUTOR_TURNS, d) for d in turns] + [(QUOTA, d) for d in quotas]
        th_docs = await self.store.get_many(TUTOR_THREADS, threads) if threads else {}
        dels += [(TUTOR_THREADS, d) for d in th_docs.values()]
        for i in range(0, len(dels), 300):
            chunk2 = dels[i : i + 300]

            async def rm(tx: ScopedTransaction, chunk2: list[tuple[str, Doc]] = chunk2) -> None:
                for coll, d in chunk2:
                    await tx.delete_read(coll, d.id, d.data)

            await self.store.run_transaction(rm)
        return len(usage), len(turns)


async def _stream(store: ScopedStore, coll: str, f: Any, owned: str | None = None) -> Any:
    cursor: str | None = None
    while True:
        page = await store.query(
            coll,
            user_id=owned,
            filters=() if owned else (f,),
            order_by=(("created_at", "asc"),),
            limit=_PAGE,
            cursor=cursor,
        )
        for d in page.items:
            yield d
        if not page.next_cursor:
            return
        cursor = page.next_cursor


def metering() -> AIUsageRepo:
    return AIUsageRepo(ScopedStore.system(METERING))


def tutor_history_repo() -> AIUsageRepo:
    return AIUsageRepo(ScopedStore.system("ai.tutor_history"))
