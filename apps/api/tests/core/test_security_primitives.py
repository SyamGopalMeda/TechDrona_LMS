from __future__ import annotations

import pytest

from app.core.security import (
    HmacKeyring,
    KeyringError,
    generate_numeric_otp,
    generate_token,
    hash_password,
    hash_token,
    password_needs_rehash,
    verify_password,
)


def test_argon2id_parameters_and_verify() -> None:
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert verify_password(h, "correct horse battery staple")
    assert not verify_password(h, "wrong password here!!")
    assert not password_needs_rehash(h)
    assert hash_password("same") != hash_password("same")  # salted


def test_verify_unknown_user_is_false() -> None:
    assert verify_password(None, "anything") is False
    assert verify_password("not-a-hash", "anything") is False


def test_tokens_are_random_and_long_enough() -> None:
    tokens = {generate_token() for _ in range(200)}
    assert len(tokens) == 200
    t = next(iter(tokens))
    assert len(t) == 43  # 256-bit base64url, no padding
    assert "=" not in t
    assert len(generate_token(16)) == 22
    with pytest.raises(ValueError):
        generate_token(15)  # < 128 bits refused


def test_otp_format() -> None:
    otp = generate_numeric_otp()
    assert len(otp) == 6 and otp.isdigit()


def test_token_hash_is_sha256() -> None:
    import hashlib

    t = generate_token()
    assert hash_token(t) == hashlib.sha256(t.encode()).digest()
    assert len(hash_token(t)) == 32
    assert hash_token(t) == hash_token(t.encode())


def _ring(active: int, **keys: str) -> HmacKeyring:
    env = {f"TD_K_DEVICE_KEY_{k}": v for k, v in keys.items()}
    env["TD_K_DEVICE_ACTIVE_VERSION"] = str(active)
    return HmacKeyring.from_env("device", env)


def test_hmac_rotation() -> None:
    k1, k2 = "ab" * 32, "cd" * 32
    ring1 = _ring(1, V1=k1)
    v, d1 = ring1.sign("device-raw-id")
    assert v == 1 and len(d1) == 32

    ring2 = _ring(2, V1=k1, V2=k2)
    v2, d2 = ring2.sign("device-raw-id")
    assert v2 == 2 and d2 != d1
    # Old digests stay verifiable during rotation, and are flagged for re-hash.
    assert ring2.verify("device-raw-id", d1, 1)
    assert ring2.needs_rehash(1) and not ring2.needs_rehash(2)
    assert [ver for ver, _ in ring2.all_digests("device-raw-id")] == [2, 1]
    assert (1, d1) in ring2.all_digests("device-raw-id")
    assert not ring2.verify("other-id", d1, 1)
    assert not ring2.verify("device-raw-id", d1, 9)  # unknown version


def test_hmac_active_version_must_be_loaded() -> None:
    with pytest.raises(KeyringError):
        _ring(2, V1="ab" * 32)


def test_hmac_rejects_short_keys() -> None:
    with pytest.raises(KeyringError):
        _ring(1, V1="short")
