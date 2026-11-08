"""Versioned AES-256-GCM keyrings for field-level encryption (e.g. TOTP secrets).

Keys come from ``TD_K_<NAME>_KEY_V{n}`` (64 hex chars = 256 bits) and
``TD_K_<NAME>_ACTIVE_VERSION``. New ciphertexts use the active version; every loaded version
can still decrypt, so rotation = add ``V{n+1}``, flip ``ACTIVE_VERSION``, run the module's
re-encrypt utility, then retire the old version.

Token format (ASCII, stored as bytes): ``v{n}:{b64url(nonce 12B)}:{b64url(ciphertext‖tag)}``.

KMS: in AWS the key material is a Secrets Manager value injected into the env. Wrapping the
data keys with KMS (``TD_APP_ENVELOPE_KMS_KEY_ID``) is a later infra task (Planned); the
token format's version prefix leaves room for a ``kms{n}:`` scheme.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.security import load_env_mapping

NONCE_BYTES = 12
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
_TOKEN_RE = re.compile(rb"^v([0-9]+):([A-Za-z0-9_-]+={0,2}):([A-Za-z0-9_-]+={0,2})$")


class CryptoError(RuntimeError):
    pass


def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def _b64d(s: bytes) -> bytes:
    s = s.rstrip(b"=")
    return base64.urlsafe_b64decode(s + b"=" * (-len(s) % 4))


def parse_key(raw: str) -> tuple[bytes, bool]:
    """``(key, is_strong)``. Non-hex placeholders are stretched with SHA-256 (dev only;
    the production gate refuses them via ``is_strong=False``)."""
    raw = raw.strip()
    if _HEX64.match(raw):
        return bytes.fromhex(raw), True
    return hashlib.sha256(raw.encode("utf-8")).digest(), False


@dataclass(frozen=True)
class AeadKeyring:
    name: str
    keys: Mapping[int, bytes] = field(repr=False)
    active_version: int
    weak_versions: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if self.active_version not in self.keys:
            raise CryptoError(
                f"AEAD keyring {self.name!r}: active version {self.active_version} is not loaded"
            )
        for v, k in self.keys.items():
            if len(k) != 32:
                raise CryptoError(f"AEAD keyring {self.name!r} v{v}: key must be 256 bits")

    @property
    def versions(self) -> tuple[int, ...]:
        return tuple(sorted(self.keys))

    def encrypt(self, plaintext: bytes, aad: bytes = b"") -> bytes:
        v = self.active_version
        nonce = os.urandom(NONCE_BYTES)
        ct = AESGCM(self.keys[v]).encrypt(nonce, plaintext, aad or None)
        return f"v{v}:{_b64e(nonce)}:{_b64e(ct)}".encode("ascii")

    @staticmethod
    def token_version(token: bytes) -> int | None:
        m = _TOKEN_RE.match(token)
        return int(m.group(1)) if m else None

    def decrypt(self, token: bytes, aad: bytes = b"") -> bytes:
        m = _TOKEN_RE.match(token)
        if not m:
            raise CryptoError("unsupported ciphertext format")
        v = int(m.group(1))
        key = self.keys.get(v)
        if key is None:
            raise CryptoError(f"AEAD keyring {self.name!r}: version {v} not loaded")
        try:
            nonce, ct = _b64d(m.group(2)), _b64d(m.group(3))
        except (binascii.Error, ValueError) as e:
            raise CryptoError("malformed ciphertext") from e
        if len(nonce) != NONCE_BYTES:
            raise CryptoError("malformed ciphertext")
        try:
            return AESGCM(key).decrypt(nonce, ct, aad or None)
        except InvalidTag as e:
            raise CryptoError("ciphertext authentication failed") from e

    def needs_reencrypt(self, token: bytes) -> bool:
        return self.token_version(token) != self.active_version

    @classmethod
    def from_env(
        cls,
        name: str,
        env: Mapping[str, str | None] | None = None,
        *,
        dev_fallback: str | None = None,
    ) -> AeadKeyring:
        """Load ``TD_K_<NAME>_KEY_V{n}`` + ``TD_K_<NAME>_ACTIVE_VERSION``. ``dev_fallback``
        (non-production only) supplies v1 when no version is configured at all."""
        source = env if env is not None else load_env_mapping()
        prefix = f"TD_K_{name.upper()}_KEY_V"
        keys: dict[int, bytes] = {}
        weak: set[int] = set()
        for k, val in source.items():
            if k.startswith(prefix) and val and k[len(prefix) :].isdigit():
                v = int(k[len(prefix) :])
                keys[v], strong = parse_key(val)
                if not strong:
                    weak.add(v)
        if not keys and dev_fallback:
            keys[1] = hashlib.sha256(f"td-dev-{name}:{dev_fallback}".encode()).digest()
            weak.add(1)
        active_raw = source.get(f"TD_K_{name.upper()}_ACTIVE_VERSION") or "1"
        try:
            active = int(active_raw)
        except ValueError as e:
            raise CryptoError(f"TD_K_{name.upper()}_ACTIVE_VERSION must be an integer") from e
        return cls(name=name.lower(), keys=keys, active_version=active, weak_versions=frozenset(weak))


_rings: dict[str, AeadKeyring] = {}


def get_aead_keyring(name: str) -> AeadKeyring:
    """Process-wide cached AEAD keyring (``totp`` = k_totp). Outside production a missing
    keyring falls back to a key derived from ``TD_LOCAL_ENVELOPE_KEY`` (flagged weak)."""
    ring = _rings.get(name)
    if ring is None:
        from app.core.config import get_settings

        env = load_env_mapping()
        fallback = None if get_settings().is_production else (env.get("TD_LOCAL_ENVELOPE_KEY") or "local")
        ring = AeadKeyring.from_env(name, env, dev_fallback=fallback)
        _rings[name] = ring
    return ring


def reset_aead_keyrings() -> None:
    _rings.clear()


REQUIRED_AEAD_KEYRINGS = ("totp",)
