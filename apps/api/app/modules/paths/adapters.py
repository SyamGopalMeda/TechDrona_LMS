"""What paths needs from other modules (orgs, identity, learning, assessments).

Every read goes through the owning module's ``public.py`` (each runs on Postgres or Firestore per
that module's own ``TD_STORE_*``), so paths itself touches no foreign table. Where the service
ran the lookup inside a named system context on Postgres (``paths.members`` / ``paths.names``),
the call is still wrapped in it on Postgres; without a Postgres session there is no RLS to lift
(``_system``).
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import AsyncGenerator, Iterable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.company import COMPANY_ORG_ID


def like_pattern(q: str | None) -> str:
    """The escaped ``ILIKE`` pattern the service builds (``%q%``)."""
    return "%" + (q or "").replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


@contextlib.asynccontextmanager
async def _system(session: AsyncSession, job: str) -> AsyncGenerator[None]:
    if not session:  # None / NO_POSTGRES: no RLS context to switch
        yield
        return
    from app.core.db import system_context

    async with system_context(session, job):
        yield


# --------------------------------------------------------------------------- orgs


async def batch_exists(session: AsyncSession, batch_id: uuid.UUID) -> bool:
    from app.modules.orgs import public as orgs

    return await orgs.get_batch(session, batch_id) is not None


async def existing_batch_ids(session: AsyncSession, batch_ids: Iterable[uuid.UUID]) -> set[uuid.UUID]:
    from app.modules.orgs import public as orgs

    return set(await orgs.get_batches(session, batch_ids))


async def batch_name(session: AsyncSession, batch_id: uuid.UUID) -> str | None:
    from app.modules.orgs import public as orgs

    return (await orgs.batch_names(session, [batch_id])).get(batch_id)


async def active_batches(session: AsyncSession, only: set[uuid.UUID] | None) -> list[dict[str, Any]]:
    """Active batches by name (``only``: restrict to these ids; empty set = none)."""
    from app.modules.orgs import public as orgs

    rows = await orgs.list_batches(session, status="active", ids=only, order="name")
    return [{"id": b.id, "name": b.name, "code": b.code} for b in rows]


async def active_batch_students(
    session: AsyncSession, batch_ids: set[uuid.UUID], user_ids: list[uuid.UUID]
) -> set[uuid.UUID]:
    """Of ``user_ids``, the active student members of any of ``batch_ids``."""
    from app.modules.orgs import public as orgs

    if not batch_ids or not user_ids:
        return set()
    async with _system(session, "paths.members"):
        rows = await orgs.batch_members(
            session, batch_ids=batch_ids, user_ids=user_ids, member_role="student"
        )
    return {m.user_id for m in rows}


async def batch_students(session: AsyncSession, batch_id: uuid.UUID) -> list[uuid.UUID]:
    from app.modules.orgs import public as orgs

    return [m.user_id for m in await orgs.batch_members(session, batch_ids=[batch_id], member_role="student")]


async def student_batch_ids(session: AsyncSession, user_id: uuid.UUID) -> set[uuid.UUID]:
    """Batches where ``user_id`` is an active student (the learner's allocation targets)."""
    from app.modules.orgs import public as orgs

    return {m.batch_id for m in await orgs.batch_members(session, user_ids=[user_id], member_role="student")}


async def active_member_of_batches(
    session: AsyncSession, user_id: uuid.UUID, batch_ids: Iterable[uuid.UUID]
) -> bool:
    from app.modules.orgs import public as orgs

    return bool(await orgs.batch_members(session, user_ids=[user_id], batch_ids=list(batch_ids)))


async def active_company_members(session: AsyncSession, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    from app.modules.orgs import public as orgs

    async with _system(session, "paths.members"):
        rows = await orgs.org_memberships(session, user_ids=user_ids, organization_id=COMPANY_ORG_ID)
    return {m.user_id for m in rows}


# --------------------------------------------------------------------------- identity


async def user_names(session: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[str, str]]:
    """``{user_id: (full_name, email)}`` (system context ``paths.names`` on Postgres)."""
    from app.modules.identity import public as identity

    if not user_ids:
        return {}
    async with _system(session, "paths.names"):
        cards = await identity.user_cards(session, user_ids)
    return {u: (c.full_name or "", c.email or "") for u, c in cards.items()}


async def batch_people(
    session: AsyncSession, batch_id: uuid.UUID, q: str | None, *, search_email: bool
) -> list[tuple[uuid.UUID, str | None, str | None]]:
    """Active student members of a batch as ``(user_id, email, full_name)``, ordered by name then
    email (nulls last, as Postgres sorts), at most 500; ``q`` matches the name (and the email when
    ``search_email``) case-insensitively."""
    from app.modules.identity import public as identity
    from app.modules.orgs import public as orgs

    async with _system(session, "paths.members"):
        members = await orgs.batch_members(session, batch_ids=[batch_id], member_role="student")
        cards = await identity.user_cards(session, [m.user_id for m in members])
    needle = (q or "").lower()
    rows: list[tuple[uuid.UUID, str | None, str | None]] = []
    for m in members:
        c = cards.get(m.user_id)
        if c is None:  # inner join on users
            continue
        if needle:
            in_email = search_email and needle in (c.email or "").lower()
            hit = needle in (c.full_name or "").lower() or in_email
            if not hit:
                continue
        rows.append((m.user_id, c.email, c.full_name))
    # ORDER BY full_name, email: Postgres collation (en_US.utf8) with NULLS LAST
    from app.core.firestore.collation import sort_rows

    rows = sort_rows(rows, [(lambda r: r[2], False), (lambda r: r[1], False)])
    return rows[:500]


# --------------------------------------------------------------------------- learning


async def assignment_in_org(session: AsyncSession, assignment_id: uuid.UUID, org_id: uuid.UUID) -> bool:
    from app.modules.learning import public as learning

    return await learning.assignment_in_org(session, assignment_id, org_id)


async def assignment_options(
    session: AsyncSession, org_id: uuid.UUID, q: str | None
) -> list[tuple[Any, ...]]:
    from app.modules.learning import public as learning

    return list(await learning.assignment_link_options(session, org_id, q, 25))


async def assignment_released(session: AsyncSession, assignment_id: uuid.UUID) -> bool:
    from app.modules.learning import public as learning

    return await learning.assignment_grades_released_at(session, assignment_id) is not None


async def graded_submissions(
    session: AsyncSession, assignment_id: uuid.UUID, user_id: uuid.UUID | None
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """``(user_id, submission_id)`` of graded submissions (one user when ``user_id``)."""
    from app.modules.learning import public as learning

    return list(await learning.graded_submissions(session, assignment_id, user_id))


# --------------------------------------------------------------------------- assessments


async def test_in_org(session: AsyncSession, test_id: uuid.UUID, org_id: uuid.UUID) -> bool:
    from app.modules.assessments import public as assessments

    return await assessments.test_linkable(session, test_id, org_id)


async def test_options(session: AsyncSession, org_id: uuid.UUID, q: str | None) -> list[tuple[Any, ...]]:
    from app.modules.assessments import public as assessments

    return list(await assessments.search_tests(session, org_id, q, 25))


async def attempt_outcome(session: AsyncSession, attempt_id: uuid.UUID) -> tuple[Any, ...] | None:
    """``(user_id, test_id, integrity_status, passed, pass_percentage)`` of a scored attempt."""
    from app.modules.assessments import public as assessments

    return await assessments.attempt_scored_facts(session, attempt_id)
