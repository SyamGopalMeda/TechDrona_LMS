"""Audit Phase B regressions for core: DB-03 (unique races -> 409), DB-06 (scoped system
context), SEC-02 (shared rate limiter), COM-14 (beat leader lock), E2E-06 (worker liveness),
DB-11 (seed guard), SEC-01 (BFF client IP)."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import exc as sa_exc
from sqlalchemy import text

from app.core import ratelimit
from app.core.db import as_system, set_rls_context, system_context
from app.core.errors import (
    ProblemError,
    install_error_handlers,
    register_unique_conflict,
    unique_conflict_problem,
)

# --------------------------------------------------------------------------- DB-03


async def _unique_violation(db: Any) -> sa_exc.IntegrityError:
    await db.execute(
        text("CREATE TEMP TABLE IF NOT EXISTS _phase_b_u (k int CONSTRAINT _phase_b_u_k_key UNIQUE)")
    )
    await db.execute(text("INSERT INTO _phase_b_u VALUES (1)"))
    try:
        async with db.begin_nested():
            await db.execute(text("INSERT INTO _phase_b_u VALUES (1)"))
    except sa_exc.IntegrityError as e:
        return e
    raise AssertionError("expected a unique violation")


async def test_db03_unique_violation_maps_to_409_problem(db) -> None:
    err = await _unique_violation(db)
    p = unique_conflict_problem(err)
    assert p is not None and p.status == 409 and p.code == "conflict"
    register_unique_conflict("_phase_b_u_k_key", "active_attempt_exists")
    p = unique_conflict_problem(err)
    assert p is not None and p.code == "active_attempt_exists"

    app = FastAPI()
    install_error_handlers(app)

    @app.get("/race")
    async def race() -> None:
        raise err

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://t"
    ) as c:
        r = await c.get("/race")
    assert r.status_code == 409
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["code"] == "active_attempt_exists"


def test_db03_wiring_registers_spec_codes_for_known_races() -> None:
    from app.core.errors import _UNIQUE_CONFLICTS
    from app.wiring import _register_unique_conflicts

    _register_unique_conflicts()
    assert _UNIQUE_CONFLICTS["ux_att_one_open"][0] == "active_attempt_exists"
    assert _UNIQUE_CONFLICTS["enrolments_user_id_course_id_key"][0] == "conflict"
    with pytest.raises(ValueError):
        register_unique_conflict("x", "not_a_catalogue_code")


def test_db03_non_unique_integrity_error_is_not_mapped() -> None:
    class Orig(Exception):
        sqlstate = "23503"  # foreign_key_violation

    err = sa_exc.IntegrityError("INSERT", {}, Orig())
    assert unique_conflict_problem(err) is None


# --------------------------------------------------------------------------- DB-06


async def _guc(db: Any, name: str) -> str | None:
    return (await db.execute(text(f"SELECT current_setting('app.{name}', true)"))).scalar_one()


async def test_db06_scoped_system_context_restores_principal_context(db) -> None:
    uid = str(uuid.uuid4())
    await set_rls_context(db, user_id=uid, org_ids=["o1"], actor=f"user:{uid}", roles=["student"])
    async with system_context(db, "test.scoped"):
        assert await _guc(db, "is_platform") == "on"
        assert await _guc(db, "actor") == "system:test.scoped"
    assert await _guc(db, "is_platform") == "off"
    assert await _guc(db, "user_id") == uid
    assert await _guc(db, "org_ids") == "o1"
    assert await _guc(db, "roles") == "student"

    with pytest.raises(ProblemError):
        async with as_system(db, "test.scoped"):
            raise ProblemError("not_found")
    assert await _guc(db, "is_platform") == "off" and await _guc(db, "user_id") == uid

    await system_context(db, "test.whole_txn")  # legacy form: rest of the transaction
    assert await _guc(db, "is_platform") == "on"


def test_db06_system_context_rejects_bad_job_names() -> None:
    with pytest.raises(ValueError):
        system_context(None, "bad name;")  # type: ignore[arg-type]


# --------------------------------------------------------------------------- SEC-02 limiter


async def test_ratelimit_memory_backend_window_and_problem() -> None:
    prev = ratelimit.set_backend(ratelimit.MemoryBackend())
    try:
        rules = (ratelimit.Rule(2, 60),)
        await ratelimit.hit("t:a", rules)
        await ratelimit.hit("t:a", rules)
        assert await ratelimit.exhausted("t:a", rules)
        with pytest.raises(ProblemError) as ei:
            await ratelimit.hit("t:a", rules, scope="auth01")
        p = ei.value
        assert p.status == 429 and p.code == "rate_limited"
        assert int(p.headers["Retry-After"]) >= 1 and p.ext["retry_after_seconds"] >= 1
        assert await ratelimit.check("t:b", rules) is None  # other keys unaffected
    finally:
        ratelimit.set_backend(prev)


async def test_ratelimit_fails_open_when_backend_down() -> None:
    class Down:
        async def incr(self, keys: Any) -> list[int]:
            raise ConnectionError("down")

        async def peek(self, keys: Any) -> list[int]:
            raise ConnectionError("down")

    prev = ratelimit.set_backend(Down())  # type: ignore[arg-type]
    try:
        await ratelimit.hit("t:x", (ratelimit.Rule(0, 60),))
        assert not await ratelimit.exhausted("t:x", (ratelimit.Rule(0, 60),))
    finally:
        ratelimit.set_backend(prev)


# --------------------------------------------------------------------------- COM-14


def _queue_redis() -> Any:
    import redis

    from app.core.config import get_settings

    client = redis.Redis.from_url(get_settings().REDIS_QUEUE_URL, socket_timeout=2, socket_connect_timeout=2)
    client.ping()
    return client


def test_com14_beat_leader_lock_single_leader_and_standby() -> None:
    from app.core.celery_ops import BeatLeaderLock

    client = _queue_redis()
    key = f"td:test:scheduler:leader:{uuid.uuid4().hex}"
    lost: list[bool] = []
    a = BeatLeaderLock(client, 5, key=key, poll_seconds=0.05, on_lost=lambda: lost.append(True))
    b = BeatLeaderLock(client, 5, key=key, poll_seconds=0.05)
    try:
        assert a.acquire_blocking(max_wait=1)
        assert not b.acquire_blocking(max_wait=0.3)  # standby while a leads
        a.start_renewal()
        time.sleep(0.2)
        assert client.pttl(key) > 4000  # renewed
        client.set(key, "someone-else")  # lock stolen/expired -> leader must step down
        time.sleep(0.3)
        assert lost == [True]
        client.delete(key)
        assert b.acquire_blocking(max_wait=1)
        b.stop()
        assert client.get(key) is None  # released on shutdown
    finally:
        a._stop.set()
        client.delete(key)


def test_com14_beat_init_signal_is_connected() -> None:
    from celery.signals import beat_init

    import app.worker  # noqa: F401  (create_celery installs the hook)

    assert any("_take_leadership" in repr(r[1]) for r in beat_init.receivers)


# --------------------------------------------------------------------------- E2E-06


def test_e2e06_worker_health_file_bootstep_and_freshness(tmp_path: Path) -> None:
    from app.core.celery_ops import is_fresh, touch
    from app.worker import celery_app

    names = {getattr(s, "__name__", "") for s in celery_app.steps["worker"]}
    assert "WorkerHealthFile" in names
    f = tmp_path / "alive"
    assert not is_fresh(f, 60)
    touch(f)
    assert is_fresh(f, 60)
    old = time.time() - 120
    import os

    os.utime(f, (old, old))
    assert not is_fresh(f, 60)


def test_e2e06_compose_healthcheck_no_longer_spawns_inspect_ping() -> None:
    compose = (Path(__file__).resolve().parents[4] / "docker-compose.yml").read_text(encoding="utf-8")
    assert "inspect ping" not in compose
    assert "TD_WORKER_HEALTH_FILE" in compose


# --------------------------------------------------------------------------- DB-11


@pytest.mark.parametrize("env", ["staging", "prod", "production"])
def test_db11_seed_guard_is_an_allowlist(env: str, monkeypatch) -> None:
    from app.core.config import reset_settings_cache
    from app.seeds import dev_users, seeds_allowed

    assert seeds_allowed()  # APP_ENV=test (conftest)
    monkeypatch.setenv("APP_ENV", env)
    reset_settings_cache()
    try:
        assert not seeds_allowed()
        with pytest.raises(dev_users.ProductionRefused):
            dev_users.guard()
    finally:
        monkeypatch.undo()
        reset_settings_cache()


# --------------------------------------------------------------------------- SEC-01 (API side)


@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"x-td-client-ip": "198.51.100.7"}, "198.51.100.7"),
        ({}, None),  # BFF sent no IP: unknown, never the BFF's own socket address
    ],
)
async def test_sec01_service_requests_never_use_the_bff_socket_ip(
    headers: dict[str, str], expected: Any
) -> None:
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    from app.core.middleware import ServiceAuthMiddleware
    from tests.conftest import SERVICE_TOKEN

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        req = Request(scope, receive)
        await JSONResponse({"ip": req.state.client_ip})(scope, receive, send)

    app = ServiceAuthMiddleware(inner)
    transport = httpx.ASGITransport(app=app, client=("10.0.0.5", 1234))  # the BFF container
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/", headers={"Authorization": f"Service {SERVICE_TOKEN}", **headers})
    assert r.json()["ip"] == expected
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/", headers=headers)  # direct (no service token): socket peer, headers ignored
    assert r.json()["ip"] == "10.0.0.5"


# --------------------------------------------------------------------------- BE-01 (wiring)


async def test_be01_video_coverage_lookup_capped_at_asset_duration(db) -> None:
    from app.wiring import video_coverage_lookup
    from tests.catalog.factory import make_published_course
    from tests.identity.factory import make_user

    author = (await make_user(db)).id
    pc = await make_published_course(db, author, is_free=True)
    uid = (await make_user(db)).id
    await system_context(db, "test")
    dur = (
        await db.execute(
            text("SELECT duration_seconds FROM lesson_assets WHERE id = :a"), {"a": pc.assets["video"]}
        )
    ).scalar_one()
    cap = dur or 600
    # covered_s beyond the video length (forged/double-counted windows) is clipped
    await db.execute(
        text(
            "INSERT INTO video_watch_coverage (user_id, lesson_asset_id, lesson_id, covered_s, "
            "coverage_pct, duration_s) VALUES (:u, :a, :l, :c, 100, :d)"
        ),
        {"u": uid, "a": pc.assets["video"], "l": pc.lessons["video"], "c": cap * 3, "d": cap},
    )
    assert await video_coverage_lookup(db, uid, pc.keys["video"]) == cap
