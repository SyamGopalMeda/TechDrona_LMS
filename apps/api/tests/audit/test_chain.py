"""Pure hash-chain tests (no database)."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

from app.core.ids import uuid7
from app.modules.audit.chain import GENESIS_HASH, compute_row_hash, verify_rows


def _chain(n: int) -> list[dict]:
    rows, prev = [], GENESIS_HASH
    t0 = datetime(2026, 11, 3, tzinfo=UTC)
    for i in range(1, n + 1):
        row = {
            "seq": i,
            "occurred_at": t0 + timedelta(seconds=i),
            "id": uuid7(),
            "actor_type": "user",
            "actor_user_id": uuid7(),
            "actor_session_id": None,
            "actor_roles": ["super_admin"],
            "action": "case.decide",
            "target_type": "security_case",
            "target_id": uuid7(),
            "organization_id": None,
            "subject_user_id": uuid7(),
            "reason_code": "case_review",
            "reason": None,
            "before_state": {"level": 3},
            "after_state": {"level": 0},
            "request_id": f"req-{i:08d}",
            "ip": "10.0.0.1",
        }
        row["prev_hash"] = prev
        row["row_hash"] = compute_row_hash(prev, row)
        prev = row["row_hash"]
        rows.append(row)
    return rows


def test_valid_chain_verifies() -> None:
    rows = _chain(20)
    res = verify_rows(rows)
    assert res.ok and res.checked == 20 and res.last_seq == 20 and res.last_hash == rows[-1]["row_hash"]


def test_altered_field_detected() -> None:
    rows = _chain(10)
    tampered = copy.deepcopy(rows)
    tampered[4]["after_state"] = {"level": 4}
    res = verify_rows(tampered)
    assert not res.ok and res.first_bad_seq == 5 and "row_hash" in (res.reason or "")


def test_recomputed_row_breaks_next_link() -> None:
    """An attacker who recomputes the altered row's hash still breaks the following row."""
    rows = _chain(10)
    tampered = copy.deepcopy(rows)
    tampered[4]["reason"] = "covered up"
    tampered[4]["row_hash"] = compute_row_hash(tampered[4]["prev_hash"], tampered[4])
    res = verify_rows(tampered)
    assert not res.ok and res.first_bad_seq == 6 and res.reason == "prev_hash mismatch"


def test_deleted_row_detected() -> None:
    rows = _chain(10)
    del rows[3]
    res = verify_rows(rows)
    assert not res.ok and res.first_bad_seq == 5 and "gap" in (res.reason or "")


def test_canonical_form_is_type_stable() -> None:
    """Values read back from Postgres (UUID objects, inet objects) hash like the strings
    written by the sealer."""
    import ipaddress

    row = _chain(1)[0]
    as_strings = {
        k: (str(v) if k in ("id", "actor_user_id", "target_id", "subject_user_id") else v)
        for k, v in row.items()
    }
    as_strings["ip"] = ipaddress.ip_interface("10.0.0.1/32")
    assert compute_row_hash(GENESIS_HASH, as_strings) == row["row_hash"]
