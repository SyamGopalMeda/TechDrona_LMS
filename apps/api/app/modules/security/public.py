"""Public, store-neutral API of the security module (data-ops agent).

Other modules import only this file from ``security``. Functions take the caller's Postgres
``session`` (used for the Postgres store and for identity/sessions side effects); on
``TD_STORE_SECURITY=firestore`` the security rows are read from Firestore.

* Step-up / permission helpers: ``require_fresh_step_up``, ``P5``, ``S10``, ``make_ref``.
* Restriction state: ``restriction_state`` (sessions hook), ``active_restrictions``,
  ``restriction_out``, ``apply_restriction``, ``end_restriction``.
* Read helpers for admin / support / privacy: ``restricted_users_by_level``, ``open_case_count``,
  ``user_restrictions``, ``user_unblock_requests``, ``get_unblock_request``.
* Engine/cases entry points used by assessments integrity: ``open_case``, ``case_note``.
* Retention: ``evidence_holds`` (held users / cases of the evidence purge).
* Signals wiring: ``report_event``, ``EngagedBucket``, ``register_engaged_bucket_feed``.
"""

from __future__ import annotations

import uuid
from typing import Any

from app.core.firestore.backend import uses_firestore
from app.modules.security.cases import case_note
from app.modules.security.engine import open_case
from app.modules.security.policies import P5, S10, require_fresh_step_up
from app.modules.security.refs import make_ref
from app.modules.security.restrictions import (
    active_restrictions,
    apply_restriction,
    end_restriction,
    restriction_out,
    restriction_state,
)
from app.modules.security.signals import EngagedBucket, register_engaged_bucket_feed, report_event

__all__ = [
    "P5",
    "S10",
    "EngagedBucket",
    "active_restrictions",
    "apply_restriction",
    "case_note",
    "end_restriction",
    "evidence_holds",
    "get_unblock_request",
    "make_ref",
    "open_case",
    "open_case_count",
    "pending_unblock_attachment_keys",
    "register_engaged_bucket_feed",
    "report_event",
    "require_fresh_step_up",
    "restricted_users_by_level",
    "restriction_out",
    "restriction_state",
    "set_unblock_attachment_scan",
    "user_restrictions",
    "user_unblock_requests",
]


async def evidence_holds(
    session: Any, user_ids: Any, case_ids: Any = ()
) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """Retention hold of security evidence (``maint.purge_expired_rows``, privacy §7): the users
    among ``user_ids`` with a case that is not closed or is on legal hold, and the cases among
    ``case_ids`` that are not closed or are on legal hold. Their signals / evaluations are kept."""
    users = [uuid.UUID(str(u)) for u in dict.fromkeys(user_ids) if u is not None]
    cases = [uuid.UUID(str(c)) for c in dict.fromkeys(case_ids) if c is not None]
    if uses_firestore("security"):
        from app.modules.security.repo_fs_engine import held_subjects

        return await held_subjects(users, cases)
    from sqlalchemy import or_, select

    from app.modules.security.models import SecurityCase

    held = or_(SecurityCase.status != "closed", SecurityCase.legal_hold.is_(True))
    hu: set[uuid.UUID] = set()
    hc: set[uuid.UUID] = set()
    if users:
        q = select(SecurityCase.user_id).where(SecurityCase.user_id.in_(users), held)
        hu = set((await session.execute(q)).scalars())
    if cases:
        q = select(SecurityCase.id).where(SecurityCase.id.in_(cases), held)
        hc = set((await session.execute(q)).scalars())
    return hu, hc


def _repo() -> Any:
    from app.modules.security.repo_firestore import system_repo

    return system_repo("security.public")


async def restricted_users_by_level(session: Any) -> dict[int, int]:
    """Active restrictions: level -> number of distinct, not-deleted users (admin dashboard)."""
    if uses_firestore("security"):
        from app.modules.security.adapters import non_deleted_user_ids

        by_level = await _repo().level_counts()
        alive = await non_deleted_user_ids(session, list({u for s in by_level.values() for u in s}))
        return {lvl: len(users & alive) for lvl, users in sorted(by_level.items()) if users & alive}
    from sqlalchemy import select

    from app.modules.security.adapters import non_deleted_user_ids
    from app.modules.security.models import AccountRestriction

    # Postgres: the active rows of this module, then identity.public for the users' status
    # (was a JOIN on ``users``); same counts: distinct, not-deleted users per level.
    pairs = (
        await session.execute(
            select(AccountRestriction.level, AccountRestriction.user_id).where(
                AccountRestriction.ended_at.is_(None)
            )
        )
    ).all()
    by_lvl: dict[int, set[Any]] = {}
    for lvl, uid in pairs:
        by_lvl.setdefault(int(lvl), set()).add(uid)
    live = await non_deleted_user_ids(session, list({u for us in by_lvl.values() for u in us}))
    return {lvl: len(us & live) for lvl, us in sorted(by_lvl.items()) if us & live}


async def open_case_count(session: Any) -> int:
    if uses_firestore("security"):
        return int(await _repo().open_case_count())
    from sqlalchemy import func, select

    from app.modules.security.models import SecurityCase

    q = (
        select(func.count())
        .select_from(SecurityCase)
        .where(SecurityCase.status.not_in(("decided", "closed")))
    )
    return int((await session.execute(q)).scalar_one())


async def user_restrictions(session: Any, user_id: uuid.UUID, *, active_only: bool = False) -> list[Any]:
    """The user's restriction rows (ORM-compatible attributes). ``active_only`` sorts by level
    desc, then ``starts_at`` desc (the support account panel order)."""
    if uses_firestore("security"):
        rows = list(await _repo().restrictions_for_user(user_id, active_only=active_only))
    else:
        from sqlalchemy import select

        from app.modules.security.models import AccountRestriction as AR

        q = select(AR).where(AR.user_id == user_id)
        if active_only:
            q = q.where(AR.ended_at.is_(None))
        rows = list((await session.execute(q)).scalars())
    if active_only:
        rows.sort(key=lambda r: (-int(r.level), -r.starts_at.timestamp()))
    return rows


async def user_unblock_requests(session: Any, user_id: uuid.UUID) -> list[Any]:
    if uses_firestore("security"):
        return list(await _repo().unblock_requests_for_user(user_id))
    from sqlalchemy import select

    from app.modules.security.models import UnblockRequest

    return list(
        (await session.execute(select(UnblockRequest).where(UnblockRequest.user_id == user_id))).scalars()
    )


async def get_unblock_request(session: Any, request_id: uuid.UUID) -> Any | None:
    if uses_firestore("security"):
        return await _repo().get_unblock(request_id)
    from app.modules.security.models import UnblockRequest

    return await session.get(UnblockRequest, request_id)


# --------------------------------------------------------------------------- INV-12 (media scan job)


async def set_unblock_attachment_scan(session: Any, s3_key: str, result: str) -> int:
    """Set ``scan_status`` of the *pending* unblock-request attachment stored under ``s3_key``
    (``clean`` / ``infected``). Returns the number of requests holding that key (the Postgres
    ``UPDATE ... WHERE attachments @> [{s3_key}]`` row count). Caller supplies system context."""
    if uses_firestore("security"):
        return int(await _repo().set_attachment_scan(s3_key, result))
    from sqlalchemy import text

    res = await session.execute(
        text(
            """
            UPDATE unblock_requests
               SET attachments = (
                     SELECT jsonb_agg(
                              CASE WHEN a->>'s3_key' = :k AND a->>'scan_status' = 'pending'
                                   THEN a || jsonb_build_object('scan_status', CAST(:r AS text))
                                   ELSE a END
                              ORDER BY ord)
                       FROM jsonb_array_elements(attachments) WITH ORDINALITY AS t(a, ord))
             WHERE attachments @> jsonb_build_array(jsonb_build_object('s3_key', CAST(:k AS text)))
            """
        ),
        {"k": s3_key, "r": result},
    )
    return int(getattr(res, "rowcount", 0) or 0)


async def pending_unblock_attachment_keys(session: Any, limit: int) -> list[str]:
    """S3 keys of unblock-request attachments still ``pending`` a scan, by request id."""
    if uses_firestore("security"):
        return list(await _repo().pending_attachment_keys(limit))
    from sqlalchemy import text

    rows = await session.execute(
        text(
            """
            SELECT a->>'s3_key'
              FROM unblock_requests, jsonb_array_elements(attachments) AS a
             WHERE a->>'scan_status' = 'pending' AND a->>'s3_key' IS NOT NULL
             ORDER BY unblock_requests.id
             LIMIT :n
            """
        ),
        {"n": limit},
    )
    return list(rows.scalars())
