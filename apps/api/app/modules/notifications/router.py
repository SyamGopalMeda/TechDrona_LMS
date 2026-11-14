"""Notifications API (api-specification §21): NTF-01/02/03 inbox, NTF-06 batch announcement.

Preferences (NTF-04/05), templates (NTF-07..09) and the SSE stream (NTF-10) are Planned.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import any_, func, literal, select, update

from app.core.audit import audit
from app.core.auth import require_active_principal, require_permission, scope_from_path
from app.core.db import PrincipalDbSession, system_context, tenant_context
from app.core.errors import ProblemError
from app.core.firestore.backend import uses_firestore
from app.core.idempotency import IdemResult, idempotent
from app.core.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cursor, page_meta
from app.core.principal import Principal
from app.core.routing import authenticated_router
from app.core.time import to_rfc3339
from app.modules.identity import clock
from app.modules.notifications.models import Notification
from app.modules.notifications.service import notify

inbox = authenticated_router(
    prefix="/me/notifications", tags=["notifications"], route_tag="account_status", idle="neutral"
)
staff = authenticated_router(tags=["notifications"])

ANNOUNCEMENTS_PER_BATCH_PER_DAY = 3


class AnnouncementIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=2000)
    send_email: bool = False


def _out(n: Any) -> dict[str, Any]:
    return {
        "notification_id": str(n.id),
        "template_key": n.template_key,
        "category": n.category,
        "priority": n.priority,
        "data": n.data,
        "read_at": to_rfc3339(n.read_at) if n.read_at else None,
        "created_at": to_rfc3339(n.created_at),
    }


@inbox.get("")
async def list_inbox(
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
    unread_only: bool = False,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
) -> dict[str, Any]:
    if uses_firestore("notifications"):
        from app.modules.notifications.repo_firestore import NotificationRow, user_repo

        repo = user_repo(principal)
        page = await repo.inbox(principal.user_id, unread_only=unread_only, cursor=cursor, limit=limit)
        return {
            "data": [_out(NotificationRow.of(d.data)) for d in page.items],
            "unread_count": await repo.unread_count(principal.user_id),
            "page": page.meta(),
        }
    q = select(Notification).where(
        Notification.user_id == principal.user_id, literal("in_app") == any_(Notification.channels)
    )
    if unread_only:
        q = q.where(Notification.read_at.is_(None))
    if cursor:
        pos = decode_cursor(cursor)
        try:
            q = q.where(Notification.id < uuid.UUID(str(pos["id"])))
        except (KeyError, ValueError) as e:
            raise ProblemError("invalid_cursor") from e
    rows = list((await session.execute(q.order_by(Notification.id.desc()).limit(limit + 1))).scalars())
    more = len(rows) > limit
    rows = rows[:limit]
    unread = (
        await session.execute(
            select(func.count()).where(
                Notification.user_id == principal.user_id,
                Notification.read_at.is_(None),
                literal("in_app") == any_(Notification.channels),
            )
        )
    ).scalar_one()
    return {
        "data": [_out(n) for n in rows],
        "unread_count": unread,
        "page": page_meta({"id": str(rows[-1].id)} if more and rows else None, limit),
    }


@inbox.post("/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID,
    session: PrincipalDbSession,
    principal: Principal = Depends(require_active_principal),
) -> dict[str, Any]:
    if uses_firestore("notifications"):
        from app.modules.notifications.repo_firestore import user_repo

        read_at = await user_repo(principal).mark_read(principal.user_id, notification_id, clock.now())
        if read_at is None:
            raise ProblemError("not_found")
        return {"notification_id": str(notification_id), "read_at": to_rfc3339(read_at)}
    n = (
        await session.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == principal.user_id
            )
        )
    ).scalar_one_or_none()
    if n is None:
        raise ProblemError("not_found")
    if n.read_at is None:
        n.read_at = clock.now()
    return {"notification_id": str(n.id), "read_at": to_rfc3339(n.read_at)}


@inbox.post("/read-all")
async def mark_all_read(
    session: PrincipalDbSession, principal: Principal = Depends(require_active_principal)
) -> dict[str, Any]:
    if uses_firestore("notifications"):
        from app.modules.notifications.repo_firestore import user_repo

        return {"marked": await user_repo(principal).mark_all_read(principal.user_id, clock.now())}
    r = await session.execute(
        update(Notification)
        .where(Notification.user_id == principal.user_id, Notification.read_at.is_(None))
        .values(read_at=clock.now())
    )
    return {"marked": int(getattr(r, "rowcount", 0) or 0)}


@staff.post("/batches/{batch_id}/announcements", status_code=201)
async def batch_announcement(
    batch_id: uuid.UUID,
    body: AnnouncementIn,
    request: Request,
    session: PrincipalDbSession,
    principal: Principal = Depends(
        require_permission("notification.batch_announce", scope=scope_from_path("batch_id", "batch"))
    ),
) -> Any:
    from app.modules.identity import public as identity
    from app.modules.orgs import public as orgs

    async def op() -> IdemResult:
        b = await orgs.get_batch(session, batch_id)
        if b is None:
            raise ProblemError("not_found")
        # active student members joined to their user rows (inner join)
        bms = await orgs.batch_members(session, batch_ids=[batch_id], member_role="student")
        users = await identity.get_users(session, [m.user_id for m in bms])
        members = [
            (m.user_id, users[m.user_id].email, users[m.user_id].is_minor) for m in bms if m.user_id in users
        ]
        # Fan-out writes other users' inbox rows: named system job, then back to the principal.
        await system_context(session, "notifications.batch_announce")
        since = clock.now() - timedelta(days=1)
        sent_today = await _announcements_since(session, batch_id, since)
        if sent_today >= ANNOUNCEMENTS_PER_BATCH_PER_DAY:
            raise ProblemError(
                "rate_limited",
                headers={"Retry-After": "3600"},
                detail="A batch can receive at most 3 announcements per day.",
            )
        announcement_id = uuid.uuid4().hex
        channels = ("in_app", "email") if body.send_email else ("in_app",)
        for uid, email, is_minor in members:
            await notify(
                session,
                uid,
                "batch.announcement",
                category="learning",
                organization_id=b.organization_id,
                channels=channels,
                data={"batch_id": str(batch_id), "title": body.title, "body": body.body},
                dedupe_key=f"ann:{announcement_id}",
                is_minor=is_minor,
                email_to=email,
                email_subject=body.title,
                email_text=body.body,
            )
        await tenant_context(session, principal)
        await audit(
            session,
            principal,
            "notification.batch_announced",
            "batch",
            batch_id,
            organization_id=b.organization_id,
            after={"recipients": len(members)},
        )
        return IdemResult(status=201, body={"recipients": len(members), "announcement_id": announcement_id})

    return await idempotent(request, session, user_id=principal.user_id, operation=op, required=False)


async def _announcements_since(session: Any, batch_id: uuid.UUID, since: Any) -> int:
    """Distinct announcements to one batch since ``since`` (the per-day cap), either store."""
    if uses_firestore("notifications"):
        from app.modules.notifications.repo_firestore import system_repo

        return await system_repo("notifications.batch_announce").distinct_dedupe_keys_since(
            "batch.announcement", str(batch_id), since
        )
    return int(
        (
            await session.execute(
                select(func.count(func.distinct(Notification.dedupe_key))).where(
                    Notification.template_key == "batch.announcement",
                    Notification.data["batch_id"].astext == str(batch_id),
                    Notification.created_at > since,
                )
            )
        ).scalar_one()
    )


router = APIRouter()
router.include_router(inbox)
router.include_router(staff)
