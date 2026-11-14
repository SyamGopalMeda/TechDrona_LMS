"""Firestore repository for the support desk (``TD_STORE_SUPPORT=firestore``).

``service.py`` / ``router.py`` / ``privacy.py`` dispatch here when the switch is on; the HTTP
contract is unchanged. Rows come back as ``TicketRow`` / ``MessageRow`` / ``NoteRow`` with the
attribute names and Python types of the ORM models, so the route code and serializers are shared.

**Authorization (replacing RLS).** The repository is built from the caller's Postgres
transaction scope (``app.core.db.rls_scope``: ``app.user_id`` / ``app.is_platform``) and applies
the Postgres policy of each table to it: tickets and messages are visible when
``requester_id = app.user_id() OR app.is_platform()`` (others answer ``None``, no existence
oracle); notes are platform-only. Reads and writes then go through a named system
job. Every route permission and lane check stays in the router (``ticket.*``, ``user.read``).

**Unit of work (replacing ``SELECT ... FOR UPDATE``).** A loaded ticket keeps the document it was
read from. Route code mutates the row and queues messages (``add_message``) exactly as with the
ORM; ``save`` then commits the changed fields of every touched ticket plus the new messages in
one transaction, after checking that no ticket changed since it was loaded (optimistic lock: a
lost race answers 409 ``conflict`` instead of waiting on a row lock).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, fields
from datetime import datetime
from typing import Any

from app.core.db import RlsScope
from app.core.errors import ProblemError
from app.core.firestore.repository import FirestoreRepository, platform_only
from app.core.firestore.store import Doc, Order, ScopedStore, ScopedTransaction
from app.core.ids import uuid7
from app.modules.support.store_specs import (
    COUNTERS,
    MESSAGES,
    NOTES,
    TICKET_SEQ,
    TICKET_UUIDS,
    TICKETS,
)

PLATFORM = "support.platform"  # held by no role: only the platform branch (system job) passes
_PAGE = 200


def _uuid(v: Any) -> uuid.UUID | None:
    return uuid.UUID(str(v)) if v else None


def _store_value(v: Any) -> Any:
    return str(v) if isinstance(v, uuid.UUID) else v


# --------------------------------------------------------------------------- rows


@dataclass
class TicketRow:
    id: uuid.UUID
    ticket_number: str
    requester_id: uuid.UUID
    category: str
    subject: str
    body: str
    organization_id: uuid.UUID | None = None
    status: str = "open"
    priority: str = "normal"
    assigned_to: uuid.UUID | None = None
    related_order_id: uuid.UUID | None = None
    related_case_id: uuid.UUID | None = None
    related_unblock_request_id: uuid.UUID | None = None
    privacy_request_id: uuid.UUID | None = None
    is_grievance: bool = False
    escalated_to: str | None = None
    merged_into_id: uuid.UUID | None = None
    context: dict[str, Any] = field(default_factory=dict)
    first_response_due_at: datetime | None = None
    resolution_due_at: datetime | None = None
    first_responded_at: datetime | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    last_message_at: datetime | None = None
    csat_score: int | None = None
    csat_comment: str | None = None
    csat_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    # unit of work (not persisted)
    _loaded: dict[str, Any] | None = field(default=None, repr=False, compare=False)
    _new_messages: list[MessageRow] = field(default_factory=list, repr=False, compare=False)

    @classmethod
    def of(cls, d: dict[str, Any]) -> TicketRow:
        kw: dict[str, Any] = {f.name: d.get(f.name) for f in fields(cls) if not f.name.startswith("_")}
        kw["id"] = uuid.UUID(d["id"])
        for k in TICKET_UUIDS:
            kw[k] = _uuid(d.get(k))
        kw["context"] = dict(d.get("context") or {})
        kw["is_grievance"] = bool(d.get("is_grievance"))
        row = cls(**kw)
        row._loaded = dict(d)
        return row

    def doc(self) -> dict[str, Any]:
        return {
            f.name: _store_value(getattr(self, f.name))
            for f in fields(self)
            if not f.name.startswith("_") and f.name != "updated_at"
        } | {"id": str(self.id)}

    def changes(self) -> dict[str, Any]:
        cur, old = self.doc(), self._loaded or {}
        return {k: v for k, v in cur.items() if k not in ("id", "created_at") and old.get(k) != v}


@dataclass
class MessageRow:
    id: uuid.UUID
    support_ticket_id: uuid.UUID
    author_kind: str
    body: str
    requester_id: uuid.UUID | None = None
    organization_id: uuid.UUID | None = None
    author_id: uuid.UUID | None = None
    visibility: str = "public"
    attachments: list[Any] = field(default_factory=list)
    redacted_at: datetime | None = None
    created_at: datetime | None = None

    @classmethod
    def of(cls, d: dict[str, Any]) -> MessageRow:
        return cls(
            id=uuid.UUID(d["id"]),
            support_ticket_id=uuid.UUID(d["support_ticket_id"]),
            requester_id=_uuid(d.get("requester_id")),
            organization_id=_uuid(d.get("organization_id")),
            author_id=_uuid(d.get("author_id")),
            author_kind=d["author_kind"],
            visibility=d.get("visibility") or "public",
            body=d.get("body") or "",
            attachments=list(d.get("attachments") or []),
            redacted_at=d.get("redacted_at"),
            created_at=d.get("created_at"),
        )

    def doc(self) -> dict[str, Any]:
        return {f.name: _store_value(getattr(self, f.name)) for f in fields(self)}


@dataclass
class NoteRow:
    id: uuid.UUID
    user_id: uuid.UUID
    author_id: uuid.UUID
    body: str
    support_ticket_id: uuid.UUID | None = None
    created_at: datetime | None = None

    @classmethod
    def of(cls, d: dict[str, Any]) -> NoteRow:
        return cls(
            id=uuid.UUID(d["id"]),
            user_id=uuid.UUID(d["user_id"]),
            author_id=uuid.UUID(d["author_id"]),
            body=d["body"],
            support_ticket_id=_uuid(d.get("support_ticket_id")),
            created_at=d.get("created_at"),
        )


# --------------------------------------------------------------------------- repository


class SupportRepo(FirestoreRepository):
    """Built per call from the caller's Postgres RLS scope (see the module docstring)."""

    def __init__(self, store: ScopedStore, scope: RlsScope) -> None:
        super().__init__(store)
        self.scope = scope

    def _visible(self, d: Doc | None) -> bool:
        return d is not None and self.scope.allows(d.get("requester_id"))

    def _require_platform(self) -> None:
        if not self.scope.is_platform:
            raise ProblemError("not_found")  # platform-only tables: invisible, as under RLS

    # ------------------------------------------------------------------ tickets: reads

    async def get_ticket(self, user_id: uuid.UUID | None, ticket_id: uuid.UUID) -> TicketRow | None:
        """``user_id``: unused marker of the RLS-scoped read (the scope decides visibility)."""
        d = await self.store.get(TICKETS, str(ticket_id))
        return TicketRow.of(d.data) if d is not None and self._visible(d) else None

    async def tickets_of(
        self,
        user_id: uuid.UUID,
        *,
        status: str | None = None,
        cursor: str | None = None,
        limit: int = 50,
        order: Order = ("id", "desc"),
    ) -> tuple[list[TicketRow], str | None]:
        if not self.scope.allows(user_id):
            return [], None
        filters: list[Any] = [("status", "==", status)] if status else []
        page = await self.store.query(
            TICKETS,
            user_id=user_id,
            filters=filters,
            order_by=(order,),
            limit=limit,
            cursor=cursor,
        )
        return [TicketRow.of(d.data) for d in page.items], page.next_cursor

    async def count_tickets_since(self, user_id: uuid.UUID, since: datetime) -> int:
        if not self.scope.allows(user_id):
            return 0
        return await self.store.count(TICKETS, user_id=user_id, filters=(("created_at", ">", since),))

    @platform_only(PLATFORM)
    async def lane_tickets(self, statuses: Iterable[str]) -> list[TicketRow]:
        """Every ticket in ``statuses`` (the queue filters the lane, the search and the SLA order
        in memory: single company, bounded open queue)."""
        self._require_platform()
        st = list(statuses)
        filters: list[Any] = [("status", "in", st)] if len(st) > 1 else [("status", "==", st[0])]
        return [TicketRow.of(d.data) for d in await self._all(TICKETS, filters)]

    @platform_only(PLATFORM)
    async def resolved_before(self, cutoff: datetime, limit: int) -> list[TicketRow]:
        self._require_platform()
        page = await self.store.query(
            TICKETS,
            filters=(("status", "==", "resolved"), ("resolved_at", "<=", cutoff)),
            order_by=(("resolved_at", "asc"),),
            limit=limit,
        )
        return [TicketRow.of(d.data) for d in page.items]

    async def _all(self, coll: str, filters: list[Any], user_id: uuid.UUID | None = None) -> list[Doc]:
        out: list[Doc] = []
        cursor: str | None = None
        while True:
            page = await self.store.query(
                coll, user_id=user_id, filters=filters, order_by=(), limit=_PAGE, cursor=cursor
            )
            out += page.items
            if not page.next_cursor:
                return out
            cursor = page.next_cursor

    # ------------------------------------------------------------------ messages

    async def message_counts(
        self, user_id: uuid.UUID | None, ticket_ids: list[uuid.UUID], *, internal: bool
    ) -> dict[uuid.UUID, int]:
        out: dict[uuid.UUID, int] = {}
        for tid in ticket_ids:
            filters: list[Any] = [("support_ticket_id", "==", str(tid))]
            if not internal:
                filters.append(("visibility", "==", "public"))
            n = await self.store.count(MESSAGES, filters=filters)
            if n:
                out[tid] = n
        return out

    async def thread(self, user_id: uuid.UUID | None, t: TicketRow, *, internal: bool) -> list[MessageRow]:
        if not self.scope.allows(t.requester_id):
            return []
        filters: list[Any] = [("support_ticket_id", "==", str(t.id))]
        if not internal:
            filters.append(("visibility", "==", "public"))
        rows = [MessageRow.of(d.data) for d in await self._all(MESSAGES, filters)]
        return sorted(rows, key=lambda m: (m.created_at or datetime.min, str(m.id)))

    async def get_message(
        self, user_id: uuid.UUID | None, t: TicketRow, message_id: uuid.UUID
    ) -> MessageRow | None:
        d = await self.store.get(MESSAGES, str(message_id))
        if d is None or not self._visible(d) or d.get("support_ticket_id") != str(t.id):
            return None
        return MessageRow.of(d.data)

    async def count_messages_by_author_since(self, user_id: uuid.UUID, since: datetime) -> int:
        """Messages written by ``user_id`` since ``since`` on tickets the scope sees."""
        if self.scope.is_platform:
            return await self.store.count(
                MESSAGES, filters=(("author_id", "==", str(user_id)), ("created_at", ">", since))
            )
        if not self.scope.allows(user_id):
            return 0
        return await self.store.count(
            MESSAGES, user_id=user_id, filters=(("author_id", "==", str(user_id)), ("created_at", ">", since))
        )

    # ------------------------------------------------------------------ writes (unit of work)

    async def insert_ticket(self, user_id: uuid.UUID, t: TicketRow, number: Any) -> TicketRow:
        """Insert ``t`` with the next gap-free ticket number (``number(n) -> str``), one transaction."""
        if not self.scope.allows(user_id) or t.requester_id != user_id:
            raise ProblemError("permission_denied")

        async def fn(tx: ScopedTransaction) -> TicketRow:
            n = await tx.next_sequence(TICKET_SEQ, collection=COUNTERS)
            t.ticket_number = number(n)
            stored = await tx.create(TICKETS, t.doc(), doc_id=str(t.id))
            for m in t._new_messages:
                await tx.create(MESSAGES, m.doc(), doc_id=str(m.id))
            return TicketRow.of(stored.data)

        saved = await self.store.run_transaction(fn)
        _refresh(t, saved)
        return t

    async def save(self, user_id: uuid.UUID | None, tickets: Iterable[TicketRow]) -> None:
        """Commit changed fields + queued messages of ``tickets`` atomically (optimistic lock)."""
        todo = [t for t in {id(t): t for t in tickets}.values() if t.changes() or t._new_messages]
        for t in todo:
            if not self.scope.allows(t.requester_id):
                raise ProblemError("not_found")
        if not todo:
            return

        async def fn(tx: ScopedTransaction) -> list[Doc]:
            current = []
            for t in todo:
                cur = await tx.get(TICKETS, str(t.id))
                if cur is None:
                    raise ProblemError("not_found")
                if cur.get("updated_at") != (t._loaded or {}).get("updated_at"):
                    raise ProblemError("conflict")
                current.append(cur)
            saved = []
            for t, cur in zip(todo, current, strict=True):
                ch = t.changes()
                saved.append(await tx.update_read(TICKETS, cur, ch) if ch else cur)
                for m in t._new_messages:
                    await tx.create(MESSAGES, m.doc(), doc_id=str(m.id))
            return saved

        for t, d in zip(todo, await self.store.run_transaction(fn), strict=True):
            t._new_messages.clear()
            _refresh(t, TicketRow.of(d.data))

    @platform_only(PLATFORM)
    async def patch_ticket(self, ticket_id: uuid.UUID, changes: dict[str, Any]) -> None:
        """Direct field update (system jobs and tests); no optimistic check."""
        self._require_platform()
        await self.store.update(TICKETS, str(ticket_id), {k: _store_value(v) for k, v in changes.items()})

    @platform_only(PLATFORM)
    async def patch_messages(self, ticket_id: uuid.UUID, changes: dict[str, Any]) -> int:
        self._require_platform()
        docs = await self._all(MESSAGES, [("support_ticket_id", "==", str(ticket_id))])
        for d in docs:
            await self.store.update(MESSAGES, d.id, {k: _store_value(v) for k, v in changes.items()})
        return len(docs)

    # ------------------------------------------------------------------ user notes (platform)

    @platform_only(PLATFORM)
    async def notes_for(self, subject_id: uuid.UUID, limit: int) -> list[NoteRow]:
        self._require_platform()
        page = await self.store.query(
            NOTES,
            filters=(("user_id", "==", str(subject_id)),),
            order_by=(("created_at", "desc"),),
            limit=limit,
        )
        return [NoteRow.of(d.data) for d in page.items]

    @platform_only(PLATFORM)
    async def count_notes(self, subject_id: uuid.UUID) -> int:
        self._require_platform()
        return await self.store.count(NOTES, filters=(("user_id", "==", str(subject_id)),))

    @platform_only(PLATFORM)
    async def add_note(self, note: NoteRow) -> NoteRow:
        self._require_platform()
        data = {
            "id": str(note.id),
            "user_id": str(note.user_id),
            "author_id": str(note.author_id),
            "support_ticket_id": _store_value(note.support_ticket_id),
            "body": note.body,
        }
        stored = await self.store.create(NOTES, data, doc_id=str(note.id))
        return NoteRow.of(stored.data)

    # ------------------------------------------------------------------ erasure (DB-01)

    async def erase_user(
        self, user_id: uuid.UUID, *, subject: str, body: str, now: datetime
    ) -> dict[str, int]:
        """Same minimisation as the Postgres provider; idempotent."""
        if not self.scope.is_platform:
            raise ProblemError("not_found")
        own = await self._all(TICKETS, [], user_id=user_id)
        own_ids = {d.id for d in own}
        msgs: dict[str, Doc] = {}
        for d in await self._all(MESSAGES, [("author_id", "==", str(user_id))]):
            msgs[d.id] = d
        for d in await self._all(MESSAGES, [], user_id=user_id):
            if d.get("support_ticket_id") in own_ids and d.get("attachments"):
                msgs[d.id] = d
        redacted = 0
        for d in msgs.values():
            if d.get("redacted_at") is None:
                await self.store.update(MESSAGES, d.id, {"body": body, "attachments": [], "redacted_at": now})
                redacted += 1
        minimised = 0
        for d in own:
            if d.get("subject") != subject:
                changes: dict[str, Any] = {
                    "subject": subject,
                    "body": body,
                    "context": {},
                    "csat_comment": None,
                }
                await self.store.update(TICKETS, d.id, changes)
                minimised += 1
        return {"tickets_minimised": minimised, "messages_redacted": redacted}

    # ------------------------------------------------------------------ dashboard (admin)

    @platform_only(PLATFORM)
    async def open_tickets(self, statuses: Iterable[str]) -> list[TicketRow]:
        return await self.lane_tickets(statuses)


def _refresh(t: TicketRow, saved: TicketRow) -> None:
    for f in fields(t):
        if not f.name.startswith("_"):
            setattr(t, f.name, getattr(saved, f.name))
    t._loaded = saved._loaded


def new_message(t: TicketRow, **kw: Any) -> MessageRow:
    return MessageRow(
        id=uuid7(),
        support_ticket_id=t.id,
        requester_id=t.requester_id,
        organization_id=t.organization_id,
        **kw,
    )


def repo(scope: RlsScope, job: str = "support.desk") -> SupportRepo:
    return SupportRepo(ScopedStore.system(job), scope)
