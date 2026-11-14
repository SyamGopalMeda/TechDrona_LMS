"""AI usage ledger, tutor quota (D10) and tutor history on Firestore (``TD_STORE_AI=firestore``).
Emulator only, no Postgres: ``ai.store`` is called with ``session=None`` (unused on Firestore)."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.firestore.repository import assert_repository_scoped
from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.ai import store
from app.modules.ai import store_specs_usage as su
from app.modules.ai.repo_firestore_usage import AIUsageRepo, metering

FS_MODULES = ("ai",)
pytestmark = pytest.mark.usefixtures("fs_env")
S = store.PlatformAI()


async def _reserve(
    user: Any = None, ctx: Any = None, limit: int | None = None, **kw: Any
) -> store.Reservation:
    args: dict[str, Any] = {
        "settings": S,
        "user_id": user,
        "feature": "tutor" if ctx else "grading",
        "provider": "anthropic",
        "model": "claude-x",
        "est_tokens_in": 100,
        "max_tokens": 50,
        "context_type": "assignment" if ctx else None,
        "context_id": ctx,
        "tutor_limit": limit,
    }
    args.update(kw)
    return await store.reserve(**args)


def test_scope_lint() -> None:
    assert_repository_scoped(AIUsageRepo)


def test_cost_micros_exact() -> None:
    assert su.micros(Decimal("0.001234")) == 1234
    assert str(su.from_micros(1234)) == "0.001234" and str(su.from_micros(0)) == "0.000000"


async def test_reserve_finalize_guard_and_rollup() -> None:
    r = await _reserve()
    u = await metering().get_usage(r.id)
    assert u["outcome"] == "reserved" and (u["tokens_in"], u["tokens_out"]) == (100, 50)
    await store.finalize(
        r.id, provider="anthropic", model="claude-y", tokens_in=80, tokens_out=20, outcome="ok"
    )
    # a second finalise is a no-op (ai_usage_finalize_guard)
    await store.finalize(
        r.id, provider="anthropic", model="z", tokens_in=1, tokens_out=1, outcome="provider_error"
    )
    u = await metering().get_usage(r.id)
    assert (u["outcome"], u["model"], u["tokens_in"], u["tokens_out"]) == ("ok", "claude-y", 80, 20)
    summary = await store.usage_summary(None, datetime.now(UTC).date())  # type: ignore[arg-type]
    assert summary["totals"]["calls"] == 1 and summary["totals"]["tokens_in"] == 80
    assert summary["by_feature"][0]["feature"] == "grading" and summary["by_feature"][0]["tokens_out"] == 20
    assert summary["by_day"] == [{"date": datetime.now(UTC).date().isoformat(), "calls": 1, "tokens": 100}]
    empty = await store.usage_summary(None, datetime(2020, 1, 1).date())  # type: ignore[arg-type]
    assert empty["totals"] == {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_estimate": "0"}
    assert empty["by_feature"] == [] and empty["by_day"] == []


async def test_monthly_caps() -> None:
    capped = store.PlatformAI(monthly_call_cap=2)
    await _reserve(settings=capped)
    await _reserve(settings=capped)
    with pytest.raises(store.CapExceeded) as e:
        await _reserve(settings=capped)
    assert e.value.kind == "calls" and e.value.used == 2
    with pytest.raises(store.CapExceeded) as e2:
        await _reserve(settings=store.PlatformAI(monthly_token_cap=300))
    assert e2.value.kind == "tokens"


async def test_tutor_limit_concurrent_exactly_limit() -> None:
    user, ctx = uuid7(), uuid7()

    async def one() -> str:
        try:
            await _reserve(user, ctx, limit=3)
            return "ok"
        except store.CapExceeded as e:
            return e.kind

    results = await asyncio.gather(*(one() for _ in range(6)))
    assert results.count("ok") == 3 and results.count("tutor") == 3
    assert await store.tutor_used(None, user, "assignment", ctx) == 3  # type: ignore[arg-type]


async def test_tutor_count_ok_and_expired_reservations() -> None:
    user, ctx = uuid7(), uuid7()
    r1 = await _reserve(user, ctx, limit=5)
    r2 = await _reserve(user, ctx, limit=5)
    assert r2.tutor_used == 1
    await store.finalize(r1.id, provider="fake", model="m", tokens_in=1, tokens_out=1, outcome="ok")
    await store.finalize(
        r2.id, provider="fake", model="m", tokens_in=1, tokens_out=1, outcome="invalid_output"
    )
    assert await store.tutor_used(None, user, "assignment", ctx) == 1  # type: ignore[arg-type]
    # an abandoned reservation stops counting after RESERVATION_TTL
    qid = su.quota_id(user, "assignment", ctx)
    old = datetime.now(UTC) - store.RESERVATION_TTL - timedelta(seconds=5)
    await ScopedStore.system("t").update(su.QUOTA, qid, {"reserved": {"x": old}})
    assert await store.tutor_used(None, user, "assignment", ctx) == 1  # type: ignore[arg-type]


async def test_history_order_threads_and_erasure() -> None:
    user, other, ctx, item = uuid7(), uuid7(), uuid7(), uuid7()
    await store.append_turns(None, user, "assignment", ctx, None, [("learner", "q1"), ("tutor", "a1\x00")])  # type: ignore[arg-type]
    await store.append_turns(None, user, "assignment", ctx, None, [("learner", "q2"), ("tutor", "  ")])  # type: ignore[arg-type]
    await store.append_turns(None, user, "assignment", ctx, item, [("learner", "item q")])  # type: ignore[arg-type]
    await store.append_turns(None, other, "assignment", ctx, None, [("learner", "other")])  # type: ignore[arg-type]
    h = await store.history(None, user, "assignment", ctx, None, 10)  # type: ignore[arg-type]
    assert [(t.role, t.content) for t in h] == [("learner", "q1"), ("tutor", "a1"), ("learner", "q2")]
    assert [t.content for t in await store.history(None, user, "assignment", ctx, None, 2)] == ["a1", "q2"]  # type: ignore[arg-type]
    assert [t.content for t in await store.history(None, user, "assignment", ctx, item, 10)] == ["item q"]  # type: ignore[arg-type]
    r = await _reserve(user, ctx, limit=5)
    await store.finalize(r.id, provider="fake", model="m", tokens_in=1, tokens_out=1, outcome="ok")
    from app.modules.ai.router import erase_user

    out = await erase_user(None, user)
    assert out == {"ai_usage_pseudonymised": 1, "ai_tutor_turns_deleted": 4}
    assert await store.history(None, user, "assignment", ctx, None, 10) == []  # type: ignore[arg-type]
    assert [t.content for t in await store.history(None, other, "assignment", ctx, None, 10)] == ["other"]  # type: ignore[arg-type]
    assert (await metering().get_usage(r.id))["user_id"] is None
    assert await store.tutor_used(None, user, "assignment", ctx) == 0  # type: ignore[arg-type]
    # the monthly report keeps the pseudonymised call
    assert (await store.usage_summary(None, datetime.now(UTC).date()))["totals"]["calls"] == 1  # type: ignore[arg-type]


async def test_learner_cannot_read_others_turns(make_principal: Any, auth: Any) -> None:
    from app.core.firestore.errors import StoreAccessDeniedError

    alice, bob, ctx = make_principal(), make_principal(), uuid7()
    await store.append_turns(None, alice.user_id, "assignment", ctx, None, [("learner", "hi")])  # type: ignore[arg-type]
    mine = await ScopedStore(alice).query(su.TUTOR_TURNS, user_id=alice.user_id, order_by=(("seq", "asc"),))
    assert len(mine.items) == 1
    with pytest.raises(StoreAccessDeniedError):
        await ScopedStore(bob).query(su.TUTOR_TURNS, user_id=alice.user_id)
    with pytest.raises(StoreAccessDeniedError):  # learners never write history themselves
        await ScopedStore(alice).create(su.TUTOR_TURNS, {"user_id": str(alice.user_id), "content": "x"})
    with pytest.raises(StoreAccessDeniedError):
        await ScopedStore(alice).query(su.USAGE)


def test_month_rollup_matches_row_level_aggregation() -> None:
    """The backfill loader's rollup equals the Postgres GROUP BY of ``usage_summary``."""
    rows = []
    t0 = datetime(2026, 10, 31, 23, 30, tzinfo=UTC)
    for i, (feat, tin, tout, cost) in enumerate(
        [("tutor", 10, 5, "0.000100"), ("grading", 7, 3, "0.000050"), ("tutor", 1, 1, "0")]
    ):
        rows.append(
            su.usage_doc(
                {
                    "id": uuid7(),
                    "feature": feat,
                    "provider": "p",
                    "model": "m",
                    "tokens_in": tin,
                    "tokens_out": tout,
                    "cost_estimate": Decimal(cost),
                    "outcome": "ok",
                    "created_at": t0 + timedelta(hours=i),
                }
            )
        )
    months: dict[str, Any] = defaultdict(su.empty_month)
    for u in rows:
        su.add_to_month(months[u["month"]], u)
    assert set(months) == {"2026-10", "2026-11"}
    nov = months["2026-11"]
    assert nov["calls"] == 2 and nov["by_feature"]["tutor"]["tokens_in"] == 1
    assert str(su.from_micros(months["2026-10"]["cost_micros"])) == "0.000100"
    su.add_to_month(nov, rows[2], -1)
    assert "tutor" not in nov["by_feature"] and nov["calls"] == 1


def test_index_fragment() -> None:
    p = Path(su.__file__).with_name("firestore.indexes.fragment.json")
    declared = {tuple(f["fieldPath"] for f in i["fields"]) for i in json.loads(p.read_text())["indexes"]}
    assert ("user_id", "thread", "seq") in declared and ("user_id", "created_at") in declared
