"""cost-media: ingest reads one ``analytics_page_heartbeats`` summary per page instead of every batch
of the page (docs/firebase/agents/cost-media.md). Emulator only, no Postgres.

The same video viewing (30 s client batches of two engaged heartbeats with played ranges, a retried
batch, a too-close sample, an over-claimed range, a late sample between stored ones, a keepalive)
is ingested by two learners: once with the summaries (new path) and once reading the batches (the
previous path). Per-event results, credited seconds, the stored rows (kind, flags, clamped ranges)
and the resulting ``video_watch_coverage`` / daily aggregates must be identical. The legacy page
(batches stored before summaries existed), the size cap fallback and erasure are covered too.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest

from app.core.ids import uuid7
from app.core.time import ist_date
from tests.analytics.conftest import Page, batch, principal_for
from tests.paths.fs.http_harness import FakeSession

FS_MODULES = ("analytics",)
pytestmark = pytest.mark.usefixtures("fs_env")


class _Allow:
    async def check(
        self, session: Any, principal: Any, rtype: Any, rid: Any, *, is_free: bool = False
    ) -> Any:
        from app.core.access import AccessDecision

        return AccessDecision(True, "test")


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Any]]:
    from app.core.access import get_access_checker, register_access_checker
    from app.modules.analytics import consumer, hooks, jobs, service

    course, lesson, asset = uuid7(), uuid7(), uuid7()

    async def lesson_course(session: Any, ctx: Any, lid: uuid.UUID) -> uuid.UUID | None:
        return course if lid == lesson else None

    async def asset_lesson(session: Any, ctx: Any, aid: uuid.UUID) -> uuid.UUID | None:
        return lesson if aid == asset else None

    async def no_org(session: Any, principal: Any, ref: Any) -> None:
        return None

    async def adult(session: Any, user_id: uuid.UUID) -> tuple[str, bool]:
        return ("adult", False)

    async def touch(session_id: uuid.UUID) -> None:
        return None

    class Meta(hooks.LessonMetaLookup):
        async def assets(self, session: Any, ids: set[uuid.UUID]) -> dict[uuid.UUID, hooks.AssetMeta]:
            return {a: hooks.AssetMeta(duration_s=1800) for a in ids if a == asset}

    prev = get_access_checker()
    register_access_checker(_Allow())
    monkeypatch.setattr(service, "_lesson_course", lesson_course)
    monkeypatch.setattr(service, "_asset_lesson", asset_lesson)
    monkeypatch.setattr(jobs, "_user_flags", adult)
    monkeypatch.setattr(consumer, "_user", adult)
    hooks.register_org_resolver(no_org)
    hooks.register_lesson_meta_lookup(Meta())
    hooks.register_engagement_toucher(touch)
    try:
        yield {"course": course, "lesson": lesson, "asset": asset}
    finally:
        register_access_checker(prev)
        hooks.register_org_resolver(None)
        hooks.register_lesson_meta_lookup(None)
        hooks.register_engagement_toucher(None)


def _media(asset: uuid.UUID, a: float, b: float) -> dict[str, Any]:
    return {"lesson_asset_id": str(asset), "position_s": b, "rate": 1.0, "played_ranges": [[a, b]]}


def _plan(world: dict[str, Any], t0: datetime) -> list[tuple[datetime, list[dict[str, Any]]]]:
    """(received_at, events) per client batch of one video page instance."""
    asset = world["asset"]
    page = Page(
        "lesson_video", {"course_id": world["course"], "lesson_id": world["lesson"], "lesson_asset_id": asset}
    )
    out: list[tuple[datetime, list[dict[str, Any]]]] = [(t0 + timedelta(seconds=1), [page.view(t0)])]
    pos = 0.0
    for k in range(12):
        base = t0 + timedelta(seconds=30 * k)
        evs = []
        for i in (1, 2):
            at = base + timedelta(seconds=15 * i)
            evs.append(page.hb(at, media=True, input_recent=False, media_info=_media(asset, pos, pos + 15)))
            pos += 15
        if k == 4:  # a second engaged sample 5 s after the previous one: rate_capped
            evs.append(
                page.hb(base + timedelta(seconds=35), media=True, media_info=_media(asset, pos, pos + 5))
            )
        if k == 6:  # over-claimed ranges (90 s of media in a 15 s sample): clamped
            evs.append(
                page.hb(base + timedelta(seconds=44), media=True, media_info=_media(asset, pos, pos + 90))
            )
        if k == 9:  # idle keepalive carrying hidden-tab coverage
            evs.append(
                page.hb(
                    base + timedelta(seconds=41),
                    kind="keepalive",
                    active_ms=0,
                    interval_ms=300000,
                    media=True,
                    media_info=_media(asset, pos, pos + 10),
                )
            )
        out.append((base + timedelta(seconds=32), evs))
        if k == 3:  # the client retries batch k=2 (network timeout): all duplicates
            out.append((base + timedelta(seconds=33), out[-2][1]))
    # a late sample that falls between already stored ones (delivered at the end)
    late_at = t0 + timedelta(seconds=30 * 5 + 22)
    out.append(
        (
            t0 + timedelta(seconds=30 * 12 + 400),  # > 5 min after it happened: flagged late
            [page.hb(late_at, kind="keepalive", active_ms=0, media=True, media_info=_media(asset, 500, 512))],
        )
    )
    return out


async def _play(world: dict[str, Any], t0: datetime, *, legacy_after: int | None = None) -> dict[str, Any]:
    """Ingest the plan for a fresh learner; ``legacy_after=n``: the summary is removed after the
    n-th batch, as for a page whose earlier batches were stored before summaries existed."""
    from app.modules.analytics import fs_raw
    from app.modules.analytics.schemas import BatchIn
    from app.modules.analytics.service import ingest_batch

    uid = uuid7()
    p = principal_for(uid)
    session: Any = FakeSession()
    statuses: list[list[str]] = []
    credited: list[float] = []
    page_id: str | None = None
    for n, (received, events) in enumerate(_plan(world, t0)):
        page_id = events[0]["page_instance_id"]
        b = BatchIn.model_validate(batch(events, received))
        res = await ingest_batch(session, p, b, now=received)
        statuses.append([r["status"] + ":" + r.get("code", "") for r in res.results])
        credited.append(round(res.credited_s, 6))
        if legacy_after is not None and n == legacy_after:
            await fs_raw.delete_user_docs(fs_raw.PAGE_HEARTBEATS, uid)
    assert page_id is not None
    hbs, _ = await fs_raw.rows_for_page(uid, uuid.UUID(page_id))
    rows = sorted(
        (
            h.effective_at,
            h.kind,
            h.active_ms,
            tuple(h.ingest_flags or ()),
            tuple((r.lower, r.upper) for r in (h.played_ranges or [])),
        )
        for h in hbs
    )
    return {"uid": uid, "page": page_id, "statuses": statuses, "credited": credited, "rows": rows}


def _same(a: dict[str, Any], b: dict[str, Any]) -> None:
    assert a["statuses"] == b["statuses"]
    assert a["credited"] == b["credited"]
    assert a["rows"] == b["rows"]


@pytest.fixture
def legacy_reader(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Switch ingest back to the previous reader (every batch of the page) and back again."""
    from app.modules.analytics import fs_raw

    original = fs_raw.page_heartbeats

    async def scan(user_id: uuid.UUID, page_id: uuid.UUID) -> list[Any]:
        return (await fs_raw.rows_for_page(user_id, page_id))[0]

    class Switch:
        def on(self) -> None:
            monkeypatch.setattr(fs_raw, "page_heartbeats", scan)

        def off(self) -> None:
            monkeypatch.setattr(fs_raw, "page_heartbeats", original)

    return Switch()


async def test_summary_reader_gives_identical_ingest_results(
    world: dict[str, Any], legacy_reader: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.analytics import fs_raw

    t0 = datetime.now(UTC) - timedelta(minutes=30)
    scans: list[str] = []
    real_rows_for_page = fs_raw.rows_for_page

    async def counting(user_id: uuid.UUID, page_id: uuid.UUID) -> Any:
        scans.append(str(page_id))
        return await real_rows_for_page(user_id, page_id)

    monkeypatch.setattr(fs_raw, "rows_for_page", counting)
    new = await _play(world, t0)
    # the batch scan ran for the page's first heartbeat batch only (no summary yet), never again
    # (the second scan is ``_play``'s own read of the stored rows)
    assert len(scans) == 2
    monkeypatch.setattr(fs_raw, "rows_for_page", real_rows_for_page)
    legacy_reader.on()
    old = await _play(world, t0)
    legacy_reader.off()
    _same(new, old)
    flat = [s for batch_statuses in new["statuses"] for s in batch_statuses]
    # the scenario exercises every branch the stored heartbeats decide
    assert "rejected:rate_capped" in flat and "duplicate:" in flat
    assert any("implausible_clamped" in r[3] for r in new["rows"])
    assert any("late" in r[3] for r in new["rows"])

    # the summary holds exactly the page's stored heartbeats
    hbs, _ = await fs_raw.rows_for_page(new["uid"], uuid.UUID(new["page"]))
    summary = await fs_raw.page_heartbeats(new["uid"], uuid.UUID(new["page"]))
    assert sorted((h.event_id, h.kind, h.effective_at) for h in summary) == sorted(
        (h.event_id, h.kind, h.effective_at) for h in hbs
    )

    # downstream results: video coverage and daily aggregates are the same for both learners
    from app.modules.analytics.jobs import run_daily_aggregation, run_interval_builder, run_video_coverage

    now = datetime.now(UTC)
    session: Any = FakeSession()
    await run_interval_builder(session, now=now)
    await run_video_coverage(session, now=now)
    day = ist_date(t0)
    await run_daily_aggregation(session, days=[day], now=now)
    cov = {
        d["user_id"]: (d["covered_s"], d["coverage_pct"], d.get("last_position_s"))
        for d in await fs_raw.all_docs("video_watch_coverage")
    }
    assert cov[str(new["uid"])] == cov[str(old["uid"])]
    daily = {}
    for uid in (new["uid"], old["uid"]):
        daily[uid] = sorted(
            (
                r.entity_kind,
                str(r.entity_id) if r.entity_kind != "_total" else "-",
                r.m2_active_s,
                r.m3_video_playback_s,
                r.m5_learning_s,
            )
            for r in await fs_raw.daily_rows(uid, day)
        )
    assert daily[new["uid"]] == daily[old["uid"]] and daily[new["uid"]]


async def test_page_stored_before_summaries_is_seeded_from_its_batches(
    world: dict[str, Any], legacy_reader: Any
) -> None:
    from app.modules.analytics import fs_raw

    t0 = datetime.now(UTC) - timedelta(minutes=30)
    seeded = await _play(world, t0, legacy_after=5)
    legacy_reader.on()
    old = await _play(world, t0)
    legacy_reader.off()
    _same(seeded, old)
    d = await fs_raw.store().get(fs_raw.PAGE_HEARTBEATS, fs_raw.page_hb_id(seeded["uid"], seeded["page"]))
    hbs, _ = await fs_raw.rows_for_page(seeded["uid"], uuid.UUID(seeded["page"]))
    assert d is not None and not d["overflow"] and len(d["hbs"]) == len(hbs)


async def test_oversized_summary_falls_back_to_the_batches(
    world: dict[str, Any], legacy_reader: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.modules.analytics import fs_raw

    monkeypatch.setattr(fs_raw, "PAGE_HB_CAP", 5)
    t0 = datetime.now(UTC) - timedelta(minutes=30)
    capped = await _play(world, t0)
    legacy_reader.on()
    old = await _play(world, t0)
    legacy_reader.off()
    _same(capped, old)
    d = await fs_raw.store().get(fs_raw.PAGE_HEARTBEATS, fs_raw.page_hb_id(capped["uid"], capped["page"]))
    assert d is not None and d["overflow"] is True and d["hbs"] == []


async def test_erasure_deletes_the_page_summaries(world: dict[str, Any]) -> None:
    from app.modules.analytics import fs_jobs, fs_raw

    played = await _play(world, datetime.now(UTC) - timedelta(minutes=30))
    assert await fs_raw.all_docs(fs_raw.PAGE_HEARTBEATS, user_id=played["uid"])
    await fs_jobs.erase_user(played["uid"])
    assert await fs_raw.all_docs(fs_raw.PAGE_HEARTBEATS, user_id=played["uid"]) == []
    assert await fs_raw.all_docs(fs_raw.BATCHES, user_id=played["uid"]) == []


async def test_coverage_groups_reads_only_the_lessons_asked_for(world: dict[str, Any]) -> None:
    """MED-05's coverage lookup: the ``lesson_id in`` query returns the same groups as filtering
    every coverage document of the learner, without reading the other lessons' documents."""
    from app.modules.analytics import fs_raw
    from app.modules.analytics.evidence import coverage_groups
    from app.modules.analytics.store_specs import VideoRow

    uid = uuid7()
    lessons = [uuid7() for _ in range(35)]  # more than one ``in`` chunk of 30
    now = datetime.now(UTC)
    st = fs_raw.store()
    for i, le in enumerate(lessons):
        for j in range(2 if i % 7 == 0 else 1):  # some lessons have two assets
            row = VideoRow(
                user_id=uid,
                lesson_asset_id=uuid7(),
                organization_id=None,
                lesson_id=le,
                covered_ranges=None,
                covered_s=10 * (i + 1) + j,
                coverage_pct=50,
                duration_s=600 if j == 0 else None,
                last_position_s=5,
                updated_at=now,
            ).doc()
            await st.create("video_watch_coverage", row, doc_id=f"{uid}:{i}:{j}")

    async def expected(want: list[uuid.UUID]) -> list[tuple[Any, Any, Any]]:
        g: dict[Any, list[Any]] = {}
        for d in await fs_raw.all_docs("video_watch_coverage", user_id=uid):
            r = VideoRow.of(d)
            if r.lesson_id in set(want):
                g.setdefault(r.lesson_asset_id, []).append(r)
        out = []
        for a, rs in g.items():
            cov = [x.covered_s for x in rs if x.covered_s is not None]
            dur = [x.duration_s for x in rs if x.duration_s is not None]
            out.append((a, sum(cov) if cov else None, max(dur) if dur else None))
        return sorted(out, key=lambda t: str(t[0]))

    for want in ([lessons[0]], lessons[:3], lessons, [uuid7()]):
        got = await coverage_groups(cast(Any, None), uid, want)
        assert sorted(got, key=lambda t: str(t[0])) == await expected(want)
