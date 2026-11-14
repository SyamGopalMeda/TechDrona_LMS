"""The mentoring + résumé HTTP suites re-run with ``TD_STORE_MENTORING=firestore``.

Needs Postgres (users, RBAC, entitlements, batches, audit stay there) and the Firestore emulator.
Each test starts from a wiped emulator with mentoring backfilled from the Postgres test DB. The
original files keep running on Postgres, so together they cover both stores.

``shift_slot`` (the suites' "time passes" helper) updates ``mentor_slots`` with SQL; on Firestore it
is replaced by the equivalent document update (slot start, its time key, and the bookings'
denormalised ``slot_starts_at``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any

import pytest

from tests.firestore.matrix import activate_firestore
from tests.mentoring import test_mentoring as _suite
from tests.mentoring.test_mentoring import *  # noqa: F403
from tests.mentoring.test_resumes import *  # noqa: F403


async def fs_shift_slot(db: Any, booking_or_slot: str, hours: float, *, by_booking: bool = True) -> None:
    from app.core.firestore.store import ScopedStore
    from app.core.time import utcnow
    from app.modules.mentoring import store_specs as ss

    st = ScopedStore.system("test.factory")
    ident = str(uuid.UUID(booking_or_slot))
    if by_booking:
        b = await st.get(ss.BOOKINGS, ident)
        assert b is not None
        ident = b["mentor_slot_id"]
    slot = await st.get(ss.SLOTS, ident)
    assert slot is not None
    new = utcnow() + timedelta(minutes=int(hours * 60))
    old_key = ss.slot_time_key(slot["mentor_id"], slot["starts_at"])
    await st.update(ss.SLOTS, ident, {"starts_at": new})
    if await st.get(ss.SLOT_TIMES, old_key) is not None:
        await st.delete(ss.SLOT_TIMES, old_key)
        await st.create(ss.SLOT_TIMES, {"slot_id": ident}, doc_id=ss.slot_time_key(slot["mentor_id"], new))
    page = await st.query(ss.BOOKINGS, filters=(("mentor_slot_id", "==", ident),), order_by=(), limit=100)
    for d in page.items:
        await st.update(ss.BOOKINGS, d.id, {"slot_starts_at": new})


@pytest.fixture(autouse=True)
async def mentoring_on_firestore(
    request: pytest.FixtureRequest, db: Any, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[str]:
    restore = await activate_firestore(request, db, monkeypatch, ("mentoring",))
    monkeypatch.setattr(_suite, "shift_slot", fs_shift_slot)
    try:
        yield "firestore"
    finally:
        await restore()
