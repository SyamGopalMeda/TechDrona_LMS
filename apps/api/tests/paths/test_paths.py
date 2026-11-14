"""Guided learning paths: authoring + publish validation, allocation plan, learner player with
sequential locks and dwell time, strict-flow credit penalty, event-driven completion of
assignment/assessment steps, article sanitising and share-audience authorization, AI draft,
permission denials, single-company rules (no organization input, batch-members picker, D9 embed
allow-list) and the SEC-01 cross-batch regression."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text, update

from app.core.db import system_context
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.outbox import emit_event, relay_pending
from app.core.time import utcnow
from app.modules.paths import schedule
from app.modules.paths.articles import sanitize_markdown, table_of_contents
from app.modules.paths.models import PathStepProgress
from app.modules.paths.service import embeddable
from app.modules.rbac.service import reset_role_permission_cache
from tests.catalog.factory import idem, staff
from tests.identity.factory import Browser, UserHandle, add_member, company_org, make_batch, make_user

# --------------------------------------------------------------------------- pure units


def test_schedule_pace_and_finish_date() -> None:
    per_day = schedule.per_day_from_pace({"mode": "every_day", "hours_per_day": 2})
    assert sum(per_day.values()) == 14
    # 20 h at 2 h/day from Monday 2 Nov 2026 -> day 10 (Wed 11 Nov)
    fin, days = schedule.finish_date(date(2026, 11, 2), Decimal(20), per_day)
    assert fin == date(2026, 11, 11) and days == 10
    wk = schedule.per_day_from_pace({"mode": "weekdays", "hours_per_day": 4})
    assert wk["sat"] == 0 and wk["mon"] == 4
    # 8 h on weekdays from Friday: Fri 4 + Mon 4 -> Monday
    assert schedule.finish_date(date(2026, 11, 6), Decimal(8), wk)[0] == date(2026, 11, 9)
    mixed = schedule.per_day_from_pace({"mode": "weekdays_weekends", "hours_per_day": 1, "weekend_hours": 5})
    assert mixed["sun"] == 5 and mixed["tue"] == 1
    custom = schedule.per_day_from_pace({"mode": "custom", "per_day": {"sat": 3}})
    assert sum(custom.values()) == 3
    with pytest.raises(ProblemError):
        schedule.per_day_from_pace({"mode": "custom", "per_day": {}})
    assert schedule.due_dates(date(2026, 11, 2), [Decimal(1), Decimal(3), Decimal(5)], per_day) == [
        date(2026, 11, 2),
        date(2026, 11, 3),
        date(2026, 11, 4),
    ]


def test_markdown_sanitiser_and_toc() -> None:
    raw = (
        "# Title\n\n## Intro <b>bold</b>\n<script>alert(1)</script>Hello <img src=x onerror=alert(1)>\n"
        "[x](javascript:alert(1)) [ok](https://python.org) [rel](/app/path)\n\n"
        ":::warning-zone\nCareful\n:::\n\n```html\n<script>kept as code</script>\n```\n\n"
        "## Intro\n### Deep dive\n:::exercise Try it\nQ\n:::answer\nA\n:::\n<iframe src=https://evil>x</iframe>"
    )
    md = sanitize_markdown(raw)
    assert "alert(1)</script>" not in md.split("```")[0]
    assert "<b>" not in md and "<img" not in md and "<iframe" not in md and "onerror" not in md
    assert "](#)" in md and "](https://python.org)" in md and "](/app/path)" in md
    assert ":::note" in md and ":::warning-zone" not in md
    assert "<script>kept as code</script>" in md  # code fences are verbatim (rendered as text)
    assert ":::exercise Try it" in md and ":::answer" in md
    toc = table_of_contents(md)
    assert [t["id"] for t in toc] == ["intro-bold", "intro", "deep-dive"]
    assert toc[2]["level"] == 3
    # unclosed fence is closed
    assert sanitize_markdown("```py\nx = 1").endswith("```")


def test_embed_allow_list_d9() -> None:
    ok = [
        "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
        "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ?start=30",
        "https://player.vimeo.com/video/76979871",
        "https://docs.google.com/document/d/1AbC_d-9/preview",
        "https://docs.google.com/presentation/d/e/2PACX-1x/embed?start=false",
        "https://docs.google.com/spreadsheets/d/1AbC/pubhtml",
        "https://drive.google.com/file/d/1AbC_d-9/preview",
    ]
    bad = [
        None,
        "",
        "https://www.youtube.com/watch?v=x",
        "https://www.youtube.com/embed/x",
        "https://youtube-nocookie.com.evil.example/embed/x",
        "http://www.youtube-nocookie.com/embed/x",
        "https://user@www.youtube-nocookie.com/embed/x",
        "https://www.youtube-nocookie.com:8443/embed/x",
        "https://www.youtube-nocookie.com/embed/",
        "https://player.vimeo.com/video/abc",
        "https://vimeo.com/76979871",
        "https://docs.google.com/document/d/1AbC/edit",
        "https://docs.google.com/",
        "https://drive.google.com/file/d/1AbC/view",
        "https://drive.google.com/uc?id=1AbC",
        "https://example.org/handbook",
    ]
    assert all(embeddable(u) for u in ok), [u for u in ok if not embeddable(u)]
    assert not any(embeddable(u) for u in bad), [u for u in bad if embeddable(u)]


# --------------------------------------------------------------------------- world


@dataclass
class World:
    org: uuid.UUID
    batch: uuid.UUID
    trainer: UserHandle
    tb: Browser
    s1: UserHandle
    b1: Browser
    s2: UserHandle
    b2: Browser


async def _world(db: Any, browser: Browser) -> World:
    reset_role_permission_cache()
    org = company_org()
    creator = await make_user(db)
    batch = await make_batch(db, org, creator.id)
    tb = browser
    trainer = await staff(db, tb, "trainer", "batch", batch)
    await add_member(db, org, trainer.id, member_type="staff", batch_id=batch)
    b1 = browser.fork()
    s1 = await make_user(db, full_name="Asha Learner")
    await add_member(db, org, s1.id, batch_id=batch)
    assert (await b1.login(s1.email)).status_code == 200
    b2 = browser.fork()
    s2 = await make_user(db, full_name="Ravi Other")
    await add_member(db, org, s2.id)  # company member, not in the batch
    assert (await b2.login(s2.email)).status_code == 200
    return World(org, batch, trainer, tb, s1, b1, s2, b2)


async def _assignment(db: Any, org: uuid.UUID, by: uuid.UUID, batch: uuid.UUID) -> uuid.UUID:
    await system_context(db, "test.paths")
    aid = uuid7()
    await db.execute(
        text(
            "INSERT INTO assignments (id, organization_id, batch_id, title, instructions_md, submission_type, "
            "max_score, created_by) VALUES (:id, :o, :b, 'CLI project', 'Build it', 'text', 32, :u)"
        ),
        {"id": aid, "o": org, "b": batch, "u": by},
    )
    return aid


async def _test(db: Any, org: uuid.UUID, by: uuid.UUID) -> uuid.UUID:
    await system_context(db, "test.paths")
    tid = uuid7()
    await db.execute(
        text(
            "INSERT INTO tests (id, organization_id, test_kind, title, review_policy, integrity_settings, "
            "created_by, status, pass_percentage) "
            "VALUES (:id, :o, 'mock', 'Python check', '{}'::jsonb, '{}'::jsonb, :u, 'published', 60)"
        ),
        {"id": tid, "o": org, "u": by},
    )
    return tid


async def _scored_attempt(
    db: Any, test_id: uuid.UUID, user: uuid.UUID, org: uuid.UUID, passed: bool
) -> uuid.UUID:
    from app.modules.assessments.models import AttemptResult

    await system_context(db, "test.paths")
    aid = uuid7()
    now = utcnow()
    await db.execute(
        text(
            "INSERT INTO test_attempts (id, test_id, test_version, user_id, organization_id, attempt_no, status, "
            "selection_seed, layout, started_at, submitted_at, submit_reason, idempotency_key) "
            "VALUES (:id, :t, 1, :u, :o, (SELECT count(*) + 1 FROM test_attempts WHERE test_id = :t AND "
            "user_id = :u), 'graded', :seed, '{}'::jsonb, :s, :s, 'user', :k)"
        ),
        {"id": aid, "t": test_id, "u": user, "o": org, "seed": os.urandom(16), "s": now, "k": aid.hex},
    )
    db.add(
        AttemptResult(
            attempt_id=aid,
            user_id=user,
            organization_id=org,
            test_id=test_id,
            score=Decimal(8 if passed else 2),
            max_score=Decimal(10),
            percentage=Decimal(80 if passed else 20),
            correct_count=8 if passed else 2,
            incorrect_count=2 if passed else 8,
            unanswered_count=0,
            time_taken_seconds=600,
            section_scores=[],
            topic_scores=[],
            passed=passed,
        )
    )
    await db.flush()
    await emit_event(
        db,
        "attempt.scored",
        {"attempt_id": str(aid), "test_id": str(test_id), "user_id": str(user)},
        aggregate_type="test_attempt",
        aggregate_id=aid,
        organization_id=org,
    )
    return aid


async def _backdate(db: Any, user: uuid.UUID, seconds: int = 400) -> None:
    await system_context(db, "test.paths")
    await db.execute(
        update(PathStepProgress)
        .where(PathStepProgress.user_id == user)
        .values(opened_at=utcnow() - timedelta(seconds=seconds))
    )
    await db.flush()


def _steps(player: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {s["title"]: s for s in player["steps"]}


async def _build_path(db: Any, w: World) -> tuple[str, dict[str, Any], uuid.UUID, uuid.UUID]:
    tb = w.tb
    # single company: an organization can no longer be chosen (extra fields are rejected)
    r = await tb.post("/paths", {"organization_id": str(w.org), "title": "Core Python"})
    assert r.status_code in (400, 422), r.text
    r = await tb.post("/paths", {"title": "Core Python"}, headers=idem())
    assert r.status_code == 201, r.text
    assert r.json()["organization_id"] == str(company_org())
    pid = r.json()["id"]
    r = await tb.post(
        "/path-articles",
        {"title": "Variables", "body_md": "## Names\n<script>x</script>Text"},
    )
    assert r.status_code == 201, r.text
    art = r.json()
    assert "<script>" not in art["body_md"] and art["toc"] == [{"id": "names", "text": "Names", "level": 2}]
    asg = await _assignment(db, w.org, w.trainer.id, w.batch)
    tst = await _test(db, w.org, w.trainer.id)
    steps = [
        {
            "step_type": "video",
            "title": "Install Python",
            "url": "https://www.youtube.com/watch?v=x",
            "est_hours": 1,
            "credits": 5,
        },
        {
            "step_type": "article",
            "title": "Variables",
            "article_id": art["id"],
            "est_hours": 1.5,
            "credits": 10,
        },
        {
            "step_type": "super_step",
            "title": "Control flow",
            "children": [
                {
                    "step_type": "reading",
                    "title": "Docs: if",
                    "url": "https://docs.python.org/3/",
                    "est_hours": 1,
                    "credits": 10,
                },
                {
                    "step_type": "reading",
                    "title": "Docs: loops",
                    "url": "https://docs.python.org/3/",
                    "est_hours": 1,
                    "credits": 10,
                },
            ],
        },
        {"step_type": "assignment", "title": "Task manager", "est_hours": 5, "credits": 25},
        {
            "step_type": "assessment",
            "title": "Knowledge check",
            "test_id": str(tst),
            "est_hours": 3,
            "credits": 20,
        },
    ]
    r = await tb.request("PUT", f"/paths/{pid}/steps", json={"steps": steps})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["step_count"] == 6 and d["total_credits"] == 80 and d["total_hours"] == 12.5
    # D9: a youtube.com watch URL is kept as a plain link; only allow-listed embeds are embeddable
    assert d["steps"][0]["url"] == "https://www.youtube.com/watch?v=x"
    assert d["steps"][0]["embeddable"] is False
    assert d["steps"][2]["credits"] == 20 and len(d["steps"][2]["children"]) == 2
    # the assignment step has no assignment attached -> publish refused with field errors
    r = await tb.post(f"/paths/{pid}/publish")
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "link_required", r.text
    # bad links are rejected on save; http is refused
    bad = [dict(steps[0], url="http://insecure.example")]
    assert (await tb.request("PUT", f"/paths/{pid}/steps", json={"steps": bad})).status_code == 400
    bad = [{"step_type": "assignment", "title": "x", "assignment_id": str(uuid.uuid4())}]
    assert (await tb.request("PUT", f"/paths/{pid}/steps", json={"steps": bad})).status_code == 400
    nested = [
        {"step_type": "super_step", "title": "s", "children": [{"step_type": "super_step", "title": "t"}]}
    ]
    assert (await tb.request("PUT", f"/paths/{pid}/steps", json={"steps": nested})).status_code == 400
    steps[3]["assignment_id"] = str(asg)
    # keep the existing step keys (drag reorder keeps progress keys stable)
    keyed = d["steps"]
    for s_in, s_out in zip(steps, keyed, strict=True):
        s_in["step_key"] = s_out["step_key"]
    r = await tb.request("PUT", f"/paths/{pid}/steps", json={"steps": steps})
    assert r.status_code == 200, r.text
    r = await tb.post(f"/paths/{pid}/publish")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "published" and r.json()["version_no"] == 1
    assert r.json()["has_unpublished_changes"] is False
    return pid, art, asg, tst


# --------------------------------------------------------------------------- flows


@pytest.mark.usefixtures("catalog_backend")
async def test_author_allocate_sequential_player_and_dwell(browser, db) -> None:
    w = await _world(db, browser)
    pid, art, _, _ = await _build_path(db, w)
    tb = w.tb
    pace = {"mode": "every_day", "hours_per_day": 2}
    start = date(2026, 11, 2)
    r = await tb.post(f"/paths/{pid}/allocation-preview", {"start_date": start.isoformat(), "pace": pace})
    assert r.status_code == 200, r.text
    assert r.json()["weekly_hours"] == 14 and r.json()["finish_date"] == "2026-11-08"  # 12.5 h at 2 h/day
    body = {
        "target_type": "batch",
        "batch_id": str(w.batch),
        "flow": "lenient",
        "sequential": True,
        "start_date": start.isoformat(),
        "pace": pace,
    }
    r = await tb.post(f"/paths/{pid}/allocations", body, headers=idem())
    assert r.status_code == 201, r.text
    alloc = r.json()
    assert alloc["finish_date"] == "2026-11-08" and alloc["learner_count"] == 1 and alloc["version_no"] == 1

    # learner in the batch sees it; a member outside the batch does not
    mine = (await w.b1.get("/me/paths")).json()["data"]
    assert len(mine) == 1 and mine[0]["step_count"] == 6 and mine[0]["pct"] == 0
    assert (await w.b2.get("/me/paths")).json()["data"] == []
    assert (await w.b2.get(f"/me/paths/{alloc['id']}")).status_code == 404

    aid = alloc["id"]
    pl = (await w.b1.get(f"/me/paths/{aid}")).json()
    st = _steps(pl)
    assert st["Install Python"]["state"] == "available" and st["Variables"]["state"] == "locked"
    assert st["Install Python"]["embeddable"] is False
    assert st["Control flow"]["number"] == "3" and st["Docs: if"]["number"] == "3.1"
    k1, k2 = st["Install Python"]["step_key"], st["Variables"]["step_key"]
    # locked step cannot be opened or completed (server-side)
    r = await w.b1.post(f"/me/paths/{aid}/steps/{k2}/open")
    assert r.status_code == 409 and r.json()["code"] == "step_locked"
    # complete without opening -> 409; then too early (dwell time)
    assert (await w.b1.post(f"/me/paths/{aid}/steps/{k1}/complete")).status_code == 409
    r = await w.b1.post(f"/me/paths/{aid}/steps/{k1}/open")
    assert r.status_code == 200 and r.json()["state"] == "in_progress"
    r = await w.b1.post(f"/me/paths/{aid}/steps/{k1}/complete")
    assert r.status_code == 409 and r.json()["code"] == "too_early" and r.json()["retry_after_seconds"] > 0
    await _backdate(db, w.s1.id)
    r = await w.b1.post(f"/me/paths/{aid}/steps/{k1}/complete")
    assert r.status_code == 200, r.text
    assert r.json()["step"]["state"] == "completed" and r.json()["credits_earned"] == 5
    assert r.json()["pct"] == round(100 / 6, 1)
    # idempotent re-complete
    assert (await w.b1.post(f"/me/paths/{aid}/steps/{k1}/complete")).json()["credits_earned"] == 5
    st = _steps((await w.b1.get(f"/me/paths/{aid}")).json())
    assert st["Variables"]["state"] == "available" and st["Docs: if"]["state"] == "locked"
    # the learner on the path may read the (unpublished) article; the other member may not
    assert (await w.b1.get(f"/read/{art['id']}")).status_code == 200
    assert (await w.b2.get(f"/read/{art['id']}")).status_code == 404

    # trainer progress dashboard
    r = await tb.get(f"/path-allocations/{aid}/progress")
    assert r.status_code == 200, r.text
    row = r.json()["learners"][0]
    assert row["full_name"] == "Asha Learner" and row["completed_steps"] == 1 and row["credits_earned"] == 5
    assert row["email"] is None  # F9: learner emails are Admin-only
    # learners cannot see staff endpoints
    assert (await w.b1.get(f"/path-allocations/{aid}/progress")).status_code in (403, 404)
    assert (await w.b1.post("/paths", {"title": "x"})).status_code == 403
    assert (await w.b1.get(f"/paths/{pid}")).status_code == 403
    # revoke hides it from the learner
    assert (await tb.delete(f"/path-allocations/{aid}")).status_code == 204
    assert (await w.b1.get("/me/paths")).json()["data"] == []


@pytest.mark.usefixtures("catalog_backend")
async def test_strict_flow_late_penalty_and_event_driven_completion(browser, db) -> None:
    w = await _world(db, browser)
    pid, _, asg, tst = await _build_path(db, w)
    start = (utcnow() - timedelta(days=60)).date()  # every due date has passed
    body = {
        "target_type": "users",
        "user_ids": [str(w.s1.id)],
        "flow": "strict",
        "sequential": False,
        "start_date": start.isoformat(),
        "pace": {"mode": "every_day", "hours_per_day": 1},
    }
    r = await w.tb.post(f"/paths/{pid}/allocations", body)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    st = _steps((await w.b1.get(f"/me/paths/{aid}")).json())
    assert st["Variables"]["state"] == "available"  # not sequential: any order
    assert st["Install Python"]["due_date"] is not None
    k = st["Variables"]["step_key"]
    await w.b1.post(f"/me/paths/{aid}/steps/{k}/open")
    await _backdate(db, w.s1.id)
    r = await w.b1.post(f"/me/paths/{aid}/steps/{k}/complete")
    assert r.status_code == 200 and r.json()["step"]["credits_awarded"] == 5  # 10 credits, late -> half

    # assignment / assessment steps never complete from the learner
    ka = st["Task manager"]["step_key"]
    r = await w.b1.post(f"/me/paths/{aid}/steps/{ka}/complete")
    assert r.status_code == 409 and r.json()["code"] == "completion_by_evaluation"

    # graded but not released -> still open
    await system_context(db, "test.paths")
    sid = uuid7()
    await db.execute(
        text(
            "INSERT INTO assignment_submissions (id, assignment_id, user_id, organization_id, body_text, status, "
            "submitted_at, score, graded_at) VALUES (:id, :a, :u, :o, 'done', 'graded', now(), 30, now())"
        ),
        {"id": sid, "a": asg, "u": w.s1.id, "o": w.org},
    )
    await emit_event(
        db,
        "learning.submission_graded",
        {"submission_id": str(sid), "assignment_id": str(asg), "user_id": str(w.s1.id), "action": "grade"},
        aggregate_type="assignment",
        aggregate_id=asg,
        organization_id=w.org,
    )
    await relay_pending(db)
    assert _steps((await w.b1.get(f"/me/paths/{aid}")).json())["Task manager"]["state"] != "completed"
    # release -> completes from the event (state re-read from the database)
    await system_context(db, "test.paths")
    await db.execute(text("UPDATE assignments SET grades_released_at = now() WHERE id = :a"), {"a": asg})
    await emit_event(
        db,
        "learning.grades_released",
        {"assignment_id": str(asg)},
        aggregate_type="assignment",
        aggregate_id=asg,
        organization_id=w.org,
    )
    await relay_pending(db)
    st = _steps((await w.b1.get(f"/me/paths/{aid}")).json())
    assert st["Task manager"]["state"] == "completed" and st["Task manager"]["credits_awarded"] == 12

    # a failed attempt does not complete the assessment step; a pass does
    await _scored_attempt(db, tst, w.s1.id, w.org, passed=False)
    await relay_pending(db)
    assert _steps((await w.b1.get(f"/me/paths/{aid}")).json())["Knowledge check"]["state"] != "completed"
    await _scored_attempt(db, tst, w.s1.id, w.org, passed=True)
    await relay_pending(db)
    pl = (await w.b1.get(f"/me/paths/{aid}")).json()
    assert _steps(pl)["Knowledge check"]["state"] == "completed"
    assert pl["credits_earned"] == 5 + 12 + 10
    # another learner's pass never completes this learner's steps (and s2 has no allocation)
    r = await w.tb.get(f"/path-allocations/{aid}/progress")
    assert r.json()["learners"][0]["behind"] is True


@pytest.mark.usefixtures("catalog_backend")
async def test_article_share_audiences(browser, db) -> None:
    w = await _world(db, browser)
    tb = w.tb
    r = await tb.post("/path-articles", {"title": "Tips", "body_md": ":::tip\nHi\n:::"})
    art = r.json()["id"]
    # draft: only authors
    assert (await tb.get(f"/read/{art}")).json()["can_edit"] is True
    assert (await w.b1.get(f"/read/{art}")).status_code == 404
    # chosen people
    r = await tb.post(f"/path-articles/{art}/publish", {"audience": "people", "user_ids": [str(w.s2.id)]})
    assert r.status_code == 200 and r.json()["status"] == "published", r.text
    assert (await w.b2.get(f"/read/{art}")).status_code == 200
    assert (await w.b1.get(f"/read/{art}")).status_code == 404
    # chosen batches
    r = await tb.post(f"/path-articles/{art}/publish", {"audience": "batches", "batch_ids": [str(w.batch)]})
    assert r.status_code == 200
    assert (await w.b1.get(f"/read/{art}")).status_code == 200
    assert (await w.b2.get(f"/read/{art}")).status_code == 404
    # the "whole organization" audience is gone (single company)
    r = await tb.post(f"/path-articles/{art}/publish", {"audience": "org"})
    assert r.status_code in (400, 422), r.text
    assert (await w.b2.get(f"/read/{art}")).status_code == 404
    # a public learner (no batch, no company membership) never reads it
    outsider = await make_user(db)
    ob = browser.fork()
    assert (await ob.login(outsider.email)).status_code == 200
    assert (await ob.get(f"/read/{art}")).status_code == 404
    # ... and cannot be chosen as a reader
    r = await tb.post(f"/path-articles/{art}/publish", {"audience": "people", "user_ids": [str(outsider.id)]})
    assert r.status_code == 400
    # unpublish
    assert (await tb.post(f"/path-articles/{art}/unpublish")).json()["status"] == "draft"
    assert (await w.b2.get(f"/read/{art}")).status_code == 404
    # learners cannot author articles
    assert (await w.b1.patch(f"/path-articles/{art}", {"title": "x"})).status_code == 403


@pytest.mark.usefixtures("catalog_backend")
async def test_sec01_other_batch_trainer_cannot_touch_batch_allocation(browser, db) -> None:
    """SEC-01 regression (was tests/_review_scratch/test_sec_paths_probe.py): a trainer holding
    path.allocate only on batch Y cannot read, revoke or re-target batch X's allocation or
    learners. Path authoring stays company-wide for batch trainers (intended)."""
    w = await _world(db, browser)
    pid, _art, _, _ = await _build_path(db, w)
    pace = {"mode": "every_day", "hours_per_day": 2}
    r = await w.tb.post(
        f"/paths/{pid}/allocations",
        {"target_type": "batch", "batch_id": str(w.batch), "start_date": "2026-11-02", "pace": pace},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    alloc = r.json()["id"]

    creator = await make_user(db)
    batch_y = await make_batch(db, w.org, creator.id)
    tyb = browser.fork()
    ty = await staff(db, tyb, "trainer", "batch", batch_y)
    await add_member(db, w.org, ty.id, member_type="staff", batch_id=batch_y)
    sy = await make_user(db, full_name="Yamuna Learner")
    await add_member(db, w.org, sy.id, batch_id=batch_y)

    # allocate to batch X: denied
    body = {"target_type": "batch", "batch_id": str(w.batch), "pace": pace}
    assert (await tyb.post(f"/paths/{pid}/allocations", body, headers=idem())).status_code == 403
    # batch X allocation progress (names + emails) and revoke: denied, no company fallback
    r = await tyb.get(f"/path-allocations/{alloc}/progress")
    assert r.status_code in (403, 404), r.text
    assert "Asha Learner" not in r.text
    assert (await tyb.request("DELETE", f"/path-allocations/{alloc}")).status_code in (403, 404)
    assert (await w.tb.get(f"/path-allocations/{alloc}/progress")).status_code == 200  # still active
    # individual allocation of batch X's learner, or of a company member outside any of
    # trainer Y's batches: denied
    for ids in ([w.s1.id], [w.s1.id, w.s2.id], [w.s2.id]):
        body = {"target_type": "users", "user_ids": [str(u) for u in ids], "pace": pace}
        assert (await tyb.post(f"/paths/{pid}/allocations", body, headers=idem())).status_code == 403
    # the org-wide member list is gone; the batch picker is limited to own batches
    r = await tyb.get("/paths/org-members", params={"organization_id": str(w.org)})
    assert r.status_code in (400, 404, 422) and "Asha" not in r.text, r.text
    assert (await tyb.get("/paths/batch-members", params={"batch_id": str(w.batch)})).status_code == 403
    r = await tyb.get("/paths/batch-members", params={"batch_id": str(batch_y)})
    assert r.status_code == 200 and [m["full_name"] for m in r.json()["data"]] == ["Yamuna Learner"]
    assert [m["email"] for m in r.json()["data"]] == [None]  # names only for trainers (F9)
    assert (await tyb.get("/paths/batch-members", params={"batch_id": str(uuid.uuid4())})).status_code == 404
    # trainer Y may allocate to their own learner individually; trainer X cannot manage that one
    body = {"target_type": "users", "user_ids": [str(sy.id)], "pace": pace}
    r = await tyb.post(f"/paths/{pid}/allocations", body, headers=idem())
    assert r.status_code == 201, r.text
    own = r.json()["id"]
    assert (await tyb.get(f"/path-allocations/{own}/progress")).status_code == 200
    assert (await w.tb.get(f"/path-allocations/{own}/progress")).status_code == 403
    assert (await w.tb.request("DELETE", f"/path-allocations/{own}")).status_code == 403
    # context lists only the caller's batches; no organizations
    ctx = (await w.tb.get("/paths/context")).json()
    assert [b["id"] for b in ctx["batches"]] == [str(w.batch)]
    assert ctx["can_author"] is True and ctx["can_allocate_any_learner"] is False
    assert "organizations" not in ctx
    # the organization_id query parameter is gone (ignored, never a filter)
    assert (await tyb.get("/paths", params={"organization_id": str(uuid.uuid4())})).status_code == 200
    # authoring is company-wide for batch trainers (documented): trainer Y may edit the path
    assert (await tyb.request("PATCH", f"/paths/{pid}", json={"title": "Core Python 2"})).status_code == 200
    # revoking with the right batch grant still works
    assert (await w.tb.request("DELETE", f"/path-allocations/{alloc}")).status_code == 204


@pytest.mark.usefixtures("catalog_backend")
async def test_removed_batch_member_loses_path_access(browser, db) -> None:
    """SEC-03 analogue: only *active* batch membership counts (allocations, pickers)."""
    w = await _world(db, browser)
    pid, _art, _, _ = await _build_path(db, w)
    pace = {"mode": "every_day", "hours_per_day": 2}
    r = await w.tb.post(
        f"/paths/{pid}/allocations", {"target_type": "batch", "batch_id": str(w.batch), "pace": pace}
    )
    assert r.status_code == 201, r.text
    assert len((await w.b1.get("/me/paths")).json()["data"]) == 1
    await system_context(db, "test.factory")
    await db.execute(
        text("UPDATE batch_members SET status='removed', removed_at=now() WHERE user_id=:u AND batch_id=:b"),
        {"u": w.s1.id, "b": w.batch},
    )
    await db.flush()
    assert (await w.b1.get("/me/paths")).json()["data"] == []
    members = (await w.tb.get("/paths/batch-members", params={"batch_id": str(w.batch)})).json()["data"]
    assert members == []
    body = {"target_type": "users", "user_ids": [str(w.s1.id)], "pace": pace}
    assert (await w.tb.post(f"/paths/{pid}/allocations", body)).status_code == 403


@pytest.mark.usefixtures("catalog_backend")
async def test_ai_generate_draft_and_errors(browser, db, monkeypatch) -> None:
    from app.modules.ai import service as ai

    w = await _world(db, browser)
    seen: dict[str, Any] = {}

    async def fake(session, *, user_id, spec, org_id=None):
        seen["spec"] = spec
        return {
            "title": "Core Python Fundamentals",
            "description": "A 20-hour path",
            "steps": [
                {
                    "title": "Install",
                    "step_type": "video",
                    "est_hours": 1,
                    "credits": 5,
                    "url": "https://youtube.com/watch?v=a",
                },
                {
                    "title": "Variables",
                    "step_type": "article",
                    "est_hours": 1.5,
                    "credits": 10,
                    "description_md": "## Names\n<script>bad</script>",
                },
                {"title": "Project", "step_type": "assignment", "est_hours": 5, "credits": 25},
                {
                    "title": "Weird",
                    "step_type": "hologram",
                    "est_hours": 1,
                    "credits": 1,
                    "url": "javascript:x",
                },
            ],
        }

    monkeypatch.setattr(ai, "generate_path", fake)
    body = {
        "topic": "Core Python",
        "style": "mixed",
        "level": "beginner",
        "target_hours": 40,
        "approx_steps": 8,
        "guidelines": "Valid content only",
    }
    r = await w.tb.post("/paths/ai-generate", body)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["source"] == "ai" and d["status"] == "draft" and d["step_count"] == 4
    assert seen["spec"].target_hours == 40 and seen["spec"].style == "mixed"
    types = [s["step_type"] for s in d["steps"]]
    assert types == ["video", "article", "assignment", "reading"] and d["steps"][3]["url"] is None
    art = d["steps"][1]["article_id"]
    a = (await w.tb.get(f"/path-articles/{art}")).json()
    assert a["status"] == "draft" and "<script>" not in a["body_md"]
    # never auto-published: allocation refuses a draft
    body2 = {
        "target_type": "batch",
        "batch_id": str(w.batch),
        "pace": {"mode": "every_day", "hours_per_day": 2},
    }
    assert (await w.tb.post(f"/paths/{d['id']}/allocations", body2)).status_code == 409

    async def down(session, **kw):
        raise ai.AIUnavailable("provider down")

    monkeypatch.setattr(ai, "generate_path", down)
    r = await w.tb.post("/paths/ai-generate", body)
    assert r.status_code == 503 and r.json()["code"] == "ai_unavailable"

    async def off(session, **kw):
        raise ai.AIDisabled("off")

    monkeypatch.setattr(ai, "generate_path", off)
    assert (await w.tb.post("/paths/ai-generate", body)).status_code == 403
    # learners cannot generate
    assert (await w.b1.post("/paths/ai-generate", body)).status_code == 403


@pytest.mark.usefixtures("catalog_backend")
async def test_admin_creates_publishes_allocates_company_wide(browser, db) -> None:
    """Admin (platform grant) replaces the college coordinator: every batch, any batch learner."""
    reset_role_permission_cache()
    org = company_org()
    creator = await make_user(db)
    batch = await make_batch(db, org, creator.id)
    cb = browser
    await staff(db, cb, "super_admin", "platform")
    learner = await make_user(db, full_name="Meena Learner")
    await add_member(db, org, learner.id, batch_id=batch)
    lb = browser.fork()
    assert (await lb.login(learner.email)).status_code == 200

    ctx = (await cb.get("/paths/context")).json()
    assert str(batch) in [b["id"] for b in ctx["batches"]]
    assert ctx["can_author"] is True and ctx["can_allocate_any_learner"] is True
    r = await cb.post("/paths", {"title": "Onboarding"}, headers=idem())
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    steps = [
        {
            "step_type": "reading",
            "title": "Handbook",
            "url": "https://example.org/handbook",
            "est_hours": 2,
            "credits": 10,
        },
        {
            "step_type": "video",
            "title": "Welcome",
            "url": "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ",
            "est_hours": 1,
            "credits": 5,
        },
    ]
    r = await cb.request("PUT", f"/paths/{pid}/steps", json={"steps": steps})
    assert r.status_code == 200, r.text
    assert [s["embeddable"] for s in r.json()["steps"]] == [False, True]
    r = await cb.post(f"/paths/{pid}/publish")
    assert r.status_code == 200 and r.json()["version_no"] == 1, r.text
    pace = {"mode": "weekdays", "hours_per_day": 1}
    r = await cb.post(
        f"/paths/{pid}/allocations",
        {"target_type": "batch", "batch_id": str(batch), "flow": "lenient", "pace": pace},
    )
    assert r.status_code == 201 and r.json()["learner_count"] == 1, r.text
    r = await cb.post(
        f"/paths/{pid}/allocations",
        {
            "target_type": "users",
            "user_ids": [str(learner.id)],
            "flow": "strict",
            "sequential": True,
            "pace": pace,
        },
    )
    assert r.status_code == 201, r.text
    members = (await cb.get("/paths/batch-members", params={"batch_id": str(batch)})).json()["data"]
    assert [m["full_name"] for m in members] == ["Meena Learner"]
    progress = (await cb.get(f"/path-allocations/{r.json()['id']}/progress")).json()
    assert progress["learners"][0]["total_steps"] == 2
    # Admin still sees learner emails (F9)
    assert members[0]["email"] and progress["learners"][0]["email"]
    mine = (await lb.get("/me/paths")).json()["data"]
    assert len(mine) == 2
    pl = (await lb.get(f"/me/paths/{mine[0]['allocation_id']}")).json()
    assert {s["title"]: s["embeddable"] for s in pl["steps"]} == {"Handbook": False, "Welcome": True}
    # a public learner who is not a company member cannot be allocated individually
    public = await make_user(db)
    body = {"target_type": "users", "user_ids": [str(public.id)], "pace": pace}
    r = await cb.post(f"/paths/{pid}/allocations", body)
    assert r.status_code == 400 and r.json()["errors"][0]["code"] == "not_member", r.text
