"""S3-compatible object storage helpers: SigV4 presigned POST (uploads) and presigned GET
(downloads). No binaries ever pass through the API or Postgres (brief §1 Media).

Local development points ``S3_ENDPOINT_URL`` at SeaweedFS/MinIO (``http://localhost:9000``,
path-style); AWS uses virtual-hosted style with no endpoint override. Implemented with the
standard library so no SDK is required; production credentials from the ECS task role need a
credential provider (requested: ``boto3``/``botocore`` dependency, see module README/report).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Protocol
from urllib.parse import quote, urlsplit

import httpx
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import ENV_FILES
from app.core.errors import ProblemError
from app.core.time import utcnow

MAX_PRESIGN_SECONDS = 300  # CloudFront/S3 signed URLs <= 5 min (MED-07, LRN-12)


class StorageSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore")

    AWS_REGION: str = "ap-south-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_SESSION_TOKEN: str = ""
    S3_ENDPOINT_URL: str = ""
    S3_BUCKET_UPLOADS: str = "local-td-uploads"
    S3_BUCKET_CONTENT: str = "local-td-content"
    S3_BUCKET_CERTIFICATES: str = "local-td-certificates"


@lru_cache(maxsize=1)
def storage_settings() -> StorageSettings:
    return StorageSettings()


def reset_storage_settings() -> None:
    storage_settings.cache_clear()


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = _SAFE_NAME.sub("_", base).strip("._") or "file"
    return base[:120]


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def signing_key(secret: str, date: str, region: str) -> bytes:
    k = _hmac(("AWS4" + secret).encode(), date)
    k = _hmac(k, region)
    k = _hmac(k, "s3")
    return _hmac(k, "aws4_request")


def bucket_url(s: StorageSettings, bucket: str) -> tuple[str, str]:
    """(base url for the bucket, canonical path prefix)."""
    if s.S3_ENDPOINT_URL:
        return f"{s.S3_ENDPOINT_URL.rstrip('/')}/{bucket}", f"/{bucket}"
    return f"https://{bucket}.s3.{s.AWS_REGION}.amazonaws.com", ""


@dataclass(frozen=True, slots=True)
class PresignedPost:
    url: str
    fields: dict[str, str]
    expires_at: datetime


def presign_post(
    bucket: str,
    key: str,
    *,
    content_type: str,
    max_bytes: int,
    expires_s: int = MAX_PRESIGN_SECONDS,
    now: datetime | None = None,
) -> PresignedPost:
    s = storage_settings()
    now = now or utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")
    credential = f"{s.AWS_ACCESS_KEY_ID}/{date}/{s.AWS_REGION}/s3/aws4_request"
    expires_at = now + timedelta(seconds=expires_s)
    conditions: list[Any] = [
        {"bucket": bucket},
        ["eq", "$key", key],
        ["eq", "$Content-Type", content_type],
        ["content-length-range", 1, max_bytes],
        {"x-amz-algorithm": "AWS4-HMAC-SHA256"},
        {"x-amz-credential": credential},
        {"x-amz-date": amz_date},
    ]
    if s.AWS_SESSION_TOKEN:
        conditions.append({"x-amz-security-token": s.AWS_SESSION_TOKEN})
    policy = {"expiration": expires_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"), "conditions": conditions}
    policy_b64 = base64.b64encode(json.dumps(policy, separators=(",", ":")).encode()).decode()
    signature = hmac.new(
        signing_key(s.AWS_SECRET_ACCESS_KEY, date, s.AWS_REGION), policy_b64.encode(), hashlib.sha256
    ).hexdigest()
    fields = {
        "key": key,
        "Content-Type": content_type,
        "x-amz-algorithm": "AWS4-HMAC-SHA256",
        "x-amz-credential": credential,
        "x-amz-date": amz_date,
        "policy": policy_b64,
        "x-amz-signature": signature,
    }
    if s.AWS_SESSION_TOKEN:
        fields["x-amz-security-token"] = s.AWS_SESSION_TOKEN
    url, _ = bucket_url(s, bucket)
    return PresignedPost(url=url, fields=fields, expires_at=expires_at)


def presign_get(
    bucket: str,
    key: str,
    *,
    expires_s: int = MAX_PRESIGN_SECONDS,
    filename: str | None = None,
    now: datetime | None = None,
    subresource: str | None = None,
) -> tuple[str, datetime]:
    """SigV4 query-string presigned GET (``UNSIGNED-PAYLOAD``), at most 5 minutes.
    ``subresource`` (e.g. ``"tagging"``) signs a GET on that object sub-resource instead."""
    s = storage_settings()
    expires_s = max(1, min(MAX_PRESIGN_SECONDS, expires_s))
    now = now or utcnow()
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date = now.strftime("%Y%m%d")
    scope = f"{date}/{s.AWS_REGION}/s3/aws4_request"
    base, prefix = bucket_url(s, bucket)
    host = urlsplit(base).netloc
    path = f"{prefix}/{quote(key, safe='/-_.~')}"
    params: dict[str, str] = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{s.AWS_ACCESS_KEY_ID}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires_s),
        "X-Amz-SignedHeaders": "host",
    }
    if s.AWS_SESSION_TOKEN:
        params["X-Amz-Security-Token"] = s.AWS_SESSION_TOKEN
    if subresource:
        params[subresource] = ""
    if filename:
        params["response-content-disposition"] = f'attachment; filename="{safe_filename(filename)}"'
    qs = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(params.items()))
    canonical = f"GET\n{path}\n{qs}\nhost:{host}\n\nhost\nUNSIGNED-PAYLOAD"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    sig = hmac.new(
        signing_key(s.AWS_SECRET_ACCESS_KEY, date, s.AWS_REGION), to_sign.encode(), hashlib.sha256
    ).hexdigest()
    origin = base[: len(base) - len(prefix)] if prefix else base
    return f"{origin}{path}?{qs}&X-Amz-Signature={sig}", now + timedelta(seconds=expires_s)


# --------------------------------------------------------------------------- object deletion
#
# Retention and erasure delete objects through this abstraction (privacy §7: security case
# attachments 90 days after closure; account erasure: avatar and user-owned uploads). Deletes are
# idempotent: a missing object is not an error. ``APP_ENV=test`` uses an in-memory store so a
# test run never deletes anything in a real bucket.


class StorageUnavailable(ProblemError):
    """The object store could not be reached or refused the request (retry later; 503)."""

    def __init__(self, reason: str) -> None:
        super().__init__("service_unavailable", detail="File storage is unavailable. Try again.")
        self.reason = reason

    def __str__(self) -> str:
        return self.reason


class ObjectStore(Protocol):
    name: str

    async def delete(self, bucket: str, key: str) -> None:
        """Delete one object; succeeds when the object does not exist."""
        ...

    async def list_keys(self, bucket: str, prefix: str) -> list[str]: ...


class S3ObjectStore:
    """SigV4-signed S3 REST calls (DeleteObject, ListObjectsV2) over httpx."""

    name = "s3"

    def __init__(self, timeout: float = 30.0) -> None:
        self._timeout = timeout

    def _signed(
        self, method: str, bucket: str, key: str, query: dict[str, str]
    ) -> tuple[str, dict[str, str]]:
        s = storage_settings()
        base, prefix = bucket_url(s, bucket)
        host = urlsplit(base).netloc
        now = utcnow()
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(b"").hexdigest()
        headers = {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
        if s.AWS_SESSION_TOKEN:
            headers["x-amz-security-token"] = s.AWS_SESSION_TOKEN
        names = sorted(headers)
        canonical_headers = "".join(f"{n}:{headers[n].strip()}\n" for n in names)
        signed = ";".join(names)
        path = f"{prefix}/{quote(key, safe='/-_.~')}" if key else f"{prefix}/"
        qs = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in sorted(query.items()))
        canonical = f"{method}\n{path}\n{qs}\n{canonical_headers}\n{signed}\n{payload_hash}"
        scope = f"{date}/{s.AWS_REGION}/s3/aws4_request"
        to_sign = "\n".join(
            ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()]
        )
        sig = hmac.new(
            signing_key(s.AWS_SECRET_ACCESS_KEY, date, s.AWS_REGION), to_sign.encode(), hashlib.sha256
        ).hexdigest()
        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={s.AWS_ACCESS_KEY_ID}/{scope}, "
            f"SignedHeaders={signed}, Signature={sig}"
        )
        headers.pop("host")
        origin = base[: len(base) - len(prefix)] if prefix else base
        return f"{origin}{path}" + (f"?{qs}" if qs else ""), headers

    async def _request(self, method: str, bucket: str, key: str, query: dict[str, str]) -> httpx.Response:
        url, headers = self._signed(method, bucket, key, query)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                return await c.request(method, url, headers=headers)
        except httpx.HTTPError as e:
            raise StorageUnavailable(f"{method} {bucket}: {type(e).__name__}") from e

    async def delete(self, bucket: str, key: str) -> None:
        r = await self._request("DELETE", bucket, key, {})
        if r.status_code not in (200, 204, 404):
            raise StorageUnavailable(f"DELETE {bucket}: HTTP {r.status_code}")

    async def list_keys(self, bucket: str, prefix: str) -> list[str]:
        keys: list[str] = []
        token: str | None = None
        while True:
            q = {"list-type": "2", "prefix": prefix}
            if token:
                q["continuation-token"] = token
            r = await self._request("GET", bucket, "", q)
            if r.status_code == 404:
                return keys
            if r.status_code != 200:
                raise StorageUnavailable(f"LIST {bucket}: HTTP {r.status_code}")
            body = r.text
            keys.extend(html.unescape(k) for k in _XML_KEY.findall(body))
            m = _XML_NEXT.search(body)
            if "<IsTruncated>true</IsTruncated>" not in body or m is None:
                return keys
            token = html.unescape(m.group(1))


_XML_KEY = re.compile(r"<Key>(.*?)</Key>", re.S)
_XML_NEXT = re.compile(r"<NextContinuationToken>(.*?)</NextContinuationToken>", re.S)


class MemoryObjectStore:
    """In-memory store (tests, ``APP_ENV=test``): ``objects`` maps (bucket, key) -> bytes."""

    name = "memory"

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.deleted: list[tuple[str, str]] = []

    def put(self, bucket: str, key: str, data: bytes = b"x") -> None:
        self.objects[(bucket, key)] = data

    async def delete(self, bucket: str, key: str) -> None:
        self.objects.pop((bucket, key), None)
        self.deleted.append((bucket, key))

    async def list_keys(self, bucket: str, prefix: str) -> list[str]:
        return sorted(k for b, k in self.objects if b == bucket and k.startswith(prefix))


_object_store: ObjectStore | None = None


def get_object_store() -> ObjectStore:
    global _object_store
    if _object_store is None:
        from app.core.config import get_settings

        _object_store = MemoryObjectStore() if get_settings().APP_ENV == "test" else S3ObjectStore()
    return _object_store


def set_object_store(store: ObjectStore | None) -> None:
    """Replace the process-wide store (tests); ``None`` re-selects it on next use."""
    global _object_store
    _object_store = store


async def delete_objects(bucket: str, keys: Iterable[str]) -> int:
    """Delete each key (missing objects are fine); returns how many deletes were issued."""
    store = get_object_store()
    n = 0
    for key in dict.fromkeys(k for k in keys if k):
        await store.delete(bucket, key)
        n += 1
    return n


async def delete_prefix(bucket: str, prefix: str) -> int:
    """Delete every object under ``prefix`` (which must end with ``/``)."""
    if not prefix.endswith("/") or prefix.count("/") < 2:
        raise ValueError("refusing to delete under a short or open prefix")
    return await delete_objects(bucket, await get_object_store().list_keys(bucket, prefix))
