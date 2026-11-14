"""app.core.firestore.rows: the stored document format of both codec families (must not drift)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

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


def _round_trip(obj: Any) -> dict[str, Any]:
    cols = [c.key for c in Sample.__table__.columns]  # type: ignore[attr-defined]
    return {k: getattr(obj, k) for k in cols}


def test_json_family_document_format() -> None:
    """learning / engage / mentoring documents: hex bytes, unscaled decimals, wrapped nested lists."""
    doc = rows.doc_mapper(Sample)(ROW)
    assert doc == {
        "id": str(ROW["id"]),
        "ids": [str(ROW["ids"][0])],
        "tags": ["a", "b"],
        "amount": "12.5",
        "blob": "00ff6162",
        "day": "2026-11-12",
        "at": ROW["at"],
        "ip": "10.0.0.1",
        "meta": {"k": [{"$l": [1, 2]}, {"$l": [3]}], "u": "x"},
        "n": 7,
    }
    s = Sample()
    for k, v in ROW.items():
        setattr(s, k, v)
    assert rows.doc_of(s) == doc
    back = _round_trip(rows.orm_of(Sample, doc))
    assert back == {**ROW, "meta": {"k": [[1, 2], [3]], "u": "x"}}


def test_scaled_family_document_format() -> None:
    """placement / assessments / coding documents: base64 bytes, decimals quantized to the scale."""
    doc = rows.row_doc(Sample, ROW)
    assert doc["amount"] == "12.50" and doc["blob"] == "AP9hYg=="
    assert doc["id"] == str(ROW["id"]) and doc["ids"] == [str(ROW["ids"][0])] and doc["ip"] == "10.0.0.1"
    assert doc["meta"] == ROW["meta"] and doc["day"] == ROW["day"] and doc["at"] == ROW["at"]
    back = _round_trip(rows.orm_of_scaled(Sample, doc))
    assert back == {**ROW, "amount": Decimal("12.50")}
    assert rows.pk_id(Sample)(ROW) == str(ROW["id"])
