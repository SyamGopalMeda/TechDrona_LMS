"""WS4 regression tests (single company): SEC-02 (cross-batch grading) + evaluator_ids,
SEC-03 (removed batch members), SEC-09 (archived assignments), SEC-11 (legacy grade of
structured work), SEC-12 (self-extension), the evaluator role's limits, and the removed
``organization_id`` inputs. SEC-02/03 were probes in ``tests/_review_scratch``."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text

from app.core.db import system_context
from app.core.time import utcnow
from tests.learning.test_structured_assignments import _DenyAll, rbac, world  # noqa: F401
from tests.placement.world import World, idem

API = "/api/v1"

ESSAY = {
    "sections": [
        {
            "title": "S",
            "items": [{"source": "inline", "item_type": "essay", "prompt_md": "Explain.", "marks": 10}],
        }
    ]
}


async def _make(client: Any, who: Any, batch: uuid.UUID | None, structure: dict[str, Any]) -> tuple[str, str]:
    body: dict[str, Any] = {"title": "T", "submission_type": "structured", "max_score": 10}
    if batch is not None:
        body["batch_id"] = str(batch)
    r = await client.post(f"{API}/assignments", json=body, headers=who.headers)
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    r = await client.put(f"{API}/assignments/{aid}/structure", json=structure, headers=who.headers)
    assert r.status_code == 200 and r.json()["marks"]["ok"], r.text
    return aid, r.json()["sections"][0]["id"]


async def _alloc(
    client: Any, who: Any, aid: str, batch: uuid.UUID, sec: str, evaluators: tuple[uuid.UUID, ...] = ()
) -> str:
    r = await client.post(
        f"{API}/assignments/{aid}/allocations",
        json={
            "batch_id": str(batch),
            "due_at": (utcnow() + timedelta(days=1)).isoformat(),
            "section_engines": {sec: "pure_manual"},
            "evaluator_ids": [str(e) for e in evaluators],
        },
        headers=who.headers,
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def _submit(client: Any, stu: Any, aid: str) -> tuple[str, str]:
    r = await client.post(f"{API}/me/assignments/{aid}/workspace/start", headers=stu.headers)
    assert r.status_code == 200, r.text
    item = r.json()["sections"][0]["items"][0]["id"]
    r = await client.put(
        f"{API}/me/assignments/{aid}/workspace/items/{item}",
        json={"response": {"text": "private answer"}},
        headers=stu.headers,
    )
    assert r.status_code == 200, r.text
    r = await client.post(f"{API}/me/assignments/{aid}/workspace/submit", headers={**stu.headers, **idem()})
    assert r.status_code == 200, r.text
    return r.json()["id"], item


async def _remove_member(db: Any, user_id: uuid.UUID, batch: uuid.UUID) -> None:
    async with system_context(db, "test.factory"):
        await db.execute(
            text(
                "UPDATE batch_members SET status='removed', removed_at=now() WHERE user_id=:u AND batch_id=:b"
            ),
            {"u": user_id, "b": batch},
        )
        await db.flush()


@pytest.mark.usefixtures("catalog_backend")
async def test_sec02_grader_of_other_batch_cannot_read_or_grade(client, world: World) -> None:  # noqa: F811
    w = world
    stu = w.personas["student"]
    admin = w.personas["admin"]
    boss = await w.persona(
        "boss",
        grants=(("trainer", "batch", w.batch_a), ("trainer", "batch", w.batch_a2)),
        org_ids=(w.org_a,),
        tier="staff",
    )
    t2 = await w.persona(
        "trainer_a2", grants=(("trainer", "batch", w.batch_a2),), org_ids=(w.org_a,), tier="staff"
    )
    aid, sec = await _make(client, boss, w.batch_a, ESSAY)
    await _alloc(client, boss, aid, w.batch_a, sec)
    alloc_a2 = await _alloc(client, boss, aid, w.batch_a2, sec)
    sid, item = await _submit(client, stu, aid)

    # the batch_a2 grader sees only batch_a2's allocation and no batch_a learner
    r = await client.get(f"{API}/assignments/{aid}/evaluation", headers=t2.headers)
    assert r.status_code == 200 and r.json()["rows"] == [], r.text
    r = await client.get(f"{API}/assignments/{aid}/allocations", headers=t2.headers)
    assert [a["id"] for a in r.json()["data"]] == [alloc_a2]
    assert (
        await client.get(f"{API}/assignment-submissions/{sid}/review", headers=t2.headers)
    ).status_code == 403
    r = await client.post(
        f"{API}/assignment-submissions/{sid}/finalize",
        json={"items": [{"item_id": item, "marks": 1}]},
        headers=t2.headers,
    )
    assert r.status_code == 403, r.text
    # the owner grades; Admin (no assignment.grade) cannot
    assert (
        await client.get(f"{API}/assignment-submissions/{sid}/review", headers=boss.headers)
    ).status_code == 200
    assert (await client.get(f"{API}/assignments/{aid}/evaluation", headers=admin.headers)).status_code == 403


@pytest.mark.usefixtures("catalog_backend")
async def test_evaluator_ids_grant_grading_on_that_allocation_only(client, world: World) -> None:  # noqa: F811
    w = world
    stu = w.personas["student"]
    tr = w.personas["trainer_a"]
    # an evaluator granted on batch_a2 only, named on the batch_a allocation
    ev = await w.persona(
        "ev_a2", grants=(("evaluator", "batch", w.batch_a2),), org_ids=(w.org_a,), tier="staff"
    )
    other_ev = await w.persona(
        "ev_other", grants=(("evaluator", "batch", w.batch_a2),), org_ids=(w.org_a,), tier="staff"
    )
    from tests.identity.factory import add_member

    for p in (ev, other_ev):
        await add_member(w.db, w.org_a, p.id, "staff", w.batch_a2)
    aid, sec = await _make(client, tr, w.batch_a, ESSAY)
    # a learner cannot be named as evaluator
    r = await client.post(
        f"{API}/assignments/{aid}/allocations",
        json={
            "batch_id": str(w.batch_a),
            "due_at": (utcnow() + timedelta(days=1)).isoformat(),
            "section_engines": {sec: "pure_manual"},
            "evaluator_ids": [str(stu.id)],
        },
        headers=tr.headers,
    )
    assert r.status_code == 422 and r.json()["errors"][0]["code"] == "not_evaluator", r.text
    await _alloc(client, tr, aid, w.batch_a, sec, evaluators=(ev.id,))
    sid, item = await _submit(client, stu, aid)

    r = await client.get(f"{API}/assignments/{aid}/evaluation", headers=ev.headers)
    assert r.status_code == 200 and [x["submission_id"] for x in r.json()["rows"]] == [sid]
    r = await client.post(
        f"{API}/assignment-submissions/{sid}/finalize",
        json={"items": [{"item_id": item, "marks": 7}]},
        headers={**ev.headers, **idem()},
    )
    assert r.status_code == 200, r.text
    # D3: evaluators also publish (release) results ... on assignments in their batch scope;
    # this one belongs to batch_a, so the named evaluator of batch_a2 cannot release it
    assert (
        await client.post(f"{API}/assignments/{aid}/release-grades", headers=ev.headers)
    ).status_code == 403
    # an evaluator who is not named gets nothing
    assert (
        await client.get(f"{API}/assignments/{aid}/evaluation", headers=other_ev.headers)
    ).status_code == 403
    assert (
        await client.get(f"{API}/assignment-submissions/{sid}/review", headers=other_ev.headers)
    ).status_code == 403
    # the named evaluator sees the assignment in the staff list
    r = await client.get(f"{API}/assignments", headers=ev.headers)
    assert aid in {a["id"] for a in r.json()["data"]}


@pytest.mark.usefixtures("catalog_backend")
async def test_evaluator_grades_and_releases_but_cannot_author(client, world: World) -> None:  # noqa: F811
    w = world
    stu = w.personas["student"]
    tr = w.personas["trainer_a"]
    ev = w.personas["evaluator_a"]  # evaluator @ batch_a
    aid, sec = await _make(client, tr, w.batch_a, ESSAY)
    al = await _alloc(client, tr, aid, w.batch_a, sec)
    sid, item = await _submit(client, stu, aid)
    r = await client.post(
        f"{API}/assignment-submissions/{sid}/finalize",
        json={"items": [{"item_id": item, "marks": 6}]},
        headers={**ev.headers, **idem()},
    )
    assert r.status_code == 200, r.text
    assert (
        await client.post(f"{API}/assignments/{aid}/release-grades", headers=ev.headers)
    ).status_code == 200
    # no assignment.manage / authoring
    r = await client.post(
        f"{API}/assignments",
        json={"batch_id": str(w.batch_a), "title": "x", "submission_type": "structured", "max_score": 5},
        headers=ev.headers,
    )
    assert r.status_code == 403
    assert (
        await client.put(f"{API}/assignments/{aid}/structure", json=ESSAY, headers=ev.headers)
    ).status_code == 403
    assert (
        await client.patch(
            f"{API}/assignment-allocations/{al}", json={"status": "revoked"}, headers=ev.headers
        )
    ).status_code == 403
    assert (
        await client.post(
            f"{API}/studio/courses", json={"title": "Nope", "slug": "nope-ev"}, headers=ev.headers
        )
    ).status_code == 403


@pytest.mark.usefixtures("catalog_backend")
async def test_sec03_removed_member_loses_workspace_and_coding_grant(client, world: World, db) -> None:  # noqa: F811
    from app.core import access
    from app.core.principal import Principal
    from app.modules.coding import service as coding
    from app.modules.coding.schemas import ProblemCreateIn
    from app.modules.learning.structured import coding_access_grant

    coding.register_access_grant(coding_access_grant)
    prev = access.get_access_checker()
    access.register_access_checker(_DenyAll())
    try:
        w = world
        tr, stu = w.personas["trainer_a"], w.personas["student"]
        await system_context(db, "test.factory")
        p = await coding.create_problem(
            db,
            Principal(user_id=w.personas["author"].id, session_id=uuid.uuid4()),
            ProblemCreateIn(slug=f"s-{uuid.uuid4().hex[:8]}", title="Sum", statement_md="x", difficulty=1),
        )
        p.status = "published"
        await db.flush()
        prob = f"{API}/coding/problems/{p.id}"
        body = {
            "sections": [
                {
                    "title": "Code",
                    "items": [
                        {
                            "source": "inline",
                            "item_type": "coding",
                            "prompt_md": "Sum.",
                            "coding_problem_id": str(p.id),
                            "marks": 10,
                        }
                    ],
                }
            ]
        }
        aid, sec = await _make(client, tr, w.batch_a, body)
        await _alloc(client, tr, aid, w.batch_a, sec)
        r = await client.post(f"{API}/me/assignments/{aid}/workspace/start", headers=stu.headers)
        assert r.status_code == 200, r.text
        assert (await client.get(prob, headers=stu.headers)).status_code == 200  # grant while allocated
        await _remove_member(db, stu.id, w.batch_a)
        assert (
            await client.get(f"{API}/me/assignments/{aid}/workspace", headers=stu.headers)
        ).status_code == 404
        assert (
            await client.post(f"{API}/me/assignments/{aid}/workspace/start", headers=stu.headers)
        ).status_code == 404
        r = await client.get(prob, headers=stu.headers)
        assert r.status_code == 403, r.text
        assert aid not in {
            a["id"] for a in (await client.get(f"{API}/me/assignments", headers=stu.headers)).json()["data"]
        }
    finally:
        access.register_access_checker(prev)


@pytest.mark.usefixtures("catalog_backend")
async def test_sec09_sec11_sec12(client, world: World, db) -> None:  # noqa: F811
    w = world
    stu = w.personas["student"]
    tr = w.personas["trainer_a"]
    aid, sec = await _make(client, tr, w.batch_a, ESSAY)
    al = await _alloc(client, tr, aid, w.batch_a, sec)
    r = await client.post(f"{API}/me/assignments/{aid}/workspace/start", headers=stu.headers)
    assert r.status_code == 200, r.text
    item = r.json()["sections"][0]["items"][0]["id"]
    draft_id = r.json()["submission"]["id"]
    # SEC-11: the legacy grade endpoint refuses structured work (and drafts)
    r = await client.post(
        f"{API}/assignment-submissions/{draft_id}/grade", json={"score": 5}, headers={**tr.headers, **idem()}
    )
    assert r.status_code == 409, r.text
    # SEC-12: a grader can never extend their own deadline
    r = await client.post(
        f"{API}/assignment-allocations/{al}/extensions",
        json={
            "user_id": str(tr.id),
            "until": (utcnow() + timedelta(days=3)).isoformat(),
            "reason": "own deadline",
        },
        headers=tr.headers,
    )
    assert r.status_code == 403 and r.json()["code"] == "conflict_of_interest", r.text
    # extensions only for learners of the allocation
    r = await client.post(
        f"{API}/assignment-allocations/{al}/extensions",
        json={
            "user_id": str(w.personas["student_b"].id),
            "until": (utcnow() + timedelta(days=3)).isoformat(),
            "reason": "not in this batch",
        },
        headers=tr.headers,
    )
    assert r.status_code == 422, r.text
    # SEC-09: once archived, no autosave / submit / tutor; the workspace stays readable
    r = await client.patch(f"{API}/assignments/{aid}", json={"status": "archived"}, headers=tr.headers)
    assert r.status_code == 200, r.text
    r = await client.put(
        f"{API}/me/assignments/{aid}/workspace/items/{item}",
        json={"response": {"text": "late edit"}},
        headers=stu.headers,
    )
    assert r.status_code in (404, 409), r.text
    r = await client.post(f"{API}/me/assignments/{aid}/workspace/submit", headers={**stu.headers, **idem()})
    assert r.status_code in (404, 409), r.text
    r = await client.post(
        f"{API}/me/assignments/{aid}/tutor", json={"item_id": item, "mode": "guide"}, headers=stu.headers
    )
    assert r.status_code in (404, 409), r.text


@pytest.mark.usefixtures("catalog_backend")
async def test_company_wide_assignment_needs_platform_and_no_org_input(client, world: World) -> None:  # noqa: F811
    w = world
    tr = w.personas["trainer_a"]
    r = await client.post(
        f"{API}/assignments",
        json={"organization_id": str(w.org_a), "title": "x", "submission_type": "structured", "max_score": 5},
        headers=tr.headers,
    )
    assert r.status_code == 400
    assert (
        await client.get(f"{API}/enrolments", params={"organization_id": str(w.org_a)}, headers=tr.headers)
    ).status_code == 403


async def _alloc_users(client: Any, who: Any, aid: str, sec: str, users: list[uuid.UUID]) -> Any:
    return await client.post(
        f"{API}/assignments/{aid}/allocations",
        json={
            "user_ids": [str(u) for u in users],
            "due_at": (utcnow() + timedelta(days=1)).isoformat(),
            "section_engines": {sec: "pure_manual"},
        },
        headers=who.headers,
    )


@pytest.mark.usefixtures("catalog_backend")
async def test_individual_allocation_limited_to_callers_batches(client, world: World) -> None:  # noqa: F811
    """A trainer may name individual learners only from batches where they hold
    ``assignment.manage``. Another batch's learner of the same company and an unknown id get the
    same 422 (no existence oracle)."""
    w = world
    tr = w.personas["trainer_a"]
    aid, sec = await _make(client, tr, w.batch_a, ESSAY)
    errors = []
    for target in (w.personas["student_b"].id, uuid.uuid4()):
        r = await _alloc_users(client, tr, aid, sec, [target])
        assert r.status_code == 422, r.text
        errors.append(r.json()["errors"])
    assert errors[0] == errors[1] and errors[0][0]["code"] == "not_member"
    # a mix is refused as a whole, pointing at the out-of-scope entry
    r = await _alloc_users(client, tr, aid, sec, [w.personas["student"].id, w.personas["student_b"].id])
    assert r.status_code == 422 and r.json()["errors"][0]["field"] == "user_ids.1", r.text
    # own batch's learner: allowed
    r = await _alloc_users(client, tr, aid, sec, [w.personas["student"].id])
    assert r.status_code == 201, r.text
    # a trainer holding both batches may name either learner
    boss = await w.persona(
        "boss_users",
        grants=(("trainer", "batch", w.batch_a), ("trainer", "batch", w.batch_b)),
        org_ids=(w.org_a,),
        tier="staff",
    )
    r = await _alloc_users(client, boss, aid, sec, [w.personas["student"].id, w.personas["student_b"].id])
    assert r.status_code == 201, r.text


@pytest.mark.usefixtures("catalog_backend")
async def test_patch_allocation_checks_the_allocations_own_batch(client, world: World) -> None:  # noqa: F811
    """Managing the assignment (batch_a) is not enough to edit its batch_a2 allocation."""
    w = world
    tr = w.personas["trainer_a"]  # trainer @ batch_a only
    boss = await w.persona(
        "boss_patch",
        grants=(("trainer", "batch", w.batch_a), ("trainer", "batch", w.batch_a2)),
        org_ids=(w.org_a,),
        tier="staff",
    )
    aid, sec = await _make(client, boss, w.batch_a, ESSAY)
    own = await _alloc(client, boss, aid, w.batch_a, sec)
    other = await _alloc(client, boss, aid, w.batch_a2, sec)
    r = await client.patch(
        f"{API}/assignment-allocations/{other}", json={"status": "revoked"}, headers=tr.headers
    )
    assert r.status_code == 403 and r.json()["permission"] == "assignment.manage", r.text
    r = await client.patch(
        f"{API}/assignment-allocations/{own}",
        json={"due_at": (utcnow() + timedelta(days=2)).isoformat()},
        headers=tr.headers,
    )
    assert r.status_code == 200, r.text
    r = await client.patch(
        f"{API}/assignment-allocations/{other}", json={"status": "revoked"}, headers=boss.headers
    )
    assert r.status_code == 200 and r.json()["status"] == "revoked", r.text
