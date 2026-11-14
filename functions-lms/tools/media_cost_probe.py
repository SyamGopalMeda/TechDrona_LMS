"""Firestore cost probe for VIDEO VIEWING (cost-media agent, docs/firebase/agents/cost-media.md).

    apps/api/.venv/Scripts/python functions-lms/tools/media_cost_probe.py [--minutes 10] [--json out.json]

Counts billable Firestore operations at the google-cloud-firestore RPC level (every GAPIC call of
the async client: documents returned by get/batchGet/runQuery = reads, a query returning nothing
= 1 read, each Write of a Commit = 1 write or delete) while it drives the REAL service code of a
learner watching one video lesson on the all-Firestore stack (every ``TD_STORE_*=firestore``,
``TD_CACHE_BACKEND=firestore``, fake VdoCipher):

1. seed (not counted): a free published course with one 600 s video lesson + asset, an enrolment;
2. MED-04 ``issue_playback`` (once per viewing);
3. per player interval (default 30 s): MED-05 ``heartbeat`` (media + learning + analytics
   coverage lookup + sessions ``touch_engaged``) and one ANL-01 analytics batch (what the SPA
   tracker flushes every 30 s while a video plays: two ``page.heartbeat`` engaged samples with
   ``media.played_ranges``) through ``enforce_rate_limits`` + ``ingest_batch`` + ``after_ingest``;
4. MED-06 ``stop``.

Not counted here (other agents' scope, measured by their probes): the per-request middleware
(session resolve, CSRF, rate limit of MED-05 itself, idempotency). The analytics ingest rate
limit IS counted (it is called by the analytics route body).

DEMO ONLY: refuses unless ``FIRESTORE_EMULATOR_HOST`` is set; uses its own ``demo-cost-media``
project on the emulator and wipes only that project.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

API = Path(__file__).resolve().parents[2] / "apps" / "api"
sys.path.insert(0, str(API))
PROJECT = "demo-cost-media"


# =========================================================================== RPC-level counter


def _coll(name: str) -> str:
    """Collection id of a document path ``projects/p/databases/d/documents/<coll>/<id>[/...]``."""
    parts = name.split("/documents/", 1)[-1].split("/")
    return parts[-2] if len(parts) >= 2 else parts[0]


class OpCounter:
    """Billable reads / writes / deletes per collection, plus RPC counts."""

    def __init__(self) -> None:
        self.reads: Counter[str] = Counter()
        self.writes: Counter[str] = Counter()
        self.deletes: Counter[str] = Counter()
        self.rpcs: Counter[str] = Counter()

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]

    def totals(self) -> dict[str, int]:
        return {
            "reads": sum(self.reads.values()),
            "writes": sum(self.writes.values()),
            "deletes": sum(self.deletes.values()),
            "rpcs": sum(self.rpcs.values()),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            **self.totals(),
            "reads_by_collection": dict(self.reads.most_common()),
            "writes_by_collection": dict(self.writes.most_common()),
            "deletes_by_collection": dict(self.deletes.most_common()),
            "rpcs_by_method": dict(self.rpcs.most_common()),
        }


def install_counter(counter: OpCounter) -> Callable[[], None]:
    """Patch ``FirestoreAsyncClient`` (the GAPIC layer every async Firestore call goes through)."""
    from google.cloud.firestore_v1.services.firestore import async_client as ac
    from google.cloud.firestore_v1.types import firestore as fpb

    req_types = {
        "commit": fpb.CommitRequest,
        "get_document": fpb.GetDocumentRequest,
        "batch_get_documents": fpb.BatchGetDocumentsRequest,
        "run_query": fpb.RunQueryRequest,
        "run_aggregation_query": fpb.RunAggregationQueryRequest,
    }

    def norm(name: str, req: Any) -> Any:
        t = req_types.get(name)
        return t(req) if t is not None and isinstance(req, dict) else req

    cls = ac.FirestoreAsyncClient
    saved: dict[str, Any] = {}

    def unary(name: str, on_req: Callable[[Any], None], on_resp: Callable[[Any], None] | None = None) -> None:
        orig = getattr(cls, name)
        saved[name] = orig

        async def wrapped(self: Any, request: Any = None, **kw: Any) -> Any:
            counter.rpcs[name] += 1
            on_req(norm(name, request))
            resp = await orig(self, request=request, **kw)
            if on_resp is not None:
                on_resp(resp)
            return resp

        setattr(cls, name, wrapped)

    def stream(name: str, on_req: Callable[[Any], str], on_item: Callable[[Any, str], int]) -> None:
        orig = getattr(cls, name)
        saved[name] = orig

        def wrapped(self: Any, request: Any = None, **kw: Any) -> Any:
            counter.rpcs[name] += 1
            coll = on_req(norm(name, request))

            async def go() -> Any:
                it = await orig(self, request=request, **kw)

                async def gen() -> Any:
                    n = 0
                    async for item in it:
                        n += on_item(item, coll)
                        yield item
                    if n == 0:  # an empty query / lookup is still billed one read
                        counter.reads[coll] += 1

                return gen()

            return go()

        setattr(cls, name, wrapped)

    def commit_req(req: Any) -> None:
        for w in getattr(req, "writes", []) or []:
            kind = w._pb.WhichOneof("operation")
            if kind == "delete":
                counter.deletes[_coll(w.delete)] += 1
            elif kind == "update":
                counter.writes[_coll(w.update.name)] += 1
            elif kind == "transform":
                counter.writes[_coll(w.transform.document)] += 1

    def get_doc(req: Any) -> None:
        counter.reads[_coll(req.name)] += 1

    def bget_req(req: Any) -> str:
        docs = list(getattr(req, "documents", []) or [])
        return _coll(docs[0]) if docs else "?"

    def bget_item(item: Any, coll: str) -> int:
        if item._pb.HasField("found"):
            counter.reads[_coll(item.found.name)] += 1
            return 1
        if item.missing:  # a missing document is billed as a read too
            counter.reads[_coll(item.missing)] += 1
            return 1
        return 0

    def query_req(req: Any) -> str:
        sq = req.structured_query
        return sq.from_[0].collection_id if sq.from_ else "?"

    def query_item(item: Any, coll: str) -> int:
        if item._pb.HasField("document"):
            counter.reads[_coll(item.document.name)] += 1
            return 1
        return 0

    def agg_item(item: Any, coll: str) -> int:
        if item._pb.HasField("result"):
            counter.reads[coll + " (aggregate)"] += 1
            return 1
        return 0

    def agg_req(req: Any) -> str:
        sq = req.structured_aggregation_query.structured_query
        return sq.from_[0].collection_id if sq.from_ else "?"

    unary("commit", commit_req)
    unary("get_document", get_doc)
    unary("begin_transaction", lambda r: None)
    unary("rollback", lambda r: None)
    stream("batch_get_documents", bget_req, bget_item)
    stream("run_query", query_req, query_item)
    stream("run_aggregation_query", agg_req, agg_item)

    def uninstall() -> None:
        for k, v in saved.items():
            setattr(cls, k, v)

    return uninstall


# =========================================================================== environment


def _env() -> None:
    host = os.environ.get("FIRESTORE_EMULATOR_HOST") or "127.0.0.1:18080"
    os.environ["FIRESTORE_EMULATOR_HOST"] = host
    os.environ["FIREBASE_PROJECT_ID"] = PROJECT
    os.environ["APP_ENV"] = "test"
    os.environ["DATABASE_URL"] = ""
    os.environ["TD_RUNTIME"] = "firebase"
    os.environ["TD_CACHE_BACKEND"] = "firestore"
    # No Cloud Tasks from a probe: job hints/kicks (scheduler agent's scope, its own probe) stay off.
    os.environ["TD_TASKS_BACKEND"] = "celery"
    os.environ["VDOCIPHER_MODE"] = "stub"
    from app.core.firestore.backend import MODULES

    for m in MODULES:
        os.environ[f"TD_STORE_{m.upper()}"] = "firestore"


def _wipe() -> None:
    import httpx

    host = os.environ["FIRESTORE_EMULATOR_HOST"]
    httpx.delete(
        f"http://{host}/emulator/v1/projects/{PROJECT}/databases/(default)/documents", timeout=60.0
    ).raise_for_status()


# =========================================================================== world


async def seed(duration_s: int, paid: bool, watched: int = 0) -> dict[str, Any]:
    from app.core.db import NO_POSTGRES
    from app.core.firestore.store import ScopedStore
    from app.core.ids import uuid7
    from app.core.time import utcnow
    from app.modules.catalog.store_specs import ASSETS, COURSES, LESSONS, VERSIONS
    from app.modules.learning import service as learning

    now = utcnow()
    staff = uuid7()
    course_id, version_id, lesson_id, asset_id, module_id = (uuid7() for _ in range(5))
    s = ScopedStore.system("firestore.backfill")
    base = {"organization_id": None, "created_at": now, "updated_at": now}
    await s.import_documents(
        COURSES,
        [
            (
                str(course_id),
                {
                    **base,
                    "id": str(course_id),
                    "slug": "probe-video",
                    "title": "Probe",
                    "course_kind": "course",
                    "visibility": "public",
                    "status": "published",
                    "is_free": not paid,
                    "current_version_id": str(version_id),
                    "completeness_pct": "0",
                    "created_by": str(staff),
                    "deleted_at": None,
                },
            )
        ],
    )
    await s.import_documents(
        VERSIONS,
        [
            (
                str(version_id),
                {
                    **base,
                    "id": str(version_id),
                    "course_id": str(course_id),
                    "version_no": 1,
                    "title": "Probe",
                    "outcomes": [],
                    "language": "en",
                    "tags": [],
                    "status": "published",
                    "created_by": str(staff),
                    "published_at": now,
                    "certificate_rule": None,
                    "outline": [],
                    "lesson_count": 1,
                    "duration_seconds": duration_s,
                },
            )
        ],
    )
    await s.import_documents(
        LESSONS,
        [
            (
                str(lesson_id),
                {
                    **base,
                    "id": str(lesson_id),
                    "course_module_id": str(module_id),
                    "course_version_id": str(version_id),
                    "course_id": str(course_id),
                    "lesson_key": str(lesson_id),
                    "title": "Video",
                    "lesson_type": "video",
                    "position": 1,
                    "is_required": True,
                    "is_free_preview": False,
                    "duration_seconds": duration_s,
                    "topics": [],
                },
            )
        ],
    )
    await s.import_documents(
        ASSETS,
        [
            (
                str(asset_id),
                {
                    **base,
                    "id": str(asset_id),
                    "lesson_id": str(lesson_id),
                    "asset_type": "video",
                    "provider": "vdocipher",
                    "provider_asset_id": "probe-fake-1",
                    "duration_seconds": duration_s,
                    "status": "available",
                    "scan_status": "not_required",
                    "position": 1,
                },
            )
        ],
    )
    from app.modules.catalog import api as catalog_api

    course = (await catalog_api.get_courses(NO_POSTGRES, [course_id]))[course_id]
    user = uuid7()
    if paid:  # a paid course the learner bought: course entitlement (what checkout grants)
        from app.modules.entitlements import service as ent

        # The repository write of ``entitlements.service.grant`` (its cache bump needs a SQL session).
        values = {
            "id": uuid7(),
            "user_id": user,
            "organization_id": None,
            "product_id": None,
            "course_id": course_id,
            "feature_key": None,
            "source_type": "admin_grant",
            "order_item_id": None,
            "subscription_id": None,
            "coupon_redemption_id": None,
            "granted_by": staff,
            "grant_reason": "cost probe",
            "status": "active",
            "starts_at": now - timedelta(days=1),
            "ends_at": None,
            "grace_ends_at": None,
        }
        ev = ent._event_fields(
            "granted", ent.Actor("system"), to_status="active", delta={}, reason="cost probe"
        )
        await ent._repo().grant(values, ev)
    enr = await learning.create_enrolment(
        NO_POSTGRES, user_id=user, course=course, source="purchase" if paid else "free"
    )
    await learning.fss.flush(NO_POSTGRES)
    if watched:  # coverage documents of other videos the learner watched before
        from app.modules.analytics.store_specs import VideoRow

        await s.import_documents(
            "video_watch_coverage",
            [
                (
                    f"{user}:{i}",
                    VideoRow(
                        user_id=user,
                        lesson_asset_id=uuid7(),
                        organization_id=None,
                        lesson_id=uuid7(),
                        covered_ranges=None,
                        covered_s=100,
                        coverage_pct=50,
                        duration_s=200,
                        last_position_s=100,
                        updated_at=now,
                    ).doc(),
                )
                for i in range(watched)
            ],
        )
    return {"user": user, "course": course_id, "lesson": lesson_id, "asset": asset_id, "enrolment": enr.id}


def _uuid7_at(ts: Any) -> str:
    """A UUIDv7 carrying ``ts`` (ingest checks the id time against ``occurred_at``)."""
    ms = int(ts.timestamp() * 1000)
    rnd = int.from_bytes(os.urandom(10), "big")
    n = (ms << 80) | (0x7 << 76) | ((rnd >> 64) & 0xFFF) << 64 | (0b10 << 62) | (rnd & ((1 << 62) - 1))
    return str(uuid.UUID(int=n))


def _batch(world: dict[str, Any], page: str, tab: str, seq: int, t0: float, step_s: int) -> Any:
    """What the SPA tracker flushes every 30 s during playback: two engaged heartbeats (15 s)
    carrying the played media ranges."""
    from app.core.time import utcnow
    from app.modules.analytics.schemas import BatchIn

    now = utcnow()
    events = []
    half = step_s // 2
    for i in range(2):
        a = t0 + i * half
        occurred = now - timedelta(seconds=(1 - i) * half)
        events.append(
            {
                "event_id": _uuid7_at(occurred),
                "event_type": "page.heartbeat",
                "schema_version": 1,
                "occurred_at": occurred.isoformat(),
                "mono_ms": int((t0 + (i + 1) * half) * 1000),
                "tab_id": tab,
                "page_instance_id": page,
                "seq": seq + i,
                "route": "/app/learn/[courseId]/[lessonId]",
                "surface": "lesson_video",
                "entity": {
                    "course_id": str(world["course"]),
                    "lesson_id": str(world["lesson"]),
                    "lesson_asset_id": str(world["asset"]),
                },
                "payload": {
                    "kind": "engaged",
                    "sample_interval_ms": half * 1000,
                    "active_ms": min(20000, half * 1000),
                    "state": {"visible": True, "focused": True, "input_recent": False, "media_playing": True},
                    "input_events": 0,
                    "media": {
                        "lesson_asset_id": str(world["asset"]),
                        "position_s": a + half,
                        "rate": 1.0,
                        "played_ranges": [[a, a + half]],
                    },
                },
            }
        )
    return BatchIn.model_validate(
        {
            "sent_at": now.isoformat(),
            "client": {"app_version": "probe", "platform": "web", "measurement_version": "tm-1.0"},
            "events": events,
        }
    )


async def run(minutes: int, step_s: int, paid: bool, session_kind: str, watched: int = 0) -> dict[str, Any]:
    from app.core import time as core_time
    from app.core.db import NO_POSTGRES
    from app.core.errors import ProblemError
    from app.core.firestore.sqlstore import _memory_relay
    from app.core.ids import uuid7
    from app.core.principal import Principal
    from app.main import create_app
    from app.modules.analytics import service as anl
    from app.modules.media import service as media

    create_app()  # wiring: coverage lookup, hooks, outbox handlers
    world = await seed(max(600, minutes * 60 + 60), paid, watched)
    principal = Principal(
        user_id=world["user"], session_id=uuid7(), device_id=uuid7(), is_minor=False, privacy_tier="adult"
    )
    counter = OpCounter()
    uninstall = install_counter(counter)

    async def in_tx(fn: Callable[[Any], Any]) -> Any:
        """One request: the media routes' session. ``--session memory`` = a ``MemoryTx`` (what
        ``StorePrincipalDbSession`` gives); ``nopg`` = ``NO_POSTGRES`` (what
        ``core.db.PrincipalDbSession``, the media router's dependency today, gives)."""
        if session_kind == "nopg":
            return await fn(NO_POSTGRES)
        relay = _memory_relay(principal)
        tx = await relay.__anext__()
        out = await fn(tx)
        async for _ in relay:
            pass
        return out

    out: dict[str, Any] = {}
    real_now = core_time.utcnow
    clock = {"t": real_now()}

    def fake_now() -> Any:
        return clock["t"]

    # Advance a fake clock between heartbeats so elapsed/plausibility rules credit the watch.
    patched = []
    import app.modules.analytics.service as anl_mod
    import app.modules.learning.service as lrn_mod
    import app.modules.media.service as med_mod

    for mod in (core_time, med_mod, lrn_mod, anl_mod):
        if hasattr(mod, "utcnow"):
            patched.append((mod, mod.utcnow))
            mod.utcnow = fake_now  # type: ignore[attr-defined]
    try:
        counter.reset()
        tok = await in_tx(
            lambda tx: media.issue_playback(
                tx, principal, asset_id=world["asset"], tab_id=uuid.uuid4(), take_over_id=None
            )
        )
        assert isinstance(tok, dict), tok
        out["issue_playback"] = counter.snapshot()
        ps_id = uuid.UUID(tok["playback_session_id"])

        hb_snaps: list[dict[str, Any]] = []
        anl_snaps: list[dict[str, Any]] = []
        page, tab = str(uuid.uuid4()), str(uuid.uuid4())
        pos = 0
        steps = max(1, (minutes * 60) // step_s)
        for i in range(steps):
            clock["t"] = clock["t"] + timedelta(seconds=step_s)
            counter.reset()
            at = pos + step_s

            async def beat(tx: Any, at: int = at) -> Any:
                return await media.heartbeat(tx, principal, ps_id, position_s=at, playing=True)

            problem, credited = await in_tx(beat)
            assert problem is None, problem
            if credited:
                from app.modules.sessions.resolver import touch_engaged

                await touch_engaged(principal.session_id)
            hb_snaps.append(counter.snapshot())
            counter.reset()
            try:  # its counters use the real clock: the fast probe trips them (ops still counted)
                await anl.enforce_rate_limits(principal, "203.0.113.7")
            except ProblemError as e:
                if e.status != 429:
                    raise
            # ANL-01's session: StorePrincipalDbSession = a MemoryTx committed after the route.
            relay = _memory_relay(principal)
            tx = await relay.__anext__()
            res = await anl.ingest_batch(
                tx, principal, _batch(world, page, tab, i * 2, pos, step_s), now=clock["t"]
            )
            await anl.after_ingest(principal, res)
            if i == 0:
                out["analytics_results_first"] = res.results
            async for _ in relay:
                pass
            anl_snaps.append(counter.snapshot())
            pos += step_s
        counter.reset()
        await in_tx(lambda tx: media.stop(tx, principal, ps_id))
        out["stop"] = counter.snapshot()
        out["heartbeat_first"] = hb_snaps[0]
        out["heartbeat_steady"] = hb_snaps[-1]
        out["analytics_batch_first"] = anl_snaps[0]
        out["analytics_batch_steady"] = anl_snaps[-1]
        per_hour = 3600 // step_s

        def hour(snaps: list[dict[str, Any]], k: str) -> float:
            avg = sum(s[k] for s in snaps) / len(snaps)
            return round(avg * per_hour, 1)

        out["per_viewing_hour"] = {
            "function_invocations": {
                "MED-05 heartbeat": per_hour,
                "ANL-01 analytics batch": per_hour,
                "MED-04 token + MED-06 stop (per viewing, not per hour)": 2,
            },
            "MED-05": {k: hour(hb_snaps, k) for k in ("reads", "writes", "deletes")},
            "ANL-01": {k: hour(anl_snaps, k) for k in ("reads", "writes", "deletes")},
        }
        from app.modules.learning import service as learning

        enr = await learning.get_enrolment(NO_POSTGRES, world["user"], world["course"])
        assert enr is not None
        lp = await learning.get_progress(NO_POSTGRES, enr, world["lesson"], create=False)
        out["result"] = {
            "watched_seconds": lp.watched_seconds if lp else None,
            "status": lp.status if lp else None,
            "intervals": lp.watched_intervals if lp else None,
        }
    finally:
        for mod, fn in patched:
            mod.utcnow = fn  # type: ignore[attr-defined]
        uninstall()
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=10)
    ap.add_argument("--step", type=int, default=30, help="player heartbeat / analytics flush interval (s)")
    ap.add_argument("--free", action="store_true", help="free course (default: a purchased course)")
    ap.add_argument("--session", choices=("memory", "nopg"), default="memory")
    ap.add_argument("--watched", type=int, default=0, help="other videos the learner watched before")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    _env()
    if not os.environ["FIREBASE_PROJECT_ID"].startswith("demo-"):
        sys.exit("refusing: not a demo-* project")
    _wipe()
    from app.core.config import reset_settings_cache
    from app.core.models_registry import import_all_models

    reset_settings_cache()
    import_all_models()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    out = asyncio.run(run(args.minutes, args.step, not args.free, args.session, args.watched))
    text = json.dumps(out, indent=2, default=str)
    if args.json:
        Path(args.json).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
