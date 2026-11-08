"""Money (ADR-0012): integer paise, currency INR, half-up rounding per line item.

Never use floats for money. Rates are expressed as ``Decimal`` percentages.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CURRENCY = "INR"


def _as_decimal(v: Decimal | int | str) -> Decimal:
    if isinstance(v, float):  # pragma: no cover - defensive
        raise TypeError("floats are not allowed for money")
    return Decimal(v)


def round_half_up(amount: Decimal) -> int:
    """Round a (fractional) paise amount half-up to an integer number of paise."""
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rupees_to_paise(rupees: Decimal | int | str) -> int:
    return round_half_up(_as_decimal(rupees) * 100)


def paise_to_rupees(paise: int) -> Decimal:
    return (Decimal(paise) / 100).quantize(Decimal("0.01"))


def percent_of(amount_paise: int, percent: Decimal | int | str) -> int:
    """``percent`` of ``amount_paise``, half-up to paise (e.g. GST component on a line)."""
    if not isinstance(amount_paise, int):
        raise TypeError("amount_paise must be int")
    return round_half_up(Decimal(amount_paise) * _as_decimal(percent) / 100)


@dataclass(frozen=True, slots=True)
class GstSplit:
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int

    @property
    def tax_paise(self) -> int:
        return self.cgst_paise + self.sgst_paise + self.igst_paise

    @property
    def total_paise(self) -> int:
        return self.taxable_paise + self.tax_paise


def gst_on_line(taxable_paise: int, rate_percent: Decimal | int | str, *, intra_state: bool) -> GstSplit:
    """GST for one line item. Intra-state: CGST+SGST at half the rate each; else IGST."""
    if taxable_paise < 0:
        raise ValueError("taxable amount must be >= 0")
    rate = _as_decimal(rate_percent)
    if intra_state:
        half = rate / 2
        c = percent_of(taxable_paise, half)
        return GstSplit(taxable_paise, c, c, 0)
    return GstSplit(taxable_paise, 0, 0, percent_of(taxable_paise, rate))


def format_inr(paise: int) -> str:
    """Display helper (not for storage): ``₹1,23,456.78`` Indian digit grouping."""
    sign = "-" if paise < 0 else ""
    rupees, p = divmod(abs(paise), 100)
    s = str(rupees)
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups: list[str] = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join([*groups, tail])
    return f"{sign}₹{s}.{p:02d}"
