"""Core request 7: erasure deletes the avatar object (not only ``avatar_s3_key``) through the
storage abstraction. An in-memory store stands in for S3: nothing touches a real bucket."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import update

from app.core.db import system_context
from app.modules.identity.erasure import erase_user
from app.modules.identity.models import UserProfile
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


async def test_identity_erasure_deletes_avatar_object_idempotently(db, store) -> None:
    u = await make_user(db)
    await system_context(db, "test.erasure")
    key = f"uploads/avatar/{u.id}/me.png"
    other = "uploads/avatar/someone-else/me.png"
    store.put(BUCKET, key)
    store.put(BUCKET, other)
    await db.execute(update(UserProfile).where(UserProfile.user_id == u.id).values(avatar_s3_key=key))

    out = await erase_user(db, u.id)
    assert out["avatar_objects_deleted"] == 1 and out["profiles_scrubbed"] == 1
    assert (BUCKET, key) not in store.objects and (BUCKET, other) in store.objects
    db.expire_all()
    prof = await db.get(UserProfile, u.id)
    assert prof is not None and prof.avatar_s3_key is None

    again = await erase_user(db, u.id)
    assert again["avatar_objects_deleted"] == 0


async def test_identity_erasure_tolerates_missing_avatar_object(db, store) -> None:
    u = await make_user(db)
    await system_context(db, "test.erasure")
    key = f"uploads/avatar/{u.id}/gone.png"  # recorded, but the object no longer exists
    await db.execute(update(UserProfile).where(UserProfile.user_id == u.id).values(avatar_s3_key=key))
    out = await erase_user(db, u.id)
    assert out["avatar_objects_deleted"] == 1 and store.deleted == [(BUCKET, key)]


async def test_identity_erasure_raises_before_scrubbing_when_storage_is_down(db, store, monkeypatch) -> None:
    u = await make_user(db)
    await system_context(db, "test.erasure")
    key = f"uploads/avatar/{u.id}/me.png"
    store.put(BUCKET, key)
    await db.execute(update(UserProfile).where(UserProfile.user_id == u.id).values(avatar_s3_key=key))

    async def boom(bucket: str, k: str) -> None:
        raise storage.StorageUnavailable("down")

    monkeypatch.setattr(store, "delete", boom)
    with pytest.raises(storage.StorageUnavailable) as e:
        await erase_user(db, u.id)
    assert e.value.status == 503
    db.expire_all()
    prof = await db.get(UserProfile, u.id)
    assert prof is not None and prof.avatar_s3_key == key  # nothing scrubbed: re-runnable
