"""One-off / rotation utility: re-encrypt ``mfa_factors.totp_secret_encrypted``.

Handles two cases:

* legacy rows written by the pre-AES-GCM HMAC-CTR envelope (``0x01‖nonce‖ct‖tag`` with a
  data key wrapped under ``sha256(TD_LOCAL_ENVELOPE_KEY)``) — dev data only;
* rows under a non-active ``TD_K_TOTP_KEY_V{n}`` version (key rotation).

    python -m app.modules.identity.reencrypt_totp            # dry run: counts only
    python -m app.modules.identity.reencrypt_totp --apply

Runs under ``system_context`` (platform RLS) on ``DATABASE_URL``.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import AeadKeyring, CryptoError
from app.core.security import load_env_mapping
from app.modules.identity.crypto import decrypt_totp_secret, encrypt_totp_secret, needs_reencrypt
from app.modules.identity.models import MfaFactor

_LEGACY_VERSION = b"\x01"


def _legacy_open(key: bytes, blob: bytes) -> bytes:
    if len(blob) < 1 + 16 + 32 or blob[:1] != _LEGACY_VERSION:
        raise CryptoError("not a legacy envelope")
    k_enc = hmac.new(key, b"td-envelope-enc", hashlib.sha256).digest()
    k_mac = hmac.new(key, b"td-envelope-mac", hashlib.sha256).digest()
    nonce, ct, tag = blob[1:17], blob[17:-32], blob[-32:]
    if not hmac.compare_digest(tag, hmac.new(k_mac, _LEGACY_VERSION + nonce + ct, hashlib.sha256).digest()):
        raise CryptoError("legacy envelope authentication failed")
    stream = bytearray()
    counter = 0
    while len(stream) < len(ct):
        stream += hmac.new(k_enc, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(a ^ b for a, b in zip(ct, stream, strict=False))


def legacy_decrypt(ciphertext: bytes, wrapped_key: bytes, local_envelope_key: str) -> str:
    kek = hashlib.sha256(local_envelope_key.encode("utf-8")).digest()
    dk = _legacy_open(kek, wrapped_key)
    return _legacy_open(dk, ciphertext).decode("utf-8")


def reencrypt_value(
    ciphertext: bytes, wrapped_key: bytes | None, local_envelope_key: str | None
) -> bytes | None:
    """New token for a row that needs it, else None."""
    ciphertext = bytes(ciphertext)
    if AeadKeyring.token_version(ciphertext) is not None:
        if not needs_reencrypt(ciphertext):
            return None
        return encrypt_totp_secret(decrypt_totp_secret(ciphertext))
    if not wrapped_key or not local_envelope_key:
        raise CryptoError("legacy TOTP row needs totp_wrapped_key and TD_LOCAL_ENVELOPE_KEY")
    return encrypt_totp_secret(legacy_decrypt(ciphertext, bytes(wrapped_key), local_envelope_key))


async def reencrypt_all(session: AsyncSession, *, apply: bool) -> tuple[int, int]:
    """Returns ``(rows_needing_change, failures)``; caller owns the transaction."""
    from app.core.firestore.backend import uses_firestore

    legacy_key = load_env_mapping().get("TD_LOCAL_ENVELOPE_KEY")
    if uses_firestore("identity"):
        return await _reencrypt_firestore(legacy_key, apply=apply)
    from app.core.db import system_context

    await system_context(session, "reencrypt_totp")
    rows = (
        await session.execute(select(MfaFactor).where(MfaFactor.totp_secret_encrypted.is_not(None)))
    ).scalars()
    changed = failed = 0
    for f in rows:
        try:
            new = reencrypt_value(f.totp_secret_encrypted or b"", f.totp_wrapped_key, legacy_key)
        except CryptoError:
            failed += 1
            continue
        if new is None:
            continue
        changed += 1
        if apply:
            f.totp_secret_encrypted = new
            f.totp_wrapped_key = None
    await session.flush()
    return changed, failed


async def _reencrypt_firestore(legacy_key: str | None, *, apply: bool) -> tuple[int, int]:
    """``TD_STORE_IDENTITY=firestore``: same pass over ``mfa_factors`` (named job)."""
    from app.modules.identity.repo_firestore import system_repo
    from app.modules.identity.store_specs import MFA

    repo = system_repo("identity.reencrypt_totp")
    changed = failed = 0
    for f in await repo._objs(MfaFactor, MFA):
        if f.totp_secret_encrypted is None:
            continue
        try:
            new = reencrypt_value(f.totp_secret_encrypted, f.totp_wrapped_key, legacy_key)
        except CryptoError:
            failed += 1
            continue
        if new is None:
            continue
        changed += 1
        if apply:
            f.totp_secret_encrypted = new
            f.totp_wrapped_key = None
            await repo.save_factor(f)
    return changed, failed


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - CLI
    p = argparse.ArgumentParser(description="Re-encrypt TOTP secrets under the active k_totp version")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args(argv)

    async def _run() -> tuple[int, int]:
        from app.core.db import NO_POSTGRES, dispose_engine, get_sessionmaker
        from app.core.firestore.backend import uses_firestore

        if uses_firestore("identity"):
            return await reencrypt_all(NO_POSTGRES, apply=args.apply)
        try:
            async with get_sessionmaker()() as s, s.begin():
                return await reencrypt_all(s, apply=args.apply)
        finally:
            await dispose_engine()

    changed, failed = asyncio.run(_run())
    print(f"{'re-encrypted' if args.apply else 'would re-encrypt'}: {changed}; undecryptable: {failed}")
    return 1 if failed else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
