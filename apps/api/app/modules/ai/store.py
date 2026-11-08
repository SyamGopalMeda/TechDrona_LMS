"""Platform AI settings, platform app toggles, the usage ledger (reserve → call → finalise) and
server-side tutor history.

Single company (ai_0002): settings and app toggles are platform-wide singletons; there is no
organization layer.

Ledger transactions (SEC-14 / SEC-15). ``reserve`` and ``finalize`` each run in their **own short
transaction** (``ledger_tx``) — a separate session from ``get_sessionmaker()`` that commits
before the provider is called. ``reserve`` takes a transaction-scoped advisory lock (released at
that commit), checks the monthly platform caps — counting in-flight reservations, so concurrent
requests cannot overshoot — and, for the tutor, the per-(learner, activity) limit, then inserts an
``ai_usage`` row with outcome ``reserved`` and the worst-case token estimate. No AI lock and no
AI transaction is held while the provider runs. ``finalize`` turns the reservation into the real
record (ok / invalid_output / provider_error; a DB trigger only lets a ``reserved`` row change
once). Because the ledger commits on its own, spending is recorded even when the caller's request
later rolls back. In tests the session factory is bound to the test connection, so these
"separate" transactions are savepoints and still roll back with the test.

A reservation that is never finalised (process crash) keeps counting against the monthly caps
(conservative); it counts against a learner's tutor limit only for ``RESERVATION_TTL``.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import apply_db_role, as_system, get_sessionmaker
from app.core.ids import uuid7
from app.modules.ai.adapters import cost_estimate
from app.modules.ai.models import AISettings, AIUsage, AppSetting, TutorTurn

APPS: dict[str, tuple[str, str]] = {
    "assignments": ("Assignments", "learning"),
    "assessments": ("Assessments & exams", "learning"),
    "question_banks": ("Question banks", "learning"),
    "engage": ("Live engage (polls, word clouds, quizzes)", "learning"),
    "paths": ("Learning paths", "learning"),
    "ai_tutor": ("AI tutor (Guide / Explain)", "ai"),
    "ai_grading": ("AI grading suggestions", "ai"),
    "ai_generation": ("Generate with AI (questions, paths)", "ai"),
}
FEATURES = ("question_generation", "grading", "tutor", "path_generation")
RESERVATION_TTL = timedelta(minutes=10)
CAPS_LOCK = "ai.caps"
TUTOR_HISTORY_TURNS = 6
TUTOR_TURN_MAX = 4000


@dataclass(frozen=True, slots=True)
class PlatformAI:
    """Effective platform AI settings. Defaults mirror ``ai_0002`` (D10: 20 tutor turns)."""

    enabled: bool = True
    model: str | None = None
    monthly_token_cap: int = 50_000_000
    monthly_call_cap: int = 50_000
    per_activity_default_cap: int = 20
    tutor_per_minute: int = 10
    tutor_per_day: int = 200
    generate_per_hour: int = 30
    generate_per_day: int = 100
    updated_at: datetime | None = None


OrgAI = PlatformAI  # old name, kept for importers during the transition
SETTING_FIELDS = (
    "enabled",
    "model",
    "monthly_token_cap",
    "monthly_call_cap",
    "per_activity_default_cap",
    "tutor_per_minute",
    "tutor_per_day",
    "generate_per_hour",
    "generate_per_day",
)


def month_bounds(d: date | None = None) -> tuple[datetime, datetime]:
    d = d or datetime.now(UTC).date()
    start = datetime(d.year, d.month, 1, tzinfo=UTC)
    end = datetime(d.year + (d.month == 12), d.month % 12 + 1, 1, tzinfo=UTC)
    return start, end


# --------------------------------------------------------------------------- settings


async def read_settings(session: AsyncSession) -> PlatformAI:
    row = await session.get(AISettings, 1, populate_existing=True)
    if row is None:
        return PlatformAI()
    return PlatformAI(
        **{f: getattr(row, f) for f in SETTING_FIELDS},
        updated_at=row.updated_at,
    )


async def read_apps(session: AsyncSession) -> dict[str, bool]:
    rows = (await session.execute(select(AppSetting.app_key, AppSetting.enabled))).all()
    out = dict.fromkeys(APPS, True)
    out.update({k: bool(v) for k, v in rows if k in APPS})
    return out


async def system_settings(session: AsyncSession) -> PlatformAI:
    async with as_system(session, "ai.settings"):
        return await read_settings(session)


async def system_apps(session: AsyncSession) -> dict[str, bool]:
    async with as_system(session, "ai.settings"):
        return await read_apps(session)


async def write_settings(session: AsyncSession, changes: dict[str, Any], by: uuid.UUID) -> None:
    """Caller holds platform RLS scope (admin route)."""
    row = await session.get(AISettings, 1)
    if row is None:
        row = AISettings(id=1)
        session.add(row)
    for k, v in changes.items():
        setattr(row, k, v)
    row.updated_by = by
    await session.flush()


async def write_apps(session: AsyncSession, apps: dict[str, bool], by: uuid.UUID) -> None:
    for key, enabled in apps.items():
        res = await session.execute(
            update(AppSetting).where(AppSetting.app_key == key).values(enabled=enabled, updated_by=by)
        )
        if not getattr(res, "rowcount", 0):
            session.add(AppSetting(app_key=key, enabled=enabled, updated_by=by))
    await session.flush()


# --------------------------------------------------------------------------- ledger


@asynccontextmanager
async def ledger_tx(job: str) -> AsyncGenerator[AsyncSession]:
    """A short transaction of its own, at platform RLS scope, committed on exit."""
    async with get_sessionmaker()() as s, s.begin():
        await apply_db_role(s)
        await s.execute(text("SELECT set_config('lock_timeout', '5s', true)"))
        async with as_system(s, job):
            yield s


async def month_totals(
    session: AsyncSession, start: datetime, end: datetime
) -> tuple[int, int, int, Decimal]:
    row = (
        await session.execute(
            select(
                func.count(AIUsage.id),
                func.coalesce(func.sum(AIUsage.tokens_in), 0),
                func.coalesce(func.sum(AIUsage.tokens_out), 0),
                func.coalesce(func.sum(AIUsage.cost_estimate), 0),
            ).where(AIUsage.created_at >= start, AIUsage.created_at < end)
        )
    ).one()
    return int(row[0]), int(row[1]), int(row[2]), Decimal(row[3])


async def _lock(session: AsyncSession, key: str) -> None:
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"), {"k": key})


async def _tutor_used(
    session: AsyncSession, user_id: uuid.UUID, ctx: str, ctx_id: uuid.UUID, now: datetime
) -> int:
    n = (
        await session.execute(
            select(func.count(AIUsage.id)).where(
                AIUsage.user_id == user_id,
                AIUsage.feature == "tutor",
                AIUsage.context_type == ctx,
                AIUsage.context_id == ctx_id,
                or_(
                    AIUsage.outcome == "ok",
                    (AIUsage.outcome == "reserved") & (AIUsage.created_at > now - RESERVATION_TTL),
                ),
            )
        )
    ).scalar_one()
    return int(n)


async def tutor_used(session: AsyncSession, user_id: uuid.UUID, ctx: str, ctx_id: uuid.UUID) -> int:
    """Valid tutor replies (plus in-flight reservations) for one learner and activity."""
    async with as_system(session, "ai.metering"):
        now = (await session.execute(select(func.now()))).scalar_one()
        return await _tutor_used(session, user_id, ctx, ctx_id, now)


@dataclass(frozen=True, slots=True)
class Reservation:
    id: uuid.UUID
    tutor_used: int  # valid tutor replies before this one (0 for other features)


class CapExceeded(Exception):
    def __init__(self, kind: str, used: int = 0, limit: int = 0) -> None:
        super().__init__(kind)
        self.kind = kind  # "calls" | "tokens" | "tutor"
        self.used = used
        self.limit = limit


async def reserve(
    *,
    settings: PlatformAI,
    user_id: uuid.UUID | None,
    feature: str,
    provider: str,
    model: str,
    est_tokens_in: int,
    max_tokens: int,
    context_type: str | None = None,
    context_id: uuid.UUID | None = None,
    tutor_limit: int | None = None,
) -> Reservation:
    """Check caps and insert a ``reserved`` row in one short, committed transaction."""
    async with ledger_tx("ai.metering") as s:
        used = 0
        if tutor_limit is not None and user_id is not None and context_type and context_id:
            await _lock(s, f"ai.tutor:{user_id}:{context_type}:{context_id}")
            now = (await s.execute(select(func.now()))).scalar_one()
            used = await _tutor_used(s, user_id, context_type, context_id, now)
            if used >= tutor_limit:
                raise CapExceeded("tutor", used, tutor_limit)
        await _lock(s, CAPS_LOCK)
        start, end = month_bounds()
        calls, tin, tout, _ = await month_totals(s, start, end)
        if calls >= settings.monthly_call_cap:
            raise CapExceeded("calls", calls, settings.monthly_call_cap)
        if tin + tout >= settings.monthly_token_cap:
            raise CapExceeded("tokens", tin + tout, settings.monthly_token_cap)
        rid = uuid7()
        s.add(
            AIUsage(
                id=rid,
                organization_id=None,
                user_id=user_id,
                feature=feature,
                context_type=context_type,
                context_id=context_id,
                provider=provider,
                model=model,
                tokens_in=est_tokens_in,
                tokens_out=max_tokens,
                cost_estimate=cost_estimate(provider, model, est_tokens_in, max_tokens),
                outcome="reserved",
            )
        )
        await s.flush()
    return Reservation(rid, used)


async def finalize(
    reservation_id: uuid.UUID, *, provider: str, model: str, tokens_in: int, tokens_out: int, outcome: str
) -> None:
    async with ledger_tx("ai.metering") as s:
        await s.execute(
            update(AIUsage)
            .where(AIUsage.id == reservation_id, AIUsage.outcome == "reserved")
            .values(
                outcome=outcome,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_estimate=cost_estimate(provider, model, tokens_in, tokens_out),
            )
        )


async def usage_summary(session: AsyncSession, d: date) -> dict[str, Any]:
    start, end = month_bounds(d)
    calls, tin, tout, cost = await month_totals(session, start, end)
    window = (AIUsage.created_at >= start, AIUsage.created_at < end)
    by_feature = (
        await session.execute(
            select(
                AIUsage.feature,
                func.count(AIUsage.id),
                func.coalesce(func.sum(AIUsage.tokens_in), 0),
                func.coalesce(func.sum(AIUsage.tokens_out), 0),
                func.coalesce(func.sum(AIUsage.cost_estimate), 0),
            )
            .where(*window)
            .group_by(AIUsage.feature)
            .order_by(AIUsage.feature)
        )
    ).all()
    day = func.date_trunc("day", AIUsage.created_at)
    by_day = (
        await session.execute(
            select(
                day,
                func.count(AIUsage.id),
                func.coalesce(func.sum(AIUsage.tokens_in + AIUsage.tokens_out), 0),
            )
            .where(*window)
            .group_by(day)
            .order_by(day)
        )
    ).all()
    return {
        "period_start": start.date().isoformat(),
        "period_end": end.date().isoformat(),
        "totals": {"calls": calls, "tokens_in": tin, "tokens_out": tout, "cost_estimate": str(cost)},
        "by_feature": [
            {
                "feature": f,
                "calls": int(c),
                "tokens_in": int(i),
                "tokens_out": int(o),
                "cost_estimate": str(Decimal(k)),
            }
            for f, c, i, o, k in by_feature
        ],
        "by_day": [{"date": d_.date().isoformat(), "calls": int(c), "tokens": int(t)} for d_, c, t in by_day],
    }


# --------------------------------------------------------------------------- tutor history


def _ctx_filter(
    user_id: uuid.UUID, ctx: str, ctx_id: uuid.UUID, item_id: uuid.UUID | None
) -> tuple[Any, ...]:
    return (
        TutorTurn.user_id == user_id,
        TutorTurn.context_type == ctx,
        TutorTurn.context_id == ctx_id,
        TutorTurn.item_id.is_(None) if item_id is None else TutorTurn.item_id == item_id,
    )


async def history(
    session: AsyncSession,
    user_id: uuid.UUID,
    ctx: str,
    ctx_id: uuid.UUID,
    item_id: uuid.UUID | None,
    limit: int,
) -> list[TutorTurn]:
    """The last ``limit`` turns, oldest first (caller's RLS context: own rows or platform)."""
    rows = (
        (
            await session.execute(
                select(TutorTurn)
                .where(*_ctx_filter(user_id, ctx, ctx_id, item_id))
                .order_by(TutorTurn.seq.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return list(reversed(rows))


async def append_turns(
    session: AsyncSession,
    user_id: uuid.UUID,
    ctx: str,
    ctx_id: uuid.UUID,
    item_id: uuid.UUID | None,
    turns: list[tuple[str, str]],
) -> None:
    async with as_system(session, "ai.tutor_history"):
        for role, content in turns:
            body = (content or "").replace("\x00", "").strip()[:TUTOR_TURN_MAX]
            if body:
                session.add(
                    TutorTurn(
                        user_id=user_id,
                        context_type=ctx,
                        context_id=ctx_id,
                        item_id=item_id,
                        role=role,
                        content=body,
                    )
                )
                await session.flush()  # one at a time: ``seq`` keeps the order
