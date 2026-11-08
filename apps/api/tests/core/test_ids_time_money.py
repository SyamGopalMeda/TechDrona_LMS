from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.ids import new_request_id, uuid7, uuid7_timestamp_ms
from app.core.money import format_inr, gst_on_line, percent_of, rupees_to_paise
from app.core.time import ist_date, to_rfc3339, utcnow


def test_uuid7_version_order_and_time() -> None:
    before = int(time.time() * 1000)
    ids = [uuid7() for _ in range(5000)]
    after = int(time.time() * 1000)
    assert all(u.version == 7 and u.variant == "specified in RFC 4122" for u in ids)
    assert ids == sorted(ids)  # monotonic within the process
    assert len(set(ids)) == len(ids)
    assert before <= uuid7_timestamp_ms(ids[0]) <= after + 5


def test_request_id_shape() -> None:
    rid = new_request_id()
    assert len(rid) == 26 and rid.isalnum() and rid.upper() == rid


def test_time_helpers() -> None:
    now = utcnow()
    assert now.tzinfo is UTC
    dt = datetime(2026, 11, 3, 10, 15, 2, 123456, tzinfo=UTC)
    assert to_rfc3339(dt) == "2026-11-03T10:15:02.123Z"
    ist = timezone(timedelta(hours=5, minutes=30))
    assert to_rfc3339(datetime(2026, 11, 3, 15, 45, tzinfo=ist)) == "2026-11-03T10:15:00.000Z"
    # 20:00 UTC is already the next IST calendar day
    assert ist_date(datetime(2026, 11, 3, 20, 0, tzinfo=UTC)) == date(2026, 11, 4)
    with pytest.raises(ValueError):
        to_rfc3339(datetime(2026, 1, 1))  # naive refused


def test_money_half_up_and_gst() -> None:
    assert rupees_to_paise("199.995") == 20000
    assert rupees_to_paise(Decimal("10.004")) == 1000
    assert percent_of(1001, 9) == 90  # 90.09 -> 90
    assert percent_of(1005, 10) == 101  # 100.5 -> 101 (half-up)
    intra = gst_on_line(99900, 18, intra_state=True)
    assert (intra.cgst_paise, intra.sgst_paise, intra.igst_paise) == (8991, 8991, 0)
    inter = gst_on_line(99900, 18, intra_state=False)
    assert inter.igst_paise == 17982 and inter.total_paise == 117882
    with pytest.raises(TypeError):
        percent_of(10.5, 5)  # type: ignore[arg-type]


def test_format_inr() -> None:
    assert format_inr(12345678) == "₹1,23,456.78"
    assert format_inr(99) == "₹0.99"
    assert format_inr(-150000) == "-₹1,500.00"
