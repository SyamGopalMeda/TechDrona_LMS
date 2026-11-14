"""Public API of media for other modules (Firestore migration).

Media owns one table, ``playback_sessions`` (``TD_STORE_MEDIA``); no other module reads or writes
it, so nothing about it is exported. Other modules use media's object storage and provider
helpers, which do not depend on the store; import them from here instead of ``media.storage`` /
``media.providers`` / ``media.service`` so the module boundary is one file.
"""

from __future__ import annotations

from app.modules.media.providers import get_scanner, get_video_provider
from app.modules.media.service import scan_changes, scan_result_for
from app.modules.media.storage import (
    MAX_PRESIGN_SECONDS,
    bucket_url,
    delete_objects,
    delete_prefix,
    presign_get,
    presign_post,
    safe_filename,
    signing_key,
    storage_settings,
)

__all__ = [
    "MAX_PRESIGN_SECONDS",
    "bucket_url",
    "delete_objects",
    "delete_prefix",
    "get_scanner",
    "get_video_provider",
    "presign_get",
    "presign_post",
    "safe_filename",
    "scan_changes",
    "scan_result_for",
    "signing_key",
    "storage_settings",
]
