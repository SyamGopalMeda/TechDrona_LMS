"""Core request 7: the media erasure provider deletes user-owned objects in the uploads bucket
through the storage abstraction (in-memory store here; never a real bucket). Security-case
attachments stay (D8 legal hold, purged by ``security.purge_closed_cases``)."""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy import update

from app.core.db import system_context
from app.modules.admin import privacy as prv
from app.modules.identity.models import UserProfile
from app.modules.media import privacy as media_privacy
from app.modules.media import storage
from tests.identity.factory import make_user

BUCKET = "test-uploads"


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> Iterator[storage.MemoryObjectStore]:
    mem = storage.MemoryObjectStore()
    storage.set_object_store(mem)
    monkeypatch.setattr(storage.storage_settings(), "S3_BUCKET_UPLOADS", BUCKET)
    yield mem
    storage.set_object_store(None)


def test_tests_never_get_the_real_s3_store() -> None:
    storage.set_object_store(None)
    assert isinstance(storage.get_object_store(), storage.MemoryObjectStore)
    storage.set_object_store(None)


async def test_media_provider_deletes_user_uploads_only(db, store) -> None:
    u = await make_user(db)
    other = await make_user(db)
    mine = [
        f"uploads/support_attachment/{u.id}/a/x.pdf",
        f"uploads/support_attachment/{u.id}/b/y.png",
        f"uploads/assignment_submission/{u.id}/c/z.zip",
    ]
    kept = [
        f"uploads/unblock_request/{u.id}/r/a/proof.pdf",  # D8 legal hold
        f"uploads/support_attachment/{other.id}/a/x.pdf",
    ]
    for k in mine + kept:
        store.put(BUCKET, k)

    out = await media_privacy.erase_user(db, u.id)
    assert out["objects_deleted"] == 3
    assert {k for _b, k in store.objects} == set(kept)
    again = await media_privacy.erase_user(db, u.id)
    assert again["objects_deleted"] == 0


async def test_execute_erasure_runs_media_and_deletes_avatar_and_uploads(app, db, store) -> None:
    assert "media" in prv.REQUIRED_ERASURE_MODULES and "media" in prv.erasure_providers()
    u = await make_user(db)
    await system_context(db, "test.erasure")
    avatar = f"uploads/avatar/{u.id}/me.png"
    upload = f"uploads/assignment_submission/{u.id}/c/z.zip"
    store.put(BUCKET, avatar)
    store.put(BUCKET, upload)
    await db.execute(update(UserProfile).where(UserProfile.user_id == u.id).values(avatar_s3_key=avatar))

    result = await prv.execute_erasure(db, u.id)
    assert "media" in result.ran and "media" not in result.missing
    assert result.ran["media"]["objects_deleted"] == 1
    assert result.ran["identity"]["avatar_objects_deleted"] == 1
    assert store.objects == {}


async def test_delete_prefix_refuses_open_prefixes(store) -> None:
    for bad in ("uploads/", "uploads", ""):
        with pytest.raises(ValueError):
            await storage.delete_prefix(BUCKET, bad)


async def test_s3_store_signs_delete_and_list_and_treats_404_as_deleted(monkeypatch) -> None:
    """The real adapter against a mock transport (no network): DELETE 404 is success, list
    follows continuation tokens, 5xx raises a 503 problem."""
    seen: list[httpx.Request] = []
    pages = {
        None: "<ListBucketResult><Key>p/u/a</Key><Key>p/u/b&amp;c</Key><IsTruncated>true</IsTruncated>"
        "<NextContinuationToken>t2</NextContinuationToken></ListBucketResult>",
        "t2": "<ListBucketResult><Key>p/u/d</Key><IsTruncated>false</IsTruncated></ListBucketResult>",
    }

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        assert req.headers["authorization"].startswith("AWS4-HMAC-SHA256 Credential=")
        if req.method == "GET":
            return httpx.Response(200, text=pages[req.url.params.get("continuation-token")])
        if req.url.path.endswith("/missing"):
            return httpx.Response(404)
        if req.url.path.endswith("/broken"):
            return httpx.Response(500)
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient

    def client(*a: object, **kw: object) -> httpx.AsyncClient:
        kw["transport"] = transport
        return real(*a, **kw)  # type: ignore[arg-type]

    monkeypatch.setattr(storage.httpx, "AsyncClient", client)
    s3 = storage.S3ObjectStore()
    assert await s3.list_keys("b", "p/u/") == ["p/u/a", "p/u/b&c", "p/u/d"]
    await s3.delete("b", "p/u/missing")
    await s3.delete("b", "p/u/a")
    with pytest.raises(storage.StorageUnavailable):
        await s3.delete("b", "p/u/broken")
    assert [r.method for r in seen] == ["GET", "GET", "DELETE", "DELETE", "DELETE"]
