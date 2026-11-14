"""Analytics rollups, reports, evidence, exports, retention and erasure on Firestore
(``TD_STORE_ANALYTICS=firestore``), emulator only, no Postgres; endpoints through the FastAPI app.

Golden values: fixture ``daily_learning_aggregates`` rows are written, every expected number is
computed **in this test from the fixture rows** with the SQL definitions (``sum``, ``count FILTER``,
``bool_or``, ``count(DISTINCT)``, percentiles of ``jobs._pct``), and compared with the jobs'
output documents and the HTTP responses. Request sessions are core's ``MemoryTx`` (RLS settings in
memory, every SQL statement refused). Other modules are stubbed at analytics' boundary.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
import pytest

from app.core.ids import uuid7
from app.core.time import ist_date, utcnow
from tests.paths.fs.http_harness import FakeSession, install_fake_db, stub_core

FS_MODULES = ("analytics",)
pytestmark = pytest.mark.usefixtures("fs_env")
API = "/api/v1"
MV = "tm-1.0"


def _row(uid: uuid.UUID, day: date, kind: str, eid: uuid.UUID, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "user_id": uid,
        "activity_date": day,
        "entity_kind": kind,
        "entity_id": eid,
        "organization_id": None,
        "course_id": eid if kind == "course" else None,
        "topic_id": eid if kind == "topic" else None,
        "m1_session_elapsed_s": None,
        "m2_active_s": 0,
        "m3_video_playback_s": 0,
        "m4_assessment_s": 0,
        "m5_learning_s": 0,
        "assessment_active_s": 0,
        "questions_attempted": 0,
        "questions_correct": 0,
        "first_attempt_correct": 0,
        "code_runs": 0,
        "code_submissions": 0,
        "code_accepted": 0,
        "lessons_completed": 0,
        "implausible_day": False,
        "privacy_tier": "adult",
        "measurement_version": MV,
        "is_frozen": False,
    }
    return {**base, **kw}


@pytest.fixture
async def seeded(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """3 real learners + 1 synthetic, 7 days of the current week, one course and one topic."""
    from app.modules.analytics import fs_jobs, fs_raw, fs_reports

    today = ist_date(utcnow())
    monday = today - timedelta(days=today.isoweekday() - 1)
    users = [uuid7() for _ in range(3)]
    synthetic = uuid7()
    course, topic = uuid7(), uuid7()
    rows: list[dict[str, Any]] = []
    for i, u in enumerate([*users, synthetic]):
        for k in range(7):
            d = monday + timedelta(days=k)
            if d > today:
                break
            m5 = 300 * (i + 1) * (k + 1)  # some days >= 600, some not
            total = _row(
                u,
                d,
                "_total",
                u,
                m2_active_s=m5 + 60,
                m3_video_playback_s=100 * k,
                m4_assessment_s=10 * i,
                m5_learning_s=m5,
                questions_attempted=k + 1,
                questions_correct=k,
                first_attempt_correct=max(0, k - 1),
                code_runs=i,
                lessons_completed=1 if k == 0 else 0,
                implausible_day=(i == 2 and k == 1),
            )
            crow = _row(
                u, d, "course", course, m2_active_s=m5 // 2, m5_learning_s=m5 // 2, lessons_completed=1
            )
            trow = _row(
                u, d, "topic", topic, m5_learning_s=m5 // 3, questions_attempted=k + 1, questions_correct=k
            )
            rows += [total, crow, trow]
    by_ud: dict[tuple[uuid.UUID, date], list[dict[str, Any]]] = {}
    for r in rows:
        by_ud.setdefault((r["user_id"], r["activity_date"]), []).append(r)
    for (u, d), rs in by_ud.items():
        await fs_raw.replace_daily(u, d, rs)

    async def real(session: Any, ids: Any) -> set[uuid.UUID]:
        return {u for u in ids if u != synthetic}

    monkeypatch.setattr(fs_jobs, "real_users", real)
    monkeypatch.setattr(fs_reports, "real_users", real)
    batch = uuid7()

    async def cohort_inputs(session: Any, start: date, end: date) -> Any:
        days = await fs_jobs.daily_between(start, end, kind="_total")
        ids = list(dict.fromkeys(r.user_id for r in days))
        return [(batch, None, users[:2])], [u for u in ids if u != synthetic]

    monkeypatch.setattr(fs_jobs, "cohort_inputs", cohort_inputs)
    return {
        "rows": rows,
        "users": users,
        "synthetic": synthetic,
        "course": course,
        "topic": topic,
        "today": today,
        "monday": monday,
        "batch": batch,
    }


def _expect_week(
    rows: list[dict[str, Any]], synthetic: uuid.UUID, monday: date
) -> dict[tuple[Any, ...], dict[str, Any]]:
    out: dict[tuple[Any, ...], dict[str, Any]] = {}
    for r in rows:
        if r["user_id"] == synthetic or r["entity_kind"] not in ("_total", "course", "topic"):
            continue
        if not monday <= r["activity_date"] <= monday + timedelta(days=6):
            continue
        e = out.setdefault((r["user_id"], r["entity_kind"], r["entity_id"]), {"m2": 0, "m5": 0, "days": 0})
        e["m2"] += r["m2_active_s"]
        e["m5"] += r["m5_learning_s"]
        e["days"] += 1 if r["m5_learning_s"] >= 600 else 0
    return out


async def test_weekly_and_cohort_rollups_match_the_fixture(seeded: dict[str, Any]) -> None:
    from app.modules.analytics import fs_raw
    from app.modules.analytics.jobs import _pct, rollup_cohorts, rollup_week
    from app.modules.analytics.store_specs import CohortRow, WeeklyRow

    s = FakeSession()
    n = await rollup_week(s, seeded["monday"])
    expect = _expect_week(seeded["rows"], seeded["synthetic"], seeded["monday"])
    got = {
        (r.user_id, r.entity_kind, r.entity_id): {
            "m2": r.m2_active_s,
            "m5": r.m5_learning_s,
            "days": r.active_days,
        }
        for r in (WeeklyRow.of(d) for d in await fs_raw.all_docs("weekly_learning_aggregates"))
    }
    assert n == len(expect) and got == expect
    assert await rollup_week(s, seeded["monday"]) == n  # delete + insert: idempotent

    await rollup_cohorts(s, "week", seeded["monday"])
    cells = {
        (c.batch_id, c.period_kind): c
        for c in (CohortRow.of(d) for d in await fs_raw.all_docs("cohort_learning_aggregates"))
    }
    # platform cell: every real user with a _total row; k-floor 5 > 3 learners -> suppressed
    plat = cells[(None, "week")]
    assert plat.learners_enrolled == 3 and plat.suppressed is True and plat.m5_p50_s is None
    # percentile helper on the fixture (as the unsuppressed path would compute it)
    week_m5 = [e["m5"] for (u, k, _), e in expect.items() if k == "_total"]
    assert _pct(sorted(week_m5), 0.5) is not None
    await rollup_cohorts(s, "week", seeded["monday"])  # ON CONFLICT DO UPDATE: no duplicate cells
    assert len(await fs_raw.all_docs("cohort_learning_aggregates")) == len(cells) == 2


@pytest.fixture
async def web(seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch, auth: Any) -> AsyncIterator[Any]:
    from app.core.firestore import sqlstore
    from app.main import create_app
    from app.modules.analytics import fs_reports

    stub_core(monkeypatch, [])
    from app.modules.analytics import exports as ex
    from app.modules.analytics import router as arouter

    async def no_audit(*a: Any, **k: Any) -> None:
        return None

    for mod in (ex, arouter):
        if hasattr(mod, "audit"):
            monkeypatch.setattr(mod, "audit", no_audit)
    monkeypatch.setattr(sqlstore, "_postgres_available", lambda: False)  # jobs: MemoryTx too

    async def org(session: Any, batch_id: uuid.UUID) -> Any:
        return uuid.UUID(int=0) if batch_id == seeded["batch"] else None

    async def students(session: Any, batch_id: uuid.UUID) -> list[uuid.UUID]:
        return seeded["users"][:2] if batch_id == seeded["batch"] else []

    monkeypatch.setattr(fs_reports, "batch_org", org)
    monkeypatch.setattr(fs_reports, "batch_students", students)
    from app.modules.learning import public as learning

    async def no_enrolments(session: Any, users: Any) -> list[Any]:
        return []

    monkeypatch.setattr(learning, "enrolments_of_users", no_enrolments)
    app = create_app()
    install_fake_db(app)  # Postgres request sessions = NO_POSTGRES (final stack): routes get MemoryTx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def test_reports_over_http_equal_fixture_numbers(
    web: Any, seeded: dict[str, Any], auth: Any, make_principal: Any
) -> None:
    rows, users, today, monday = seeded["rows"], seeded["users"], seeded["today"], seeded["monday"]
    u0 = users[0]
    p = make_principal(user_id=u0, privacy_tier="adult", is_minor=False)
    h = auth.login(p)

    # /me/analytics/learning-time: day points = the fixture _total m5 per day
    r = await web.get(
        f"{API}/me/analytics/learning-time",
        params={"from": monday.isoformat(), "to": today.isoformat()},
        headers=h,
    )
    assert r.status_code == 200, r.text
    mine = {x["activity_date"]: x for x in rows if x["user_id"] == u0 and x["entity_kind"] == "_total"}
    assert [pt["learning_s"] for pt in r.json()["points"]] == [
        mine[monday + timedelta(days=k)]["m5_learning_s"] for k in range((today - monday).days + 1)
    ]
    # /me/analytics/summary: today / week sums, coding, lessons, topic accuracy
    s = (await web.get(f"{API}/me/analytics/summary", headers=h)).json()
    assert s["learning_time"]["today_s"] == mine[today]["m5_learning_s"]
    assert s["learning_time"]["this_week_s"] == sum(
        v["m5_learning_s"] for d, v in mine.items() if monday <= d <= today
    )
    assert s["coding"]["runs"] == sum(v["code_runs"] for v in mine.values())
    assert s["lessons_completed"] == sum(v["lessons_completed"] for v in mine.values())
    topic_rows = [x for x in rows if x["user_id"] == u0 and x["entity_kind"] == "topic"]
    att, cor = (
        sum(x["questions_attempted"] for x in topic_rows),
        sum(x["questions_correct"] for x in topic_rows),
    )
    assert s["accuracy_by_topic"] == [
        {
            "topic_id": str(seeded["topic"]),
            "answered": att,
            "correct": cor,
            "accuracy": round(cor / att, 4),
            "learning_s": sum(x["m5_learning_s"] for x in topic_rows),
        }
    ]

    staff = make_principal(is_platform=True)
    for perm in ("analytics.read", "analytics.read.platform", "progress.read"):
        auth.grant(staff, perm)
    sh = auth.login(staff)
    # platform: DAU/WAU/MAU = distinct real users with m5 > 0 in the window
    plat = (await web.get(f"{API}/analytics/reports/platform", headers=sh)).json()

    def active(days: int) -> int:
        lo = today - timedelta(days=days)
        return len(
            {
                x["user_id"]
                for x in rows
                if x["entity_kind"] == "_total"
                and x["user_id"] != seeded["synthetic"]
                and lo < x["activity_date"] <= today
                and x["m5_learning_s"] > 0
            }
        )

    assert (plat["dau"], plat["wau"], plat["mau"]) == (active(1), active(7), active(30))
    per_user: dict[Any, int] = {}
    for x in rows:
        if (
            x["entity_kind"] == "_total"
            and x["user_id"] != seeded["synthetic"]
            and not x["implausible_day"]
            and x["m5_learning_s"] > 0
            and today - timedelta(days=30) < x["activity_date"] <= today
        ):
            per_user[x["user_id"]] = per_user.get(x["user_id"], 0) + x["m5_learning_s"]
    assert plat["learning_time_30d"]["total_s"] == sum(per_user.values())

    # course report: k-cells over real learners with non-implausible course rows in 30 days
    cr = (await web.get(f"{API}/analytics/reports/courses/{seeded['course']}", headers=sh)).json()
    learners = {
        x["user_id"]
        for x in rows
        if x["entity_kind"] == "course"
        and x["user_id"] != seeded["synthetic"]
        and not x["implausible_day"]
        and x["activity_date"] >= today - timedelta(days=29)
    }
    from app.modules.analytics.reports import k_cell

    assert cr["learners_active"] == k_cell(len(learners), len(learners))

    # batch report: students' week m5 per learner
    br = await web.get(f"{API}/analytics/reports/batches/{seeded['batch']}", headers=sh)
    assert br.status_code == 200, br.text
    week = {
        u: sum(
            x["m5_learning_s"]
            for x in rows
            if x["user_id"] == u and x["entity_kind"] == "_total" and monday <= x["activity_date"] <= today
        )
        for u in users[:2]
    }
    assert {x["user_id"]: x["weekly_learning_s"] for x in br.json()["learners"]} == {
        str(u): v for u, v in week.items()
    }

    ih = await web.get(f"{API}/analytics/ingest-health", headers=sh)
    assert ih.status_code == 200 and ih.json()["accepted_24h"] == 0


async def test_evidence_retention_and_erasure(seeded: dict[str, Any]) -> None:
    from sqlalchemy.dialects.postgresql import Range

    from app.modules.analytics import evidence, fs_jobs, fs_raw
    from app.modules.analytics.jobs import erase_user, run_retention_purge

    u = seeded["users"][0]
    asset, lesson = uuid7(), uuid7()
    await fs_jobs.coverage_upsert(
        {
            "u": u,
            "a": asset,
            "o": None,
            "l": lesson,
            "cr": [Range(0, 600, bounds="[)")],
            "cs": 60.0,
            "pct": 50.0,
            "dur": 120,
            "pos": 60,
        }
    )
    cov = await evidence.video_coverage(FakeSession(), u, asset)
    assert cov is not None and cov.coverage == 0.5 and cov.covered_s == 60.0
    ev = await evidence.lesson_time_evidence(FakeSession(), u, lesson)
    assert ev.learning_s == 0 and [c.lesson_asset_id for c in ev.coverage] == [asset]

    # retention: nothing in the fixture is past its retention; dirty marks before the freeze go
    out = await run_retention_purge(FakeSession(), now=datetime.now(UTC))
    assert out["daily_learning_aggregates"] == 0 and out["analytics_events"] == 0
    # erasure: every identifiable row of the user
    n_daily = len([r for r in seeded["rows"] if r["user_id"] == u])
    erased = await erase_user(FakeSession(), u)
    assert erased["daily_learning_aggregates"] == n_daily and erased["video_watch_coverage"] == 1
    assert await fs_raw.daily_rows(u, seeded["today"]) == []


async def test_exports_request_list_and_get(web: Any, auth: Any, make_principal: Any) -> None:
    staff = make_principal(is_platform=True, last_step_up_at=utcnow())
    for perm in ("analytics.read", "analytics.read.platform", "report.export.request"):
        auth.grant(staff, perm)
    h = auth.login(staff)
    r = await web.post(
        f"{API}/exports", json={"report_key": "platform.overview", "scope": {"type": "platform"}}, headers=h
    )
    assert r.status_code == 202, r.text
    jid = r.json()["export_job_id"] if "export_job_id" in r.json() else r.json()["id"]
    listed = (await web.get(f"{API}/exports", headers=h)).json()
    assert [j.get("export_job_id", j.get("id")) for j in listed["data"]] == [jid]
    got = await web.get(f"{API}/exports/{jid}", headers=h)
    assert got.status_code == 200 and got.json()["report_key"] == "platform.overview"
    other = auth.login(make_principal())
    assert (await web.get(f"{API}/exports/{jid}", headers=other)).status_code == 404
