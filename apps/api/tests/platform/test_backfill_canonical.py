"""A4: the backfill verify hash accepts bytes (bytea / Firestore Bytes) on both sides."""

from __future__ import annotations

from app.core.firestore.backfill import canonical, doc_hash


def test_bytes_hash_as_hex_on_both_sides() -> None:
    pg_row = {"id": "x", "blob": b"\x00\xffab", "nested": {"k": [memoryview(b"\x01")]}}
    fs_doc = {"id": "x", "blob": bytearray(b"\x00\xffab"), "nested": {"k": [b"\x01"]}}
    assert canonical(pg_row)["blob"] == "00ff6162"
    assert doc_hash(pg_row) == doc_hash(fs_doc)
    assert doc_hash({"blob": b"\x00"}) != doc_hash({"blob": b"\x01"})
