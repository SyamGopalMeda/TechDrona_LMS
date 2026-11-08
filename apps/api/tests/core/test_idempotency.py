from __future__ import annotations

from sqlalchemy import func, select

from app.core.models import IdempotencyKey, OutboxEvent


async def _outbox_count(db) -> int:
    return (await db.execute(select(func.count()).select_from(OutboxEvent))).scalar_one()


async def test_idempotency_flow(probe_client, db, auth, make_principal) -> None:
    p = make_principal()
    h = auth.login(p)
    url = "/api/v1/_probe/idem"

    r = await probe_client.post(url, json={"n": 1}, headers=h)
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"

    h1 = {**h, "Idempotency-Key": "key-0001-abcdef"}
    base = await _outbox_count(db)
    first = await probe_client.post(url, json={"n": 1}, headers=h1)
    assert first.status_code == 201
    assert "idempotency-replayed" not in first.headers
    assert await _outbox_count(db) == base + 1

    replay = await probe_client.post(url, json={"n": 1}, headers=h1)
    assert replay.status_code == 201
    assert replay.headers["idempotency-replayed"] == "true"
    assert replay.json() == first.json()  # same generated id => stored response
    assert await _outbox_count(db) == base + 1  # side effect not repeated

    reuse = await probe_client.post(url, json={"n": 2}, headers=h1)
    assert reuse.status_code == 409 and reuse.json()["code"] == "idempotency_key_reuse"


async def test_4xx_is_stored_and_replayed_without_side_effects(
    probe_client, db, auth, make_principal
) -> None:
    p = make_principal()
    h = {**auth.login(p), "Idempotency-Key": "key-fail-000001"}
    base = await _outbox_count(db)
    r1 = await probe_client.post("/api/v1/_probe/idem", json={"fail": True}, headers=h)
    assert r1.status_code == 409 and r1.json()["code"] == "invalid_state_transition"
    assert await _outbox_count(db) == base  # business writes rolled back to the savepoint
    r2 = await probe_client.post("/api/v1/_probe/idem", json={"fail": True}, headers=h)
    assert r2.status_code == 409 and r2.headers["idempotency-replayed"] == "true"


async def test_5xx_is_not_stored(probe_client, db, auth, make_principal) -> None:
    p = make_principal()
    h = {**auth.login(p), "Idempotency-Key": "key-crash-00001"}
    r = await probe_client.post("/api/v1/_probe/idem", json={"crash": True}, headers=h)
    assert r.status_code == 503
    # The key is free again: retry with a different body is not a "reuse".
    r2 = await probe_client.post("/api/v1/_probe/idem", json={"n": 5}, headers=h)
    assert r2.status_code == 201


async def test_keys_are_scoped_per_user_and_rls_hidden(probe_client, db, auth, make_principal) -> None:
    from app.core.db import set_rls_context

    a, b = make_principal(), make_principal()
    key = "shared-key-00001"
    ra = await probe_client.post(
        "/api/v1/_probe/idem", json={"n": 1}, headers={**auth.login(a), "Idempotency-Key": key}
    )
    rb = await probe_client.post(
        "/api/v1/_probe/idem", json={"n": 2}, headers={**auth.login(b), "Idempotency-Key": key}
    )
    assert ra.status_code == rb.status_code == 201
    assert "idempotency-replayed" not in rb.headers

    await set_rls_context(db, user_id=str(a.user_id))
    rows = (
        (await db.execute(select(IdempotencyKey.user_id).where(IdempotencyKey.idem_key == key)))
        .scalars()
        .all()
    )
    assert rows == [a.user_id]  # policy O: B's row is invisible to A


async def test_invalid_key_format(probe_client, auth, make_principal) -> None:
    h = {**auth.login(make_principal()), "Idempotency-Key": "short"}
    r = await probe_client.post("/api/v1/_probe/idem", json={"n": 1}, headers=h)
    assert r.status_code == 400 and r.json()["code"] == "validation_failed"
