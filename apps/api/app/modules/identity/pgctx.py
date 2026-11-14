"""Postgres-context helpers that tolerate a stack without Postgres.

On the final Firebase stack (``runtime.postgres_enabled()`` False) request sessions are
``NO_POSTGRES`` (falsy; any use raises). Routes of the access modules still call
``system_context`` for the benefit of other modules' Postgres reads in the same request; these
helpers make that a no-op when there is no Postgres session.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from app.core.db import as_system, system_context


async def sys_ctx(session: Any, job: str) -> None:
    """``await system_context(session, job)`` when there is a Postgres session."""
    if session:
        await system_context(session, job)


def sys_scope(session: Any, job: str) -> Any:
    """``async with sys_scope(session, job):`` = ``as_system`` with Postgres, else a no-op."""
    return as_system(session, job) if session else nullcontext(session)
