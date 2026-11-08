"""Encryption of TOTP secrets (``mfa_factors.totp_secret_encrypted``).

AES-256-GCM via ``app.core.crypto.AeadKeyring`` (``cryptography``) with the versioned key
family ``TD_K_TOTP_KEY_V{n}`` / ``TD_K_TOTP_ACTIVE_VERSION``. Stored value:
``v{n}:{nonce}:{ciphertext}`` (ASCII bytes); the AAD binds it to this column.
``totp_wrapped_key`` is no longer used (NULL for new rows): per-row data keys wrapped by KMS
are a later infra task (Planned; ``TD_APP_ENVELOPE_KMS_KEY_ID``).

Rotation / legacy rows: rows written by the earlier HMAC-CTR scheme (dev data only) are NOT
readable any more; run ``python -m app.modules.identity.reencrypt_totp`` once, which
re-encrypts legacy rows (needs ``TD_LOCAL_ENVELOPE_KEY``) and rows under an old key version.
"""

from __future__ import annotations

from app.core.crypto import CryptoError, get_aead_keyring

TOTP_AAD = b"td:mfa_factors.totp_secret"
KEYRING = "totp"

EnvelopeError = CryptoError  # backwards-compatible name


def encrypt_totp_secret(plaintext: str) -> bytes:
    return get_aead_keyring(KEYRING).encrypt(plaintext.encode("utf-8"), TOTP_AAD)


def decrypt_totp_secret(token: bytes) -> str:
    return get_aead_keyring(KEYRING).decrypt(bytes(token), TOTP_AAD).decode("utf-8")


def needs_reencrypt(token: bytes) -> bool:
    return get_aead_keyring(KEYRING).needs_reencrypt(bytes(token))


def encrypt_secret(plaintext: str) -> tuple[bytes, None]:
    """Compatibility shim: ``(totp_secret_encrypted, totp_wrapped_key=None)``."""
    return encrypt_totp_secret(plaintext), None


def decrypt_secret(ciphertext: bytes, wrapped_key: bytes | None = None) -> str:
    """Compatibility shim; ``wrapped_key`` is ignored (AES-GCM keyring scheme)."""
    return decrypt_totp_secret(ciphertext)
