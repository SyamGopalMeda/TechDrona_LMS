"""ANL-01/02/03 ingest + config through the API (real Postgres, RLS as td_app)."""

from __future__ import annotations

import json
from datetime import timedelta

from sqlalchemy import text

from app.core.db import system_context
from tests.analytics.conftest import TOUCHED, Page, batch, make_user, principal_for, uuid7_at

URL = "/api/v1/analytics/events"


async def _count(db, table: str, user) -> int:
    await system_context(db, "test.count")
    return int(
        (await db.execute(text(f"SELECT count(*) FROM {table} WHERE user_id = :u"), {"u": user})).scalar()
    )


async def test_ingest_happy_path_identity_from_session_and_engaged_touch(client, db, auth, now) -> None:
    uid = await make_user(db)
    p = principal_for(uid)
    page = Page("lesson_text")
    t = now - timedelta(seconds=40)
    events = [page.view(t), page.hb(t + timedelta(seconds=15)), page.hb(t + timedelta(seconds=30))]
    TOUCHED.clear()
    r = await client.post(URL, json=batch(events), headers=auth.login(p))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] == 3 and body["duplicate"] == 0 and body["rejected"] == 0
    assert body["config_version"] == "tm-1.0"
    await system_context(db, "test")
    row = (
        await db.execute(
            text(
                "SELECT user_id, auth_session_id, device_id, privacy_tier, kind, state_bits FROM activity_heartbeats "
                "WHERE page_instance_id = :p ORDER BY seq LIMIT 1"
            ),
            {"p": page.page_instance_id},
        )
    ).one()
    assert row.user_id == uid and row.auth_session_id == p.session_id and row.device_id == p.device_id
    assert row.privacy_tier == "adult" and row.kind == "engaged" and row.state_bits == 7
    assert TOUCHED == [p.session_id]  # engaged credit slides the idle timer


async def test_keepalive_only_batch_never_touches_session(client, db, auth, now) -> None:
    uid = await make_user(db)
    page = Page("lesson_text")
    TOUCHED.clear()
    r = await client.post(
        URL,
        json=batch(
            [page.hb(now - timedelta(seconds=5), kind="keepalive", input_recent=False, interval_ms=300000)]
        ),
        headers=auth.login(principal_for(uid)),
    )
    assert r.status_code == 200 and r.json()["accepted"] == 1
    assert TOUCHED == []


async def test_client_cannot_assert_identity_fields(client, db, auth, now) -> None:
    uid = await make_user(db)
    page = Page("lesson_text")
    ev = page.view(now - timedelta(seconds=1))
    ev["user_id"] = "00000000-0000-7000-8000-000000000000"
    b = batch([ev])
    r = await client.post(URL, json=b, headers=auth.login(principal_for(uid)))
    assert r.json()["results"][0] == {
        "event_id": ev["event_id"],
        "status": "rejected",
        "code": "invalid_payload",
    }
    b2 = batch([page.view(now)])
    b2["organization_id"] = "00000000-0000-7000-8000-000000000000"
    r2 = await client.post(URL, json=b2, headers=auth.login(principal_for(uid)))
    assert r2.status_code == 422 and r2.json()["code"] == "validation_failed"


async def test_duplicate_retries_are_idempotent(client, db, auth, now) -> None:
    uid = await make_user(db)
    p = principal_for(uid)
    page = Page("practice")
    t = now - timedelta(minutes=2)
    events = [page.view(t)] + [page.hb(t + timedelta(seconds=15 * i)) for i in range(1, 5)]
    headers = auth.login(p)
    first = await client.post(URL, json=batch(events), headers=headers)
    assert first.json()["accepted"] == 5
    before = await _count(db, "activity_heartbeats", uid), await _count(db, "analytics_events", uid)
    for _ in range(10):  # §8.2: identical batch retried 10x (fresh session: burst limit is per session)
        r = await client.post(URL, json=batch(events), headers=auth.login(principal_for(uid)))
        assert r.status_code == 200
        assert r.json()["duplicate"] == 5 and r.json()["accepted"] == 0
    after = await _count(db, "activity_heartbeats", uid), await _count(db, "analytics_events", uid)
    assert before == after == (4, 1)
    twice = page.view(now)
    same_batch = await client.post(URL, json=batch([twice, twice]), headers=headers)
    statuses = [x["status"] for x in same_batch.json()["results"]]
    assert statuses == ["accepted", "duplicate"]


async def test_clock_skew_is_corrected_from_sent_at(client, db, auth, now) -> None:
    uid = await make_user(db)
    for offset in (timedelta(hours=3), -timedelta(hours=3)):
        page = Page("lesson_text")
        client_now = now + offset  # device clock 3 h fast / slow
        ev = page.view(client_now)
        r = await client.post(
            URL, json=batch([ev], sent_at=client_now), headers=auth.login(principal_for(uid))
        )
        assert r.json()["accepted"] == 1, r.text
        await system_context(db, "t")
        row = (
            await db.execute(
                text(
                    "SELECT effective_at, received_at, ingest_flags FROM analytics_events WHERE page_instance_id = :p"
                ),
                {"p": page.page_instance_id},
            )
        ).one()
        assert abs((row.effective_at - row.received_at).total_seconds()) < 1.0  # §8.3
        assert "large_skew" in row.ingest_flags


async def test_events_older_than_72h_are_rejected_and_counted(client, db, auth, now) -> None:
    uid = await make_user(db)
    page = Page("lesson_text")
    old = page.view(now - timedelta(hours=73))
    ok = page.view(now - timedelta(hours=48))
    r = await client.post(URL, json=batch([old, ok]), headers=auth.login(principal_for(uid)))
    res = {x["event_id"]: x for x in r.json()["results"]}
    assert res[old["event_id"]]["code"] == "event_too_old"
    assert res[ok["event_id"]]["status"] == "accepted"
    await system_context(db, "t")
    n = (
        await db.execute(
            text("SELECT sum(count) FROM analytics_ingest_rejections WHERE code = 'event_too_old'")
        )
    ).scalar()
    assert n and n >= 1


async def test_per_event_rejection_codes(client, db, auth, now) -> None:
    uid = await make_user(db)
    page = Page("practice")
    t = now - timedelta(seconds=30)
    server_only = page.ev("practice.answer_submitted", t, {"is_correct": True})
    unknown = page.ev("page.teleport", t, {})
    bad_version = page.view(t) | {"schema_version": 2}
    mismatch = page.view(t) | {"event_id": uuid7_at(t - timedelta(minutes=10))}
    bad_payload = page.ev("page.heartbeat", t, {"kind": "engaged"})
    big = page.ev("page.view", t, {f"k{i}": i for i in range(30)})
    hb1 = page.hb(t)
    hb2 = page.hb(t + timedelta(seconds=3))  # engaged heartbeats < 10 s apart
    r = await client.post(
        URL,
        json=batch([server_only, unknown, bad_version, mismatch, bad_payload, big, hb1, hb2]),
        headers=auth.login(principal_for(uid)),
    )
    codes = [x.get("code") for x in r.json()["results"]]
    assert codes == [
        "server_only_event",
        "unknown_event_type",
        "unsupported_schema_version",
        "uuid_time_mismatch",
        "invalid_payload",
        "payload_too_large",
        None,
        "rate_capped",
    ]


async def test_batch_limits(client, db, auth, now) -> None:
    uid = await make_user(db)
    headers = auth.login(principal_for(uid))
    page = Page("other")
    too_many = batch([page.view(now) for _ in range(101)])
    r = await client.post(URL, json=too_many, headers=headers)
    assert r.status_code == 422
    huge = json.dumps(batch([page.view(now)])).replace('"web-test"', '"' + "x" * 70000 + '"')
    r2 = await client.post(URL, content=huge, headers={**headers, "content-type": "application/json"})
    assert r2.status_code == 413


async def test_minor_product_events_dropped_and_adult_needs_consent(client, db, auth, now) -> None:
    from tests.analytics.conftest import grant_consent

    minor = await make_user(db, minor=True)
    adult = await make_user(db)
    page = Page("lesson_video")
    buf = page.ev("video.buffering", now - timedelta(seconds=2), {"position_s": 3.0, "buffer_ms": 800})
    r = await client.post(URL, json=batch([buf]), headers=auth.login(principal_for(minor, adult=False)))
    assert r.json()["results"][0]["code"] == "purpose_not_permitted"
    r = await client.post(URL, json=batch([buf]), headers=auth.login(principal_for(adult)))
    assert r.json()["results"][0]["code"] == "purpose_not_permitted"
    await grant_consent(db, adult, "analytics_product")
    buf2 = page.ev("video.buffering", now - timedelta(seconds=1), {"position_s": 3.0, "buffer_ms": 800})
    r = await client.post(URL, json=batch([buf2]), headers=auth.login(principal_for(adult)))
    assert r.json()["results"][0]["status"] == "accepted"
    cfg = await client.get("/api/v1/analytics/config", headers=auth.login(principal_for(minor, adult=False)))
    assert cfg.status_code == 200
    assert cfg.json()["purposes"] == {"learning": True, "product": False}
    assert cfg.json()["params"]["idle_threshold_by_surface_s"]["lesson_text"] == 180


async def test_entity_entitlement_is_checked(client, db, auth, now) -> None:
    from app.core.access import AccessDecision, register_access_checker

    class Deny:
        async def check(self, *a, **k):
            return AccessDecision(False, "no_entitlement")

    register_access_checker(Deny())  # restored by the autouse fixture
    uid = await make_user(db)
    page = Page("lesson_text", entity={"course_id": "0193b000-0000-7000-8000-000000000001"})
    r = await client.post(URL, json=batch([page.view(now)]), headers=auth.login(principal_for(uid)))
    assert r.json()["results"][0]["code"] == "entity_not_entitled"


async def test_beacon_variant_returns_204_and_checks_fetch_site(client, db, auth, now) -> None:
    uid = await make_user(db)
    headers = auth.login(principal_for(uid))
    page = Page("lesson_text")
    b = batch([page.view(now)]) | {"csrf": "signed-token-validated-by-bff"}
    r = await client.post(
        URL + "/beacon",
        content=json.dumps(b),
        headers={**headers, "content-type": "text/plain;charset=UTF-8", "sec-fetch-site": "same-origin"},
    )
    assert r.status_code == 204
    assert await _count(db, "analytics_events", uid) == 1
    r2 = await client.post(
        URL + "/beacon", content=json.dumps(b), headers={**headers, "sec-fetch-site": "cross-site"}
    )
    assert r2.status_code == 403 and r2.json()["code"] == "csrf_failed"


async def test_auth_gates(client, db, auth, now) -> None:
    page = Page("lesson_text")
    r = await client.post(URL, json=batch([page.view(now)]))
    assert r.status_code == 401
    uid = await make_user(db)
    restricted = principal_for(uid, scope="restricted")
    r2 = await client.post(URL, json=batch([page.view(now)]), headers=auth.login(restricted))
    assert r2.status_code == 403 and r2.json()["code"] == "account_restricted"
    # L3 read-only sessions can still read their own summary (route tag l3_readonly).
    r3 = await client.get("/api/v1/me/analytics/summary", headers=auth.login(restricted))
    assert r3.status_code == 200


async def test_session_burst_rate_limit_returns_429_with_retry_after(client, db, auth, now) -> None:
    uid = await make_user(db)
    headers = auth.login(principal_for(uid))
    page = Page("other")
    codes, retry_after = [], None
    for i in range(25):  # > 2 burst windows even if a 10 s boundary is crossed
        r = await client.post(URL, json=batch([page.view(now - timedelta(seconds=i))]), headers=headers)
        codes.append(r.status_code)
        if r.status_code == 429:
            retry_after = int(r.headers["retry-after"])
    assert 429 in codes and codes.count(200) <= 20
    assert retry_after is not None and retry_after >= 1
