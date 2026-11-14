"""Support on Firestore (P2b, docs/firebase/p2.md): backfill/verify (including the number
sequences), gap-free ticket numbers under concurrency, the RLS predicate of each
table (requester-or-platform; platform-only notes), the optimistic lock that replaces
``SELECT ... FOR UPDATE``, the repository scope lint and the index declarations.

HTTP-level parity is covered by the existing support tests run through the ``support_backend``
matrix fixture."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text

from app.core.db import RlsScope, system_context
from app.core.errors import ProblemError
from app.core.firestore.repository import assert_repository_scoped
from app.core.ids import uuid7
from app.modules.identity import clock
from tests.firestore.matrix import activate_firestore
from tests.security.helpers import adult
from tests.support.test_audit_fixes import _student, body

PLATFORM = RlsScope("", True)


@pytest.fixture
async def fs(request: pytest.FixtureRequest, db: Any, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[None]:
    restore = await activate_firestore(request, db, monkeypatch, ("support",))
    try:
        yield
    finally:
        await restore()


def _repo(scope: RlsScope = PLATFORM) -> Any:
    from app.modules.support.repo_firestore import repo

    return repo(scope, "test.support")


def _ticket(requester: uuid.UUID, **kw: Any) -> Any:
    from app.modules.support.repo_firestore import TicketRow

    now = clock.now()
    return TicketRow(
        id=uuid7(),
        ticket_number="",
        requester_id=requester,
        category="technical",
        subject="Video does not play",
        body="The lesson video stays black after pressing play.",
        created_at=now,
        last_message_at=now,
        **kw,
    )


def test_repository_is_principal_or_platform_scoped() -> None:
    from app.modules.support.repo_firestore import SupportRepo

    assert_repository_scoped(SupportRepo)


async def test_backfill_from_postgres_verifies_clean_with_sequences(
    request: pytest.FixtureRequest, client: Any, db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.firestore.backfill import verify
    from app.modules.support import service as sv

    _s, sb = await _student(client, db)
    t = (await sb.post("/support/tickets", body("technical"))).json()
    assert (await sb.post(f"/support/tickets/{t['ticket_id']}/messages", {"body": "more"})).status_code == 201
    await system_context(db, "t")
    seq = (await db.execute(text("SELECT last_value FROM support_ticket_number_seq"))).scalar_one()
    restore = await activate_firestore(request, db, monkeypatch, ("support",))  # backfills
    try:
        reports = {r.collection: r for r in await verify(db, "support")}
        assert set(reports) == {
            "support_tickets",
            "support_ticket_messages",
            "support_user_notes",
            "support_counters",
        }
        for r in reports.values():
            assert r.ok, r.as_dict()
        assert reports["support_tickets"].fs_docs >= 1 and reports["support_ticket_messages"].fs_docs >= 1
        # The next Firestore ticket continues the Postgres sequence (no number reused).
        s2 = await adult(db)
        row = await sv.insert_ticket(db, _ticket(s2.id))
        assert row.ticket_number.endswith(f"-{int(seq) + 1:06d}")
        moved = await _repo().get_ticket(None, uuid.UUID(t["ticket_id"]))
        assert moved is not None and moved.ticket_number == t["ticket_number"]
    finally:
        await restore()


async def test_ticket_numbers_are_gap_free_under_concurrency(db: Any, fs: None) -> None:
    from app.modules.support.service import ticket_number

    u = await adult(db)
    repo = _repo()
    rows = await asyncio.gather(*(repo.insert_ticket(u.id, _ticket(u.id), ticket_number) for _ in range(5)))
    nums = sorted(int(r.ticket_number.rsplit("-", 1)[1]) for r in rows)
    assert nums == list(range(nums[0], nums[0] + 5))


async def test_requester_or_platform_predicate_and_platform_only_notes(db: Any, fs: None) -> None:
    from app.modules.support import service as sv
    from app.modules.support.repo_firestore import NoteRow

    a, b = await adult(db), await adult(db)
    t = await _repo().insert_ticket(a.id, _ticket(a.id), sv.ticket_number)
    await sv.add_message(db, t, author_id=a.id, author_kind="requester", body="hello")
    await _repo().save(None, [t])
    as_a, as_b = _repo(RlsScope(str(a.id), False)), _repo(RlsScope(str(b.id), False))
    assert (await as_a.get_ticket(None, t.id)) is not None
    assert await as_b.get_ticket(None, t.id) is None  # invisible, no existence oracle
    assert await as_b.thread(None, t, internal=True) == []
    assert (await as_b.tickets_of(a.id))[0] == [] and await as_b.count_tickets_since(a.id, clock.now()) == 0
    (msg,) = await as_a.thread(None, t, internal=True)
    assert await as_b.get_message(None, t, msg.id) is None
    t.status = "closed"
    with pytest.raises(ProblemError) as e:
        await as_b.save(None, [t])  # cannot write someone else's ticket
    assert e.value.code == "not_found"
    with pytest.raises(ProblemError):
        await as_b.insert_ticket(a.id, _ticket(a.id), sv.ticket_number)  # cannot plant one
    note = NoteRow(
        id=uuid7(), user_id=a.id, author_id=b.id, body="Called the learner", created_at=clock.now()
    )
    for weak in (as_a, as_b):
        with pytest.raises(ProblemError):
            await weak.add_note(note)
        with pytest.raises(ProblemError):
            await weak.notes_for(a.id, 10)
    await _repo().add_note(note)
    assert [n.body for n in await _repo().notes_for(a.id, 10)] == ["Called the learner"]


async def test_optimistic_lock_replaces_select_for_update(db: Any, fs: None) -> None:
    from app.modules.support import service as sv

    u = await adult(db)
    t = await _repo().insert_ticket(u.id, _ticket(u.id), sv.ticket_number)
    first, second = await _repo().get_ticket(None, t.id), await _repo().get_ticket(None, t.id)
    first.status = "resolved"
    await _repo().save(None, [first])
    second.priority = "urgent"
    with pytest.raises(ProblemError) as e:
        await _repo().save(None, [second])
    assert e.value.code == "conflict"
    fresh = await _repo().get_ticket(None, t.id)
    assert fresh.status == "resolved" and fresh.priority == "normal"
    # A merge-style save of two tickets plus their messages commits together.
    other = await _repo().insert_ticket(u.id, _ticket(u.id), sv.ticket_number)
    fresh.status, other.status = "closed", "pending_user"
    await sv.add_message(db, fresh, author_id=None, author_kind="system", body="Merged.")
    await sv.add_message(db, other, author_id=None, author_kind="system", body="Merged in.")
    await _repo().save(None, [fresh, other])
    assert [m.body for m in await _repo().thread(None, fresh, internal=True)] == ["Merged."]
    assert (await _repo().get_ticket(None, other.id)).status == "pending_user"


def test_composite_indexes_are_declared() -> None:
    spec = json.loads((Path(__file__).resolve().parents[4] / "firestore.indexes.json").read_text())
    declared = {
        (i["collectionGroup"].removeprefix("lms_"), tuple(f["fieldPath"] for f in i["fields"]))
        for i in spec["indexes"]
    }
    for want in (
        ("support_tickets", ("requester_id", "id")),  # SUP-02
        ("support_tickets", ("requester_id", "status", "id")),
        ("support_tickets", ("requester_id", "created_at")),  # SUP-11, daily cap
        ("support_tickets", ("status", "resolved_at")),  # auto-close
        ("support_ticket_messages", ("support_ticket_id", "visibility")),  # thread, counts
        ("support_ticket_messages", ("author_id", "created_at")),  # hourly cap
        ("support_user_notes", ("user_id", "created_at")),
    ):
        assert want in declared, want
