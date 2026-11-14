"""Measure the billed Firestore operations and CPU of the scheduled jobs (no deploy, emulator only).

    cd apps/api
    .venv/Scripts/python ../../functions-lms/tools/firestore_cost_probe.py [--mode jobs|dispatcher|both]
                                                                          [--project demo-costprobe]

* Instruments ``google.cloud.firestore`` at the gRPC (GAPIC) level, so every RPC the app makes is
  seen exactly as Firestore bills it:

  - ``RunQuery``: one read per returned document, **one read for a query that returns nothing**;
  - ``RunAggregationQuery``: one read per started 1000 index entries (counted as 1 when idle);
  - ``BatchGetDocuments`` / ``GetDocument``: one read per requested document (found or missing);
  - ``Commit`` / ``BatchWrite``: one write per write, one delete per delete (transforms are free
    when attached to a write);
  - ``BeginTransaction`` / ``Rollback``: free (counted separately for information).

* ``--mode jobs``: runs every job of ``schedules.json`` once on an idle (empty) demo project and
  prints the per-run cost; the per-minute / per-day / per-month figures follow from each job's
  cron (and, for the OLD sub-minute loops, ``repeat_seconds``: 50 s budget per minute).
* ``--mode dispatcher``: runs ``app.core.scheduler.tick`` for every minute of one simulated UTC
  day (time is simulated, nothing sleeps) and prints the real totals.

Cloud Tasks enqueues are counted (``app.core.cloudtasks.enqueue_impl`` is replaced; nothing is
sent anywhere). CPU = ``time.process_time()`` of this process (all threads, incl. gRPC).

DEMO ONLY: refuses unless the project id starts with ``demo-`` and an emulator host is set.
"""

from __future__ import annotations

import argparse
import faulthandler
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parents[1]
API = HERE.parent / "apps" / "api"
sys.path.insert(0, str(API))

COUNTS: Counter[str] = Counter()


def _env(project: str) -> None:
    if not project.startswith("demo-"):
        sys.exit("firestore_cost_probe: refusing a non demo-* project")
    os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "127.0.0.1:18080")
    os.environ["FIREBASE_PROJECT_ID"] = project
    os.environ.setdefault("APP_ENV", "test")
    os.environ["TD_RUNTIME"] = "firebase"
    os.environ["DATABASE_URL"] = ""
    os.environ["TD_TASKS_BACKEND"] = "cloudtasks"
    os.environ["TD_CACHE_BACKEND"] = "firestore"
    os.environ.setdefault("LOG_LEVEL", "ERROR")
    os.environ.setdefault("TD_CSRF_KEY", "k" * 40)
    os.environ.setdefault("TD_SERVICE_TOKEN", "s" * 48)
    from app.core.firestore.backend import MODULES

    for m in MODULES:
        os.environ[f"TD_STORE_{m.upper()}"] = "firestore"


class _CountingStream:
    """Wraps a server-streaming response: counts documents; an empty query still bills 1 read."""

    def __init__(self, inner: Any, kind: str) -> None:
        self._inner = inner
        self._it: Any = None
        self._kind = kind
        self._docs = 0
        self._done = False

    def __aiter__(self) -> _CountingStream:
        return self

    async def __anext__(self) -> Any:
        if self._it is None:
            self._it = self._inner.__aiter__()
        try:
            resp = await self._it.__anext__()
        except StopAsyncIteration:
            if not self._done:
                self._done = True
                if self._kind == "query" and self._docs == 0:
                    COUNTS["reads"] += 1
                    COUNTS["empty_queries"] += 1
            raise
        pb = getattr(resp, "_pb", resp)
        if self._kind == "query":
            if pb.HasField("document"):
                self._docs += 1
                COUNTS["reads"] += 1
        elif self._kind == "batch_get":
            if pb.HasField("found") or pb.WhichOneof("result") == "missing":
                COUNTS["reads"] += 1
        return resp

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def instrument() -> None:
    from google.cloud.firestore_v1.services.firestore.async_client import FirestoreAsyncClient as C

    if getattr(C, "_td_probe", False):
        return
    C._td_probe = True  # type: ignore[attr-defined]
    orig_rq, orig_agg, orig_bg = C.run_query, C.run_aggregation_query, C.batch_get_documents
    orig_commit, orig_get, orig_begin, orig_rb = C.commit, C.get_document, C.begin_transaction, C.rollback

    async def run_query(self: Any, *a: Any, **kw: Any) -> Any:
        COUNTS["queries"] += 1
        return _CountingStream(await orig_rq(self, *a, **kw), "query")

    async def run_aggregation_query(self: Any, *a: Any, **kw: Any) -> Any:
        COUNTS["queries"] += 1
        COUNTS["reads"] += 1
        return await orig_agg(self, *a, **kw)

    async def batch_get_documents(self: Any, *a: Any, **kw: Any) -> Any:
        COUNTS["batch_gets"] += 1
        return _CountingStream(await orig_bg(self, *a, **kw), "batch_get")

    async def get_document(self: Any, *a: Any, **kw: Any) -> Any:
        COUNTS["reads"] += 1
        return await orig_get(self, *a, **kw)

    async def commit(self: Any, *a: Any, **kw: Any) -> Any:
        req = kw.get("request") if kw.get("request") is not None else (a[0] if a else None)
        writes = getattr(req, "writes", None) or (req or {}).get("writes", []) if req is not None else []
        COUNTS["commits"] += 1
        for w in writes:
            pb = getattr(w, "_pb", None)
            if pb is not None:
                op = pb.WhichOneof("operation")
            elif isinstance(w, dict):
                op = "delete" if w.get("delete") else ("transform" if w.get("transform") else "update")
            else:
                op = "update"
            COUNTS["deletes" if op == "delete" else "writes"] += 1
        return await orig_commit(self, *a, **kw)

    async def begin_transaction(self: Any, *a: Any, **kw: Any) -> Any:
        COUNTS["transactions"] += 1
        return await orig_begin(self, *a, **kw)

    async def rollback(self: Any, *a: Any, **kw: Any) -> Any:
        COUNTS["rollbacks"] += 1
        return await orig_rb(self, *a, **kw)

    C.run_query = run_query  # type: ignore[method-assign]
    C.run_aggregation_query = run_aggregation_query  # type: ignore[method-assign]
    C.batch_get_documents = batch_get_documents  # type: ignore[method-assign]
    C.get_document = get_document  # type: ignore[method-assign]
    C.commit = commit  # type: ignore[method-assign]
    C.begin_transaction = begin_transaction  # type: ignore[method-assign]
    C.rollback = rollback  # type: ignore[method-assign]


def _wipe(project: str) -> None:
    import httpx

    host = os.environ["FIRESTORE_EMULATOR_HOST"]
    httpx.delete(f"http://{host}/emulator/v1/projects/{project}/databases/(default)/documents", timeout=30)


def _snap() -> dict[str, int]:
    return dict(COUNTS)


def _diff(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    keys = set(a) | set(b)
    return {k: b.get(k, 0) - a.get(k, 0) for k in sorted(keys) if b.get(k, 0) - a.get(k, 0)}


def _runs_per_day(cron: str) -> int:
    from datetime import UTC, datetime, timedelta

    from app.core.scheduler import cron_matches  # the dispatcher's own matcher

    start = datetime(2026, 11, 15, tzinfo=UTC)  # a Sunday: weekly entries fire once in 7 days
    n = sum(1 for m in range(7 * 1440) if cron_matches(cron, start + timedelta(minutes=m)))
    return round(n / 7) if n >= 7 else n  # weekly -> per week figure handled by caller


def measure_jobs(capp: Any) -> list[dict[str, Any]]:
    from app.core import cloudtasks

    out = []
    for entry in json.loads((HERE / "schedules.json").read_text(encoding="utf-8")):
        job = next(j for j in cloudtasks.firebase_jobs() if j.name == entry["job"])
        print(f"... {job.name}", file=sys.stderr, flush=True)
        faulthandler.dump_traceback_later(60, exit=False)
        before, cpu0, t0 = _snap(), time.process_time(), time.perf_counter()
        try:
            cloudtasks.run_task(capp, job.task, job.args, job.kwargs)
            err = None
        except Exception as e:  # report, keep measuring the rest
            err = f"{type(e).__name__}: {e}"[:160]
        cpu, wall = time.process_time() - cpu0, time.perf_counter() - t0
        faulthandler.cancel_dump_traceback_later()
        out.append(
            {
                **entry,
                "cost": _diff(before, _snap()),
                "cpu_s": round(cpu, 3),
                "wall_s": round(wall, 3),
                "error": err,
            }
        )
    return out


def old_totals(per_job: list[dict[str, Any]]) -> dict[str, Any]:
    """The previous deployment: one scheduled function per entry; sub-minute entries loop for
    ~50 s each minute (``run_periodic(budget_s=50)``)."""
    from datetime import UTC, datetime, timedelta

    from app.core.scheduler import cron_matches

    start = datetime(2026, 11, 15, tzinfo=UTC)
    day: Counter[str] = Counter()
    invocations = 0
    loop_cpu = 0.0
    for j in per_job:
        runs_week = sum(1 for m in range(7 * 1440) if cron_matches(j["cron"], start + timedelta(minutes=m)))
        invocations += runs_week
        per_call = 1
        if j.get("repeat_seconds"):
            per_call = int(50 // j["repeat_seconds"]) + 1
            loop_cpu += runs_week / 7 * 50.0  # the instance is busy ~50 s per minute (billed time)
        for k, v in j["cost"].items():
            day[k] += v * per_call * runs_week / 7
        day["cpu_s"] += j["cpu_s"] * per_call * runs_week / 7
    return {
        "per_day": {k: round(v, 1) for k, v in sorted(day.items())},
        "invocations_per_day": round(invocations / 7),
        "billed_busy_seconds_per_day_from_loops": round(loop_cpu),
    }


def measure_dispatcher(capp: Any, minutes: int) -> dict[str, Any]:
    from datetime import UTC, datetime, timedelta

    from app.core import scheduler

    start = datetime(2026, 11, 15, tzinfo=UTC)  # Sunday 00:00 UTC
    before, cpu0, t0 = _snap(), time.process_time(), time.perf_counter()
    handed_off: Counter[str] = Counter()
    ran: Counter[str] = Counter()
    skipped: Counter[str] = Counter()
    ticks_cpu: list[float] = []
    worst_reads, worst_minute = 0, ""
    for m in range(minutes):
        now = start + timedelta(minutes=m)
        b = _snap()
        res = scheduler.tick(capp, now=now)
        r = _diff(b, _snap()).get("reads", 0)
        if r > worst_reads:
            worst_reads, worst_minute = r, now.strftime("%a %H:%M")
        for name in res.handed_off:
            handed_off[name] += 1
        ran.update(res.ran)
        skipped.update(res.skipped)
        ticks_cpu.append(time.process_time())
    cpu, wall = time.process_time() - cpu0, time.perf_counter() - t0
    return {
        "minutes": minutes,
        "total": _diff(before, _snap()),
        "cpu_s": round(cpu, 2),
        "wall_s": round(wall, 2),
        "worst_minute_reads": worst_reads,
        "worst_minute": worst_minute,
        "handed_off": dict(handed_off),
        "ran": dict(sorted(ran.items())),
        "skipped": dict(sorted(skipped.items())),
        "invocations": {"scheduler": minutes, "task_queue_handoffs": sum(handed_off.values())},
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["jobs", "dispatcher", "both"], default="both")
    p.add_argument("--project", default="demo-costprobe")
    p.add_argument("--minutes", type=int, default=1440)
    p.add_argument("--json", default="")
    args = p.parse_args()
    _env(args.project)
    instrument()
    _wipe(args.project)
    from app.core import cloudtasks

    def _fake_enqueue(function: str, location: str, data: dict[str, Any], delay: float | None) -> str:
        COUNTS["cloud_tasks_enqueued"] += 1
        return f"probe-{COUNTS['cloud_tasks_enqueued']}"

    cloudtasks.enqueue_impl = _fake_enqueue
    t0 = time.process_time()
    import app.worker as worker

    capp = worker.celery_app
    report: dict[str, Any] = {"import_cpu_s": round(time.process_time() - t0, 2)}
    if args.mode in ("jobs", "both"):
        per_job = measure_jobs(capp)
        report["jobs"] = per_job
        report["old_schedule_totals"] = old_totals(per_job)
    if args.mode in ("dispatcher", "both"):
        _wipe(args.project)
        report["dispatcher"] = measure_dispatcher(capp, args.minutes)
    text = json.dumps(report, indent=2, default=str)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
