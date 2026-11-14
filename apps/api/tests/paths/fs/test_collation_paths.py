"""Firestore-path in-memory text ORDER BY uses Postgres collation (``app.core.firestore.collation``).

Expected orders are written out as Postgres ``en_US.utf8`` sorts them (case and accents are
secondary/tertiary differences; NULLS LAST for ASC). A byte-order sort would put ``Eclair`` and
``Zebra`` before ``apple`` and the accented names last, and fails these tests.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest


async def test_batch_people_orders_by_name_then_email_with_collation(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.identity import public as identity
    from app.modules.orgs import public as orgs
    from app.modules.paths import adapters

    people = [
        ("Zebra", "z@x.test"),
        ("éclair", "e2@x.test"),
        ("apple", "b@x.test"),
        ("Eclair", "e1@x.test"),
        (None, "n@x.test"),
        ("Ábel", "a@x.test"),
        ("apple", "A@x.test"),
    ]
    ids = [uuid.uuid4() for _ in people]

    async def members(session: Any, **kw: Any) -> list[Any]:
        return [SimpleNamespace(user_id=u) for u in ids]

    async def cards(session: Any, user_ids: Any) -> dict[uuid.UUID, Any]:
        return {u: SimpleNamespace(full_name=n, email=e) for u, (n, e) in zip(ids, people, strict=True)}

    monkeypatch.setattr(orgs, "batch_members", members)
    monkeypatch.setattr(identity, "user_cards", cards)
    rows = await adapters.batch_people(None, uuid.uuid4(), None, search_email=True)  # type: ignore[arg-type]
    assert [(r[2], r[1]) for r in rows] == [
        ("Ábel", "a@x.test"),
        ("apple", "A@x.test"),
        ("apple", "b@x.test"),
        ("Eclair", "e1@x.test"),
        ("éclair", "e2@x.test"),
        ("Zebra", "z@x.test"),
        (None, "n@x.test"),  # NULLS LAST
    ]
