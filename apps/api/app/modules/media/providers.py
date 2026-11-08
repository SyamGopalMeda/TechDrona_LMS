"""Video provider adapters (ADR-0007) and the upload malware-scan adapter.

* ``VideoProvider`` — interface: upload credentials, processing status, playback OTP with a
  dynamic watermark annotation.
* ``VdoCipherProvider`` — real adapter (VdoCipher REST API, ``Authorization: Apisecret``).
  Implemented against the vendor docs; **not verified against the provider** (no credentials
  in this environment).
* ``FakeVideoProvider`` — dev/test only, selected by ``VDOCIPHER_MODE=stub|fake``. Returns
  obviously fake OTPs/playback info. Registered with the production safety gate
  (``register_fake_adapter``) so the API refuses to start in production with it, and
  ``get_video_provider`` refuses it at runtime in production as a second line.
* ``FakeMalwareScanner`` — local S3 (``S3_KMS_KEY_ID=local``) only: marks uploads clean.
  Production relies on GuardDuty Malware Protection results (event consumer Planned) via
  ``media.service.apply_scan_result``.

The OTP is never logged or stored; only its SHA-256 is kept (``provider_otp_ref_hash``).
"""

from __future__ import annotations

import base64
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache
from typing import Any, Protocol

import httpx
import structlog
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import ENV_FILES, get_settings
from app.core.errors import ProblemError
from app.core.startup_checks import register_fake_adapter
from app.core.time import utcnow

log = structlog.get_logger("app.media")


@dataclass(frozen=True, slots=True)
class Watermark:
    text: str
    moving: bool = True


@dataclass(frozen=True, slots=True)
class UploadCredentials:
    video_id: str
    upload_link: str
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VideoStatus:
    status: str  # uploading | processing | available | failed
    duration_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class PlaybackOtp:
    otp: str
    playback_info: str


class VideoProvider(Protocol):
    name: str
    is_fake: bool

    async def create_upload(self, title: str) -> UploadCredentials: ...

    async def get_status(self, video_id: str) -> VideoStatus: ...

    async def issue_otp(self, video_id: str, *, ttl_seconds: int, watermark: Watermark) -> PlaybackOtp: ...


class VdoSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILES, env_file_encoding="utf-8", extra="ignore")

    VDOCIPHER_API_SECRET: str = ""
    VDOCIPHER_API_BASE_URL: str = "https://dev.vdocipher.com/api"


@lru_cache(maxsize=1)
def vdo_settings() -> VdoSettings:
    return VdoSettings()


# --------------------------------------------------------------------------- real adapter


_VDO_STATUS = {"ready": "available", "queued": "processing", "pre-upload": "uploading", "error": "failed"}


class VdoCipherProvider:
    """VdoCipher REST adapter. Not verified against the provider in this environment."""

    name = "vdocipher"
    is_fake = False

    def __init__(self, api_secret: str, base_url: str, timeout_s: float = 5.0) -> None:
        if not api_secret or "REPLACE" in api_secret:
            raise RuntimeError("VDOCIPHER_API_SECRET is not configured")
        self._headers = {"Authorization": f"Apisecret {api_secret}", "Accept": "application/json"}
        self._base = base_url.rstrip("/")
        self._timeout = timeout_s

    async def _call(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as c:
                r = await c.request(method, f"{self._base}{path}", headers=self._headers, **kw)
        except httpx.HTTPError as e:
            log.warning("vdocipher_unreachable", error=type(e).__name__)
            raise ProblemError("service_unavailable", detail="Video service unavailable. Try again.") from e
        if r.status_code >= 400:
            log.warning("vdocipher_error", status=r.status_code, path=path.split("?")[0])
            raise ProblemError("service_unavailable", detail="Video service unavailable. Try again.")
        data = r.json()
        return data if isinstance(data, dict) else {}

    async def create_upload(self, title: str) -> UploadCredentials:
        data = await self._call("PUT", "/videos", params={"title": title[:100]})
        payload = data.get("clientPayload") or {}
        return UploadCredentials(
            video_id=str(data.get("videoId")),
            upload_link=str(payload.get("uploadLink", "")),
            fields={k: v for k, v in payload.items() if k != "uploadLink"},
        )

    async def get_status(self, video_id: str) -> VideoStatus:
        data = await self._call("GET", f"/videos/{video_id}")
        raw = str(data.get("status", "")).lower()
        length = data.get("length")
        return VideoStatus(_VDO_STATUS.get(raw, "processing"), int(length) if length else None)

    async def issue_otp(self, video_id: str, *, ttl_seconds: int, watermark: Watermark) -> PlaybackOtp:
        annotate = [
            {
                "type": "rtext",
                "text": watermark.text,
                "alpha": "0.45",
                "color": "0xFFFFFF",
                "size": "14",
                "interval": "5000",
            }
        ]
        data = await self._call(
            "POST",
            f"/videos/{video_id}/otp",
            json={"ttl": ttl_seconds, "annotate": json.dumps(annotate)},
        )
        return PlaybackOtp(otp=str(data["otp"]), playback_info=str(data["playbackInfo"]))


# --------------------------------------------------------------------------- fake adapter


class FakeVideoProvider:
    """DEV/TEST ONLY. Never used when APP_ENV is production (startup gate + runtime check)."""

    name = "vdocipher"
    is_fake = True

    def __init__(self) -> None:
        self.statuses: dict[str, VideoStatus] = {}
        self.issued: list[tuple[str, int, Watermark]] = []
        self.fail_otp = False

    async def create_upload(self, title: str) -> UploadCredentials:
        vid = "fakevid" + secrets.token_hex(12)
        self.statuses[vid] = VideoStatus("processing", None)
        return UploadCredentials(
            video_id=vid,
            upload_link="https://fake-upload.invalid/vdocipher",
            fields={"policy": "FAKE", "key": f"orig/{vid}", "x-amz-signature": "FAKE"},
        )

    async def get_status(self, video_id: str) -> VideoStatus:
        # Fake processing finishes on the first status poll (600 s video).
        st = self.statuses.get(video_id)
        if st is None or st.status == "processing":
            st = VideoStatus("available", 600)
            self.statuses[video_id] = st
        return st

    async def issue_otp(self, video_id: str, *, ttl_seconds: int, watermark: Watermark) -> PlaybackOtp:
        if self.fail_otp:
            raise ProblemError("service_unavailable", detail="Video service unavailable. Try again.")
        self.issued.append((video_id, ttl_seconds, watermark))
        info = base64.urlsafe_b64encode(
            json.dumps({"videoId": video_id, "fake": True, "issuedAt": utcnow().isoformat()}).encode()
        ).decode()
        return PlaybackOtp(otp="FAKE-OTP-" + secrets.token_hex(16), playback_info=info)


def _video_is_fake(mode: str) -> bool:
    return mode.lower() in {"stub", "fake"}


register_fake_adapter(
    "media.video (FakeVideoProvider: VDOCIPHER_MODE=stub|fake)",
    lambda s: _video_is_fake(s.VDOCIPHER_MODE),
)
register_fake_adapter(
    "media.scan (FakeMalwareScanner: local S3)",
    lambda s: s.S3_KMS_KEY_ID == "local",
)

_provider: VideoProvider | None = None


def set_video_provider(p: VideoProvider | None) -> None:
    """Tests / composition root override."""
    global _provider
    _provider = p


def get_video_provider() -> VideoProvider:
    global _provider
    s = get_settings()
    if _provider is None:
        if _video_is_fake(s.VDOCIPHER_MODE):
            _provider = FakeVideoProvider()
        else:
            vs = vdo_settings()
            _provider = VdoCipherProvider(vs.VDOCIPHER_API_SECRET, vs.VDOCIPHER_API_BASE_URL)
    if _provider.is_fake and s.is_production:
        raise ProblemError("service_unavailable", detail="Video service unavailable.")
    return _provider


# --------------------------------------------------------------------------- scanner


class MalwareScanner(Protocol):
    is_fake: bool

    def immediate_result(self, s3_key: str) -> str | None:
        """``clean`` / ``infected`` when known synchronously, else None (await the event)."""
        ...


class FakeMalwareScanner:
    """DEV/TEST ONLY (local S3): every upload is reported clean."""

    is_fake = True

    def immediate_result(self, s3_key: str) -> str | None:
        return "clean"


GUARDDUTY_TAG = "GuardDutyMalwareScanStatus"
GUARDDUTY_RESULTS = {"NO_THREATS_FOUND": "clean", "THREATS_FOUND": "infected"}


_GD_TAG_RE = re.compile(r"<Tag>\s*<Key>" + GUARDDUTY_TAG + r"</Key>\s*<Value>([A-Z_]+)</Value>\s*</Tag>")


def parse_guardduty_tagging(xml_body: str) -> str | None:
    """``clean`` / ``infected`` from an S3 GetObjectTagging response, else None (not scanned
    yet, or ``UNSUPPORTED`` / ``ACCESS_DENIED`` / ``FAILED`` - left pending for an operator).
    A fixed-shape match instead of an XML parser (no entity expansion surface)."""
    m = _GD_TAG_RE.search(xml_body)
    return GUARDDUTY_RESULTS.get(m.group(1)) if m else None


class GuardDutyScanner:
    """GuardDuty Malware Protection for S3 scans each new object and tags it with
    ``GuardDutyMalwareScanStatus`` (``NO_THREATS_FOUND`` / ``THREATS_FOUND`` / ...). The result
    is pulled from the object's tags (S3 GetObjectTagging, SigV4-presigned) when the asset
    status is polled (MED-03) and by the ``media.service.sweep_pending_scans`` job; an
    EventBridge push can still call ``media.service.apply_scan_result``.
    Implemented against the AWS docs; **not verified against AWS** (no credentials here)."""

    is_fake = False

    def immediate_result(self, s3_key: str) -> str | None:
        return None

    async def fetch_result(self, bucket: str, s3_key: str) -> str | None:
        from app.modules.media.storage import presign_get

        url, _ = presign_get(bucket, s3_key, expires_s=60, subresource="tagging")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(url)
        except httpx.HTTPError:
            log.warning("media.scan_tag_fetch_failed", s3_key=s3_key)
            return None
        if resp.status_code != 200:
            log.warning("media.scan_tag_fetch_status", s3_key=s3_key, status=resp.status_code)
            return None
        return parse_guardduty_tagging(resp.text)


def get_scanner() -> MalwareScanner:
    s = get_settings()
    if s.S3_KMS_KEY_ID == "local" and not s.is_production:
        return FakeMalwareScanner()
    return GuardDutyScanner()


def otp_expiry(now: datetime, ttl_seconds: int) -> datetime:
    from datetime import timedelta

    return now + timedelta(seconds=ttl_seconds)
