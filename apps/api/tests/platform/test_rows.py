"""app.core.firestore.rows encodes exactly like every module copy (guards drift until owners switch)."""

from __future__ import annotations

import importlib
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import (
    ARRAY,
    JSON,
    Column,
    Date,
    DateTime,
    Integer,
    LargeBinary,
    MetaData,
    Numeric,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import registry

from app.core.firestore import rows

_meta = MetaData()
_reg = registry(metadata=_meta)


class Sample:
    pass


_reg.map_imperatively(
    Sample,
    Table(
        "platformtest_rows",
        _meta,
        Column("id", PG_UUID(as_uuid=True), primary_key=True),
        Column("ids", ARRAY(PG_UUID(as_uuid=True))),
        Column("tags", ARRAY(Text)),
        Column("amount", Numeric(12, 2)),
        Column("blob", LargeBinary),
        Column("day", Date),
        Column("at", DateTime(timezone=True)),
        Column("ip", INET),
        Column("meta", JSON),
        Column("n", Integer),
    ),
)

ROW: dict[str, Any] = {
    "id": uuid.UUID("01890000-0000-7000-8000-000000000001"),
    "ids": [uuid.UUID("01890000-0000-7000-8000-000000000002")],
    "tags": ["a", "b"],
    "amount": Decimal("12.5"),
    "blob": b"\x00\xffab",
    "day": date(2026, 11, 12),
    "at": datetime(2026, 11, 12, 10, 0, tzinfo=UTC),
    "ip": "10.0.0.1",
    "meta": {"k": [[1, 2], [3]], "u": "x"},
    "n": 7,
}


@pytest.mark.parametrize("module", ["learning", "engage", "mentoring"])
def test_json_family_matches_copies(module: str) -> None:
    copy = importlib.import_module(f"app.modules.{module}.fs_rows")
    assert copy.doc_mapper(Sample)(ROW) == rows.doc_mapper(Sample)(ROW)
    doc = rows.doc_mapper(Sample)(ROW)
    a, b = copy.orm_of(Sample, doc), rows.orm_of(Sample, doc)
    cols = [c.key for c in Sample.__table__.columns]  # type: ignore[attr-defined]
    assert {k: getattr(a, k) for k in cols} == {k: getattr(b, k) for k in cols}
    assert doc["meta"] == {"k": [{"$l": [1, 2]}, {"$l": [3]}], "u": "x"} and doc["blob"] == "00ff6162"


@pytest.mark.parametrize("module", ["placement", "coding"])
def test_scaled_family_matches_copies(module: str) -> None:
    copy = importlib.import_module(f"app.modules.{module}.fsmap")
    assert copy.row_doc(Sample, ROW) == rows.row_doc(Sample, ROW)
    doc = rows.row_doc(Sample, ROW)
    a, b = copy.orm_of(Sample, doc), rows.orm_of_scaled(Sample, doc)
    cols = [c.key for c in Sample.__table__.columns]  # type: ignore[attr-defined]
    assert {k: getattr(a, k) for k in cols} == {k: getattr(b, k) for k in cols}
    assert doc["amount"] == "12.50" and doc["blob"] == "AP9hYg=="
    assert copy.pk_id(Sample)(ROW) == rows.pk_id(Sample)(ROW) == str(ROW["id"])
