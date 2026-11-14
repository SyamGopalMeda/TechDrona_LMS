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


RELAXED_MIN_LENGTH = 6


def relaxed_policy() -> bool:
    """``TD_PASSWORD_POLICY_RELAXED=true`` (owner decision 2026-11-11, testing phase): simple
    passwords allowed, min 6 characters, no blocklist / personal-info checks. Never in production
    (``TD_SIMPLE_AUTH`` turns it on in every environment)."""
    import os

    from app.core.config import get_settings

    flag = os.environ.get("TD_PASSWORD_POLICY_RELAXED", "").strip().lower() in ("1", "true", "yes", "on")
    # TD_SIMPLE_AUTH (permanent owner decision, every APP_ENV) uses the same relaxed policy.
    return (flag and not get_settings().is_production) or get_settings().simple_auth


def password_problems(password: str, *, has_mfa: bool = False, context: tuple[str, ...] = ()) -> list[str]:
    """Return validation codes (empty list = acceptable)."""
    pw = _normalise(password)
    if relaxed_policy():
        if len(pw) > MAX_LENGTH:
            return ["password_too_long"]
        return ["password_too_short"] if len(pw) < RELAXED_MIN_LENGTH else []
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
