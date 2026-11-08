"""TOTP (pyotp, RFC 6238/4226 vectors) and AES-256-GCM secret encryption + re-encrypt utility."""

from __future__ import annotations

import hashlib
import hmac
import os
from urllib.parse import parse_qs, urlparse

import pytest

from app.core.crypto import AeadKeyring, CryptoError, get_aead_keyring, reset_aead_keyrings
from app.modules.identity import totp
from app.modules.identity.crypto import (
    decrypt_secret,
    decrypt_totp_secret,
    encrypt_secret,
    encrypt_totp_secret,
    needs_reencrypt,
)
from app.modules.identity.reencrypt_totp import legacy_decrypt, reencrypt_value

RFC_SECRET = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"  # b"12345678901234567890"


@pytest.mark.parametrize(
    ("t", "code8"),
    [
        (59, "94287082"),
        (1111111109, "07081804"),
        (1111111111, "14050471"),
        (1234567890, "89005924"),
        (2000000000, "69279037"),
        (20000000000, "65353130"),
    ],
)
def test_rfc6238_sha1_vectors(t: int, code8: str) -> None:
    assert totp.hotp(RFC_SECRET, totp.current_step(t), digits=8) == code8
    assert totp.totp(RFC_SECRET, at=t) == code8[-6:]


def test_rfc4226_hotp_vectors() -> None:
    expected = ["755224", "287082", "359152", "969429", "338314", "254676", "287922", "162583"]
    assert [totp.hotp(RFC_SECRET, i) for i in range(8)] == expected


def test_match_step_window_and_replay_guard() -> None:
    t = 1_700_000_000
    step = totp.current_step(t)
    prev_code = totp.hotp(RFC_SECRET, step - 1)
    assert totp.match_step(RFC_SECRET, totp.totp(RFC_SECRET, at=t), at=t) == step
    assert totp.match_step(RFC_SECRET, prev_code, at=t) == step - 1
    assert totp.match_step(RFC_SECRET, totp.hotp(RFC_SECRET, step - 2), at=t) is None
    assert totp.match_step(RFC_SECRET, prev_code, at=t, last_used_step=step - 1) is None
    assert totp.match_step(RFC_SECRET, "12a456", at=t) is None


def test_random_secret_and_uri() -> None:
    s = totp.random_base32()
    assert len(s) == 32 and s.isalnum()
    uri = totp.provisioning_uri(s, "a@example.com")
    u = urlparse(uri)
    assert u.scheme == "otpauth" and u.netloc == "totp"
    assert parse_qs(u.query)["secret"] == [s] and parse_qs(u.query)["issuer"] == ["Tech Drona"]


# --------------------------------------------------------------------------- AES-256-GCM


def test_encrypt_format_and_roundtrip() -> None:
    tok = encrypt_totp_secret(RFC_SECRET)
    parts = tok.split(b":")
    assert parts[0] == b"v1" and len(parts) == 3
    assert RFC_SECRET.encode() not in tok
    assert decrypt_totp_secret(tok) == RFC_SECRET
    assert encrypt_totp_secret(RFC_SECRET) != tok  # fresh nonce
    ct, wrapped = encrypt_secret(RFC_SECRET)  # compatibility shim
    assert wrapped is None and decrypt_secret(ct, None) == RFC_SECRET


def test_tamper_and_wrong_aad_rejected() -> None:
    tok = encrypt_totp_secret(RFC_SECRET)
    head, nonce, ct = tok.split(b":")
    flipped = ct[:-2] + (b"A" if ct[-2:-1] != b"A" else b"B") + ct[-1:]
    with pytest.raises(CryptoError):
        decrypt_totp_secret(b":".join([head, nonce, flipped]))
    with pytest.raises(CryptoError):
        get_aead_keyring("totp").decrypt(tok, b"other-column")
    with pytest.raises(CryptoError):
        decrypt_totp_secret(b"\x01garbage")


def test_versioned_rotation() -> None:
    k1, k2 = "aa" * 32, "bb" * 32
    old = AeadKeyring.from_env("totp", {"TD_K_TOTP_KEY_V1": k1, "TD_K_TOTP_ACTIVE_VERSION": "1"})
    new = AeadKeyring.from_env(
        "totp", {"TD_K_TOTP_KEY_V1": k1, "TD_K_TOTP_KEY_V2": k2, "TD_K_TOTP_ACTIVE_VERSION": "2"}
    )
    tok = old.encrypt(b"s3cret", b"aad")
    assert new.decrypt(tok, b"aad") == b"s3cret"
    assert new.needs_reencrypt(tok) and not old.needs_reencrypt(tok)
    assert new.encrypt(b"x").startswith(b"v2:")
    assert not new.weak_versions
    with pytest.raises(CryptoError):
        AeadKeyring.from_env("totp", {"TD_K_TOTP_KEY_V1": k1, "TD_K_TOTP_ACTIVE_VERSION": "3"})
    weak = AeadKeyring.from_env("totp", {"TD_K_TOTP_KEY_V1": "placeholder-REPLACE"})
    assert weak.weak_versions == frozenset({1})


def test_production_gate_refuses_weak_or_missing_totp_key(monkeypatch) -> None:
    from app.core.startup_checks import production_problems
    from tests.core.test_logging_and_startup import _prod

    monkeypatch.setenv("TD_K_TOTP_KEY_V1", "placeholder-REPLACE")
    reset_aead_keyrings()
    try:
        assert any("AEAD keyring totp" in p for p in production_problems(_prod()))
        monkeypatch.delenv("TD_K_TOTP_KEY_V1")
        reset_aead_keyrings()
        problems = production_problems(_prod())
        assert any("totp" in p and "not loaded" in p for p in problems), problems
    finally:
        monkeypatch.undo()
        reset_aead_keyrings()


# --------------------------------------------------------------------------- re-encrypt utility


def _legacy_seal(key: bytes, plaintext: bytes) -> bytes:
    k_enc = hmac.new(key, b"td-envelope-enc", hashlib.sha256).digest()
    k_mac = hmac.new(key, b"td-envelope-mac", hashlib.sha256).digest()
    nonce = os.urandom(16)
    stream = bytearray()
    c = 0
    while len(stream) < len(plaintext):
        stream += hmac.new(k_enc, nonce + c.to_bytes(8, "big"), hashlib.sha256).digest()
        c += 1
    ct = bytes(a ^ b for a, b in zip(plaintext, stream, strict=False))
    return b"\x01" + nonce + ct + hmac.new(k_mac, b"\x01" + nonce + ct, hashlib.sha256).digest()


def test_reencrypt_legacy_row() -> None:
    local_key = "local-envelope-key-REPLACE-with-64-hex"
    kek = hashlib.sha256(local_key.encode()).digest()
    dk = os.urandom(32)
    legacy_ct, wrapped = _legacy_seal(dk, RFC_SECRET.encode()), _legacy_seal(kek, dk)
    assert legacy_decrypt(legacy_ct, wrapped, local_key) == RFC_SECRET
    new = reencrypt_value(legacy_ct, wrapped, local_key)
    assert new is not None and new.startswith(b"v1:")
    assert decrypt_totp_secret(new) == RFC_SECRET
    assert reencrypt_value(new, None, None) is None and not needs_reencrypt(new)
    with pytest.raises(CryptoError):
        reencrypt_value(legacy_ct, wrapped, "wrong-key")


async def test_reencrypt_all_rewrites_legacy_rows(db, monkeypatch) -> None:
    from sqlalchemy import select

    from app.modules.identity.models import MfaFactor
    from app.modules.identity.reencrypt_totp import reencrypt_all
    from tests.identity.factory import make_user

    u = await make_user(db, with_totp=True)
    assert u.totp_secret
    f = (await db.execute(select(MfaFactor).where(MfaFactor.user_id == u.id))).scalar_one()
    local_key = "dev-key-for-test"
    monkeypatch.setenv("TD_LOCAL_ENVELOPE_KEY", local_key)
    kek = hashlib.sha256(local_key.encode()).digest()
    dk = os.urandom(32)
    f.totp_secret_encrypted = _legacy_seal(dk, u.totp_secret.encode())
    f.totp_wrapped_key = _legacy_seal(kek, dk)
    await db.flush()
    changed, failed = await reencrypt_all(db, apply=True)
    assert changed >= 1 and failed == 0
    await db.refresh(f)
    assert f.totp_wrapped_key is None
    assert decrypt_totp_secret(f.totp_secret_encrypted or b"") == u.totp_secret
    assert (await reencrypt_all(db, apply=True))[0] == 0
