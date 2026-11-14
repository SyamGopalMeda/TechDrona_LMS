"""Commerce on the Firestore emulator **without Postgres** (``TD_STORE_COMMERCE=firestore``).

Run on its own so the Postgres-migrating root conftest is not loaded::

    TD_TEST_DB_NAME=money_test .venv/Scripts/python -m pytest tests/commerce/firestore \
        --confcutdir=tests/commerce/firestore -p no:cacheprovider

``fake_session`` stands in for the request's ``AsyncSession``: it keeps the RLS GUCs
(``set_config`` / ``current_setting``) in memory, so ``as_system`` / ``tenant_context`` and the
commerce RLS emulation work unchanged, and refuses any other SQL (proving the code path never
reaches Postgres for commerce tables). ``commit()`` does what the ``before_commit`` hook does.
PG-side collaborators (audit, outbox, entitlements) are replaced by recorders per test.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import AsyncIterator
from typing import Any

import pytest

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("TD_K_DEVICE_KEY_V1", "11" * 32)
os.environ.setdefault("TD_K_LOGIN_KEY_V1", "22" * 32)
os.environ.setdefault("TD_K_TOTP_KEY_V1", "33" * 32)

from tests.firestore.conftest import TEST_PROJECT, clear_emulator, firestore_emulator  # noqa: F401


class _Res:
    def __init__(self, row: tuple[Any, ...]) -> None:
        self._row = row

    def one(self) -> tuple[Any, ...]:
        return self._row

    def scalar_one(self) -> Any:
        return self._row[0]


class _Nested:
    is_active = True

    async def commit(self) -> None:
        self.is_active = False

    async def rollback(self) -> None:
        self.is_active = False


class FakeSession:
    def __init__(self) -> None:
        self.info: dict[str, Any] = {}
        self.guc: dict[str, str] = {
            "app.user_id": "",
            "app.org_ids": "",
            "app.is_platform": "off",
            "app.actor": "anonymous",
            "app.roles": "",
            "app.privacy_tier": "",
        }
        self.pg_added: list[Any] = []
        self.empty_other_selects = False
        self.other_selects: list[str] = []

    def as_user(self, user_id: Any) -> FakeSession:
        self.guc.update({"app.user_id": str(user_id), "app.is_platform": "off"})
        return self

    def as_platform(self) -> FakeSession:
        self.guc.update({"app.user_id": "", "app.is_platform": "on"})
        return self

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        sql = str(stmt)
        if "set_config" in sql:
            p = params or {}
            self.guc.update(
                {
                    "app.user_id": p.get("uid", ""),
                    "app.org_ids": p.get("orgs", ""),
                    "app.is_platform": p.get("plat", "off"),
                    "app.actor": p.get("actor", ""),
                    "app.roles": p.get("roles", ""),
                    "app.privacy_tier": p.get("ptier", ""),
                }
            )
            return _Res(())
        if "current_setting" in sql:
            names = re.findall(r"current_setting\('([a-z_.]+)'", sql)
            return _Res(tuple(self.guc[n] for n in names))
        if self.empty_other_selects and (hasattr(stmt, "get_final_froms") or hasattr(stmt, "table")):
            # HTTP tests: other modules' tables (still Postgres) answer "no rows"
            from app.core.firestore.sqlstore import Result

            self.other_selects.append(sql.split(" FROM ", 1)[-1][:60])
            return Result([], [])
        raise AssertionError(f"unexpected Postgres statement on the Firestore path: {sql[:200]}")

    def add(self, obj: Any) -> None:
        self.pg_added.append(obj)

    async def flush(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        raise AssertionError("refresh of a Postgres row on the Firestore path")

    async def begin_nested(self) -> _Nested:
        return _Nested()

    async def commit(self) -> None:
        from app.modules.commerce.datastore import commit_unit_of_work

        await commit_unit_of_work(self)
        self.info.clear()

    async def rollback(self) -> None:
        self.info.clear()

    async def close(self) -> None:
        self.info.clear()


@pytest.fixture
async def fs(firestore_emulator: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:  # noqa: F811
    """Emulator client installed process-wide, commerce switched to Firestore, wiped emulator."""
    from app.core.config import Settings
    from app.core.firestore import client as client_mod
    from app.core.firestore.backend import reset_store_backends

    monkeypatch.setenv("FIRESTORE_EMULATOR_HOST", firestore_emulator)
    clear_emulator(firestore_emulator)
    s = Settings(  # type: ignore[call-arg]
        _env_file=None,
        APP_ENV="test",
        FIRESTORE_EMULATOR_HOST=firestore_emulator,
        FIREBASE_PROJECT_ID=TEST_PROJECT,
    )
    client = client_mod.make_client(s)
    client_mod.set_client(client)
    monkeypatch.setenv("TD_STORE_COMMERCE", "firestore")
    reset_store_backends()
    try:
        yield client
    finally:
        monkeypatch.delenv("TD_STORE_COMMERCE", raising=False)
        reset_store_backends()
        client_mod.set_client(None)
        await client_mod.aclose(client)


@pytest.fixture
def session() -> FakeSession:
    return FakeSession().as_platform()


@pytest.fixture
def new_session() -> Any:
    return FakeSession
