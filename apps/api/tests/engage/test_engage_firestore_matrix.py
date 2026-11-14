"""The engage HTTP suite (``test_engage.py``) re-run with ``TD_STORE_ENGAGE=firestore``.

Needs Postgres (users, RBAC, batches, audit stay there) and the Firestore emulator. Each test
starts from a wiped emulator with engage backfilled from the Postgres test DB (the cutover path).
``test_engage.py`` itself keeps running on Postgres, so together they cover both stores.

Excluded here: tests that read or write engage tables with raw SQL as part of their *setup or
assertions* (they would observe Postgres, not the store under test); their behaviour is covered
on Firestore by ``test_fs_repo.py`` (timer refresh, server-order leaderboard, anonymity labels).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from tests.engage import test_engage as _suite
from tests.engage.test_engage import *  # noqa: F403
from tests.firestore.matrix import activate_firestore

_SQL_BOUND = (
    "test_fastest_first_uses_server_order",
    "test_anonymous_hides_identity",
    "test_scheduled_run_opens_and_closes_on_timer",
    "test_no_organization_target_or_picker",
)
for _name in _SQL_BOUND:
    globals().pop(_name, None)
assert all(hasattr(_suite, n) for n in _SQL_BOUND)


@pytest.fixture(autouse=True)
async def engage_on_firestore(
    request: pytest.FixtureRequest, db: Any, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[str]:
    restore = await activate_firestore(request, db, monkeypatch, ("engage",))
    try:
        yield "firestore"
    finally:
        await restore()
