# ruff: noqa: E501 - long report/format lines in a measurement tool
"""Billed Firestore operations PER REQUEST of the student request path (emulator only, no deploy).

    cd apps/api
    .venv/Scripts/python ../../functions-lms/tools/request_cost_probe.py [--project demo-costreq]
                                                                       [--json out.json] [--sites]

Companion of ``firestore_cost_probe.py`` (scheduled jobs): it reuses that file's RPC-level
instrumentation (``instrument()`` / ``COUNTS``: RunQuery = 1 read per document and 1 for an empty
result, aggregation = 1 read per started 1000 index entries, BatchGet = 1 per requested
document, Commit = 1 write / 1 delete per write) and adds a per-call-site breakdown (``--sites``).

The whole Firebase request path runs in-process exactly as on Cloud Functions: ``lms_edge.EdgeApp``
(BFF: packed ``__session`` cookie, CSRF double submit) in front of ``app.main.create_app()``, every
module on Firestore, ``TD_CACHE_BACKEND=firestore`` (rate limits in ``lms_kv``), Cloud Tasks
enqueues counted but not sent, ``TD_SIMPLE_AUTH=true`` (the live testing-phase switch).

Scenario (a wiped ``demo-*`` project): seed the role catalogue + admin/student
(``seed_emulator.py``) and a second admin, author + publish a 3-lesson article course through the
studio API (two admins: separation of duties), then measure each student request of the SPA
(``apps/lms-spa``: shell, dashboard, catalogue, course, lesson, notifications, polls) three times:
``first`` (cold process caches) and ``steady`` (third call, warm caches, same session).

Finally a model of one student-hour of study built from the SPA's own intervals (see
``hour_model``) and the ops/day budget split (50k reads, 20k writes, 20k deletes free).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))  # lms_edge

import firestore_cost_probe as fcp  # noqa: E402

BASE = "http://127.0.0.1:5000"
SAME = {
    "sec-fetch-site": "same-origin",
    "x-forwarded-for": "203.0.113.7",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
}

# (kind, collection, site) -> billed ops; filled only with --sites
SITES: Counter[tuple[str, str, str]] = Counter()
_TRACE = False


def _request_env() -> None:
    os.environ.setdefault("APP_ENV", "local")
    os.environ["TD_SIMPLE_AUTH"] = "true"
    os.environ["TD_PUBLIC_BASE_URL"] = BASE
    os.environ["TD_ALLOWED_ORIGINS"] = BASE
    os.environ["TD_COOKIE_SECURE"] = "false"
    os.environ["TD_EDGE_COOKIE_PACKING"] = "session"
    os.environ["TD_TRUSTED_PROXY_HOPS"] = "1"
    for k, v in {
        "TD_K_DEVICE_KEY_V1": "11" * 32,
        "TD_K_LOGIN_KEY_V1": "22" * 32,
        "TD_K_TOTP_KEY_V1": "33" * 32,
        "TD_FP_HMAC_KEY": "44" * 32,
        "TD_LOCAL_ENVELOPE_KEY": "55" * 32,
        "TD_ANALYTICS_SUBJECT_KEY": "66" * 32,
    }.items():  # DUMMY probe-only values (same pattern as emulate.ps1)
        os.environ.setdefault(k, v)


# ----------------------------------------------------------------------------- call-site trace


def _site() -> str:
    """The first two app frames outside the Firestore store layer (who asked for this RPC)."""
    f = sys._getframe(2)
    out: list[str] = []
    while f is not None and len(out) < 2:
        fn = f.f_code.co_filename.replace("\\", "/")
        if "/app/" in fn and "/app/core/firestore/" not in fn and "site-packages" not in fn:
            short = fn.split("/app/", 1)[1]
            out.append(f"{short}:{f.f_code.co_name}")
        f = f.f_back  # type: ignore[assignment]
    return " <- ".join(out) or "?"


def _coll_from_name(name: str) -> str:
    parts = name.split("/documents/", 1)[-1].split("/")
    return parts[-2] if len(parts) >= 2 else parts[0]


def _req(a: tuple[Any, ...], kw: dict[str, Any]) -> Any:
    return kw.get("request") if kw.get("request") is not None else (a[0] if a else None)


def _get(req: Any, key: str) -> Any:
    if isinstance(req, dict):
        return req.get(key)
    return getattr(req, key, None)


class _SiteStream:
    def __init__(self, inner: Any, kind: str, coll: str, site: str) -> None:
        self._inner, self._kind, self._coll, self._site = inner, kind, coll, site
        self._docs = 0
        self._done = False

    def __aiter__(self) -> _SiteStream:
        return self

    async def __anext__(self) -> Any:
        try:
            resp = await self._inner.__anext__()
        except StopAsyncIteration:
            if not self._done:
                self._done = True
                if self._kind == "query" and self._docs == 0:
                    SITES[("read", self._coll, self._site)] += 1
            raise
        pb = getattr(resp, "_pb", resp)
        if self._kind == "query" and pb.HasField("document"):
            self._docs += 1
            SITES[("read", self._coll, self._site)] += 1
        elif self._kind == "batch_get" and (pb.HasField("found") or pb.WhichOneof("result") == "missing"):
            name = pb.found.name if pb.HasField("found") else pb.missing
            SITES[("read", _coll_from_name(name), self._site)] += 1
        return resp

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


def adapt_streams() -> None:
    """Before ``fcp.instrument()``: hand its stream wrapper a real async iterator (a GAPIC
    ``_WrappedUnaryStreamCall`` only has ``__aiter__``, the wrapper calls ``__anext__``)."""
    from google.cloud.firestore_v1.services.firestore.async_client import FirestoreAsyncClient as C

    if getattr(C, "_td_adapted", False) or getattr(C, "_td_probe", False):
        return
    C._td_adapted = True  # type: ignore[attr-defined]

    def adapt(orig: Any) -> Any:
        async def call(self: Any, *a: Any, **kw: Any) -> Any:
            res = orig(self, *a, **kw)
            if hasattr(res, "__await__"):
                res = await res
            return res if hasattr(res, "__anext__") else res.__aiter__()

        return call

    C.run_query = adapt(C.run_query)  # type: ignore[method-assign]
    C.batch_get_documents = adapt(C.batch_get_documents)  # type: ignore[method-assign]
    C.run_aggregation_query = adapt(C.run_aggregation_query)  # type: ignore[method-assign]


def trace_sites() -> None:
    """Layered on top of ``fcp.instrument()``: same billing rules, attributed to call sites."""
    from google.cloud.firestore_v1.services.firestore.async_client import FirestoreAsyncClient as C

    if getattr(C, "_td_sites", False):
        return
    C._td_sites = True  # type: ignore[attr-defined]
    rq, agg, bg, cm = C.run_query, C.run_aggregation_query, C.batch_get_documents, C.commit

    async def run_query(self: Any, *a: Any, **kw: Any) -> Any:
        site = _site() if _TRACE else ""
        sq = _get(_req(a, kw), "structured_query")
        coll = sq.from_[0].collection_id if sq is not None and sq.from_ else "?"
        return _SiteStream(await rq(self, *a, **kw), "query", coll, site)

    async def run_aggregation_query(self: Any, *a: Any, **kw: Any) -> Any:
        if _TRACE:
            saq = _get(_req(a, kw), "structured_aggregation_query")
            sq = getattr(saq, "structured_query", None)
            coll = sq.from_[0].collection_id if sq is not None and sq.from_ else "?"
            SITES[("read(count)", coll, _site())] += 1
        return await agg(self, *a, **kw)

    async def batch_get_documents(self: Any, *a: Any, **kw: Any) -> Any:
        return _SiteStream(await bg(self, *a, **kw), "batch_get", "?", _site() if _TRACE else "")

    async def commit(self: Any, *a: Any, **kw: Any) -> Any:
        if _TRACE:
            site = _site()
            for w in _get(_req(a, kw), "writes") or []:
                pb = getattr(w, "_pb", w)
                op = pb.WhichOneof("operation")
                name = (
                    pb.delete
                    if op == "delete"
                    else (pb.update.name if op == "update" else pb.transform.document)
                )
                SITES[("delete" if op == "delete" else "write", _coll_from_name(name), site)] += 1
        return await cm(self, *a, **kw)

    C.run_query = run_query  # type: ignore[method-assign]
    C.run_aggregation_query = run_aggregation_query  # type: ignore[method-assign]
    C.batch_get_documents = batch_get_documents  # type: ignore[method-assign]
    C.commit = commit  # type: ignore[method-assign]


# ----------------------------------------------------------------------------- seed


async def seed_publisher() -> None:
    """A second platform admin (publish needs a different staff member than the author)."""
    from datetime import timedelta

    from seed_emulator import _grant, _has_role

    from app.core.db import NO_POSTGRES
    from app.core.ids import uuid7
    from app.core.security import hash_password
    from app.core.time import utcnow
    from app.modules.identity import public as identity
    from app.modules.identity import service as identity_service
    from app.modules.identity.models import User, UserCredential, UserProfile
    from app.seeds.dev_users import DEV_PASSWORD

    for staff in ("admin@dev.techdrona.local", "publisher@dev.techdrona.local"):
        u = await identity.find_user(NO_POSTGRES, "email", staff)
        if u is not None and not await _has_role(u.id, "content_manager"):
            await _grant(u.id, "content_manager", utcnow())
    email = "publisher@dev.techdrona.local"
    if await identity.find_user(NO_POSTGRES, "email", email) is not None:
        return
    now = utcnow()
    uid = uuid7()
    user = User(
        id=uid, email=email, email_verified_at=now - timedelta(days=45), status="active", is_minor=False,
        age_verified_at=now, age_verification_method="self_declared", is_synthetic=True,
        account_origin="staff_created", must_change_password=False, created_at=now, updated_at=now,
    )  # fmt: skip
    profile = UserProfile(user_id=uid, full_name="Demo Publisher", created_at=now, updated_at=now)
    cred = UserCredential(
        user_id=uid, password_hash=hash_password(DEV_PASSWORD), created_at=now, updated_at=now
    )
    await identity.create_user(NO_POSTGRES, user, profile, cred)
    for purpose in ("terms", "privacy_notice", "core_service"):
        await identity_service.record_consent(
            NO_POSTGRES, uid, purpose, "granted", "2026-11-01", channel="support"
        )
    await _grant(uid, "super_admin", now)
    await _grant(uid, "content_manager", now)


async def seed_student_consents() -> None:
    """A self-signup adult also grants optional items at sign-up (AUTH-01 consents): three here."""
    from app.core.db import NO_POSTGRES
    from app.modules.identity import public as identity
    from app.modules.identity import service as identity_service

    u = await identity.find_user(NO_POSTGRES, "email", "student@dev.techdrona.local")
    assert u is not None
    state = await identity_service.current_consents(NO_POSTGRES, u.id)
    for purpose in ("security_monitoring", "analytics_personalisation", "marketing_email"):
        if purpose not in state:
            await identity_service.record_consent(
                NO_POSTGRES, u.id, purpose, "granted", "2026-11-01", channel="support"
            )


class Browser:
    """One browser profile: cookie jar + the SPA's CSRF double submit."""

    def __init__(self, app: Any) -> None:
        import httpx

        self.c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE, timeout=120)

    def _csrf(self) -> str:
        return self.c.cookies.get("td_csrf") or ""

    async def get(self, path: str, **params: Any) -> Any:
        return await self.c.get(f"/api/v1/{path}", params=params or None, headers=SAME)

    async def send(self, method: str, path: str, body: Any = None, idem: bool = False) -> Any:
        h = {**SAME, "x-csrf-token": self._csrf(), "origin": BASE, "content-type": "application/json"}
        if idem:
            h["idempotency-key"] = str(uuid.uuid4())
        return await self.c.request(
            method, f"/api/v1/{path}", json=body if body is not None else {}, headers=h
        )

    async def login(self, email: str, password: str) -> Any:
        await self.get("_bff/csrf")
        r = await self.send("POST", "auth/login", {"identifier": email, "password": password})
        assert r.status_code == 200 and r.json().get("result") == "authenticated", r.text[:400]
        return r


async def author_course(admin: Browser, publisher: Browser) -> tuple[str, str, list[str]]:
    slug = "probe-dsa"
    r = await admin.send(
        "POST",
        "studio/courses",
        {"title": "Probe DSA", "slug": slug, "visibility": "public", "is_free": True},
    )
    assert r.status_code == 201, r.text[:400]
    cid = r.json()["id"]
    r = await admin.send(
        "PATCH",
        f"studio/courses/{cid}/draft",
        {"summary": "Arrays to graphs", "tags": ["dsa"], "level": "beginner", "category": "dsa"},
    )
    assert r.status_code == 200, r.text[:400]
    lessons = []
    for title in ("Arrays", "Linked lists", "Graphs"):
        r = await admin.send(
            "POST",
            f"studio/courses/{cid}/draft/lessons",
            {
                "title": title,
                "lesson_type": "article",
                "article_body": {"doc": title},
                "est_reading_minutes": 3,
            },
        )
        assert r.status_code == 201, r.text[:400]
        lessons.append(r.json()["id"])
    r = await admin.send(
        "PUT",
        f"studio/courses/{cid}/draft/outline",
        {
            "modules": [
                {"title": "Start", "lesson_ids": lessons[:2]},
                {"title": "More", "lesson_ids": lessons[2:]},
            ]
        },
    )
    assert r.status_code == 200, r.text[:400]
    assert (await admin.send("POST", f"studio/courses/{cid}/submit-review")).status_code == 200
    r = await publisher.send("POST", f"studio/courses/{cid}/publish", {"change_type": "major"}, idem=True)
    assert r.status_code == 200, r.text[:400]
    return cid, slug, lessons


# ----------------------------------------------------------------------------- measure


async def measure(name: str, fn: Any, results: dict[str, Any], repeat: int = 3) -> Any:
    runs = []
    last = None
    for _ in range(repeat):
        before = fcp._snap()
        sites_before = Counter(SITES)
        last = await fn()
        d = fcp._diff(before, fcp._snap())
        runs.append(
            {
                "status": getattr(last, "status_code", None),
                "reads": d.get("reads", 0),
                "writes": d.get("writes", 0),
                "deletes": d.get("deletes", 0),
                "tx": d.get("transactions", 0),
            }
        )
        if _TRACE and _ == repeat - 1:
            delta = Counter(SITES)
            delta.subtract(sites_before)
            results.setdefault("_sites", {})[name] = sorted(
                ([k[0], k[1], k[2], v] for k, v in delta.items() if v), key=lambda x: -x[3]
            )
    results[name] = {"first": runs[0], "steady": runs[-1]}
    print(
        f"{name:42s} first r{runs[0]['reads']:>3} w{runs[0]['writes']:>3} d{runs[0]['deletes']:>2}   steady r{runs[-1]['reads']:>3} w{runs[-1]['writes']:>3} d{runs[-1]['deletes']:>2}  [{runs[-1]['status']}]",
        flush=True,
    )
    return last


async def scenario(results: dict[str, Any]) -> None:
    from lms_edge import EdgeApp
    from seed_emulator import seed_catalogue, seed_users

    from app.core import cloudtasks
    from app.core.config import reset_settings_cache
    from app.core.models_registry import import_all_models
    from app.main import create_app
    from app.seeds.dev_users import DEV_PASSWORD

    def _fake_enqueue(function: str, location: str, data: dict[str, Any], delay: float | None) -> str:
        fcp.COUNTS["cloud_tasks_enqueued"] += 1
        return f"probe-{fcp.COUNTS['cloud_tasks_enqueued']}"

    cloudtasks.enqueue_impl = _fake_enqueue  # type: ignore[assignment]
    reset_settings_cache()
    import_all_models()
    await seed_catalogue()
    await seed_users()
    await seed_publisher()
    await seed_student_consents()
    app = EdgeApp(create_app())
    admin, publisher, student = Browser(app), Browser(app), Browser(app)
    await admin.login("admin@dev.techdrona.local", DEV_PASSWORD)
    await publisher.login("publisher@dev.techdrona.local", DEV_PASSWORD)
    cid, slug, lessons = await author_course(admin, publisher)

    s = student
    nav = {**SAME, "x-td-activity": "navigation"}
    await measure("GET _bff/csrf (anonymous)", lambda: s.get("_bff/csrf"), results)
    await measure("GET _bff/session (anonymous)", lambda: s.get("_bff/session"), results)

    async def do_login() -> Any:
        s.c.cookies.clear()
        await s.get("_bff/csrf")
        return await s.login("student@dev.techdrona.local", DEV_PASSWORD)

    await measure("POST auth/login (+csrf bootstrap)", do_login, results)
    await measure("GET _bff/session (signed in)", lambda: s.get("_bff/session"), results)
    shell = [
        ("GET me", "me", {}),
        ("GET me/grants", "me/grants", {}),
        ("GET me/enabled-apps", "me/enabled-apps", {}),
        ("GET me/notifications unread poll", "me/notifications", {"unread_only": "true", "limit": 1}),
        ("GET me/modules (hub)", "me/modules", {}),
        ("GET me/dashboard", "me/dashboard", {}),
        ("GET me/tests", "me/tests", {}),
        ("GET me/admissions", "me/admissions", {}),
        ("GET me/classes", "me/classes", {}),
        ("GET analytics/config", "analytics/config", {}),
    ]
    for name, path, q in shell:
        await measure(name, lambda p=path, q=q: s.get(p, **q), results)
    await measure(
        "GET public/courses/status", lambda: s.c.get("/api/public/courses/status", headers=SAME), results
    )
    await measure(
        "GET catalog/courses?limit=50 (nav)",
        lambda: s.c.get("/api/v1/catalog/courses", params={"limit": 50}, headers=nav),
        results,
    )
    await measure("GET catalog/courses/{slug}", lambda: s.get(f"catalog/courses/{slug}"), results)
    await measure("GET me/courses/{id} (not enrolled)", lambda: s.get(f"me/courses/{cid}"), results)
    await measure(
        "POST me/enrolments",
        lambda: s.send("POST", "me/enrolments", {"course_id": cid}, idem=True),
        results,
        repeat=1,
    )
    await measure("GET me/enrolments?limit=100", lambda: s.get("me/enrolments", limit=100), results)
    await measure("GET me/dashboard (enrolled)", lambda: s.get("me/dashboard"), results)
    await measure("GET me/courses/{id}", lambda: s.get(f"me/courses/{cid}"), results)
    await measure(
        "GET me/courses/{id}/lessons/{id}", lambda: s.get(f"me/courses/{cid}/lessons/{lessons[0]}"), results
    )
    r = await s.get(f"me/courses/{cid}/lessons/{lessons[0]}")
    key = (r.json().get("lesson") or r.json()).get("lesson_key") if r.status_code == 200 else None
    if key:
        await measure(
            "POST me/lessons/{key}/completion",
            lambda: s.send("POST", f"me/lessons/{key}/completion", {"evidence": {"scrolled_to_end": True}}),
            results,
            repeat=1,
        )
    await measure("GET me/notifications?limit=20", lambda: s.get("me/notifications", limit=20), results)
    await measure(
        "GET me/notifications unread poll (2)",
        lambda: s.get("me/notifications", unread_only="true", limit=1),
        results,
    )
    await measure("POST auth/logout", lambda: s.send("POST", "auth/logout"), results, repeat=1)
    await measure("GET me (after logout)", lambda: s.get("me"), results, repeat=1)

    # The simulated hour: a fresh sign-in, then the SPA's traffic on a shifted clock.
    await do_login()
    for lid in lessons:
        body = (await s.get(f"me/courses/{cid}/lessons/{lid}")).json()
        LESSON_KEYS[lid] = body["lesson_key"]
    await simulate_hour(s, cid, slug, lessons, results)


# Simulated clock for the student-hour run: every app module reads "now" through
# app.core.time.utcnow (patched in main() before any app import), so session idle/last-seen
# bookkeeping, reading-time checks etc. see the hour pass without the probe sleeping.
OFFSET_S = [0.0]


def _patch_clock() -> None:
    from datetime import timedelta

    import app.core.time as tmod

    real = tmod.utcnow

    def shifted() -> Any:
        return real() + timedelta(seconds=OFFSET_S[0])

    tmod.utcnow = shifted  # type: ignore[assignment]


def load_baseline(folder: str) -> list[str]:
    """``--baseline DIR``: measure the code BEFORE a change. ``DIR/manifest.json`` maps module
    names to files in DIR (pre-change copies, e.g. ``{"app.core.firestore.store": "store.py"}``);
    they are loaded in that order in place of the working-tree modules, before anything else
    imports them."""
    import importlib
    import importlib.util

    manifest = json.loads((Path(folder) / "manifest.json").read_text(encoding="utf-8"))
    for name, file in manifest.items():
        parent, _, leaf = name.rpartition(".")
        pkg = importlib.import_module(parent)
        spec = importlib.util.spec_from_file_location(name, str(Path(folder) / file))
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        setattr(pkg, leaf, mod)
    return list(manifest)


def _patch_window_clock() -> None:
    """Rate-limit windows (app.core.ratelimit) and lms_kv expiry read time.time(): shift them too."""
    import time as real_time
    import types
    from datetime import UTC, datetime

    from app.core import ratelimit
    from app.core.firestore import kv

    shim = types.SimpleNamespace(
        **{k: getattr(real_time, k) for k in dir(real_time) if not k.startswith("_")}
    )
    shim.time = lambda: real_time.time() + OFFSET_S[0]
    ratelimit.time = shim  # type: ignore[attr-defined]
    kv._now = lambda: datetime.fromtimestamp(real_time.time() + OFFSET_S[0], tz=UTC)  # type: ignore[attr-defined]


def _heartbeats(n: int, route: str, surface: str) -> dict[str, Any]:
    from app.core.ids import uuid7
    from app.core.time import utcnow

    now = utcnow().isoformat()
    tab, page = str(uuid.uuid4()), str(uuid.uuid4())
    return {
        "sent_at": now,
        "client": {"app_version": "probe", "platform": "web", "tz_offset_min": 330, "measurement_version": "tm-1.0"},
        "events": [
            {
                "event_id": str(uuid7()), "event_type": "page.heartbeat", "schema_version": 1, "occurred_at": now,
                "mono_ms": 1000 * (i + 1), "tab_id": tab, "page_instance_id": page, "seq": i, "route": route,
                "surface": surface,
                "payload": {"kind": "engaged", "sample_interval_ms": 15000, "active_ms": 15000,
                            "state": {"visible": True, "focused": True, "input_recent": True, "media_playing": False}},
            }
            for i in range(n)
        ],
    }  # fmt: skip


async def simulate_hour(s: Browser, cid: str, slug: str, lessons: list[str], results: dict[str, Any]) -> None:
    """One student-hour of study, request by request, from the SPA's real behaviour
    (apps/lms-spa; file:line references in docs/firebase/agents/cost-requests.md):

    * t=0 app open: ``_bff/session``, hub ``me/modules`` (one module -> redirect to /app), shell
      (``me``, ``me/grants``, ``me/enabled-apps``, bell), dashboard (``me/dashboard``,
      ``me/tests``, then ``me/admissions`` + ``me/classes``, ``public/courses/status``),
      ``analytics/config``;
    * NotificationBell: every 120 s while visible (NotificationBell.tsx:10,44) and on every
      client-side route change (:33-35);
    * 12 article lessons (~5 min each): lesson page = ``catalog/courses/{slug}`` ->
      ``me/courses/{id}`` + lesson (LessonView.tsx:354-367), completion POST after reading;
      every 4th lesson via the course page first; leaving the lesson focus route remounts the
      sidebar -> ``me/enabled-apps`` again (60 s TTL expired);
    * My learning twice (``me/enrolments``), the in-app catalogue once, the notifications page once;
    * analytics: one ``POST analytics/events`` flush of 2 heartbeats every 30 s (tracker.ts:
      heartbeat 15 s while ACTIVE, flush 30 s) -- reported separately (analytics cost pass).
    """
    nav = {**SAME, "x-td-activity": "navigation"}
    ev: list[tuple[float, str, Any]] = []

    def at(t: float, name: str, fn: Any) -> None:
        ev.append((t, name, fn))

    bell = lambda: s.get("me/notifications", unread_only="true", limit=1)  # noqa: E731
    for name, path in (("_bff/session", "_bff/session"), ("me/modules", "me/modules"), ("me", "me"),
                       ("me/grants", "me/grants"), ("me/enabled-apps", "me/enabled-apps"),
                       ("me/dashboard", "me/dashboard"), ("me/tests", "me/tests"), ("me/admissions", "me/admissions"),
                       ("me/classes", "me/classes"), ("analytics/config", "analytics/config")):  # fmt: skip
        at(0, name, lambda p=path: s.get(p))
    at(0, "bell", bell)
    at(0, "public/courses/status", lambda: s.c.get("/api/public/courses/status", headers=SAME))
    for t in range(120, 3600, 120):
        at(t, "bell", bell)
    for k in range(12):
        t0 = 60 + k * 290
        lid = lessons[k % len(lessons)]
        if k % 4 == 0:
            at(t0 - 20, "catalog/courses/{slug}", lambda: s.get(f"catalog/courses/{slug}"))
            at(t0 - 20, "me/courses/{id}", lambda: s.get(f"me/courses/{cid}"))
            at(t0 - 20, "bell", bell)
            if k:
                at(t0 - 20, "me/enabled-apps", lambda: s.get("me/enabled-apps"))
        at(t0, "catalog/courses/{slug}", lambda: s.get(f"catalog/courses/{slug}"))
        at(t0, "me/courses/{id}", lambda: s.get(f"me/courses/{cid}"))
        at(t0, "me/courses/{id}/lessons/{id}", lambda lid=lid: s.get(f"me/courses/{cid}/lessons/{lid}"))
        at(t0, "bell", bell)
        at(t0 + 240, "completion", lambda lid=lid: _complete(s, cid, lid))
    for t in (1500, 3000):
        at(t, "me/enrolments", lambda: s.get("me/enrolments", limit=100))
        at(t, "bell", bell)
    at(
        2000,
        "catalog/courses (nav)",
        lambda: s.c.get("/api/v1/catalog/courses", params={"limit": 50}, headers=nav),
    )
    at(2000, "bell", bell)
    at(2500, "me/notifications page", lambda: s.get("me/notifications", limit=20))
    at(2500, "bell", bell)
    for t in range(30, 3600, 30):
        at(
            t + 0.5,
            "analytics/events (other pass)",
            lambda: s.send("POST", "analytics/events", _heartbeats(2, "/app/learn", "lesson_text")),
        )
    ev.sort(key=lambda e: e[0])

    per: dict[str, Counter[str]] = {}
    statuses: Counter[str] = Counter()
    for t, name, fn in ev:
        OFFSET_S[0] = t
        before = fcp._snap()
        r = await fn()
        d = fcp._diff(before, fcp._snap())
        c = per.setdefault(name, Counter())
        c["requests"] += 1
        for k2 in ("reads", "writes", "deletes"):
            c[k2] += d.get(k2, 0)
        statuses[f"{name}:{getattr(r, 'status_code', '?')}"] += 1
    OFFSET_S[0] = 0.0
    total: Counter[str] = Counter()
    for name, c in per.items():
        bucket = "analytics" if name.startswith("analytics/events") else "request_path"
        for k2, v in c.items():
            total[f"{bucket}.{k2}"] += v
    results["_hour"] = {
        "by_endpoint": {k: dict(v) for k, v in sorted(per.items())},
        "totals": dict(total),
        "statuses": dict(statuses),
    }
    print("\n-- simulated student-hour --")
    for k, v in sorted(per.items()):
        print(
            f"{k:34s} n={v['requests']:>3}  reads={v['reads']:>5}  writes={v['writes']:>4}  deletes={v['deletes']:>3}"
        )
    print(json.dumps(dict(total), indent=1))
    print("statuses:", dict(statuses))


LESSON_KEYS: dict[str, str] = {}


async def _complete(s: Browser, cid: str, lid: str) -> Any:
    """LessonView's end-of-reading completion (it already holds the lesson_key)."""
    return await s.send(
        "POST", f"me/lessons/{LESSON_KEYS[lid]}/completion", {"evidence": {"scrolled_to_end": True}}
    )


def main() -> None:
    global _TRACE
    p = argparse.ArgumentParser()
    p.add_argument("--project", default="demo-costreq")
    p.add_argument("--json", default="")
    p.add_argument("--sites", action="store_true", help="per call-site breakdown in the JSON")
    p.add_argument("--baseline", default="", help="folder with pre-change module copies + manifest.json")
    args = p.parse_args()
    _request_env()
    _patch_clock()  # before any other app import binds app.core.time.utcnow
    fcp._env(args.project)
    if args.baseline:
        print("baseline modules:", load_baseline(args.baseline))
    _patch_window_clock()
    adapt_streams()
    fcp.instrument()
    trace_sites()
    _TRACE = args.sites
    fcp._wipe(args.project)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())  # type: ignore[attr-defined]
    results: dict[str, Any] = {}
    asyncio.run(scenario(results))
    tot = results["_hour"]["totals"]
    rp_r, rp_w = max(1, tot.get("request_path.reads", 0)), max(1, tot.get("request_path.writes", 0))
    all_r = rp_r + tot.get("analytics.reads", 0)
    all_w = rp_w + tot.get("analytics.writes", 0)
    results["_student_hours_per_day_free"] = {
        "request_path_only": {"by_reads": round(50_000 / rp_r, 1), "by_writes": round(20_000 / rp_w, 1)},
        "with_analytics": {
            "by_reads": round(50_000 / all_r, 1),
            "by_writes": round(20_000 / max(1, all_w), 1),
        },
    }
    print(json.dumps(results["_student_hours_per_day_free"], indent=1))
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")


if __name__ == "__main__":
    main()
