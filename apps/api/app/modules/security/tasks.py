"""Periodic security jobs (RE §5.2 nightly batch; UNB §4.3 SLAs; RE §5.7 ratification paging).

Plain async functions taking a session, plus ``run_job(name)`` which opens its own transaction
in a system RLS context. Celery: task ``security.run_job(name)``; every entry of ``SCHEDULE``
is registered with ``app.core.jobs.register_periodic`` (beat) at import time::

    python -m app.modules.security.tasks security.sla_breach_alerts   # one run
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

import structlog
from celery import shared_task
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.db import get_sessionmaker, system_context
from app.core.jobs import register_periodic, run_async
from app.core.outbox import emit_event
from app.modules.identity import clock
from app.modules.identity.models import User
from app.modules.rbac.models import ApprovalRequest
from app.modules.security import engine, retention, signals
from app.modules.security.cases import set_ur_state
from app.modules.security.models import (
    AccountRestriction,
    SecurityCase,
    SecurityCounter,
    SecuritySignal,
    UnblockRequest,
)
from app.modules.sessions import service as ss
from app.modules.sessions.models import AuthSession

log = structlog.get_logger("app.security.tasks")
SYSTEM = AuditActor.system("security.jobs")


def _alert(kind: str, **data: Any) -> dict[str, Any]:
    return {"kind": kind, "route": "security_lead", **data}


async def decay_recompute(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """Nightly 02:00 IST: derived signals for active adults, then a full SH + TO recompute with
    decay (de-escalation of L1/L2 when scores fall)."""
    now = now or clock.now()
    since = now - timedelta(days=30)
    active = set(
        (
            await session.execute(
                select(AuthSession.user_id).where(AuthSession.created_at > since).distinct()
            )
        ).scalars()
    )
    with_signals = set(
        u
        for u in (
            await session.execute(
                select(SecuritySignal.user_id)
                .where(SecuritySignal.occurred_at > since, SecuritySignal.family == "sharing")
                .distinct()
            )
        ).scalars()
        if u
    )
    low = set(
        (
            await session.execute(
                select(AccountRestriction.user_id).where(
                    AccountRestriction.ended_at.is_(None), AccountRestriction.level < 3
                )
            )
        ).scalars()
    )
    derived = evaluated = 0
    for uid in sorted(active, key=str):
        derived += len(await signals.derive_daily_signals(session, uid, now))
    for uid in sorted(with_signals | low | active, key=str):
        user = await session.get(User, uid)
        if user is None or user.is_minor:
            continue
        if await engine.evaluate_sharing(session, uid, trigger="nightly", now=now) is not None:
            evaluated += 1
    return {"derived_signals": derived, "evaluations": evaluated}


async def restriction_expiry(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """L3 past ``ends_at``: still enforced until the student re-verifies (auto-lift needs
    re-verification, RE §6.1) — notify once. Deferred L3 past ``deferred_until``: the attempt
    session is now restricted too (revoked)."""
    now = now or clock.now()
    notified = deferred = 0
    rows = (
        (
            await session.execute(
                select(AccountRestriction).where(
                    AccountRestriction.ended_at.is_(None),
                    AccountRestriction.level == 3,
                    AccountRestriction.family == "sharing",
                )
            )
        )
        .scalars()
        .all()
    )
    for r in rows:
        if r.ends_at is not None and r.ends_at <= now:
            await engine.notify_user(
                session,
                r.user_id,
                "security.l3_expired",
                subject="You can restore your learning access",
                text_body="The pause on your account has ended. Sign in and confirm it's you with a code to "
                "restore access.",
                dedupe_key=f"l3exp:{r.id}",
            )
            notified += 1
        if r.deferred_until is not None and r.deferred_until <= now:
            await ss.end_sessions_where(
                session, AuthSession.user_id == r.user_id, status="revoked", reason="risk_L3"
            )
            r.deferred_until = None
            deferred += 1
    await session.flush()
    return {"expiry_notices": notified, "deferrals_ended": deferred}


async def sla_breach_alerts(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    """UNB §4.3: alert at 80 % of the decision SLA, auto-escalate at 100 %; approval proposals
    lapse after 72 h; info requests auto-close at 7 days; rejections close after the 14-day
    appeal window; drafts are discarded after 7 idle days; unratified kill switches page at 24 h."""
    now = now or clock.now()
    out = {
        "alerts_80": 0,
        "escalated": 0,
        "approvals_expired": 0,
        "no_response": 0,
        "rejected_final": 0,
        "drafts_deleted": 0,
        "ratification_pages": 0,
    }
    cases = (
        (
            await session.execute(
                select(SecurityCase).where(
                    SecurityCase.status != "closed", SecurityCase.sla_decision_due.is_not(None)
                )
            )
        )
        .scalars()
        .all()
    )
    for c in cases:
        assert c.sla_decision_due is not None
        total = (c.sla_decision_due - c.created_at).total_seconds() or 1
        frac = (now - c.created_at).total_seconds() / total
        if c.status in ("decided",):
            continue
        if frac >= 1.0:
            ur = (
                await session.execute(
                    select(UnblockRequest).where(
                        UnblockRequest.case_id == c.id,
                        UnblockRequest.state.in_(("submitted", "under_review")),
                    )
                )
            ).scalar_one_or_none()
            if ur is not None:
                ur.escalated_at = now
                await set_ur_state(session, ur, "escalated", note={"reason": "sla_breach"})
                c.status = "escalated"
                c.escalated_at = now
                c.version += 1
                out["escalated"] += 1
                await audit(
                    session,
                    SYSTEM,
                    "unblock.escalated",
                    "unblock_request",
                    ur.id,
                    subject_user_id=ur.user_id,
                    reason="sla_breach",
                )
            if c.sla_alerted_at is None or c.sla_alerted_at < c.sla_decision_due:
                c.sla_alerted_at = now
                await emit_event(
                    session,
                    "security.alert_raised",
                    _alert("sla_breach", case_ref=c.case_ref),
                    aggregate_type="security_case",
                    aggregate_id=c.id,
                )
        elif frac >= 0.8 and c.sla_alerted_at is None:
            c.sla_alerted_at = now
            out["alerts_80"] += 1
            await emit_event(
                session,
                "security.alert_raised",
                _alert("sla_80pct", case_ref=c.case_ref),
                aggregate_type="security_case",
                aggregate_id=c.id,
            )
    for req in (
        (
            await session.execute(
                select(ApprovalRequest).where(
                    ApprovalRequest.status == "pending",
                    ApprovalRequest.expires_at <= now,
                    ApprovalRequest.action_type == "security.case.decision",
                )
            )
        )
        .scalars()
        .all()
    ):
        req.status = "expired"
        out["approvals_expired"] += 1
        await emit_event(
            session,
            "security.alert_raised",
            _alert("approval_expired", approval_request_id=str(req.id)),
            aggregate_type="approval_request",
            aggregate_id=req.id,
        )
    for ur in (
        (
            await session.execute(
                select(UnblockRequest).where(
                    UnblockRequest.state == "info_requested", UnblockRequest.info_requested_due <= now
                )
            )
        )
        .scalars()
        .all()
    ):
        await set_ur_state(session, ur, "closed", closure="no_response")
        out["no_response"] += 1
    for ur in (
        (
            await session.execute(
                select(UnblockRequest).where(
                    UnblockRequest.state == "rejected", UnblockRequest.decided_at <= now - timedelta(days=14)
                )
            )
        )
        .scalars()
        .all()
    ):
        await set_ur_state(session, ur, "closed", closure="rejected_final")
        out["rejected_final"] += 1
    res = await session.execute(
        delete(UnblockRequest).where(
            UnblockRequest.state == "draft", UnblockRequest.updated_at <= now - timedelta(days=7)
        )
    )
    out["drafts_deleted"] = int(getattr(res, "rowcount", 0) or 0)
    for req in (
        (
            await session.execute(
                select(ApprovalRequest).where(
                    ApprovalRequest.status == "pending",
                    ApprovalRequest.action_type == "risk.kill_switch.ratify",
                    ApprovalRequest.created_at <= now - timedelta(hours=24),
                )
            )
        )
        .scalars()
        .all()
    ):
        await emit_event(
            session,
            "security.alert_raised",
            {
                "kind": "kill_switch_unratified",
                "route": "security_lead+super_admins",
                "approval_request_id": str(req.id),
            },
            aggregate_type="approval_request",
            aggregate_id=req.id,
        )
        out["ratification_pages"] += 1
    await session.flush()
    return out


async def purge_counters(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    now = now or clock.now()
    res = await session.execute(
        delete(SecurityCounter).where(SecurityCounter.bucket_start < now - timedelta(days=2))
    )
    return {"deleted": int(getattr(res, "rowcount", 0) or 0)}


async def heartbeat_batch(session: AsyncSession, now: datetime | None = None) -> dict[str, int]:
    now = now or clock.now()
    users = (
        (
            await session.execute(
                select(AuthSession.user_id)
                .where(AuthSession.last_seen_at > now - timedelta(minutes=15))
                .distinct()
            )
        )
        .scalars()
        .all()
    )
    n = await signals.run_heartbeat_batch(session, list(users), now - timedelta(days=1), now)
    return {"signals": n}


Job = Callable[[AsyncSession], Awaitable[dict[str, int]]]
JOBS: dict[str, Job] = {
    "security.decay_recompute": decay_recompute,
    "security.restriction_expiry": restriction_expiry,
    "security.sla_breach_alerts": sla_breach_alerts,
    "security.purge_counters": purge_counters,
    "security.heartbeat_batch": heartbeat_batch,
}
SCHEDULE = {
    "security.decay_recompute": "30 20 * * *",  # 02:00 IST
    "security.restriction_expiry": "*/5 * * * *",
    "security.sla_breach_alerts": "*/15 * * * *",
    "security.purge_counters": "0 * * * *",
    "security.heartbeat_batch": "*/5 * * * *",
}


async def run_job(name: str) -> dict[str, int]:
    fn = JOBS[name]
    async with get_sessionmaker()() as session, session.begin():
        await system_context(session, name.replace(".", "_"))
        result = await fn(session)
    log.info("security_job_done", job=name, **result)
    return result


def celery_beat_schedule() -> dict[str, dict[str, Any]]:
    """Entries for a Celery beat config (``app.conf.beat_schedule.update(...)``)."""
    from celery.schedules import crontab

    out: dict[str, dict[str, Any]] = {}
    for name, cron in SCHEDULE.items():
        m, h, dom, mon, dow = cron.split()
        out[name] = {
            "task": "security.run_job",
            "schedule": crontab(minute=m, hour=h, day_of_month=dom, month_of_year=mon, day_of_week=dow),
            "args": (name,),
        }
    return out


@shared_task(name="security.run_job", ignore_result=True)
def run_job_task(name: str) -> dict[str, int]:
    return run_async(run_job(name))


def register_beat() -> None:
    from celery.schedules import crontab

    for name, cron in SCHEDULE.items():
        m, h, dom, mon, dow = cron.split()
        register_periodic(
            name,
            "security.run_job",
            crontab(minute=m, hour=h, day_of_month=dom, month_of_year=mon, day_of_week=dow),
            args=(name,),
            options={"expires": 300},
        )


register_beat()


# privacy §7 ``purge_closed_cases`` (weekly; Sunday 23:00 UTC = Monday 04:30 IST). Runs on the
# ``maintenance`` queue as td_maintenance, not through ``run_job`` (td_app may not delete
# cases, notes or decisions).
PURGE_CLOSED_CASES_JOB = "security.purge_closed_cases"


@shared_task(name=retention.PURGE_CLOSED_CASES_TASK, ignore_result=True)
def purge_closed_cases_task() -> int:
    result = run_async(retention.purge_closed_cases())
    return 0 if result is None else int(result["attachment_objects_deleted"])


def register_retention_beat() -> None:
    from celery.schedules import crontab

    register_periodic(
        PURGE_CLOSED_CASES_JOB,
        retention.PURGE_CLOSED_CASES_TASK,
        crontab(minute=0, hour=23, day_of_week=0),
        options={"queue": "maintenance", "expires": 6 * 3600},
    )


register_retention_beat()


if __name__ == "__main__":  # pragma: no cover
    print(asyncio.run(run_job(sys.argv[1])))
