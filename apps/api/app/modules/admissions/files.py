"""Payment proofs and resumes: validation, re-encoding, private storage, short-lived view links.

* The real type comes from the first bytes (``sniff``), never from the client's content type or
  file name. Proofs: JPEG / PNG / WebP / PDF; resumes: PDF / DOC / DOCX. Both at most 2 MiB.
* Images are decoded and re-encoded as JPEG with Pillow (strips EXIF/location data and anything
  appended to the file); a file Pillow cannot decode is refused. Decompression bombs are refused.
* ``sha256`` is of the bytes as received (what the uniqueness index uses); the website also sends
  the hash of the student's ORIGINAL file (before its in-browser re-encode), kept as
  ``proof_original_sha256`` so the same screenshot uploaded twice is still caught.
* Storage reuses the commerce ``DocumentStore`` adapter (S3/SeaweedFS in deployments, memory in
  tests) in the private uploads bucket under ``admissions/<registration_id>/``. There are no public
  URLs: staff get a presigned GET of at most 2 minutes.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import io
import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from app.core.errors import ProblemError

MAX_BYTES = 2 * 1024 * 1024
VIEW_SECONDS = 120
Kind = Literal["proof", "resume"]

PROOF_TYPES = ("image/jpeg", "image/png", "image/webp", "application/pdf")
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
RESUME_TYPES = ("application/pdf", "application/msword", DOCX)
_EXT = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "application/pdf": "pdf",
    "application/msword": "doc",
    DOCX: "docx",
}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _vf(field: str, code: str, message: str) -> ProblemError:
    return ProblemError("validation_failed", 422, errors=[{"field": field, "code": code, "message": message}])


def sniff(b: bytes) -> str:
    """Content type from magic bytes ("" when unknown). Same table as the website's filestore."""
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:5] == b"%PDF-":
        return "application/pdf"
    if b[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "application/msword"
    if b[:4] == b"PK\x03\x04":
        return DOCX
    if b[4:8] == b"ftyp":
        return "image/heic"
    return ""


@dataclass(frozen=True)
class PreparedFile:
    kind: Kind
    name: str
    content_type: str
    data: bytes
    sha256: str  # of the bytes as received
    original_sha256: str | None


def _safe_name(name: str, content_type: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[^\w.\- ()]+", "_", base).strip("._ ")[:100] or "file"
    stem = base.rsplit(".", 1)[0] if "." in base else base
    return f"{stem}.{_EXT[content_type]}"


def _reencode_image(data: bytes, field: str) -> bytes:
    try:
        from PIL import Image
    except ImportError as e:  # pragma: no cover - Pillow ships with fpdf2
        raise ProblemError("service_unavailable", detail="Image processing is unavailable.") from e
    Image.MAX_IMAGE_PIXELS = 40_000_000
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            img = img.convert("RGB")
            img.thumbnail((2000, 2000))
            out = io.BytesIO()
            img.save(out, "JPEG", quality=85, optimize=True)
    except ProblemError:
        raise
    except Exception as e:
        raise _vf(
            field, "unreadable_image", "We couldn't read that image. Upload a JPG or PNG screenshot."
        ) from e
    return out.getvalue()


def prepare(
    kind: Kind, *, filename: str, data_b64: str, original_sha256: str | None = None, field: str | None = None
) -> PreparedFile:
    """Decode, check and (images) re-encode one upload. Raises 422 problems naming ``field``."""
    f = field or kind
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise _vf(f, "invalid_file", "The file could not be read. Choose it again.") from e
    if len(raw) < 100:
        raise _vf(f, "file_empty", "That file is empty or damaged.")
    if len(raw) > MAX_BYTES:
        raise _vf(f, "file_too_large", "That file is too large. The limit is 2 MB.")
    real = sniff(raw)
    allowed = PROOF_TYPES if kind == "proof" else RESUME_TYPES
    if real == "image/heic":
        raise _vf(f, "heic_not_supported", "HEIC photos aren't supported. Upload a PNG or JPG screenshot.")
    if real not in allowed:
        raise _vf(
            f,
            "unsupported_type",
            "Upload your resume as a PDF or Word file."
            if kind == "resume"
            else "Upload a JPG, PNG or WebP screenshot, or a PDF receipt.",
        )
    digest = hashlib.sha256(raw).hexdigest()
    orig = (original_sha256 or "").strip().lower() or None
    if orig is not None and not _HEX64.match(orig):
        raise _vf(f, "invalid_hash", "The file could not be read. Choose it again.")
    data, ctype = raw, real
    if real.startswith("image/"):
        data, ctype = _reencode_image(raw, f), "image/jpeg"
        if len(data) > MAX_BYTES:
            raise _vf(f, "file_too_large", "That image is too large. Upload a normal screenshot.")
    return PreparedFile(kind, _safe_name(filename or "file", ctype), ctype, data, digest, orig)


# --------------------------------------------------------------------------- storage


def bucket() -> str:
    from app.modules.media.storage import storage_settings

    return storage_settings().S3_BUCKET_UPLOADS


def object_key(registration_id: uuid.UUID, kind: Kind, ref_id: uuid.UUID, content_type: str) -> str:
    return f"admissions/{registration_id}/{kind}-{ref_id}.{_EXT[content_type]}"


async def store(key: str, f: PreparedFile) -> None:
    from app.modules.commerce.documents import get_document_store

    await get_document_store().put(bucket(), key, f.data, f.content_type)


def view_url(key: str, filename: str) -> tuple[str, datetime]:
    """Short-lived link to view a private file (inline for images/PDF on S3)."""
    from app.modules.commerce.documents import S3DocumentStore, get_document_store

    s = get_document_store()
    if isinstance(s, S3DocumentStore):
        from app.modules.media.storage import presign_get

        return presign_get(bucket(), key, expires_s=VIEW_SECONDS)
    return s.signed_url(bucket(), key, filename=filename, expires_s=VIEW_SECONDS)
