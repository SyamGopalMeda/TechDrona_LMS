"""INV-12 on Firestore: the media scan job updates unblock-request attachment scan status
through ``security.public`` (no Postgres)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.core.db import NO_POSTGRES
from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.modules.security import public as secp
from app.modules.security.store_specs import UnblockRow
from tests.audit.fs.support import sample_row

FS_MODULES = ("security",)
pytestmark = pytest.mark.usefixtures("fs_env")


async def test_scan_status_update_and_pending_keys() -> None:
    from app.modules.security.models import UnblockRequest

    ids = sorted([uuid7(), uuid7()], key=str)
    rows = []
    for i, rid in enumerate(ids):
        r = sample_row(UnblockRequest, i)
        r["id"] = rid
        r["attachments"] = [
            {"s3_key": f"uploads/k{i}a", "scan_status": "pending", "name": "a.png"},
            {"s3_key": f"uploads/k{i}b", "scan_status": "clean", "name": "b.png"},
        ]
        r["updated_at"] = datetime.now(UTC)
        rows.append(r)
    await ScopedStore.system("firestore.backfill").import_documents(
        "unblock_requests", [(str(r["id"]), UnblockRow.from_pg(r).doc()) for r in rows]
    )
    assert await secp.pending_unblock_attachment_keys(NO_POSTGRES, 10) == ["uploads/k0a", "uploads/k1a"]
    assert await secp.pending_unblock_attachment_keys(NO_POSTGRES, 1) == ["uploads/k0a"]
    assert await secp.set_unblock_attachment_scan(NO_POSTGRES, "uploads/k0a", "infected") == 1
    assert (
        await secp.set_unblock_attachment_scan(NO_POSTGRES, "uploads/k0b", "infected") == 1
    )  # matched, not pending
    assert await secp.set_unblock_attachment_scan(NO_POSTGRES, "uploads/none", "clean") == 0
    got = await secp.get_unblock_request(NO_POSTGRES, ids[0])
    assert [a["scan_status"] for a in got.attachments] == ["infected", "clean"]
    assert await secp.pending_unblock_attachment_keys(NO_POSTGRES, 10) == ["uploads/k1a"]
