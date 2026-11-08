"""Regression tests for audit Phase B fixes in the coding module.

BE-11 submission org attribution · BE-20 draft entitlement · BE-07 public ownership check ·
COM-09 no unconsumed ``judge_*`` Celery traffic · INV-10 no dead ``stream_url``.
"""

from __future__ import annotations

import os
import uuid

from sqlalchemy import text

from app.core.db import system_context
from app.core.ids import uuid7
from app.modules.coding import service, tasks
from app.modules.coding.models import CodeSubmission
from tests.coding.conftest import idem, seed_problem
from tests.identity.factory import company_org


async def _submission(db, sid: str) -> CodeSubmission:
    await system_context(db, "test")
    sub = await db.get(CodeSubmission, uuid.UUID(sid))
    assert sub is not None
    return sub


# --------------------------------------------------------------------------- BE-20


async def test_drafts_require_problem_entitlement(client, db, actors, access) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    url = f"/api/v1/coding/problems/{p.id}/drafts/python3"
    access.allow = False
    r = await client.put(url, json={"source_code": "print(1)"}, headers=st.headers)
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "entitlement_required"
    assert (await client.get(url, headers=st.headers)).status_code == 403
    access.allow = True
    assert (await client.put(url, json={"source_code": "print(1)"}, headers=st.headers)).status_code == 200
    g = await client.get(url, headers=st.headers)
    assert g.status_code == 200 and g.json()["source_code"] == "print(1)"


# --------------------------------------------------------------------------- BE-11


async def test_company_member_submission_is_attributed(client, db, actors, access, fake_judge) -> None:
    """Single company: a batch student's practice submission belongs to the company org."""
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors(org_ids=(company_org(),))
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\n"},
        headers=idem(st.headers),
    )
    assert r.status_code == 202, r.text
    sub = await _submission(db, r.json()["submission_id"])
    assert sub.organization_id == company_org()


async def test_org_private_problem_submission_uses_problem_org(
    client, db, actors, access, fake_judge
) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    # single company: a company-private problem is attributed to the company; a public learner
    # (no company membership) cannot even reach it (RLS -> 404)
    o2 = company_org()
    await system_context(db, "test.factory")
    p.organization_id = o2
    await db.flush()
    public = await actors()
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/run",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\n"},
        headers=idem(public.headers),
    )
    assert r.status_code == 404, r.text
    st = await actors(org_ids=(o2,))
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/run",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\n"},
        headers=idem(st.headers),
    )
    assert r.status_code == 202, r.text
    assert (await _submission(db, r.json()["submission_id"])).organization_id == o2


async def test_single_org_and_d2c_attribution(client, db, actors, access, fake_judge) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    one = await actors(org_ids=(company_org(),))
    d2c = await actors()
    for actor, expected in ((one, company_org()), (d2c, None)):
        r = await client.post(
            f"/api/v1/coding/problems/{p.id}/run",
            json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\n"},
            headers=idem(actor.headers),
        )
        assert r.status_code == 202, r.text
        assert (await _submission(db, r.json()["submission_id"])).organization_id == expected


async def test_in_attempt_submission_uses_attempt_org(db, actors) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    # the attempt's organization wins over the membership rule: the caller is a public learner
    # (membership alone would attribute None)
    o_attempt = company_org()
    st = await actors()
    await system_context(db, "test.factory")
    test_id, attempt_id = uuid7(), uuid7()
    await db.execute(
        text(
            "INSERT INTO tests (id, test_kind, title, review_policy, created_by) "
            "VALUES (:id, 'mock', 'T', '{}'::jsonb, :u)"
        ),
        {"id": test_id, "u": author.id},
    )
    await db.execute(
        text(
            "INSERT INTO test_attempts (id, test_id, test_version, user_id, organization_id, attempt_no, "
            "selection_seed, layout, idempotency_key) VALUES (:id, :t, 1, :u, :o, 1, "
            "decode('00000000000000000000000000000000', 'hex'), '{}'::jsonb, :k)"
        ),
        {"id": attempt_id, "t": test_id, "u": st.id, "o": o_attempt, "k": f"k-{attempt_id}"},
    )
    org = await service.submission_org(db, st.principal, p, attempt_id=attempt_id)
    assert org == o_attempt
    # an attempt id that is not the caller's own falls through to the membership rule
    stranger = await actors(org_ids=(company_org(),))
    assert await service.submission_org(db, stranger.principal, p, attempt_id=attempt_id) == company_org()
    public = await actors()
    assert await service.submission_org(db, public.principal, p, attempt_id=attempt_id) is None


# --------------------------------------------------------------------------- BE-07 (public helper)


async def test_verify_submission_owner(client, db, actors, access, fake_judge) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    other = await seed_problem(db, author.id)
    st = await actors()
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\n"},
        headers=idem(st.headers),
    )
    sid = uuid.UUID(r.json()["submission_id"])
    run = await client.post(
        f"/api/v1/coding/problems/{p.id}/run",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\n"},
        headers=idem(st.headers),
    )
    run_id = uuid.UUID(run.json()["submission_id"])
    await system_context(db, "test")
    assert await service.verify_submission_owner(db, sid, st.id)
    assert await service.verify_submission_owner(db, sid, st.id, p.id)
    assert not await service.verify_submission_owner(db, sid, st.id, other.id)
    assert not await service.verify_submission_owner(db, sid, author.id)
    assert not await service.verify_submission_owner(db, uuid.uuid4(), st.id)
    assert not await service.verify_submission_owner(db, run_id, st.id)  # scratch runs don't count


# --------------------------------------------------------------------------- COM-09 / INV-10


def test_no_beat_entry_or_wakeup_on_unconsumed_judge_queues(monkeypatch) -> None:
    from app.core.jobs import beat_schedule

    sched = beat_schedule()
    assert tasks.SWEEP_TASK not in sched
    assert not [
        n for n, e in sched.items() if str((e.get("options") or {}).get("queue", "")).startswith("judge_")
    ]

    sent: list[tuple] = []

    class _App:
        def send_task(self, *a, **kw):
            sent.append((a, kw))

    import sys
    import types

    fake = types.ModuleType("app.worker")
    fake.celery_app = _App()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.worker", fake)
    monkeypatch.delenv(tasks.WAKEUPS_ENV, raising=False)
    tasks.notify_enqueued(uuid.uuid4(), "judge_submit")
    assert sent == []  # default deployment: the worker-judge DB poller picks the row up
    monkeypatch.setenv(tasks.WAKEUPS_ENV, "1")
    tasks.notify_enqueued(uuid.uuid4(), "judge_submit")
    assert len(sent) == 1 and sent[0][1]["queue"] == "judge_submit"
    assert os.environ.get(tasks.WAKEUPS_ENV) == "1"


async def test_accepted_body_has_no_dead_stream_url(client, db, actors, access, fake_judge) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/run",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\n"},
        headers=idem(st.headers),
    )
    assert r.status_code == 202
    assert "stream_url" not in r.json()
    assert r.json()["poll_url"].endswith(r.json()["submission_id"])


# --------------------------------------------------------------------------- DB-01 erasure provider


async def test_db01_coding_erasure_provider(client, db, actors, access, fake_judge) -> None:
    from app.modules.admin.privacy import erasure_providers
    from app.modules.coding import privacy
    from app.modules.coding.worker import judge_submission

    assert erasure_providers()["coding"] is privacy.erase_user
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    draft = f"/api/v1/coding/problems/{p.id}/drafts/python3"
    assert (await client.put(draft, json={"source_code": "print(1)"}, headers=st.headers)).status_code == 200
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\nprint('secret')\n"},
        headers=idem(st.headers),
    )
    assert r.status_code == 202, r.text
    await system_context(db, "test")
    await judge_submission(db, uuid.UUID(r.json()["submission_id"]), fake_judge, budget_s=1)
    out = await privacy.erase_user(db, st.id)
    assert out["coding_drafts_deleted"] == 1 and out["code_submissions_cleared"] == 1
    sub = await _submission(db, r.json()["submission_id"])
    await db.refresh(sub)
    assert sub.source_code == privacy.ERASED and sub.normalized_sha256 is None and sub.verdict == "AC"
    left = (
        await db.execute(
            text(
                "SELECT count(*) FROM submission_results WHERE code_submission_id = :s "
                "AND stdout_excerpt IS NOT NULL"
            ),
            {"s": sub.id},
        )
    ).scalar()
    assert left == 0
    again = await privacy.erase_user(db, st.id)
    assert again == {
        "coding_drafts_deleted": 0,
        "code_submissions_cleared": 0,
        "submission_outputs_cleared": 0,
    }
