"""Firestore collections of the AI usage ledger and tutor history (data-ops agent;
docs/firebase/agents/data-ops.md). Imported by ``store_specs`` so the same switch,
``TD_STORE_AI=firestore``, moves these together with the settings singletons.

* ``ai_usage/{id}`` -- one ledger row (system family: platform-only RLS). ``cost_estimate`` is the
  exact NUMERIC(12,6) text, ``cost_micros`` the same value as an integer (for sums); ``month`` /
  ``day`` are the UTC keys used by the rollup.
* ``ai_usage_months/{YYYY-MM}`` -- rollup ``{calls, tokens_in, tokens_out, cost_micros,
  by_feature: {f: {...}}, by_day: {YYYY-MM-DD: {calls, tokens}}}`` updated in the same transaction
  as every reserve / finalise. The monthly caps read one document (which also serialises
  reservations, as the ``ai.caps`` advisory lock did) and the usage report needs no scan.
* ``ai_quota/{user}:{context_type}:{context_id}`` -- ``{ok, reserved: {usage_id: created_at}}``:
  the per-(learner, activity) tutor count (valid replies + in-flight reservations, D10).
* ``ai_tutor_turns/{thread}:{seq:012d}`` -- owned by ``user_id`` (RLS: own rows or platform; only
  the ``ai.tutor_history`` job writes). ``ai_tutor_threads/{user}:{ctx}:{ctx_id}:{item|-}`` holds
  ``next`` (the order inside a thread). Backfilled turns keep the Postgres ``seq``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text

from app.core.firestore.backfill import Row, TableMapping, register_mapping
from app.core.firestore.collections import CollectionSpec, register_collection
from app.core.firestore.ids import compose_id

USAGE = "ai_usage"
USAGE_MONTHS = "ai_usage_months"
QUOTA = "ai_quota"
TUTOR_TURNS = "ai_tutor_turns"
TUTOR_THREADS = "ai_tutor_threads"

register_collection(CollectionSpec(USAGE, "system"))
register_collection(CollectionSpec(USAGE_MONTHS, "system"))
register_collection(CollectionSpec(QUOTA, "system"))
register_collection(CollectionSpec(TUTOR_TURNS, "owned", owner_writes=False))
register_collection(CollectionSpec(TUTOR_THREADS, "system"))

_MICRO = Decimal(1_000_000)
_SIX = Decimal("0.000001")


def micros(cost: Decimal | int | float | str) -> int:
    return int(Decimal(str(cost)) * _MICRO)


def from_micros(n: int) -> Decimal:
    return (Decimal(int(n)) / _MICRO).quantize(_SIX)


def month_key(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m")


def day_key(ts: datetime) -> str:
    return ts.astimezone(UTC).date().isoformat()


def quota_id(user_id: Any, ctx: str, ctx_id: Any) -> str:
    return compose_id(str(user_id), ctx, str(ctx_id))


def thread_id(user_id: Any, ctx: str, ctx_id: Any, item_id: Any) -> str:
    return compose_id(str(user_id), ctx, str(ctx_id), str(item_id) if item_id else "-")


def turn_id(thread: str, seq: int) -> str:
    return f"{thread}:{int(seq):012d}"


def _o(v: Any) -> str | None:
    return None if v is None else str(v)


def usage_doc(r: Row) -> dict[str, Any]:
    ts = r["created_at"]
    return {
        "id": str(r["id"]),
        "organization_id": _o(r.get("organization_id")),
        "user_id": _o(r.get("user_id")),
        "feature": r["feature"],
        "context_type": r.get("context_type"),
        "context_id": _o(r.get("context_id")),
        "provider": r["provider"],
        "model": r["model"],
        "tokens_in": int(r["tokens_in"]),
        "tokens_out": int(r["tokens_out"]),
        "cost_estimate": str(Decimal(str(r["cost_estimate"])).quantize(_SIX)),
        "cost_micros": micros(r["cost_estimate"]),
        "outcome": r["outcome"],
        "month": month_key(ts),
        "day": day_key(ts),
        "created_at": ts,
    }


def empty_month() -> dict[str, Any]:
    return {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_micros": 0, "by_feature": {}, "by_day": {}}


def add_to_month(m: dict[str, Any], u: dict[str, Any], sign: int = 1) -> None:
    """Add (``sign=1``) or remove (``-1``) one usage document's contribution to its month."""
    tin, tout, cost = int(u["tokens_in"]), int(u["tokens_out"]), int(u["cost_micros"])
    m["calls"] += sign
    m["tokens_in"] += sign * tin
    m["tokens_out"] += sign * tout
    m["cost_micros"] += sign * cost
    zero = {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_micros": 0}
    f = m["by_feature"].setdefault(u["feature"], dict(zero))
    f["calls"] += sign
    f["tokens_in"] += sign * tin
    f["tokens_out"] += sign * tout
    f["cost_micros"] += sign * cost
    d = m["by_day"].setdefault(u["day"], {"calls": 0, "tokens": 0})
    d["calls"] += sign
    d["tokens"] += sign * (tin + tout)
    if f["calls"] == 0:
        m["by_feature"].pop(u["feature"])
    if d["calls"] == 0:
        m["by_day"].pop(u["day"])


async def _usage_rows(session: Any) -> list[Row]:
    res = await session.execute(text("SELECT * FROM ai_usage ORDER BY created_at, id"))
    return [usage_doc(dict(r)) for r in res.mappings().all()]


async def _month_rows(session: Any) -> list[Row]:
    months: dict[str, dict[str, Any]] = defaultdict(empty_month)
    for u in await _usage_rows(session):
        add_to_month(months[u["month"]], u)
    return [{"month": k, **v} for k, v in sorted(months.items())]


async def _quota_rows(session: Any) -> list[Row]:
    q: dict[str, dict[str, Any]] = {}
    for u in await _usage_rows(session):
        if u["feature"] != "tutor" or not (u["user_id"] and u["context_type"] and u["context_id"]):
            continue
        k = quota_id(u["user_id"], u["context_type"], u["context_id"])
        d = q.setdefault(
            k,
            {
                "qid": k,
                "user_id": u["user_id"],
                "context_type": u["context_type"],
                "context_id": u["context_id"],
                "ok": 0,
                "reserved": {},
            },
        )
        if u["outcome"] == "ok":
            d["ok"] += 1
        elif u["outcome"] == "reserved":
            d["reserved"][u["id"]] = u["created_at"]
    return [q[k] for k in sorted(q)]


def turn_doc(r: Row) -> dict[str, Any]:
    return {
        "seq": int(r["seq"]),
        "thread": thread_id(r["user_id"], r["context_type"], r["context_id"], r["item_id"]),
        "user_id": str(r["user_id"]),
        "context_type": r["context_type"],
        "context_id": str(r["context_id"]),
        "item_id": _o(r["item_id"]),
        "role": r["role"],
        "content": r["content"],
        "created_at": r["created_at"],
    }


async def _thread_rows(session: Any) -> list[Row]:
    res = await session.execute(
        text(
            "SELECT user_id, context_type, context_id, item_id, max(seq) AS next FROM ai_tutor_turns "
            "GROUP BY user_id, context_type, context_id, item_id"
        )
    )
    out = [
        {
            "tid": thread_id(r["user_id"], r["context_type"], r["context_id"], r["item_id"]),
            "next": int(r["next"]),
        }
        for r in res.mappings().all()
    ]
    return sorted(out, key=lambda r: r["tid"])


def _without(key: str) -> Any:
    return lambda r: {k: v for k, v in r.items() if k != key}


register_mapping(TableMapping("ai", "ai_usage", USAGE, lambda r: str(r["id"]), usage_doc))
register_mapping(
    TableMapping(
        "ai", "ai_usage:months", USAGE_MONTHS, lambda r: r["month"], _without("month"), loader=_month_rows
    )
)
register_mapping(
    TableMapping("ai", "ai_usage:quota", QUOTA, lambda r: r["qid"], _without("qid"), loader=_quota_rows)
)
register_mapping(
    TableMapping(
        "ai",
        "ai_tutor_turns",
        TUTOR_TURNS,
        lambda r: turn_id(
            thread_id(r["user_id"], r["context_type"], r["context_id"], r["item_id"]), r["seq"]
        ),
        turn_doc,
        order_by="seq",
    )
)
register_mapping(
    TableMapping(
        "ai",
        "ai_tutor_turns:threads",
        TUTOR_THREADS,
        lambda r: r["tid"],
        _without("tid"),
        loader=_thread_rows,
    )
)
