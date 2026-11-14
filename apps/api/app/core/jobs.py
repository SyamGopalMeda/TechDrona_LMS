"""Periodic job registry for Celery beat (``app.worker`` builds ``beat_schedule`` from it).

Modules declare tasks in ``app/modules/<m>/tasks.py`` with ``celery.shared_task`` and register
their schedule at import time::

    from celery import shared_task
    from celery.schedules import crontab
    from app.core.jobs import register_periodic, run_async

    @shared_task(name="catalog.reindex")
    def reindex() -> None:
        run_async(_reindex())

    register_periodic("catalog.reindex.nightly", "catalog.reindex", crontab(hour=2, minute=0))

``schedule``: seconds (``float``), ``timedelta`` or a ``celery.schedules`` object (crontab).
``task`` is a registered task name or a task object. Every ``run_async`` call gets a fresh
event loop, so it disposes the process-wide engine (``app.core.db.get_sessionmaker``) and the
Redis clients when the coroutine finishes: task bodies may use ``get_sessionmaker()`` freely.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Coroutine, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any


@dataclass(frozen=True)
class PeriodicJob:
    name: str
    task: str
    schedule: Any
    args: tuple[Any, ...] = ()
    kwargs: Mapping[str, Any] = field(default_factory=dict)
    options: Mapping[str, Any] = field(default_factory=dict)


_jobs: dict[str, PeriodicJob] = {}


def _task_name(task: Any) -> str:
    if isinstance(task, str):
        return task
    name = getattr(task, "name", None)
    if not isinstance(name, str) or not name:
        raise TypeError("task must be a task name or a Celery task object")
    return name


def register_periodic(
    name: str,
    task: Any,
    schedule: float | timedelta | Any,
    *,
    args: tuple[Any, ...] = (),
    kwargs: Mapping[str, Any] | None = None,
    options: Mapping[str, Any] | None = None,
) -> PeriodicJob:
    """Register (or replace, by ``name``) a beat entry. ``options`` are Celery apply options
    such as ``{"queue": "maintenance", "expires": 60}``."""
    if isinstance(schedule, int | float) and schedule <= 0:
        raise ValueError("schedule must be positive")
    job = PeriodicJob(name, _task_name(task), schedule, tuple(args), dict(kwargs or {}), dict(options or {}))
    _jobs[name] = job
    return job


def unregister_periodic(name: str) -> None:
    _jobs.pop(name, None)


def periodic_jobs() -> tuple[PeriodicJob, ...]:
    return tuple(_jobs[k] for k in sorted(_jobs))


def beat_schedule() -> dict[str, dict[str, Any]]:
    """Celery ``beat_schedule`` mapping for every registered job."""
    out: dict[str, dict[str, Any]] = {}
    for j in periodic_jobs():
        entry: dict[str, Any] = {"task": j.task, "schedule": j.schedule}
        if j.args:
            entry["args"] = j.args
        if j.kwargs:
            entry["kwargs"] = dict(j.kwargs)
        if j.options:
            entry["options"] = dict(j.options)
        out[j.name] = entry
    return out


def run_async[T](coro: Coroutine[Any, Any, T]) -> T:
    """Run an async job body from a (sync) Celery task. Pooled connections are bound to the
    loop that created them, so the shared engine/Redis clients are released before the loop
    closes (the next task builds new ones on its own loop)."""

    async def _run() -> T:
        try:
            return await coro
        finally:
            from app.core.db import dispose_engine
            from app.core.redis import close_redis

            await dispose_engine()
            await close_redis()
            if "app.core.firestore.client" in sys.modules:  # its gRPC channel is loop-bound too
                from app.core.firestore import lifecycle

                await lifecycle.close()

    return asyncio.run(_run())
