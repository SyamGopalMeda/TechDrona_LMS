"""Runtime switches for the VM -> Firebase move (docs/firebase/agents/platform.md).

One place decides which implementation of the VM-only pieces is used. Every default keeps the
VM stack unchanged (Redis, Celery + beat); the Firebase functions set ``TD_RUNTIME=firebase``.

==================  =========================  =============================================
Setting             Default (VM)               ``TD_RUNTIME=firebase``
==================  =========================  =============================================
``TD_CACHE_BACKEND``  ``redis``                ``firestore`` (``lms_kv``; rate limits, cache)
``TD_TASKS_BACKEND``  ``celery`` (Redis broker)  ``cloudtasks`` (task-queue functions)
==================  =========================  =============================================

An explicit ``TD_CACHE_BACKEND`` / ``TD_TASKS_BACKEND`` always wins over the runtime default.
Pure Python (no google imports): safe to import from every process.
"""

from __future__ import annotations

from typing import Literal

from app.core.config import get_settings

CacheBackend = Literal["redis", "firestore"]
TasksBackend = Literal["celery", "cloudtasks"]


def is_firebase() -> bool:
    return get_settings().TD_RUNTIME == "firebase"


def cache_backend() -> CacheBackend:
    explicit = get_settings().TD_CACHE_BACKEND
    if explicit:
        return explicit
    return "firestore" if is_firebase() else "redis"


def tasks_backend() -> TasksBackend:
    explicit = get_settings().TD_TASKS_BACKEND
    if explicit:
        return explicit
    return "cloudtasks" if is_firebase() else "celery"


def cloud_task_queues() -> dict[str, str]:
    """Celery queue name -> task-queue function name (``TD_CLOUD_TASKS_QUEUES``)."""
    out: dict[str, str] = {}
    for part in get_settings().TD_CLOUD_TASKS_QUEUES.split(","):
        q, _, fn = part.partition("=")
        if q.strip() and fn.strip():
            out[q.strip()] = fn.strip()
    return out


def all_modules_on_firestore() -> bool:
    from app.core.firestore.backend import MODULES, firestore_modules

    return set(firestore_modules()) >= MODULES


def postgres_enabled() -> bool:
    """False only on the final Firebase stack: ``TD_RUNTIME=firebase`` with every
    ``TD_STORE_<MODULE>=firestore`` (owner decision 2026-11-12: no Postgres bridge), or when no
    ``DATABASE_URL`` is configured at all. Then no engine is ever built (``app.core.db``), request
    sessions are ``None`` and readiness checks Firestore instead. Default (VM): True."""
    if not get_settings().DATABASE_URL.strip():
        return False
    return not (is_firebase() and all_modules_on_firestore())
