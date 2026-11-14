"""Pure fee / instalment / status rules (no database). Port of ``tech drona/src/lib/feeplan.js``.

Money is integer paise everywhere (ADR-0012). Only VERIFIED claims count: the outstanding balance
is ``fee - verified_total``; a pending, needs-info or rejected claim never changes it and a
screenshot alone never verifies anything.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

# --------------------------------------------------------------------------- statuses

REGISTRATION_STATUSES = (
    "registered",
    "pending_verification",
    "partially_paid",
    "payment_verified",
    "enrolled",
    "rejected",
    "cancelled",
    "completed",
)
# Set by staff; payments never move a registration out of them.
MANUAL_STATUSES = frozenset({"rejected", "cancelled", "completed"})
# A registration in one of these no longer holds the "one registration per email per course" slot.
ENDED_STATUSES = frozenset({"rejected", "cancelled"})
CLAIM_STATUSES = ("pending", "needs_info", "verified", "rejected", "reversed")
OPEN_CLAIM_STATUSES = frozenset({"pending", "needs_info"})
STUDENT_METHODS = ("upi", "bank")
STAFF_METHODS = ("upi", "bank", "cash", "other")
PROVIDERS = ("manual_upi", "admin_entry")
# Claims a registration may have waiting for review at once (website rule).
MAX_OPEN_CLAIMS = 3
MAX_FEE_PAISE = 100_000_000  # Rs 10,00,000
MAX_INSTALMENTS = 6
MAX_PAID_ON_AGE_DAYS = 180

REG_NO_RE = re.compile(r"^TDR-[A-Z0-9]{8}$")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
REF_RE = re.compile(r"^[A-Z0-9]{10,22}$")
STAFF_REF_RE = re.compile(r"^[A-Z0-9]{4,22}$")
UPI_ID_RE = re.compile(r"^[a-zA-Z0-9._-]{2,255}@[a-zA-Z][a-zA-Z0-9.-]{1,64}$")
_REG_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I


def new_reg_no() -> str:
    return "TDR-" + "".join(secrets.choice(_REG_ALPHABET) for _ in range(8))


def normalize_reg_no(v: str | None) -> str | None:
    """``"tdr-1a2b 3c4d"`` / ``"1A2B3C4D"`` -> ``"TDR-1A2B3C4D"``; None when it isn't one."""
    s = re.sub(r"[\s-]", "", str(v or "").upper())
    core = s[3:] if s.startswith("TDR") else s
    return f"TDR-{core}" if re.fullmatch(r"[A-Z0-9]{8}", core) else None


def normalize_ref(v: str | None) -> str:
    """Transaction reference as stored: upper case, no spaces or dashes."""
    return re.sub(r"[\s-]", "", str(v or "").upper())


def ref_problem(ref: str, method: str) -> str | None:
    """What is wrong with a student's payment reference (None when fine). Same text as the website."""
    r = normalize_ref(ref)
    if not r:
        return "Enter the transaction reference (UTR) from your payment app or bank."
    if method == "upi":
        if r[0] in "TP" or re.search(r"[A-Z]", r):
            return (
                "That looks like the app's own transaction ID. Enter the 12-digit UPI reference / UTR "
                "number instead (only digits)."
            )
        if not re.fullmatch(r"\d{12,16}", r):
            return "A UPI reference (UTR) is usually 12 digits. Please check the number."
    if not REF_RE.match(r):
        return "Enter the reference exactly as shown (10-22 letters and digits)."
    return None


def paid_on_problem(d: date, today: date) -> str | None:
    if d > today:
        return "The payment date can't be in the future."
    if (today - d) > timedelta(days=MAX_PAID_ON_AGE_DAYS):
        return "That date is more than 6 months ago. Please check it, or contact us."
    return None


def indian_mobile(v: str | None) -> str | None:
    """``"+91 98480 12345"`` / ``"09848012345"`` -> ``"+919848012345"``; None otherwise."""
    d = re.sub(r"\D", "", str(v or ""))
    if len(d) == 12 and d.startswith("91"):
        d = d[2:]
    elif len(d) == 11 and d.startswith("0"):
        d = d[1:]
    return f"+91{d}" if re.fullmatch(r"[6-9]\d{9}", d) else None


def rupees(paise: int) -> str:
    neg = paise < 0
    whole, part = divmod(abs(int(paise)), 100)
    s = f"{whole:,}"
    # Indian grouping: 1,00,000
    if whole >= 1000:
        head, tail = str(whole)[:-3], str(whole)[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups) + "," + tail
    return f"{'-' if neg else ''}Rs {s}{f'.{part:02d}' if part else ''}"


# --------------------------------------------------------------------------- plans


@dataclass(frozen=True)
class Instalment:
    label: str
    amount_paise: int
    due: str = ""  # YYYY-MM-DD or ""

    def as_dict(self) -> dict[str, Any]:
        return {"label": self.label, "amount_paise": self.amount_paise, "due": self.due}


@dataclass(frozen=True)
class PlanTerms:
    """The money terms of a fee plan (also snapshotted on each registration)."""

    fee_paise: int
    allow_instalments: bool
    schedule: tuple[Instalment, ...]
    policy: str  # "full" | "instalments"
    min_first_paise: int
    access_min_paise: int
    problems: tuple[str, ...] = field(default=())


def clean_terms(
    *,
    fee_paise: int,
    allow_instalments: bool,
    schedule: list[dict[str, Any]] | None,
    min_first_paise: int | None = None,
    access_min_paise: int | None = None,
) -> PlanTerms:
    """``cleanFeePlan`` + ``planProblems``: a consistent plan from what staff typed."""
    fee = max(0, int(fee_paise or 0))
    allow = bool(allow_instalments) and fee > 0
    rows: list[Instalment] = []
    if allow:
        for i, x in enumerate((schedule or [])[:MAX_INSTALMENTS]):
            amt = max(0, int((x or {}).get("amount_paise") or 0))
            if amt <= 0:
                continue
            due = str((x or {}).get("due") or "")
            rows.append(
                Instalment(
                    label=str((x or {}).get("label") or f"Instalment {i + 1}").strip()[:60]
                    or f"Instalment {i + 1}",
                    amount_paise=amt,
                    due=due if re.fullmatch(r"\d{4}-\d{2}-\d{2}", due) else "",
                )
            )
    if not allow or not rows:
        rows = [Instalment("Full fee", fee, "")]
    policy = "instalments" if allow else "full"
    first = rows[0].amount_paise or fee
    min_first = min(fee, max(100, int(min_first_paise or first))) if allow else fee
    access_min = fee if policy == "full" else min(fee, max(100, int(access_min_paise or first)))
    problems: list[str] = []
    if not (100 <= fee <= MAX_FEE_PAISE):
        problems.append("Set a course fee between Rs 1 and Rs 10,00,000.")
    if allow:
        total = sum(r.amount_paise for r in rows)
        if total != fee:
            problems.append(f"The instalments add up to {rupees(total)}, but the fee is {rupees(fee)}.")
    return PlanTerms(fee, allow, tuple(rows), policy, min_first, access_min, tuple(problems))


def next_due(terms: PlanTerms, verified: int) -> dict[str, Any] | None:
    """The next payment the student owes, or None when the fee is fully paid."""
    fee = terms.fee_paise
    if verified >= fee:
        return None
    cum = 0
    for x in terms.schedule or (Instalment("Full fee", fee),):
        cum += x.amount_paise
        if cum > verified:
            return {"label": x.label, "amount_paise": min(cum, fee) - verified, "due": x.due}
    return {"label": "Balance", "amount_paise": fee - verified, "due": ""}


def amount_range(terms: PlanTerms, balance: int, *, first_payment: bool) -> tuple[int, int]:
    """How much a student may claim now: ``(min, max)`` in paise."""
    if balance <= 0:
        return 0, 0
    if not terms.allow_instalments:
        return balance, balance
    lo = min(balance, terms.min_first_paise or 100) if first_payment else min(balance, 100)
    return lo, balance


# --------------------------------------------------------------------------- status


def derive_status(
    *, current: str, verified: int, access_min: int, open_claims: int, enrolled: bool, fee: int
) -> str:
    """The registration status that follows from the money and staff decisions (``deriveStatus``)."""
    if current in MANUAL_STATUSES:
        return current
    if enrolled:
        return "enrolled"
    if verified >= access_min and (verified > 0 or fee == 0):
        return "payment_verified"
    if verified > 0:
        return "partially_paid"
    if open_claims > 0:
        return "pending_verification"
    return "registered"


def eligible(*, status: str, verified: int, access_min: int, fee: int) -> bool:
    """Whether the access policy is satisfied (the registration may be enrolled)."""
    return status not in MANUAL_STATUSES and verified >= access_min and (verified > 0 or fee == 0)


def pay_state(verified: int, fee: int) -> str:
    return "paid" if verified >= fee else "unpaid" if verified <= 0 else "partial"


# Allowed claim decisions: from -> to.
CLAIM_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"verified", "needs_info", "rejected"}),
    "needs_info": frozenset({"verified", "rejected"}),
    "verified": frozenset({"reversed"}),
    "rejected": frozenset(),
    "reversed": frozenset(),
}


def can_move_claim(current: str, to: str) -> bool:
    return to in CLAIM_TRANSITIONS.get(current, frozenset())
