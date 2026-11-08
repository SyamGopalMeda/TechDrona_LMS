"""Password policy (NIST SP 800-63B-4, brief §1): length only, no composition rules.

* min 15 characters without MFA, 8 with an enrolled MFA factor; max 128;
* breached/common-password blocklist (``data/common_passwords.txt``, local top-N list) plus
  product terms ("techdrona", "drona") and context words (the user's own email local part);
* trivially repetitive values (a single repeated character) are refused.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache
from pathlib import Path

MIN_LENGTH_NO_MFA = 15
MIN_LENGTH_WITH_MFA = 8
MAX_LENGTH = 128
PRODUCT_TERMS = ("techdrona", "tech drona", "drona")

_DATA = Path(__file__).resolve().parent / "data" / "common_passwords.txt"


@lru_cache(maxsize=1)
def blocklist() -> frozenset[str]:
    out: set[str] = set()
    for line in _DATA.read_text(encoding="utf-8").splitlines():
        v = line.strip()
        if v and not v.startswith("#"):
            out.add(v.lower())
    return frozenset(out)


def _normalise(pw: str) -> str:
    return unicodedata.normalize("NFKC", pw)


def password_problems(password: str, *, has_mfa: bool = False, context: tuple[str, ...] = ()) -> list[str]:
    """Return validation codes (empty list = acceptable)."""
    pw = _normalise(password)
    minimum = MIN_LENGTH_WITH_MFA if has_mfa else MIN_LENGTH_NO_MFA
    if len(pw) > MAX_LENGTH:
        return ["password_too_long"]
    if len(pw) < minimum:
        return ["password_too_short"]
    low = pw.lower()
    compact = low.replace(" ", "").replace("-", "").replace("_", "")
    if low in blocklist() or compact in blocklist() or len(set(low)) <= 2:
        return ["password_breached"]
    if any(t.replace(" ", "") in compact for t in PRODUCT_TERMS):
        return ["password_breached"]
    for word in context:
        w = (word or "").strip().lower()
        if len(w) >= 4 and w in low:
            return ["password_contains_personal_info"]
    return []
