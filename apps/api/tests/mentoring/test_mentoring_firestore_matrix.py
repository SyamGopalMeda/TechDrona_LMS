"""The résumé HTTP suite re-run with ``TD_STORE_MENTORING=firestore``.

Needs Postgres (users, RBAC, audit stay there) and the Firestore emulator. Each test starts from a
wiped emulator with mentoring backfilled from the Postgres test DB. The original file keeps running
on Postgres, so together they cover both stores.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from tests.firestore.matrix import activate_firestore
from tests.mentoring.test_resumes import *  # noqa: F403


@pytest.fixture(autouse=True)
async def mentoring_on_firestore(
    request: pytest.FixtureRequest, db: Any, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[str]:
    restore = await activate_firestore(request, db, monkeypatch, ("mentoring",))
    try:
        yield "firestore"
    finally:
        await restore()
