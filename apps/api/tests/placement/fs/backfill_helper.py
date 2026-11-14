"""Run the real ``backfill`` / ``verify`` against synthetic Postgres rows (no Postgres needed).

``app.core.firestore.backfill._rows`` (the only function that runs SQL) is replaced by a lookup
in ``tables``; a mapping's ``where`` of the form ``col = 'value'`` is applied in Python.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

_WHERE = re.compile(r"^\s*(\w+)\s*=\s*'([^']*)'\s*$")
_NOT_NULL = re.compile(r"^\s*(\w+)\s+IS NOT NULL\s*$")


def fake_rows(monkeypatch: pytest.MonkeyPatch, tables: dict[str, list[dict[str, Any]]]) -> None:
    from app.core.firestore import backfill as bf

    async def _rows(session: Any, m: Any) -> list[dict[str, Any]]:
        # plain tables by name; derived (sub-query) mappings by their collection name
        rows = [dict(r) for r in tables.get(m.table, tables.get(m.collection, []) if " " in m.table else [])]
        if m.where:
            w, nn = _WHERE.match(m.where), _NOT_NULL.match(m.where)
            assert w or nn, f"unsupported where in test helper: {m.where}"
            if w:
                rows = [r for r in rows if str(r.get(w.group(1))) == w.group(2)]
            elif nn:
                rows = [r for r in rows if r.get(nn.group(1)) is not None]
        return rows

    monkeypatch.setattr(bf, "_rows", _rows)


def model_row(obj: Any) -> dict[str, Any]:
    """Column values of an ORM instance, as asyncpg returns them (UUID, Decimal, bytes, ...)."""
    return {c.key: getattr(obj, c.key) for c in type(obj).__table__.columns}


async def backfill_and_verify(module: str, client: Any) -> list[Any]:
    from app.core.firestore.backfill import backfill, verify

    await backfill(None, module, client=client)  # type: ignore[arg-type]
    return await verify(None, module, client=client)  # type: ignore[arg-type]


def sample_row(model: type[Any], **values: Any) -> dict[str, Any]:
    """A row of ``model`` with a type-appropriate value in every column (as asyncpg returns
    them), overridden by ``values``. For mapper / backfill tests."""
    import uuid
    from datetime import UTC, datetime
    from decimal import Decimal

    from sqlalchemy import ARRAY, Boolean, DateTime, Integer, LargeBinary, Numeric, SmallInteger
    from sqlalchemy.dialects.postgresql import INET, JSONB
    from sqlalchemy.dialects.postgresql import UUID as PG_UUID

    from app.core.ids import uuid7

    row: dict[str, Any] = {}
    for c in model.__table__.columns:
        t = c.type
        if c.key in values:
            row[c.key] = values[c.key]
        elif isinstance(t, PG_UUID):
            row[c.key] = uuid7()
        elif isinstance(t, DateTime):
            row[c.key] = datetime(2026, 11, 1, 9, 30, 15, 123456, tzinfo=UTC)
        elif isinstance(t, Numeric):
            row[c.key] = Decimal(1).scaleb(-(t.scale or 0)) * 7
        elif isinstance(t, LargeBinary):
            row[c.key] = bytes(range(32))
        elif isinstance(t, INET):
            row[c.key] = "203.0.113.7"
        elif isinstance(t, ARRAY):
            row[c.key] = [uuid.uuid4()] if isinstance(t.item_type, PG_UUID) else ["a", "b"]
        elif isinstance(t, JSONB):
            row[c.key] = {"k": [1, "x"]}
        elif isinstance(t, Boolean):
            row[c.key] = True
        elif isinstance(t, (Integer, SmallInteger)):
            row[c.key] = 3
        else:
            row[c.key] = f"{c.key}-value"
    return row
