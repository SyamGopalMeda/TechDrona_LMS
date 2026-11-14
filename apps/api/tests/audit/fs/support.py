"""Shared harness for the data-ops Firestore-only tests (audit, admin, ai, security, analytics, hub).

* ``migrated_database``: overrides the root session fixture so no Postgres is needed.
* ``fs_env(*modules)``: a per-test emulator client installed as the store client, with
  ``TD_STORE_<MODULE>=firestore`` for ``modules`` (switch re-read), wiped before the test.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    yield None


@pytest.fixture
async def fs_env(
    request: pytest.FixtureRequest, firestore_emulator: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Any]:
    from app.core.config import Settings
    from app.core.firestore import client as client_mod
    from app.core.firestore.backend import reset_store_backends
    from tests.firestore.conftest import TEST_PROJECT, clear_emulator

    modules: tuple[str, ...] = getattr(request, "param", None) or getattr(request.module, "FS_MODULES", ())
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
    for m in modules:
        monkeypatch.setenv(f"TD_STORE_{m.upper()}", "firestore")
    reset_store_backends()
    try:
        yield client
    finally:
        for m in modules:
            monkeypatch.delenv(f"TD_STORE_{m.upper()}", raising=False)
        reset_store_backends()
        client_mod.set_client(None)
        await client_mod.aclose(client)


def sample_row(model: Any, i: int = 0) -> dict[str, Any]:
    """A Postgres-shaped row for ``model`` with one non-null sample value per column kind
    (JSON with nested arrays and floats, NUMERIC, bytea, interval, dates)."""
    import uuid as _uuid
    from datetime import UTC, date, datetime, timedelta
    from decimal import Decimal

    from app.modules.admin.fs_rows import kind_of_column

    samples: dict[str, Any] = {
        "uuid": lambda: _uuid.uuid4(),
        "dt": lambda: datetime(2026, 11, 1, 10, 0, 0, 123456 + i, tzinfo=UTC),
        "date": lambda: date(2026, 11, 1 + i),
        "bool": lambda: True,
        "int": lambda: 7 + i,
        "decimal": lambda: Decimal("12.3450"),
        "float": lambda: 0.25,
        "json": lambda: {"a": [[1, 2], [3]], "f": 5.0, "n": None},
        "hex": lambda: b"\x00\x01\xff",
        "seconds": lambda: timedelta(days=3),
        "list": lambda: ["x", "y"],
        "uuids": lambda: [_uuid.uuid4()],
        "str": lambda: f"s{i}",
    }
    return {c.key: samples[kind_of_column(c)]() for c in model.__table__.columns}


async def roundtrip_module(module: str, models: list[Any]) -> int:
    """Every mapping of ``module``: sample rows -> mapped documents -> emulator -> read back.
    Checks the verify hash matches and that the row class decodes to the original values."""
    from app.core.firestore.backfill import doc_hash, mappings
    from app.core.firestore.store import ScopedStore
    from app.modules.admin.fs_rows import model_row

    by_table = {mdl.__tablename__: mdl for mdl in models}
    st = ScopedStore.system("firestore.backfill")
    checked = 0
    for mp in mappings(module):
        if mp.loader is not None:  # assembled documents (heads, rollups): covered by repo tests
            continue
        mdl = by_table[mp.table]
        rows = [sample_row(mdl, i) for i in range(2)]
        docs = [(mp.doc_id(r), mp.transform(r)) for r in rows]
        assert len({d for d, _ in docs}) == 2, mp.table
        await st.import_documents(mp.collection, docs)
        back = {d.id: d.data for d in await st.scan(mp.collection)}
        cls = model_row(mdl)
        for (doc_id, data), row in zip(docs, rows, strict=True):
            assert doc_hash(back[doc_id], list(data)) == doc_hash(data), mp.table
            obj = cls.of(back[doc_id])
            for k, v in row.items():
                assert getattr(obj, k) == v, (mp.table, k)
        checked += 1
    return checked
