"""Run vs submit, hidden-test protection, rate limits, entitlement, restrictions, history."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select

from app.core.db import system_context
from app.modules.coding import service
from app.modules.coding.models import CodeSubmission, CodingTestCase, CodingTestCaseBlob, SubmissionResult
from app.modules.coding.worker import judge_submission
from tests.coding.conftest import HIDDEN_INPUT, idem, seed_problem

SECRETS = ("SECRET_HIDDEN_INPUT", "SECRET_HIDDEN_EXPECTED", "424242")
HIDDEN_KEYS = {"ordinal", "is_sample", "verdict", "time_ms", "memory_kb"}


def assert_no_hidden(*texts: str) -> None:
    for t in texts:
        for s in SECRETS:
            assert s not in t, f"hidden test data leaked: {s!r} in {t[:300]!r}"


async def _judge(db, sid: str, adapter) -> str:
    return await judge_submission(db, uuid.UUID(sid), adapter, budget_s=1)


async def test_run_executes_samples_and_custom_input_only(client, db, actors, access, fake_judge) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/run",
        json={
            "language_key": "python3",
            "source_code": "# FAKE_VERDICT: AC\nprint(6)\n",
            "custom_input": "7\n",
        },
        headers=idem(st.headers),
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["mode"] == "run" and body["queue"] == "judge_run" and body["status"] == "queued"
    assert body["queue_position"] >= 1 and body["problem_version"] == 1

    assert await _judge(db, body["submission_id"], fake_judge) == "AC"
    # The judge never received hidden data for a run.
    stdins = [j.stdin for j in fake_judge.submitted]
    assert stdins == ["3\n1 2 3\n", "7\n"]
    assert_no_hidden(*stdins)

    g = await client.get(f"/api/v1/coding/submissions/{body['submission_id']}", headers=st.headers)
    assert g.status_code == 200, g.text
    d = g.json()
    assert d["status"] == "completed" and d["verdict"] == "AC" and d["score"] is None
    assert [c["is_sample"] for c in d["cases"]] == [True, True]
    sample, custom = d["cases"]
    assert (
        sample["stdout_excerpt"] == "6\n"
        and sample["expected_output"] == "6\n"
        and sample["input"] == "3\n1 2 3\n"
    )
    assert custom["is_custom"] is True and custom["input"] == "7\n" and custom["expected_output"] is None
    assert_no_hidden(r.text, g.text)


async def test_submit_judges_all_cases_hidden_are_verdict_only(
    client, db, actors, access, fake_judge
) -> None:
    author = await actors()
    p = await seed_problem(db, author.id, weights=[Decimal(2), Decimal(3)])
    st = await actors()
    src = "// FAKE_VERDICT: AC,AC,WA\nint main(){}\n"
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "cpp17", "source_code": src},
        headers=idem(st.headers),
    )
    assert r.status_code == 202, r.text
    sid = r.json()["submission_id"]
    assert r.json()["queue"] == "judge_submit"

    assert await _judge(db, sid, fake_judge) == "PARTIAL"
    # Hidden cases were sent to the judge (decrypted in worker memory only).
    assert len(fake_judge.submitted) == 3
    assert HIDDEN_INPUT in fake_judge.submitted[1].stdin

    g = await client.get(f"/api/v1/coding/submissions/{sid}", headers=st.headers)
    d = g.json()
    assert d["verdict"] == "PARTIAL" and d["passed_cases"] == 2 and d["total_cases"] == 3
    assert d["score"] == 3.0 and d["max_score"] == 6.0  # sample 1 + hidden 2 passed; hidden 3 failed
    hidden = [c for c in d["cases"] if not c["is_sample"]]
    assert [c["verdict"] for c in hidden] == ["AC", "WA"]
    for c in hidden:
        assert set(c) == HIDDEN_KEYS
    hist = await client.get(f"/api/v1/me/coding/submissions?problem_id={p.id}", headers=st.headers)
    assert hist.status_code == 200 and hist.json()["data"][0]["submission_id"] == sid
    prob = await client.get(f"/api/v1/coding/problems/{p.slug}", headers=st.headers)
    assert prob.status_code == 200 and len(prob.json()["samples"]) == 1
    listing = await client.get("/api/v1/coding/problems", headers=st.headers)
    item = next(i for i in listing.json()["data"] if i["problem_id"] == str(p.id))
    assert item["status"] == "attempted" and item["entitled"] is True
    assert_no_hidden(r.text, g.text, hist.text, prob.text, listing.text)

    # Storage: hidden stdout never stored; ciphertext only.
    await system_context(db, "test.check")
    res = (
        (await db.execute(select(SubmissionResult).where(SubmissionResult.is_hidden.is_(True))))
        .scalars()
        .all()
    )
    assert res and all(x.stdout_excerpt is None for x in res)
    blobs = (await db.execute(select(CodingTestCaseBlob.ciphertext))).scalars().all()
    assert blobs and all(b"SECRET_HIDDEN" not in bytes(b) for b in blobs)
    cases = (
        (await db.execute(select(CodingTestCase).where(CodingTestCase.is_hidden.is_(True)))).scalars().all()
    )
    assert all(c.sample_input is None and c.sample_output is None for c in cases)


async def test_compile_error_and_all_or_nothing(client, db, actors, access, fake_judge) -> None:
    author = await actors()
    p = await seed_problem(db, author.id, scoring_mode="all_or_nothing")
    st = await actors()
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "c", "source_code": "/* FAKE_VERDICT: CE */ int main(){"},
        headers=idem(st.headers),
    )
    sid = r.json()["submission_id"]
    assert await _judge(db, sid, fake_judge) == "CE"
    d = (await client.get(f"/api/v1/coding/submissions/{sid}", headers=st.headers)).json()
    assert d["verdict"] == "CE" and d["score"] == 0.0 and "compilation error" in d["compile_output"]
    assert all(c["verdict"] == "CE" for c in d["cases"])

    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "c", "source_code": "/* FAKE_VERDICT: AC,AC,TLE */"},
        headers=idem(st.headers),
    )
    sid = r.json()["submission_id"]
    assert await _judge(db, sid, fake_judge) == "TLE"
    d = (await client.get(f"/api/v1/coding/submissions/{sid}", headers=st.headers)).json()
    assert d["score"] == 0.0 and d["passed_cases"] == 2

    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "c", "source_code": "/* FAKE_VERDICT: AC */"},
        headers=idem(st.headers),
    )
    sid = r.json()["submission_id"]
    assert await _judge(db, sid, fake_judge) == "AC"
    d = (await client.get(f"/api/v1/coding/submissions/{sid}", headers=st.headers)).json()
    assert d["score"] == d["max_score"] == 3.0


async def test_run_rate_limit_and_idempotent_replay(client, db, actors, access, fake_judge) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    url = f"/api/v1/coding/problems/{p.id}/run"
    body = {"language_key": "python3", "source_code": "print(1)"}
    first = await client.post(url, json=body, headers=idem(st.headers, "fixed-key-0001"))
    replay = await client.post(url, json=body, headers=idem(st.headers, "fixed-key-0001"))
    assert replay.status_code == 202 and replay.headers.get("Idempotency-Replayed") == "true"
    assert replay.json()["submission_id"] == first.json()["submission_id"]
    for _ in range(9):
        assert (await client.post(url, json=body, headers=idem(st.headers))).status_code == 202
    limited = await client.post(url, json=body, headers=idem(st.headers))
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"
    assert limited.headers["Retry-After"] == "60"
    # Replays are not rate limited.
    again = await client.post(url, json=body, headers=idem(st.headers, "fixed-key-0001"))
    assert again.status_code == 202
    # Missing Idempotency-Key.
    nokey = await client.post(url, json=body, headers=st.headers)
    assert nokey.status_code == 400 and nokey.json()["code"] == "idempotency_key_required"


async def test_submit_in_flight_and_per_minute_limit(client, db, actors, access, fake_judge) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    url = f"/api/v1/coding/problems/{p.id}/submit"
    body = {"language_key": "python3", "source_code": "# FAKE_VERDICT: WA"}
    r = await client.post(url, json=body, headers=idem(st.headers))
    assert r.status_code == 202
    busy = await client.post(url, json=body, headers=idem(st.headers))
    assert busy.status_code == 409 and busy.json()["code"] == "submission_in_flight"
    await _judge(db, r.json()["submission_id"], fake_judge)
    for _ in range(4):
        r = await client.post(url, json=body, headers=idem(st.headers))
        assert r.status_code == 202, r.text
        await _judge(db, r.json()["submission_id"], fake_judge)
    limited = await client.post(url, json=body, headers=idem(st.headers))
    assert limited.status_code == 429 and limited.json()["code"] == "rate_limited"


async def test_validation_language_and_size(client, db, actors, access) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    url = f"/api/v1/coding/problems/{p.id}/submit"
    r = await client.post(
        url, json={"language_key": "brainfuck", "source_code": "+"}, headers=idem(st.headers)
    )
    assert r.status_code == 422 and r.json()["code"] == "language_not_allowed"
    big = "x" * (64 * 1024 + 1)
    r = await client.post(url, json={"language_key": "python3", "source_code": big}, headers=idem(st.headers))
    assert r.status_code == 413
    r = await client.post(url, json={"language_key": "python3"}, headers=idem(st.headers))
    assert r.status_code == 400


async def test_entitlement_denied_without_checker_and_free_allowed(
    client, db, actors, fake_judge, monkeypatch
) -> None:
    import app.core.access as core_access

    monkeypatch.setattr(core_access, "_access_checker", None)  # fail-closed default
    author = await actors()
    paid = await seed_problem(db, author.id)
    free = await seed_problem(db, author.id, is_free=True)
    st = await actors()
    r = await client.get(f"/api/v1/coding/problems/{paid.slug}", headers=st.headers)
    assert r.status_code == 403 and r.json()["code"] == "entitlement_required"
    for mode in ("run", "submit"):
        r = await client.post(
            f"/api/v1/coding/problems/{paid.id}/{mode}",
            json={"language_key": "python3", "source_code": "print(1)"},
            headers=idem(st.headers),
        )
        assert r.status_code == 403 and r.json()["code"] == "entitlement_required"
    r = await client.get(f"/api/v1/coding/problems/{free.slug}", headers=st.headers)
    assert r.status_code == 200
    listing = (await client.get("/api/v1/coding/problems", headers=st.headers)).json()["data"]
    ent = {i["problem_id"]: i["entitled"] for i in listing}
    assert ent[str(paid.id)] is False and ent[str(free.id)] is True


async def test_entitlement_checker_denial(client, db, actors, access) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    access.allow = False
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "python3", "source_code": "print(1)"},
        headers=idem(st.headers),
    )
    assert r.status_code == 403 and r.json()["code"] == "entitlement_required"
    assert ("coding_problem", p.id) in access.calls


async def test_restricted_principals_denied(client, db, actors, access) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    restricted = await actors(scope="restricted", restriction_level=2)
    r = await client.get("/api/v1/coding/problems", headers=restricted.headers)
    assert r.status_code == 403 and r.json()["code"] == "account_restricted"
    l3 = await actors(restriction_level=3)
    for mode in ("run", "submit"):
        r = await client.post(
            f"/api/v1/coding/problems/{p.id}/{mode}",
            json={"language_key": "python3", "source_code": "print(1)"},
            headers=idem(l3.headers),
        )
        assert r.status_code == 403 and r.json()["code"] == "account_restricted"
    unauth = await client.get("/api/v1/coding/languages")
    assert unauth.status_code == 401


async def test_unpublished_problem_hidden_from_students(client, db, actors, access) -> None:
    author = await actors()
    p = await seed_problem(db, author.id, publish=False)
    st = await actors()
    assert (await client.get(f"/api/v1/coding/problems/{p.slug}", headers=st.headers)).status_code == 404
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/run",
        json={"language_key": "python3", "source_code": "x"},
        headers=idem(st.headers),
    )
    assert r.status_code == 404


async def test_other_users_submission_is_404_staff_sees_source_not_hidden(
    client, db, actors, access, fake_judge, monkeypatch
) -> None:
    import app.modules.coding.router as coding_router

    audited: list[str] = []
    real_audit = coding_router.audit

    async def spy(session, actor, action, *a, **kw):
        audited.append(action)
        return await real_audit(session, actor, action, *a, **kw)

    monkeypatch.setattr(coding_router, "audit", spy)
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\n"},
        headers=idem(st.headers),
    )
    sid = r.json()["submission_id"]
    await _judge(db, sid, fake_judge)
    other = await actors()
    assert (await client.get(f"/api/v1/coding/submissions/{sid}", headers=other.headers)).status_code == 404
    staff = await actors("submission.code.read", is_platform=True)
    g = await client.get(f"/api/v1/coding/submissions/{sid}", headers=staff.headers)
    assert g.status_code == 200 and g.json()["source_code"] == "# FAKE_VERDICT: AC\n"
    assert all(set(c) == HIDDEN_KEYS for c in g.json()["cases"] if not c["is_sample"])
    assert_no_hidden(g.text)
    assert audited == ["coding.submission.read"]


async def test_normalized_hash_plagiarism_hook(client, db, actors, access) -> None:
    a = service.normalized_hash("python3", "x = 1  # c\nprint(x)\n")
    b = service.normalized_hash("python3", "x = 1\n\n\nprint(x)  # other comment")
    assert a == b
    assert service.normalized_hash("cpp17", "int a; // x\n/* y */ int b;") == service.normalized_hash(
        "cpp17", "int a;   int b;"
    )
    author = await actors()
    p = await seed_problem(db, author.id)
    u1, u2 = await actors(), await actors()
    ids = []
    for u, src in ((u1, "print(sum([1]))  # mine"), (u2, "print(sum([1]))\n")):
        r = await client.post(
            f"/api/v1/coding/problems/{p.id}/submit",
            json={"language_key": "python3", "source_code": src},
            headers=idem(u.headers),
        )
        ids.append(uuid.UUID(r.json()["submission_id"]))
    await system_context(db, "test.check")
    sub = await db.get(CodeSubmission, ids[0])
    assert sub is not None and sub.normalized_sha256 is not None
    assert await service.similarity_candidates(db, sub) == [ids[1]]
