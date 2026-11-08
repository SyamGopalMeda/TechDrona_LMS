"""Envelope encryption of hidden test cases (system-architecture §9.3, ADR-0005 §7).

* Every hidden case gets a fresh 256-bit data key (DK). Input and expected output are each
  sealed with AES-256-GCM under DK (96-bit random nonce, AAD binds problem id + part).
* DK is wrapped with AES-256-GCM under a versioned key-encryption key (KEK) loaded from
  ``TD_K_TESTCASE_KEY_V{n}`` (64 hex chars) with ``TD_K_TESTCASE_ACTIVE_VERSION``.
  Phase-1 stand-in for KMS key ``td-judge-testcases``: in AWS only the ``worker-judge`` task
  definition receives these variables, so only the judge worker can unwrap. The API process
  only needs them to *author* cases (wrap); production deployments should move wrapping to
  KMS ``GenerateDataKey`` so the API never holds decrypt capability (open item).
* Key rotation: add ``V{n+1}``, bump the active version, run ``rotate_wrapped_keys`` (re-wraps
  DKs; ciphertext blobs are untouched), then retire the old version.

Wire format of ``wrapped_data_key``: ``0x01 ‖ version:u16be ‖ nonce:12 ‖ AESGCM(KEK, DK)``.
Blob format: ``nonce:12 ‖ AESGCM(DK, plaintext)``.
"""

from __future__ import annotations

import hashlib
import os
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import get_settings
from app.core.security import load_env_mapping

ENV_PREFIX = "TD_K_TESTCASE_KEY_V"
ENV_ACTIVE = "TD_K_TESTCASE_ACTIVE_VERSION"
FORMAT_V1 = 1
_NONCE = 12
_HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")
# Non-production fallback when no key is configured (refused in production by startup check).
_DEV_FALLBACK = hashlib.sha256(b"td-local-dev-testcase-kek-NOT-FOR-PRODUCTION").digest()


class TestCaseCryptoError(RuntimeError):
    __test__ = False  # not a pytest class


@dataclass(frozen=True)
class TestCaseKeyring:
    __test__ = False

    keys: Mapping[int, bytes] = field(repr=False)
    active_version: int
    is_dev_fallback: bool = False
    weak_versions: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if self.active_version not in self.keys:
            raise TestCaseCryptoError(f"testcase keyring: active version {self.active_version} not loaded")
        for v, k in self.keys.items():
            if len(k) != 32:
                raise TestCaseCryptoError(f"testcase keyring v{v}: key must be 256 bits")

    @classmethod
    def from_env(cls, env: Mapping[str, str | None] | None = None) -> TestCaseKeyring:
        source = env if env is not None else load_env_mapping()
        keys: dict[int, bytes] = {}
        weak: list[int] = []
        for k, raw in source.items():
            if not (k.startswith(ENV_PREFIX) and raw and k[len(ENV_PREFIX) :].isdigit()):
                continue
            v = int(k[len(ENV_PREFIX) :])
            raw = raw.strip()
            if _HEX64.match(raw):
                keys[v] = bytes.fromhex(raw)
            else:  # local placeholder: derive, but flag it (production refuses)
                keys[v] = hashlib.sha256(raw.encode("utf-8")).digest()
                weak.append(v)
        if not keys:
            return cls(keys={1: _DEV_FALLBACK}, active_version=1, is_dev_fallback=True)
        try:
            active = int(source.get(ENV_ACTIVE) or max(keys))
        except ValueError as e:
            raise TestCaseCryptoError(f"{ENV_ACTIVE} must be an integer") from e
        return cls(keys=keys, active_version=active, weak_versions=tuple(sorted(weak)))

    @property
    def production_safe(self) -> bool:
        return not self.is_dev_fallback and not self.weak_versions


_ring: TestCaseKeyring | None = None


def get_testcase_keyring() -> TestCaseKeyring:
    """Process-wide keyring. In production a missing/non-hex key is a hard error."""
    global _ring
    if _ring is None:
        ring = TestCaseKeyring.from_env()
        if get_settings().is_production and not ring.production_safe:
            raise TestCaseCryptoError(
                "refusing to use the test-case keyring in production: set TD_K_TESTCASE_KEY_V{n} "
                "to 64 hex chars (256-bit) and TD_K_TESTCASE_ACTIVE_VERSION"
            )
        _ring = ring
    return _ring


def reset_testcase_keyring() -> None:
    global _ring
    _ring = None


def _aad(problem_id: uuid.UUID, part: str) -> bytes:
    return b"td-testcase|" + part.encode() + b"|" + problem_id.bytes


@dataclass(frozen=True, slots=True)
class SealedCase:
    wrapped_data_key: bytes
    input_blob: bytes
    expected_blob: bytes
    input_sha256: bytes
    expected_sha256: bytes
    size_bytes: int


def wrap_data_key(dk: bytes, problem_id: uuid.UUID, ring: TestCaseKeyring | None = None) -> bytes:
    r = ring or get_testcase_keyring()
    nonce = os.urandom(_NONCE)
    ct = AESGCM(r.keys[r.active_version]).encrypt(nonce, dk, _aad(problem_id, "dk"))
    return bytes([FORMAT_V1]) + r.active_version.to_bytes(2, "big") + nonce + ct


def key_version(wrapped: bytes) -> int:
    if len(wrapped) < 3 or wrapped[0] != FORMAT_V1:
        raise TestCaseCryptoError("unknown wrapped key format")
    return int.from_bytes(wrapped[1:3], "big")


def unwrap_data_key(wrapped: bytes, problem_id: uuid.UUID, ring: TestCaseKeyring | None = None) -> bytes:
    r = ring or get_testcase_keyring()
    v = key_version(wrapped)
    kek = r.keys.get(v)
    if kek is None:
        raise TestCaseCryptoError(f"testcase key version {v} not loaded")
    nonce, ct = wrapped[3 : 3 + _NONCE], wrapped[3 + _NONCE :]
    try:
        return AESGCM(kek).decrypt(nonce, ct, _aad(problem_id, "dk"))
    except InvalidTag as e:
        raise TestCaseCryptoError("wrapped data key failed authentication") from e


def seal_case(
    problem_id: uuid.UUID, input_text: str, expected_text: str, ring: TestCaseKeyring | None = None
) -> SealedCase:
    dk = AESGCM.generate_key(bit_length=256)
    aes = AESGCM(dk)
    inp, exp = input_text.encode("utf-8"), expected_text.encode("utf-8")
    n1, n2 = os.urandom(_NONCE), os.urandom(_NONCE)
    return SealedCase(
        wrapped_data_key=wrap_data_key(dk, problem_id, ring),
        input_blob=n1 + aes.encrypt(n1, inp, _aad(problem_id, "input")),
        expected_blob=n2 + aes.encrypt(n2, exp, _aad(problem_id, "expected")),
        input_sha256=hashlib.sha256(inp).digest(),
        expected_sha256=hashlib.sha256(exp).digest(),
        size_bytes=len(inp) + len(exp),
    )


def open_case(
    problem_id: uuid.UUID,
    wrapped: bytes,
    input_blob: bytes,
    expected_blob: bytes,
    ring: TestCaseKeyring | None = None,
) -> tuple[str, str]:
    """Decrypt a hidden case. Call ONLY from the judge worker path."""
    dk = unwrap_data_key(wrapped, problem_id, ring)
    aes = AESGCM(dk)
    try:
        inp = aes.decrypt(input_blob[:_NONCE], input_blob[_NONCE:], _aad(problem_id, "input"))
        exp = aes.decrypt(expected_blob[:_NONCE], expected_blob[_NONCE:], _aad(problem_id, "expected"))
    except InvalidTag as e:
        raise TestCaseCryptoError("test case ciphertext failed authentication") from e
    return inp.decode("utf-8"), exp.decode("utf-8")


def rewrap(wrapped: bytes, problem_id: uuid.UUID, ring: TestCaseKeyring | None = None) -> bytes:
    """Re-wrap a data key under the active KEK version (rotation); no-op if already active."""
    r = ring or get_testcase_keyring()
    if key_version(wrapped) == r.active_version:
        return wrapped
    return wrap_data_key(unwrap_data_key(wrapped, problem_id, r), problem_id, r)
