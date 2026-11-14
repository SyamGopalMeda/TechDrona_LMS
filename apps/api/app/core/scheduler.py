"""One dispatcher for every periodic job on Firebase (``lmsScheduler``, every minute, UTC).

Replaces the per-entry ``lmsJob*`` scheduled functions (Cloud Scheduler bills per job beyond 3 per
billing account, and every function invocation cost a cold Python import). ``tick(capp, at)`` runs
every beat entry whose cron (``cloudtasks.cron_for``, the cadence the old functions had) matches the
minute ``at``:

* ``maintenance``-queue entries are handed to the ``lmsTasksMaintenance`` task-queue function
  (540 s budget, one at a time) with ``periodic=<job>``: a failure is logged, not retried -- the
  old scheduled function did exactly that.
* Everything else runs inline, one after the other. Once ``INLINE_BUDGET_S`` of the tick is spent,
  the remaining due entries are handed to their queue's task function instead (never skipped).
* Overlap: like the old functions, nothing stops two minutes' runs of a long job from overlapping;
  the jobs keep their own guards (leases, ``FOR UPDATE``/claims, idempotent writes).

**Event mode** (``event_mode()``: Cloud Tasks backend and no Postgres -- the final Firebase stack):

* The sub-minute entries (``core.outbox_relay`` 5 s, ``core.audit_seal`` 2 s,
  ``assessments.deadline_sweeper`` 5 s) no longer loop ~50 s per minute. They are kicked by the
  writes that create their work (``app.core.jobhints``) and run here once a minute as a backstop.
* Entries in ``GATES`` are skipped while provably idle: after a run, the gate decides whether the job
  has nothing to do now *and* can only get work through a new write to one of its ``watch``
  collections (a ``limit(1)`` existence query, or the run's own result). The dispatcher records
  ``idle.<job> = S`` (the tick's read time) on the hint document; later ticks skip the job until a
  hint shows a write to a watched collection (``w.<c> >= S - SKIP_MARGIN``). Each gated job still
  runs in full once an hour (``BACKSTOP_EVERY_MIN``, at a per-job minute), so a missed hint delays
  work by at most 60 minutes and never loses it. A gate's ``fingerprint`` (e.g. the relay's
  ``TD_OUTBOX_MAX_ATTEMPTS``) invalidates the idle verdict when configuration changes.
* An idle minute costs one billed read (the hint document) plus the ungated jobs' own queries.

Outside event mode (VM: not used at all; hybrid Firebase + Postgres): no gates, no kicks; the
sub-minute entries are handed to ``lmsTasksCritical`` each minute and loop for 50 s exactly like
the old scheduled functions did (``cloudtasks.run_periodic``).
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import cache
from typing import Any

import structlog

log = structlog.get_logger("app.scheduler")

INLINE_BUDGET_S = 45.0
BACKSTOP_EVERY_MIN = 60
LOOP_BUDGET_S = 50.0

# --------------------------------------------------------------------------- cron


_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _field(spec: str, lo: int, hi: int) -> frozenset[int]:
    out: set[int] = set()
    for part in spec.split(","):
        base, _, step_s = part.partition("/")
        step = int(step_s) if step_s else 1
        if step <= 0:
            raise ValueError(f"bad cron step in {spec!r}")
        if base == "*":
            a, b = lo, hi
        elif "-" in base:
            a_s, _, b_s = base.partition("-")
            a, b = int(a_s), int(b_s)
        else:
            a = int(base)
            b = hi if step_s else a
        if a < lo or b > hi or a > b:
            raise ValueError(f"cron value out of range in {spec!r}")
        out.update(range(a, b + 1, step))
    return frozenset(out)


@cache
def _parsed(cron: str) -> tuple[frozenset[int], ...]:
    fields = cron.split()
    if len(fields) != 5:
        raise ValueError(f"cron needs 5 fields: {cron!r}")
    minute, hour, dom, month, dow = (_field(f, lo, hi) for f, (lo, hi) in zip(fields, _RANGES, strict=True))
    return minute, hour, dom, month, frozenset(0 if d == 7 else d for d in dow)


def cron_matches(cron: str, at: datetime) -> bool:
    """Standard 5-field cron (Cloud Scheduler / Vixie semantics) evaluated in UTC."""
    minute, hour, dom, month, dow = _parsed(cron)
    at = at.astimezone(UTC) if at.tzinfo else at
    if at.minute not in minute or at.hour not in hour or at.month not in month:
        return False
    fields = cron.split()
    cron_dow = (at.weekday() + 1) % 7  # Python Monday=0 -> cron Sunday=0
    dom_any, dow_any = fields[2] == "*", fields[4] == "*"
    if dom_any and dow_any:
        return True
    if dom_any:
        return cron_dow in dow
    if dow_any:
        return at.day in dom
    return at.day in dom or cron_dow in dow  # both restricted: either matches


def floor_minute(at: datetime) -> datetime:
    at = at.astimezone(UTC) if at.tzinfo else at.replace(tzinfo=UTC)
    return at.replace(second=0, microsecond=0)


# --------------------------------------------------------------------------- entries


@dataclass(frozen=True, slots=True)
class Entry:
    job: str
    task: str
    cron: str
    repeat: float | None
    queue: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)


def entries() -> list[Entry]:
    """Every beat entry + Firebase-only job (the same list ``schedules.json`` holds)."""
    import importlib

    from app.core.cloudtasks import cron_for, firebase_jobs

    # The beat entries are registered when the task modules load (``app.worker``). The scheduler
    # function imports it, but the API function does not: a job kick from a request (jobhints)
    # then found no entries ("unknown periodic job") and the request's commit failed.
    importlib.import_module("app.worker")

    out = []
    for j in firebase_jobs():
        cron, repeat = cron_for(j.schedule)
        queue = (j.options or {}).get("queue", "default")
        out.append(Entry(j.name, j.task, cron, repeat, queue, tuple(j.args), dict(j.kwargs)))
    return out


def entry_for(job: str) -> Entry:
    e = next((x for x in entries() if x.job == job), None)
    if e is None:
        raise LookupError(f"unknown periodic job {job!r}")
    return e


def due_entries(at: datetime, all_entries: list[Entry] | None = None) -> list[Entry]:
    at = floor_minute(at)
    return [e for e in (all_entries if all_entries is not None else entries()) if cron_matches(e.cron, at)]


def event_mode() -> bool:
    from app.core.runtime import postgres_enabled, tasks_backend

    return tasks_backend() == "cloudtasks" and not postgres_enabled()


# --------------------------------------------------------------------------- gates


IdleCheck = Callable[[Any, Any], Awaitable[bool]]


@dataclass(frozen=True)
class Gate:
    watch: tuple[str, ...]
    idle: IdleCheck  # (firestore client, run result) -> True when provably idle
    on_skip: Callable[[], Awaitable[None]] | None = None  # bookkeeping an idle run would do
    fingerprint: Callable[[], str] | None = None


async def _exists(client: Any, collection: str, filters: tuple[tuple[str, str, Any], ...]) -> bool:
    from app.core.firestore.jobstate import exists

    return await exists(client, collection, filters)


def _none_of(collection: str, *filters: tuple[str, str, Any]) -> IdleCheck:
    async def check(client: Any, _result: Any) -> bool:
        return not await _exists(client, collection, tuple(filters))

    return check


def _result_is(key: str, value: Any) -> IdleCheck:
    async def check(_client: Any, result: Any) -> bool:
        return isinstance(result, dict) and result.get(key) == value

    return check


async def _sessions_seen_recently(client: Any, _result: Any) -> bool:
    from app.core.time import utcnow

    # heartbeat_batch reads sessions with last_seen_at >= now - 15 min; none now -> none until a
    # session is touched again (a write to auth_sessions).
    return not await _exists(
        client, "auth_sessions", (("last_seen_at", ">=", utcnow() - timedelta(minutes=15)),)
    )


async def _relay_idle(client: Any, _result: Any) -> bool:
    from app.core.config import get_settings
    from app.core.firestore.jobstate import outbox_has_work

    return not await outbox_has_work(client, get_settings().TD_OUTBOX_MAX_ATTEMPTS)


def _relay_fp() -> str:
    from app.core.config import get_settings

    return f"max_attempts={get_settings().TD_OUTBOX_MAX_ATTEMPTS}"


async def _judge_idle(client: Any, _result: Any) -> bool:
    from app.modules.coding.judge_gateway import judge_enabled

    # JUDGE_PROVIDER=disabled: process_pending returns at once and queued rows can only move once
    # the judge is enabled again (a config change: ``_judge_fp`` invalidates this verdict).
    if not judge_enabled():
        return True
    return not await _exists(client, "code_submissions", (("status", "in", ["queued", "running"]),))


def _judge_fp() -> str:
    from app.modules.coding.judge_gateway import judge_enabled

    return f"judge_enabled={judge_enabled()}"


def _analytics_idle_state(job: str, result: dict[str, Any]) -> Callable[[], Awaitable[None]]:
    async def touch() -> None:
        from app.modules.analytics.fs_raw import record_idle_run

        await record_idle_run(job, result)

    return touch


GATES: dict[str, Gate] = {
    "admin.break_glass_expiry": Gate(
        ("break_glass_sessions",), _none_of("break_glass_sessions", ("status", "==", "active"))
    ),
    "analytics.exports_sweep": Gate(
        ("export_jobs",), _none_of("export_jobs", ("status", "in", ["ready", "awaiting_approval", "running"]))
    ),
    "analytics.interval_builder": Gate(
        ("analytics_batches", "engagement_intervals"),
        _result_is("page_instances", 0),
        on_skip=_analytics_idle_state("interval_builder", {"page_instances": 0, "intervals": 0}),
    ),
    "analytics.video_coverage": Gate(
        ("analytics_batches",),
        _result_is("assets", 0),
        on_skip=_analytics_idle_state("video_coverage", {"assets": 0}),
    ),
    "assessments.deadline_sweeper": Gate(
        ("test_attempts", "attempt_sections", "tests"),
        _none_of("test_attempts", ("status", "==", "in_progress")),
    ),
    "coding.process_pending": Gate(("code_submissions",), _judge_idle, fingerprint=_judge_fp),
    "commerce.webhook_retry": Gate(
        ("payment_webhook_events",), _none_of("payment_webhook_events", ("status", "==", "received"))
    ),
    "commerce.refund_submit_retry": Gate(("refunds",), _none_of("refunds", ("status", "==", "approved"))),
    "commerce.order_expiry": Gate(
        ("orders",), _none_of("orders", ("status", "in", ["created", "pending_payment"]))
    ),
    "core.audit_seal": Gate(("audit_outbox",), _none_of("audit_outbox")),
    "core.outbox_relay": Gate(("outbox_events",), _relay_idle, fingerprint=_relay_fp),
    "learning.certificate_outbox_send": Gate(
        ("certificate_outbox",), _none_of("certificate_outbox", ("status", "==", "pending"))
    ),
    "placement.media_scan_sweep": Gate(
        ("question_media",), _none_of("question_media", ("scan_status", "==", "pending"))
    ),
    "security.heartbeat_batch": Gate(("auth_sessions",), _sessions_seen_recently),
    "security.restriction_expiry": Gate(
        ("account_restrictions",),
        # ``ended_at == None`` as in the job's own query: a lifted L3 row is no work, and without
        # it the gate stayed busy forever once any L3 sharing restriction had existed.
        _none_of(
            "account_restrictions", ("level", "==", 3), ("family", "==", "sharing"), ("ended_at", "==", None)
        ),
    ),
}


@cache
def _watched() -> frozenset[str]:
    return frozenset(c for g in GATES.values() for c in g.watch)


def watched_collections() -> frozenset[str]:
    return _watched()


def _step_minutes(cron: str) -> int | None:
    """``* * * * *`` -> 1, ``*/N * * * *`` -> N; anything else is not gated."""
    m, *rest = cron.split()
    if rest != ["*", "*", "*", "*"]:
        return None
    if m == "*":
        return 1
    if m.startswith("*/") and 60 % int(m[2:]) == 0:
        return int(m[2:])
    return None


def backstop_minute(job: str, cron: str) -> int:
    """Minute of the hour at which a gated job always runs in full (matches its cron)."""
    step = _step_minutes(cron) or 1
    slots = BACKSTOP_EVERY_MIN // step
    h = int(hashlib.sha256(job.encode()).hexdigest()[:8], 16)
    return (h % slots) * step


def is_backstop(job: str, cron: str, at: datetime) -> bool:
    return floor_minute(at).minute == backstop_minute(job, cron)


# --------------------------------------------------------------------------- hint state


@dataclass
class HintState:
    read_time: datetime
    written: dict[str, datetime] = field(default_factory=dict)
    idle: dict[str, dict[str, Any]] = field(default_factory=dict)


def _ts(v: Any) -> datetime | None:
    return v if isinstance(v, datetime) else None


async def read_state(client: Any) -> HintState:
    from app.core.firestore.jobstate import read_hints
    from app.core.time import utcnow

    d, rt = await read_hints(client)
    rt = rt or utcnow()
    return HintState(
        rt,
        {k: t for k, v in (d.get("w") or {}).items() if (t := _ts(v)) is not None},
        {k: v for k, v in (d.get("idle") or {}).items() if isinstance(v, dict)},
    )


def should_skip(e: Entry, gate: Gate, state: HintState, at: datetime) -> bool:
    from app.core.jobhints import SKIP_MARGIN

    rec = state.idle.get(e.job)
    since = _ts((rec or {}).get("at"))
    if since is None or is_backstop(e.job, e.cron, at):
        return False
    if gate.fingerprint is not None and rec is not None and rec.get("fp") != gate.fingerprint():
        return False
    for c in gate.watch:
        w = state.written.get(c)
        if w is not None and w >= since - SKIP_MARGIN:
            return False
    return True


# --------------------------------------------------------------------------- tick


@dataclass
class TickResult:
    at: datetime
    ran: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    handed_off: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def _client() -> Any:
    from app.core.firestore.store import ScopedStore

    return ScopedStore.system("core.scheduler").client


async def _plan(due: list[Entry], at: datetime) -> tuple[HintState, set[str]]:
    client = _client()
    state = await read_state(client)
    skip: set[str] = set()
    for e in due:
        gate = GATES.get(e.job)
        if gate is not None and _step_minutes(e.cron) and should_skip(e, gate, state, at):
            skip.add(e.job)
            if gate.on_skip is not None:
                try:
                    await gate.on_skip()
                except Exception as ex:  # bookkeeping failed: run the job for real instead
                    log.warning("scheduler_skip_bookkeeping_failed", job=e.job, error=type(ex).__name__)
                    skip.discard(e.job)
    return state, skip


async def _finish(state: HintState, outcomes: list[tuple[Entry, bool, Any]]) -> None:
    from app.core.firestore.jobstate import delete_marker, merge_hints

    client = _client()
    idle: dict[str, Any] = {}
    for e, ok, result in outcomes:
        gate = GATES[e.job]
        verdict = False
        if ok:
            try:
                verdict = await gate.idle(client, result)
            except Exception as ex:
                log.warning("scheduler_idle_check_failed", job=e.job, error=type(ex).__name__)
        if verdict:
            rec: dict[str, Any] = {"at": state.read_time}
            if gate.fingerprint is not None:
                rec["fp"] = gate.fingerprint()
            prev = state.idle.get(e.job) or {}
            if prev.get("fp") != rec.get("fp") or _ts(prev.get("at")) is None or _dirty(e, gate, state):
                idle[e.job] = rec
        elif e.job in state.idle:
            idle[e.job] = delete_marker()
    if idle:
        await merge_hints(client, {"idle": idle})


def _dirty(e: Entry, gate: Gate, state: HintState) -> bool:
    from app.core.jobhints import SKIP_MARGIN

    since = _ts((state.idle.get(e.job) or {}).get("at"))
    if since is None:
        return True
    return any((w := state.written.get(c)) is not None and w >= since - SKIP_MARGIN for c in gate.watch)


def _handoff(e: Entry, *, loop: bool = False) -> None:
    from app.core import cloudtasks

    cloudtasks.send_task(e.task, e.args, e.kwargs, queue=e.queue, periodic=e.job, periodic_loop=loop)


def tick(capp: Any, now: datetime | None = None, *, inline_budget_s: float = INLINE_BUDGET_S) -> TickResult:
    """Run every entry due at the minute of ``now`` (default: the current UTC minute)."""
    from app.core.cloudtasks import run_task
    from app.core.jobs import run_async
    from app.core.time import utcnow

    at = floor_minute(now or utcnow())
    res = TickResult(at)
    due = due_entries(at)
    gating = event_mode()
    critical_first = sorted(due, key=lambda e: (e.queue != "critical", e.job))
    state: HintState | None = None
    skip: set[str] = set()
    if gating and any(e.job in GATES for e in due):
        try:
            state, skip = run_async(_plan(due, at))
        except Exception as ex:  # hints unavailable: run everything (never skip on doubt)
            log.warning("scheduler_hints_unavailable", error=type(ex).__name__)
            state, skip = None, set()
    started = time.monotonic()
    outcomes: list[tuple[Entry, bool, Any]] = []
    for e in critical_first:
        if e.job in skip:
            res.skipped.append(e.job)
            continue
        loop = not gating and e.repeat is not None
        if e.queue == "maintenance" or loop or time.monotonic() - started > inline_budget_s:
            try:
                _handoff(e, loop=loop)
                res.handed_off.append(e.job)
            except Exception as ex:  # last resort: run it here rather than lose the run
                log.error("scheduler_handoff_failed", job=e.job, error=type(ex).__name__)
                _run_inline(capp, e, res, outcomes, run_task)
            continue
        _run_inline(capp, e, res, outcomes, run_task)
    gated = [o for o in outcomes if o[0].job in GATES]
    if gating and state is not None and gated:
        try:
            run_async(_finish(state, gated))
        except Exception as ex:
            log.warning("scheduler_hint_update_failed", error=type(ex).__name__)
    if res.failed or res.handed_off:
        (log.error if res.failed else log.info)(
            "scheduler_tick_failures" if res.failed else "scheduler_tick",
            at=at.isoformat(),
            ran=len(res.ran),
            skipped=len(res.skipped),
            handed_off=res.handed_off,
            failed=res.failed,
        )
    return res


def _run_inline(
    capp: Any, e: Entry, res: TickResult, outcomes: list[tuple[Entry, bool, Any]], run_task: Any
) -> None:
    try:
        result = run_task(capp, e.task, e.args, e.kwargs)
        res.ran.append(e.job)
        outcomes.append((e, True, result))
    except Exception:  # like a beat tick whose task failed: next run retries -- but say so loudly
        log.exception("periodic_job_failed", job=e.job, task=e.task)
        res.failed.append(e.job)
        outcomes.append((e, False, None))
