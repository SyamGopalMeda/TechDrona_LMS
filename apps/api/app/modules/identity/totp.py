"""RFC 6238 TOTP (SHA-1, 6 digits, 30 s step) with a ±1 step window, via ``pyotp``.

Replay guard: a code is accepted only for a step strictly greater than
``mfa_factors.totp_last_used_step``.
"""

from __future__ import annotations

import time

import pyotp
from pyotp.utils import strings_equal

STEP_SECONDS = 30
DIGITS = 6
WINDOW = 1


def random_base32(nbytes: int = 20) -> str:
    # pyotp.random_base32(length) counts base32 characters (5 bits each).
    return pyotp.random_base32(length=nbytes * 8 // 5)


def _norm(secret_b32: str) -> str:
    return secret_b32.strip().replace(" ", "").upper()


def hotp(secret_b32: str, counter: int, digits: int = DIGITS) -> str:
    return pyotp.HOTP(_norm(secret_b32), digits=digits).at(counter)


def current_step(at: float | None = None) -> int:
    return int((time.time() if at is None else at) // STEP_SECONDS)


def totp(secret_b32: str, at: float | None = None) -> str:
    return pyotp.TOTP(_norm(secret_b32), digits=DIGITS, interval=STEP_SECONDS).at(
        int(time.time() if at is None else at)
    )


def match_step(
    secret_b32: str, code: str, *, at: float | None = None, last_used_step: int | None = None
) -> int | None:
    """Return the matching step (to store as ``totp_last_used_step``) or None."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    gen = pyotp.HOTP(_norm(secret_b32), digits=DIGITS)
    now_step = current_step(at)
    for step in range(now_step - WINDOW, now_step + WINDOW + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if strings_equal(gen.at(step), code):
            return step
    return None


def is_replay(
    secret_b32: str, code: str, *, at: float | None = None, last_used_step: int | None = None
) -> bool:
    """True when ``code`` is valid for a step in the window that was already used (E2E-12)."""
    if last_used_step is None:
        return False
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return False
    gen = pyotp.HOTP(_norm(secret_b32), digits=DIGITS)
    now_step = current_step(at)
    return any(
        strings_equal(gen.at(step), code)
        for step in range(now_step - WINDOW, now_step + WINDOW + 1)
        if step <= last_used_step
    )


def provisioning_uri(secret_b32: str, account: str, issuer: str = "Tech Drona") -> str:
    return pyotp.TOTP(_norm(secret_b32), digits=DIGITS, interval=STEP_SECONDS).provisioning_uri(
        name=account, issuer_name=issuer
    )
