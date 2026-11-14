"""RLS context for the Firestore repositories of placement / assessments / coding.

On Postgres the policies read the transaction GUCs (``tenant_context`` / ``system_context``).
On the Firebase stack there is no Postgres (the request session is ``db.NO_POSTGRES``), so the
same values come from here:

* ``bind_principal``: a router dependency that records the request's principal in a context
  variable (async dependency: it runs in the request task, so the endpoint sees the value);
* ``system_scope(session, job)``: ``async with``; on Postgres it is ``db.system_context``, without
  Postgres it marks the block as platform scope (the same effect on the RLS predicate);
* ``current_scope()``: ``(user_id, org_ids, is_platform, org_staff)`` for ``Visibility``.

``org_staff`` mirrors ``app.caller_is_org_staff()`` (orgs_0004): a live non-student role grant
on an organization or batch, or an active ``staff`` membership in one of the caller's orgs.

``app/modules/coding/rls.py`` is a copy (coding may not import placement): keep them identical.
"""

from __future__ import annotations

import contextvars
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends

from app.core.auth import require_active_principal
from app.core.principal import Principal

_principal: contextvars.ContextVar[Principal | None] = contextvars.ContextVar(
    "td_rls_principal", default=None
)
_system: contextvars.ContextVar[bool] = contextvars.ContextVar("td_rls_system", default=False)

STUDENT_ROLES = frozenset({"student", "learner"})


async def bind_principal(principal: Principal = Depends(require_active_principal)) -> None:
    _principal.set(principal)


def set_principal(principal: Principal | None) -> contextvars.Token[Principal | None]:
    """For callers outside a request (jobs, tests)."""
    return _principal.set(principal)


@asynccontextmanager
async def system_scope(session: Any, job: str) -> AsyncIterator[Any]:
    if session:
        from app.core.db import system_context

        async with system_context(session, job):
            yield session
        return
    token = _system.set(True)
    try:
        yield session
    finally:
        _system.reset(token)


def in_system_scope() -> bool:
    return _system.get()


async def current_scope() -> tuple[str, frozenset[str], bool, bool]:
    if _system.get():
        return "", frozenset(), True, True
    p = _principal.get()
    if p is None:
        return "", frozenset(), False, False
    orgs = frozenset(str(o) for o in p.org_ids)
    staff = any(g.role not in STUDENT_ROLES and g.scope_type in ("organization", "batch") for g in p.grants)
    if not staff and orgs:
        try:
            from app.modules.orgs import public as orgs_public

            ms = await orgs_public.org_memberships(None, user_ids=[p.user_id], member_type="staff")  # type: ignore[arg-type]
            staff = any(str(m.organization_id) in orgs for m in ms)
        except Exception:  # pragma: no cover - orgs on Postgres without a session
            staff = False
    return str(p.user_id), orgs, bool(p.is_platform), staff


def no_postgres(session: Any) -> bool:
    """No Postgres behind ``session``: ``db.NO_POSTGRES`` (falsy) / ``None``, or the SQL engine's
    ``MemoryTx`` (keeps the RLS GUCs in memory, refuses other SQL)."""
    return not session or memory_gucs(session) is not None


def memory_gucs(session: Any) -> dict[str, str] | None:
    """The in-memory RLS GUCs of the SQL engine's ``MemoryTx``, else ``None`` (also for
    ``db.NO_POSTGRES``, whose attribute access raises)."""
    try:
        guc = session.__dict__.get("guc") if session is not None and hasattr(session, "__dict__") else None
    except Exception:  # pragma: no cover - defensive
        return None
    return guc if isinstance(guc, dict) else None
