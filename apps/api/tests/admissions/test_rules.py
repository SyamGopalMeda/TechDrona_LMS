"""Pure fee / status rules (no database): port of the website's feeplan.js tests."""

from __future__ import annotations

import base64
import io
from datetime import date, timedelta

import pytest

from app.core.errors import ProblemError
from app.modules.admissions import files as fs
from app.modules.admissions import rules as R


def test_clean_terms_full_and_instalments() -> None:
    full = R.clean_terms(fee_paise=500000, allow_instalments=False, schedule=None)
    assert full.policy == "full" and full.access_min_paise == 500000 and full.min_first_paise == 500000
    assert [x.amount_paise for x in full.schedule] == [500000] and not full.problems

    inst = R.clean_terms(
        fee_paise=300000,
        allow_instalments=True,
        schedule=[{"label": "First", "amount_paise": 100000, "due": "2026-12-01"}, {"amount_paise": 200000}],
    )
    assert inst.policy == "instalments" and inst.access_min_paise == 100000 and inst.min_first_paise == 100000
    assert inst.schedule[1].label == "Instalment 2" and not inst.problems

    bad = R.clean_terms(fee_paise=300000, allow_instalments=True, schedule=[{"amount_paise": 100000}])
    assert bad.problems and "add up" in bad.problems[0]
    assert R.clean_terms(fee_paise=50, allow_instalments=False, schedule=None).problems


def test_next_due_and_amount_range() -> None:
    t = R.clean_terms(
        fee_paise=300000,
        allow_instalments=True,
        schedule=[{"amount_paise": 100000}, {"amount_paise": 200000}],
    )
    assert R.next_due(t, 0) == {"label": "Instalment 1", "amount_paise": 100000, "due": ""}
    assert R.next_due(t, 150000)["amount_paise"] == 150000
    assert R.next_due(t, 300000) is None
    assert R.amount_range(t, 300000, first_payment=True) == (100000, 300000)
    assert R.amount_range(t, 50000, first_payment=False) == (100, 50000)
    full = R.clean_terms(fee_paise=300000, allow_instalments=False, schedule=None)
    assert R.amount_range(full, 300000, first_payment=True) == (300000, 300000)
    assert R.amount_range(full, 0, first_payment=False) == (0, 0)


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"current": "registered", "verified": 0, "open_claims": 1}, "pending_verification"),
        ({"current": "registered", "verified": 0, "open_claims": 0}, "registered"),
        ({"current": "pending_verification", "verified": 50, "open_claims": 0}, "partially_paid"),
        ({"current": "partially_paid", "verified": 100, "open_claims": 0}, "payment_verified"),
        ({"current": "payment_verified", "verified": 100, "open_claims": 0, "enrolled": True}, "enrolled"),
        ({"current": "cancelled", "verified": 100, "open_claims": 0, "enrolled": True}, "cancelled"),
        ({"current": "rejected", "verified": 0, "open_claims": 2}, "rejected"),
    ],
)
def test_derive_status(kw: dict, expected: str) -> None:
    args = {"access_min": 100, "fee": 200, "enrolled": False, **kw}
    assert R.derive_status(**args) == expected


def test_claim_transitions() -> None:
    assert R.can_move_claim("pending", "verified") and R.can_move_claim("needs_info", "rejected")
    assert not R.can_move_claim("verified", "verified") and not R.can_move_claim("rejected", "verified")
    assert R.can_move_claim("verified", "reversed") and not R.can_move_claim("pending", "reversed")
    assert not R.can_move_claim("needs_info", "needs_info")


def test_reference_date_phone_regno() -> None:
    assert R.ref_problem("1234 5678 9012", "upi") is None
    assert "app's own" in (R.ref_problem("T2511011234567", "upi") or "")
    assert R.ref_problem("123", "upi")
    assert R.ref_problem("HDFCN52025110112", "bank") is None
    today = date(2026, 11, 11)
    assert R.paid_on_problem(today + timedelta(days=1), today)
    assert R.paid_on_problem(today - timedelta(days=200), today)
    assert R.paid_on_problem(today, today) is None
    assert R.indian_mobile("098480 12345") == "+919848012345" and R.indian_mobile("12345") is None
    assert R.normalize_reg_no("tdr-1a2b 3c4d") == "TDR-1A2B3C4D" and R.normalize_reg_no("TDR-12") is None
    assert R.REG_NO_RE.match(R.new_reg_no())
    assert R.rupees(15000050) == "Rs 1,50,000.50" and R.rupees(99900) == "Rs 999"


def _png(color: tuple[int, int, int] = (10, 20, 30)) -> bytes:
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (64, 48), color).save(out, "PNG")
    return out.getvalue()


def test_files_sniff_reencode_and_refuse() -> None:
    raw = _png()
    f = fs.prepare("proof", filename="pay.png", data_b64=base64.b64encode(raw).decode())
    assert f.content_type == "image/jpeg" and f.name == "pay.jpg" and f.data[:3] == b"\xff\xd8\xff"
    import hashlib

    assert f.sha256 == hashlib.sha256(raw).hexdigest()
    pdf = b"%PDF-1.4\n" + b"x" * 400
    assert fs.prepare("resume", filename="cv.pdf", data_b64=base64.b64encode(pdf).decode()).content_type == (
        "application/pdf"
    )
    for kind, data in (
        ("proof", b"hello world " * 20),
        ("resume", raw),
        ("proof", b"\xff\xd8\xff" + b"0" * 300),
    ):
        with pytest.raises(ProblemError) as e:
            fs.prepare(kind, filename="x", data_b64=base64.b64encode(data).decode())  # type: ignore[arg-type]
        assert e.value.status == 422
    with pytest.raises(ProblemError):
        fs.prepare(
            "proof",
            filename="big.pdf",
            data_b64=base64.b64encode(b"%PDF-" + b"0" * (2 * 1024 * 1024)).decode(),
        )
