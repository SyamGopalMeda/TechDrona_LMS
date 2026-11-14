"""Firestore queries for structured assignments (``structured.py`` / ``structured_api.py``).

Only called on the Firestore branch (``fs_store.fs()``). Every query here is an equality / ``in``
/ single ``array-contains`` filter without ``order_by`` (no composite index needed beyond the
learning fragment): result sets are per assignment / submission / user and are sorted in memory
with the same keys as the Postgres ``ORDER BY`` (UUID order == lowercase-hex string order).

Also: the assignment-id sets that replace the SQL sub-select filters of ``structured``
(``allocated_to_learner_filter`` / ``allocated_to_batches_filter`` / ``evaluator_filter``) for
callers in ``router.py``.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.modules.learning import fs_store as fss
from app.modules.learning.fs_rows import as_dt
from app.modules.learning.models import (
    AssignmentAllocation,
    AssignmentItem,
    AssignmentItemResponse,
    AssignmentRegradeRequest,
    AssignmentSection,
    AssignmentSubmission,
)

_MIN = datetime.min.replace(tzinfo=UTC)
_MAX = datetime.max.replace(tzinfo=UTC)


def chunks(ids: Iterable[Any], n: int = 30) -> list[list[Any]]:
    lst = list(dict.fromkeys(ids))
    return [lst[i : i + n] for i in range(0, len(lst), n)]


def nulls_last(dt: datetime | None) -> datetime:
    return dt if dt is not None else _MAX


def nulls_first(dt: datetime | None) -> datetime:
    return dt if dt is not None else _MIN


async def find_in(
    session: AsyncSession | None, model: type[Any], field: str, values: Iterable[Any], *extra: Any
) -> list[Any]:
    out: list[Any] = []
    for part in chunks(values):
        out += await fss.find(session, model, filters=((field, "in", part), *extra))
    return out


# --------------------------------------------------------------------------- structure


async def sections_of(session: AsyncSession | None, assignment_id: uuid.UUID) -> list[AssignmentSection]:
    rows = await fss.find(session, AssignmentSection, filters=(("assignment_id", "==", assignment_id),))
    return sorted(rows, key=lambda s: (s.position, str(s.id)))


async def items_of(session: AsyncSession | None, assignment_id: uuid.UUID) -> list[AssignmentItem]:
    rows = await fss.find(session, AssignmentItem, filters=(("assignment_id", "==", assignment_id),))
    return sorted(rows, key=lambda it: (it.position, str(it.id)))


async def allocations_of(
    session: AsyncSession | None, assignment_id: uuid.UUID
) -> list[AssignmentAllocation]:
    return await fss.find(session, AssignmentAllocation, filters=(("assignment_id", "==", assignment_id),))


async def submissions_of(
    session: AsyncSession | None, assignment_id: uuid.UUID, *, user_id: uuid.UUID | None = None
) -> list[AssignmentSubmission]:
    filters: list[Any] = [("assignment_id", "==", assignment_id)]
    if user_id is not None:
        filters.append(("user_id", "==", user_id))
    return await fss.find(session, AssignmentSubmission, filters=filters)


async def responses_of(
    session: AsyncSession | None, submission_ids: Iterable[uuid.UUID]
) -> list[AssignmentItemResponse]:
    return await find_in(session, AssignmentItemResponse, "submission_id", submission_ids)


async def regrades_of(
    session: AsyncSession | None,
    *,
    assignment_id: uuid.UUID | None = None,
    submission_id: uuid.UUID | None = None,
) -> list[AssignmentRegradeRequest]:
    filters: list[Any] = []
    if assignment_id is not None:
        filters.append(("assignment_id", "==", assignment_id))
    if submission_id is not None:
        filters.append(("submission_id", "==", submission_id))
    return await fss.find(session, AssignmentRegradeRequest, filters=filters)


async def response_for(
    session: AsyncSession | None, submission_id: uuid.UUID, item_id: uuid.UUID
) -> AssignmentItemResponse | None:
    from app.modules.learning import store_specs as ss

    rid = await fss.key_target(ss.RESPONSE_KEYS, ss.response_key(submission_id, item_id))
    return await fss.get(session, AssignmentItemResponse, rid) if rid else None


async def touch(obj: Any) -> None:
    """Stamp ``updated_at`` of an already-persisted row (Postgres: the caller's
    ``obj.updated_at = now`` + flush; ``fs_store`` diffs ignore ``updated_at``)."""
    t = fss.table(type(obj))
    d = await fss.store().update(t.collection, t.doc_id(obj), {})
    stamped = as_dt(d.data.get("updated_at"))
    if stamped is not None:
        obj.updated_at = stamped


# --------------------------------------------------------------------------- visibility sets


def _visible(al: AssignmentAllocation, now: datetime) -> bool:
    return (
        al.status == "active"
        and (al.visible_from is None or al.visible_from <= now)
        and (al.visible_until is None or al.visible_until >= now)
    )


async def _targeting(
    session: AsyncSession | None, user_id: uuid.UUID, batches: set[uuid.UUID]
) -> list[AssignmentAllocation]:
    rows = {
        al.id: al
        for al in await fss.find(
            session, AssignmentAllocation, filters=(("user_ids", "array-contains", user_id),)
        )
    }
    if batches:
        for al in await find_in(session, AssignmentAllocation, "batch_id", batches):
            rows[al.id] = al
    return list(rows.values())


async def learner_assignment_ids(
    session: AsyncSession | None, user_id: uuid.UUID, batches: set[uuid.UUID], now: datetime | None = None
) -> set[uuid.UUID]:
    """``structured.allocated_to_learner_filter``: assignments allocated to the learner (batch or
    explicit list) that are visible now, or that the learner already handed in."""
    now = now or utcnow()
    allocs = await _targeting(session, user_id, batches)
    out = {al.assignment_id for al in allocs if _visible(al, now)}
    rest = {al.assignment_id for al in allocs} - out
    if rest:
        handed = await fss.find(
            session,
            AssignmentSubmission,
            filters=(("user_id", "==", user_id),),
            where=lambda s: s.status != "draft",
        )
        out |= rest & {s.assignment_id for s in handed}
    return out


async def batch_assignment_ids(session: AsyncSession | None, batches: set[uuid.UUID]) -> set[uuid.UUID]:
    """``structured.allocated_to_batches_filter``."""
    if not batches:
        return set()
    return {al.assignment_id for al in await find_in(session, AssignmentAllocation, "batch_id", batches)}


async def evaluator_assignment_ids(session: AsyncSession | None, user_id: uuid.UUID) -> set[uuid.UUID]:
    """``structured.evaluator_filter``."""
    rows = await fss.find(
        session, AssignmentAllocation, filters=(("evaluator_ids", "array-contains", user_id),)
    )
    return {al.assignment_id for al in rows}


# --------------------------------------------------------------------------- graders (rbac API)


async def grade_role_holders(session: AsyncSession, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Users with a live grant of a role holding ``assignment.grade`` (any scope): rbac's public API."""
    from app.modules.rbac import public as rbac_public

    return await rbac_public.user_ids_with_permission(session, "assignment.grade", user_ids)
