"""Human references (UNB §2): ``SEC-YYMM-XXXXXX`` cases, ``APL-`` unblock requests, ``ACC-``
takeover events, ``INC-`` incidents, ``PRV-`` privacy requests. Six Crockford Base32 characters
(excludes I, L, O, U) from a CSPRNG (30 bits): not sequential, not an authenticator. Uniqueness
is enforced by the UNIQUE columns (callers retry on the vanishingly rare collision)."""

from __future__ import annotations

import re
import secrets

from app.modules.identity import clock

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
REF_RE = re.compile(r"^(SEC|APL|ACC|INC|PRV)-[0-9]{4}-[0-9A-HJKMNP-TV-Z]{6}$")


def make_ref(prefix: str) -> str:
    now = clock.now()
    body = "".join(secrets.choice(CROCKFORD) for _ in range(6))
    return f"{prefix}-{now:%y%m}-{body}"


def valid_ref(ref: str, prefix: str) -> bool:
    return bool(REF_RE.match(ref or "")) and ref.startswith(prefix + "-")
