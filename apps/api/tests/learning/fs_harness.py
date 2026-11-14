"""Postgres-free Firestore harness for the data-learning agent's tests (learning, engage, mentoring).

These tests run on the emulator only, so they also run where Docker/Postgres is down::

    TD_TEST_DB_NAME=learning_test .venv/Scripts/python -m pytest --noconftest -p no:cacheprovider \
        tests/learning/test_fs_data_path.py tests/engage/test_fs_repo.py tests/mentoring/test_fs_repo.py

(``--noconftest`` skips the root conftest, whose session fixture migrates Postgres.) They also run
under the normal suite. The backfill's SQL read (``backfill._rows``) is replaced by synthetic
rows, so backfill -> verify, the mappers and the repositories are exercised end to end; the SQL
itself is covered by the matrix tests, which need Postgres.
"""

from __future__ import annotations

import os
import re
import sys
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

os.environ.setdefault("APP_ENV", "test")
if sys.platform == "win32":  # pragma: no cover - same as the root conftest
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]

from tests.firestore.conftest import TEST_PROJECT, clear_emulator, firestore_emulator  # noqa: F401

Rows = dict[str, list[dict[str, Any]]]
_SUBQ = re.compile(r"\(SELECT \* FROM (\w+)(?: WHERE (.*))?\) AS \w+$", re.S)


def _pred(where: str | None) -> Callable[[dict[str, Any]], bool]:
    """Tiny evaluator for the static WHERE clauses used by the mappings (AND of simple terms)."""
    if not where:
        return lambda r: True
    terms = [t.strip() for t in re.split(r"\bAND\b", where)]

    def one(t: str) -> Callable[[dict[str, Any]], bool]:
        m = re.fullmatch(r"(\w+) IS NOT NULL", t)
        if m:
            return lambda r, k=m.group(1): r.get(k) is not None
        m = re.fullmatch(r"(\w+) IS NULL", t)
        if m:
            return lambda r, k=m.group(1): r.get(k) is None
        m = re.fullmatch(r"(\w+) <> '([^']*)'", t)
        if m:
            return lambda r, k=m.group(1), v=m.group(2): r.get(k) != v
        m = re.fullmatch(r"(\w+) = '([^']*)'", t)
        if m:
            return lambda r, k=m.group(1), v=m.group(2): r.get(k) == v
        m = re.fullmatch(r"(\w+) IN \(([^)]*)\)", t)
        if m:
            vals = {x.strip().strip("'") for x in m.group(2).split(",")}
            return lambda r, k=m.group(1), vs=vals: r.get(k) in vs
        raise AssertionError(f"harness cannot evaluate WHERE term {t!r}")

    preds = [one(t) for t in terms]
    return lambda r: all(p(r) for p in preds)


def fake_rows(rows: Rows, sources: Rows | None = None) -> Callable[..., Any]:
    """``sources``: rows for mapping tables that are joins/aggregates (keyed by ``m.table``)."""

    async def _rows(session: Any, m: Any) -> list[dict[str, Any]]:
        if sources and m.table in sources:
            return [dict(r) for r in sources[m.table]]
        sm = _SUBQ.match(m.table)
        table, where = (sm.group(1), sm.group(2)) if sm else (m.table, None)
        p, p2 = _pred(where), _pred(m.where)
        return [dict(r) for r in rows.get(table, []) if p(r) and p2(r)]

    return _rows


@pytest.fixture
async def fs(firestore_emulator: str, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:  # noqa: F811
    """A wiped emulator project installed as the process client (what the repositories use)."""
    from app.core.config import Settings
    from app.core.firestore import client as client_mod

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
    try:
        yield client
    finally:
        client_mod.set_client(None)
        await client_mod.aclose(client)


async def backfill_rows(
    monkeypatch: pytest.MonkeyPatch, module: str, rows: Rows, client: Any, sources: Rows | None = None
) -> Any:
    """Run the real backfill + verify of ``module`` over ``rows``; returns the verify reports."""
    from app.core.firestore import backfill as bf

    monkeypatch.setattr(bf, "_rows", fake_rows(rows, sources))
    await bf.backfill(None, module, client=client)  # type: ignore[arg-type]
    return await bf.verify(None, module, client=client)  # type: ignore[arg-type]
