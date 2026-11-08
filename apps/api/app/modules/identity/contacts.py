"""Contact normalisation, masking and keyed hashing (login identifiers, OTP destinations)."""

from __future__ import annotations

import re

from app.core.security import get_keyring

EMAIL_RE = re.compile(
    r"^[^@\s]{1,64}@[A-Za-z0-9](?:[A-Za-z0-9-]{0,62}[A-Za-z0-9])?(?:\.[A-Za-z0-9-]{1,63})+$"
)
E164_RE = re.compile(r"^\+[1-9][0-9]{7,14}$")


def normalize_email(raw: str) -> str | None:
    v = (raw or "").strip().lower()
    if len(v) > 254 or not EMAIL_RE.match(v):
        return None
    return v


def normalize_phone(raw: str) -> str | None:
    v = re.sub(r"[\s\-()]", "", raw or "")
    if re.fullmatch(r"[6-9][0-9]{9}", v):  # bare Indian mobile number
        v = "+91" + v
    elif re.fullmatch(r"0[6-9][0-9]{9}", v):
        v = "+91" + v[1:]
    return v if E164_RE.match(v) else None


def classify_identifier(raw: str) -> tuple[str, str] | None:
    """``("email"|"phone", normalised)`` or None."""
    if "@" in (raw or ""):
        e = normalize_email(raw)
        return ("email", e) if e else None
    p = normalize_phone(raw)
    return ("phone", p) if p else None


def mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, domain = email.split("@", 1)
    return f"{local[:1]}****@{domain}"


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    if phone.startswith("+91") and len(phone) == 13:
        return f"+91 {phone[3:5]}xxxxxx{phone[-2:]}"
    return f"{phone[:3]}xxxxxx{phone[-2:]}"


def identifier_digests(kind: str, value: str) -> list[tuple[int, bytes]]:
    """HMAC(k_login_v{n}) of the normalised identifier for every loaded key version."""
    return get_keyring("login").all_digests(f"{kind}:{value}")


def identifier_digest(kind: str, value: str) -> tuple[int, bytes]:
    return get_keyring("login").sign(f"{kind}:{value}")


def destination_hmac(channel: str, value: str) -> bytes:
    kind = "email" if channel == "email" else "phone"
    return get_keyring("login").digest(f"dest:{kind}:{value}")
