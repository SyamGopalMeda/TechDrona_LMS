"""Private object storage for report exports (ANL-13..15).

* ``S3ExportStore`` — PUT (SigV4, ``UNSIGNED``-free: the payload hash is signed) into the
  private ``S3_BUCKET_EXPORTS`` bucket with SSE, downloads through a short-lived presigned GET
  (``app.modules.media.storage.presign_get``, ≤ 5 min). Not verified against AWS (no
  credentials in this environment); works against SeaweedFS/MinIO via ``S3_ENDPOINT_URL``.
* ``FakeExportStore`` — clearly named local-directory fake (default outside production,
  ``TD_EXPORT_STORE=fake``); refused at startup in production when selected explicitly.

Selection: ``TD_EXPORT_STORE=s3|fake``; unset → ``s3`` in production, ``fake`` elsewhere.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, urlsplit

import httpx

from app.core.config import get_settings
from app.core.startup_checks import register_fake_adapter
from app.core.time import utcnow
from app.modules.media import storage as media_storage

DOWNLOAD_URL_SECONDS = 120


def exports_bucket() -> str:
    return os.environ.get("S3_BUCKET_EXPORTS") or "local-td-exports"


class ExportStore(Protocol):
    name: str

    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    async def delete(self, key: str) -> None: ...

    def download_url(
        self, key: str, filename: str, *, now: datetime | None = None
    ) -> tuple[str, datetime]: ...


class S3ExportStore:
    name = "s3"

    def _signed_headers(
        self, method: str, key: str, payload_hash: str, extra: dict[str, str]
    ) -> tuple[str, dict[str, str]]:
        s = media_storage.storage_settings()
        base, prefix = media_storage.bucket_url(s, exports_bucket())
        host = urlsplit(base).netloc
        now = utcnow()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date = now.strftime("%Y%m%d")
        headers = {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date, **extra}
        if s.AWS_SESSION_TOKEN:
            headers["x-amz-security-token"] = s.AWS_SESSION_TOKEN
        names = sorted(headers)
        canonical_headers = "".join(f"{n}:{headers[n].strip()}\n" for n in names)
        signed = ";".join(names)
        path = f"{prefix}/{quote(key, safe='/-_.~')}"
        canonical = f"{method}\n{path}\n\n{canonical_headers}\n{signed}\n{payload_hash}"
        scope = f"{date}/{s.AWS_REGION}/s3/aws4_request"
        to_sign = "\n".join(
            ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
        )
        sig = hmac.new(
            media_storage.signing_key(s.AWS_SECRET_ACCESS_KEY, date, s.AWS_REGION),
            to_sign.encode(),
            hashlib.sha256,
        ).hexdigest()
        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={s.AWS_ACCESS_KEY_ID}/{scope}, "
            f"SignedHeaders={signed}, Signature={sig}"
        )
        headers.pop("host")
        origin = base[: len(base) - len(prefix)] if prefix else base
        return f"{origin}{path}", headers

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        extra = {"content-type": content_type, "x-amz-server-side-encryption": "aws:kms"}
        kms = get_settings().S3_KMS_KEY_ID
        if not kms or kms == "local":
            extra["x-amz-server-side-encryption"] = "AES256"
        else:
            extra["x-amz-server-side-encryption-aws-kms-key-id"] = kms
        url, headers = self._signed_headers("PUT", key, hashlib.sha256(data).hexdigest(), extra)
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.put(url, content=data, headers=headers)
            r.raise_for_status()

    async def delete(self, key: str) -> None:
        url, headers = self._signed_headers("DELETE", key, hashlib.sha256(b"").hexdigest(), {})
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.delete(url, headers=headers)
            if r.status_code not in (200, 204, 404):
                r.raise_for_status()

    def download_url(self, key: str, filename: str, *, now: datetime | None = None) -> tuple[str, datetime]:
        return media_storage.presign_get(
            exports_bucket(), key, expires_s=DOWNLOAD_URL_SECONDS, filename=filename, now=now
        )


class FakeExportStore:
    """Local-directory stand-in for S3 (dev/CI only). Download URLs are presigned for the
    configured endpoint exactly like the real store, but the fake never uploads there; tests
    read the bytes back with ``read``."""

    name = "fake"

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(
            os.environ.get("TD_EXPORT_FAKE_DIR") or Path(tempfile.gettempdir()) / "td-exports"
        )

    def _path(self, key: str) -> Path:
        safe = key.replace("..", "_").lstrip("/")
        return self.root / safe

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def read(self, key: str) -> bytes | None:
        p = self._path(key)
        return p.read_bytes() if p.exists() else None

    def download_url(self, key: str, filename: str, *, now: datetime | None = None) -> tuple[str, datetime]:
        return media_storage.presign_get(
            exports_bucket(), key, expires_s=DOWNLOAD_URL_SECONDS, filename=filename, now=now
        )


def _mode() -> str:
    explicit = (os.environ.get("TD_EXPORT_STORE") or "").lower()
    if explicit in ("s3", "fake"):
        return explicit
    return "s3" if get_settings().is_production else "fake"


_override: ExportStore | None = None


def set_export_store(store: ExportStore | None) -> None:
    global _override
    _override = store


def get_export_store() -> ExportStore:
    if _override is not None:
        return _override
    return S3ExportStore() if _mode() == "s3" else FakeExportStore()


register_fake_adapter(
    "exports (TD_EXPORT_STORE=fake)", lambda s: (os.environ.get("TD_EXPORT_STORE") or "").lower() == "fake"
)
