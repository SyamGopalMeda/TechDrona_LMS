"""Security primitives: password hashing, random tokens, token hashing, versioned HMAC keys.

* Passwords: Argon2id m=19456 KiB, t=2, p=1 (brief §1, NIST 800-63B-4 / OWASP).
* Tokens: CSPRNG, >= 128 bits (sessions use 256 bits), base64url without padding.
* Stored token form: SHA-256 digest (32 bytes) — ``auth_sessions.token_hash`` etc.
* HMAC keys are versioned (``TD_K_<NAME>_KEY_V{n}`` + ``TD_K_<NAME>_ACTIVE_VERSION``).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from dotenv import dotenv_values

# --------------------------------------------------------------------------- passwords

ARGON2_MEMORY_KIB = 19456
ARGON2_TIME_COST = 2
ARGON2_PARALLELISM = 1

_hasher = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_KIB,
    parallelism=ARGON2_PARALLELISM,
    hash_len=32,
    salt_len=16,
)
# Pre-computed hash used to equalise timing for unknown identifiers.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(24))


def hash_password(password: str) -> str:
    """Return an encoded Argon2id hash (``$argon2id$v=19$m=19456,t=2,p=1$...``)."""
    return _hasher.hash(password)


def verify_password(encoded: str | None, password: str) -> bool:
    """Constant-work verification. ``encoded=None`` (unknown user) still burns one hash."""
    try:
        return _hasher.verify(encoded or _DUMMY_HASH, password) and encoded is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(encoded: str) -> bool:
    return _hasher.check_needs_rehash(encoded)


# --------------------------------------------------------------------------- tokens

MIN_TOKEN_BYTES = 16  # 128 bits
SESSION_TOKEN_BYTES = 32  # 256 bits (ADR-0002)


def generate_token(nbytes: int = SESSION_TOKEN_BYTES) -> str:
    """URL-safe random token from the OS CSPRNG. Refuses fewer than 128 bits."""
    if nbytes < MIN_TOKEN_BYTES:
        raise ValueError("tokens must carry at least 128 bits of entropy")
    return base64.urlsafe_b64encode(secrets.token_bytes(nbytes)).rstrip(b"=").decode("ascii")


def generate_numeric_otp(digits: int = 6) -> str:
    if not 6 <= digits <= 10:
        raise ValueError("OTP length must be 6..10")
    return f"{secrets.randbelow(10**digits):0{digits}d}"


def hash_token(token: str | bytes) -> bytes:
    """SHA-256 digest (32 bytes) — the only form in which tokens are stored or cached."""
    data = token.encode("utf-8") if isinstance(token, str) else token
    return hashlib.sha256(data).digest()


def constant_time_equals(a: str | bytes, b: str | bytes) -> bool:
    a_b = a.encode() if isinstance(a, str) else a
    b_b = b.encode() if isinstance(b, str) else b
    return hmac.compare_digest(a_b, b_b)


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


# --------------------------------------------------------------------------- versioned HMAC

_HEX_RE = re.compile(r"^[0-9a-fA-F]{32,}$")


class KeyringError(RuntimeError):
    pass


def _is_strong_hex(raw: str) -> bool:
    """A production key: >= 256-bit hex (64+ hex chars), not a placeholder."""
    raw = raw.strip()
    return bool(_HEX_RE.match(raw)) and len(raw) % 2 == 0 and len(raw) >= 64


def _key_bytes(raw: str) -> bytes:
    raw = raw.strip()
    if _HEX_RE.match(raw) and len(raw) % 2 == 0:
        return bytes.fromhex(raw)
    # Local placeholders are not hex; accept their UTF-8 bytes (refused in production).
    return raw.encode("utf-8")


@dataclass(frozen=True)
class HmacKeyring:
    """A named family of HMAC-SHA256 keys indexed by version.

    New digests use ``active_version``; lookups compute ``all_digests`` for every loaded
    version (``login_attempts`` never re-hash) or match then re-hash in place (``devices``).
    """

    name: str
    keys: Mapping[int, bytes] = field(repr=False)
    active_version: int
    # Versions whose configured value is not >= 256-bit hex (local placeholders such as
    # ``local_dev_key_REPLACE...``). Refused by the production startup gate (SEC-06).
    weak_versions: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if self.active_version not in self.keys:
            raise KeyringError(
                f"HMAC keyring {self.name!r}: active version {self.active_version} is not loaded"
            )
        for v, k in self.keys.items():
            if len(k) < 16:
                raise KeyringError(f"HMAC keyring {self.name!r} v{v}: key shorter than 128 bits")

    @property
    def versions(self) -> tuple[int, ...]:
        return tuple(sorted(self.keys))

    def digest(self, data: str | bytes, version: int | None = None) -> bytes:
        v = self.active_version if version is None else version
        key = self.keys.get(v)
        if key is None:
            raise KeyringError(f"HMAC keyring {self.name!r}: version {v} not loaded")
        msg = data.encode("utf-8") if isinstance(data, str) else data
        return hmac.new(key, msg, hashlib.sha256).digest()

    def sign(self, data: str | bytes) -> tuple[int, bytes]:
        """``(key_version, digest)`` under the active version."""
        return self.active_version, self.digest(data)

    def all_digests(self, data: str | bytes) -> list[tuple[int, bytes]]:
        """Digests under every loaded version (newest first) for lookups across rotation."""
        return [(v, self.digest(data, v)) for v in sorted(self.keys, reverse=True)]

    def verify(self, data: str | bytes, digest: bytes, version: int) -> bool:
        if version not in self.keys:
            return False
        return hmac.compare_digest(self.digest(data, version), digest)

    def needs_rehash(self, version: int) -> bool:
        return version != self.active_version

    @classmethod
    def from_env(cls, name: str, env: Mapping[str, str | None] | None = None) -> HmacKeyring:
        """Load ``TD_K_<NAME>_KEY_V{n}`` and ``TD_K_<NAME>_ACTIVE_VERSION``."""
        source = env if env is not None else load_env_mapping()
        prefix = f"TD_K_{name.upper()}_KEY_V"
        keys: dict[int, bytes] = {}
        weak: set[int] = set()
        for k, val in source.items():
            if k.startswith(prefix) and val:
                suffix = k[len(prefix) :]
                if suffix.isdigit():
                    keys[int(suffix)] = _key_bytes(val)
                    if not _is_strong_hex(val):
                        weak.add(int(suffix))
        active_raw = source.get(f"TD_K_{name.upper()}_ACTIVE_VERSION") or "1"
        try:
            active = int(active_raw)
        except ValueError as e:
            raise KeyringError(f"TD_K_{name.upper()}_ACTIVE_VERSION must be an integer") from e
        return cls(name=name.lower(), keys=keys, active_version=active, weak_versions=frozenset(weak))


def load_env_mapping() -> dict[str, str | None]:
    """Merged view of .env files and the process environment (environment wins)."""
    from app.core.config import ENV_FILES

    merged: dict[str, str | None] = {}
    for f in ENV_FILES:
        if f.is_file():
            merged.update(dotenv_values(f))
    merged.update(os.environ)
    return merged


_keyrings: dict[str, HmacKeyring] = {}

REQUIRED_KEYRINGS = ("device", "login")


def get_keyring(name: str) -> HmacKeyring:
    """Process-wide cached keyring (``device`` = k_device, ``login`` = k_login)."""
    ring = _keyrings.get(name)
    if ring is None:
        ring = HmacKeyring.from_env(name)
        _keyrings[name] = ring
    return ring


def reset_keyrings() -> None:
    _keyrings.clear()
