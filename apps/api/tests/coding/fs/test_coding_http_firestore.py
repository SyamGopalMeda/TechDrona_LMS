"""Coding HTTP API through the FastAPI app on Firestore, with no Postgres (the request session is
``db.NO_POSTGRES``): author -> validate -> publish -> student draft -> submit -> judge (worker on
Firestore, fake judge) -> view result; versioning; hidden-case content tokens; erasure."""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any

from app.modules.identity import clock
from tests.audit.fs.http_support import fs_http  # noqa: F401
from tests.audit.fs.support import fs_env  # noqa: F401
from tests.coding.conftest import HIDDEN_EXPECTED, HIDDEN_INPUT
from tests.coding.fs.support import seed_languages

FS_MODULES = (
    "coding",
    "placement",
    "assessments",
    "core",
    "audit",
    "identity",
    "sessions",
    "rbac",
    "notifications",
    "orgs",
    "entitlements",
    "ai",
    "analytics",
    "admin",
    "learning",
)
P = "/api/v1"
STAFF_PERMS = (
    "coding_problem.manage",
    "coding_test_case.hidden.read",
    "test.create",
    "submission.code.read",
)
SECRETS = ("SECRET_HIDDEN_INPUT", "SECRET_HIDDEN_EXPECTED", "424242")


def _idem(h: dict[str, str], key: str | None = None) -> dict[str, str]:
    return {**h, "Idempotency-Key": key or f"k-{uuid.uuid4()}"}


def _staff(make_principal: Any, auth: Any) -> tuple[Any, dict[str, str]]:
    p = make_principal(
        is_platform=True,
        roles=("content_manager",),
        tier="privileged",
        last_step_up_at=clock.now(),
        is_minor=False,
    )
    for perm in STAFF_PERMS:
        auth.grant(p, perm)
    return p, auth.login(p)


def _no_hidden(*texts: str) -> None:
    for t in texts:
        for s in SECRETS:
            assert s not in t, f"hidden test data leaked: {s!r}"


async def _author_problem(client: Any, author: dict[str, str], reviewer: dict[str, str], slug: str) -> str:
    r = await client.post(
        f"{P}/studio/coding/problems",
        json={"slug": slug, "title": "Sum of numbers", "statement_md": "Print the sum.", "difficulty": 1},
        headers=author,
    )
    assert r.status_code == 201, r.text
    pid = r.json()["problem_id"]
    assert r.json()["status"] == "draft" and r.json()["version_no"] == 1
    s = await client.post(
        f"{P}/studio/coding/problems/{pid}/test-cases",
        json={"kind": "sample", "input": "3\n1 2 3\n", "expected_output": "6\n"},
        headers=author,
    )
    assert s.status_code == 201 and s.json()["ordinal"] == 1, s.text
    for i in range(2):
        h = await client.post(
            f"{P}/studio/coding/problems/{pid}/test-cases",
            json={
                "kind": "hidden",
                "input": f"{i}{HIDDEN_INPUT}",
                "expected_output": f"{i}{HIDDEN_EXPECTED}",
            },
            headers=author,
        )
        assert h.status_code == 201 and h.json()["ordinal"] == 2 + i, h.text
        _no_hidden(h.text)
    # publish needs a passing validation of exactly this version
    early = await client.post(f"{P}/studio/coding/problems/{pid}/publish", headers=reviewer)
    assert early.status_code == 409 and early.json()["reason"] == "validation_required", early.text
    ref = await client.put(
        f"{P}/studio/coding/problems/{pid}/reference-solutions/python3",
        json={"source_code": "# FAKE_VERDICT: AC\nprint(sum(...))\n"},
        headers=author,
    )
    assert ref.status_code == 200 and "source_code" not in ref.json(), ref.text
    v = await client.post(f"{P}/studio/coding/problems/{pid}/validate", headers=author)
    assert v.status_code == 200, v.text
    assert v.json()["status"] == "passed" and v.json()["is_current"] is True
    sol = v.json()["solutions"][0]
    assert sol["verdict"] == "AC" and sol["passed_cases"] == 3
    assert all(set(c) == {"ordinal", "is_sample", "verdict", "time_ms", "memory_kb"} for c in sol["cases"])
    latest = await client.get(f"{P}/studio/coding/problems/{pid}/validation", headers=author)
    assert latest.status_code == 200 and latest.json()["validation_id"] == v.json()["validation_id"]
    _no_hidden(v.text, latest.text)
    # SoD: a platform problem is published by a reviewer, not its author
    sod = await client.post(f"{P}/studio/coding/problems/{pid}/publish", headers=author)
    assert sod.status_code == 403 and sod.json()["code"] == "sod_violation"
    pub = await client.post(f"{P}/studio/coding/problems/{pid}/publish", headers=reviewer)
    assert pub.status_code == 200 and pub.json()["status"] == "published", pub.text
    again = await client.post(f"{P}/studio/coding/problems/{pid}/publish", headers=reviewer)
    assert again.status_code == 409
    return str(pid)


async def test_author_validate_publish_submit_judge_view(
    fs_http: Any,  # noqa: F811
    make_principal: Any,
    fake_judge: Any,
    access: Any,
) -> None:
    from app.modules.coding import worker

    client, _rec, auth = fs_http
    await seed_languages()
    _a, author = _staff(make_principal, auth)
    _r, reviewer = _staff(make_principal, auth)

    langs = await client.get(f"{P}/coding/languages", headers=author)
    assert langs.status_code == 200 and [x["language_key"] for x in langs.json()["data"]] == [
        "c",
        "cpp17",
        "java17",
        "python3",
    ]
    pid = await _author_problem(client, author, reviewer, "sum-numbers")
    dup = await client.post(
        f"{P}/studio/coding/problems",
        json={"slug": "sum-numbers", "title": "Again", "statement_md": "x", "difficulty": 1},
        headers=author,
    )
    assert dup.status_code == 400 and dup.json()["errors"][0]["code"] == "duplicate"

    studio = await client.get(f"{P}/studio/coding/problems", headers=author)
    assert studio.status_code == 200, studio.text
    row = studio.json()["data"][0]
    assert row["problem_id"] == pid and row["test_cases"] == {"sample": 1, "hidden": 2}
    found = await client.get(f"{P}/studio/coding/problems", params={"q": "SUM"}, headers=author)
    assert [x["problem_id"] for x in found.json()["data"]] == [pid]
    picker = await client.get(f"{P}/studio/coding/problems/published", headers=author)
    assert picker.status_code == 200 and picker.json()["data"][0]["problem_id"] == pid, picker.text
    detail = await client.get(f"{P}/studio/coding/problems/{pid}", headers=author)
    assert detail.status_code == 200 and detail.json()["test_cases"] == {"sample": 1, "hidden": 2}

    # ---- student
    student = make_principal(is_minor=False)
    hs = auth.login(student)
    lst = await client.get(f"{P}/coding/problems", headers=hs)
    assert lst.status_code == 200, lst.text
    assert lst.json()["data"][0] == {
        "problem_id": pid,
        "slug": "sum-numbers",
        "title": "Sum of numbers",
        "difficulty": 1,
        "is_free": False,
        "entitled": True,
        "status": "not_started",
    }
    prob = await client.get(f"{P}/coding/problems/sum-numbers", headers=hs)
    assert prob.status_code == 200 and prob.json()["samples"] == [
        {"ordinal": 1, "input": "3\n1 2 3\n", "expected_output": "6\n"}
    ]
    assert [x["language_key"] for x in prob.json()["languages"]] == ["c", "cpp17", "java17", "python3"]
    by_id = await client.get(f"{P}/coding/problems/{pid}", headers=hs)
    assert by_id.json()["problem_id"] == pid

    # drafts (COD-04/05)
    none = await client.get(f"{P}/coding/problems/{pid}/drafts/python3", headers=hs)
    assert none.status_code == 404
    d1 = await client.put(
        f"{P}/coding/problems/{pid}/drafts/python3", json={"source_code": "print(1)"}, headers=hs
    )
    assert d1.status_code == 200 and d1.json()["size_bytes"] == 8, d1.text
    d2 = await client.put(
        f"{P}/coding/problems/{pid}/drafts/python3", json={"source_code": "print(2)"}, headers=hs
    )
    assert d2.status_code == 200
    got = await client.get(f"{P}/coding/problems/{pid}/drafts/python3", headers=hs)
    assert got.json()["source_code"] == "print(2)"
    bad_lang = await client.put(
        f"{P}/coding/problems/{pid}/drafts/rust", json={"source_code": "x"}, headers=hs
    )
    assert bad_lang.status_code == 422 and bad_lang.json()["code"] == "language_not_allowed"
    other = auth.login(make_principal(is_minor=False))
    assert (await client.get(f"{P}/coding/problems/{pid}/drafts/python3", headers=other)).status_code == 404

    # run: samples + custom input only
    run = await client.post(
        f"{P}/coding/problems/{pid}/run",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\n", "custom_input": "7\n"},
        headers=_idem(hs),
    )
    assert run.status_code == 202, run.text
    assert run.json()["queue"] == "judge_run" and run.json()["queue_position"] == 1

    # submit (idempotent replay through the Firestore idempotency record)
    key = f"k-{uuid.uuid4()}"
    src = "// FAKE_VERDICT: AC,AC,WA\nint main(){}\n"
    sub = await client.post(
        f"{P}/coding/problems/{pid}/submit",
        json={"language_key": "cpp17", "source_code": src},
        headers=_idem(hs, key),
    )
    assert sub.status_code == 202, sub.text
    body = sub.json()
    assert body["status"] == "queued" and body["queue"] == "judge_submit" and body["problem_version"] == 1
    assert body["queue_position"] == 1
    replay = await client.post(
        f"{P}/coding/problems/{pid}/submit",
        json={"language_key": "cpp17", "source_code": src},
        headers=_idem(hs, key),
    )
    assert replay.status_code == 202 and replay.json() == body
    busy = await client.post(
        f"{P}/coding/problems/{pid}/submit",
        json={"language_key": "cpp17", "source_code": src},
        headers=_idem(hs),
    )
    assert busy.status_code == 409 and busy.json()["code"] == "submission_in_flight"

    # judge worker on Firestore: highest priority first (submit before run)
    done = await worker.process_pending(fake_judge)
    sid, rid = body["submission_id"], run.json()["submission_id"]
    assert list(map(str, done)) == [sid, rid]
    assert done[uuid.UUID(sid)] == "PARTIAL" and done[uuid.UUID(rid)] == "AC"
    assert await worker.process_pending(fake_judge) == {}
    assert any(HIDDEN_INPUT in j.stdin for j in fake_judge.submitted)  # hidden decrypted for the judge

    view = await client.get(f"{P}/coding/submissions/{sid}", headers=hs)
    assert view.status_code == 200, view.text
    v = view.json()
    assert v["status"] == "completed" and v["verdict"] == "PARTIAL"
    assert v["passed_cases"] == 2 and v["total_cases"] == 3 and v["score"] == 2.0 and v["max_score"] == 3.0
    assert v["source_code"] is None and v["completed_at"]
    sample, *hidden = v["cases"]
    assert (
        sample["is_sample"] is True and sample["input"] == "3\n1 2 3\n" and sample["expected_output"] == "6\n"
    )
    assert [c["verdict"] for c in hidden] == ["AC", "WA"]
    assert all(set(c) == {"ordinal", "is_sample", "verdict", "time_ms", "memory_kb"} for c in hidden)
    rv = (await client.get(f"{P}/coding/submissions/{rid}", headers=hs)).json()
    assert rv["verdict"] == "AC" and rv["score"] is None
    assert [c.get("is_custom") for c in rv["cases"]] == [False, True]
    assert rv["cases"][1]["input"] == "7\n" and rv["cases"][1]["expected_output"] is None
    _no_hidden(view.text, sub.text)

    # another learner: not found; history and listing status
    assert (await client.get(f"{P}/coding/submissions/{sid}", headers=other)).status_code == 404
    hist = await client.get(f"{P}/me/coding/submissions", params={"problem_id": pid}, headers=hs)
    assert [x["submission_id"] for x in hist.json()["data"]] == [sid, rid]
    page1 = await client.get(f"{P}/me/coding/submissions", params={"limit": 1}, headers=hs)
    assert [x["submission_id"] for x in page1.json()["data"]] == [sid]
    page2 = await client.get(
        f"{P}/me/coding/submissions",
        params={"limit": 1, "cursor": page1.json()["meta"]["next_cursor"]},
        headers=hs,
    )
    assert [x["submission_id"] for x in page2.json()["data"]] == [rid]
    only_submit = await client.get(f"{P}/me/coding/submissions", params={"mode": "submit"}, headers=hs)
    assert [x["submission_id"] for x in only_submit.json()["data"]] == [sid]
    lst2 = await client.get(f"{P}/coding/problems", headers=hs)
    assert lst2.json()["data"][0]["status"] == "attempted"

    # outbox: one submission.judged event per judged submission
    from app.core.firestore.core_store import OUTBOX
    from app.core.firestore.store import ScopedStore

    events = [
        d.data
        for d in await ScopedStore.system("test.read").scan(OUTBOX)
        if d.data["event_type"] == "submission.judged"
    ]
    payloads = [json.loads(e["payload_json"]) if "payload_json" in e else e["payload"] for e in events]
    assert sorted(x["submission_id"] for x in payloads) == sorted([sid, rid])
    assert {x["verdict"] for x in payloads} == {"PARTIAL", "AC"}

    # staff view with the permission: source included, audited
    staff_view = await client.get(f"{P}/coding/submissions/{sid}", headers=reviewer)
    assert staff_view.status_code == 200 and staff_view.json()["source_code"] == src

    # versioning: a limit change after publish creates version 2 with the cases copied
    patch = await client.patch(
        f"{P}/studio/coding/problems/{pid}", json={"time_limit_ms": 1500}, headers=author
    )
    assert patch.status_code == 200 and patch.json()["version_no"] == 2, patch.text
    cases = await client.get(f"{P}/studio/coding/problems/{pid}/test-cases", headers=author)
    assert cases.json()["problem_version"] == 2 and [c["ordinal"] for c in cases.json()["data"]] == [1, 2, 3]
    stale = await client.get(f"{P}/studio/coding/problems/{pid}/validation", headers=author)
    assert stale.json()["is_current"] is False
    nochange = await client.patch(
        f"{P}/studio/coding/problems/{pid}", json={"title": "Sum of numbers"}, headers=author
    )
    assert nochange.json()["version_no"] == 2
    add = await client.post(
        f"{P}/studio/coding/problems/{pid}/test-cases",
        json={"kind": "sample", "input": "1\n5\n", "expected_output": "5\n"},
        headers=author,
    )
    assert add.status_code == 201 and add.json()["problem_version"] == 3 and add.json()["ordinal"] == 4


async def test_hidden_content_tokens_and_erasure(
    fs_http: Any,  # noqa: F811
    make_principal: Any,
    fake_judge: Any,
    access: Any,
) -> None:
    from app.core.db import NO_POSTGRES
    from app.modules.coding import privacy, worker
    from app.modules.coding.repo_firestore import system_repo

    client, _rec, auth = fs_http
    await seed_languages()
    _a, author = _staff(make_principal, auth)
    _r, reviewer = _staff(make_principal, auth)
    pid = await _author_problem(client, author, reviewer, "hidden-io")
    cases = (await client.get(f"{P}/studio/coding/problems/{pid}/test-cases", headers=author)).json()["data"]
    hidden_id = cases[1]["test_case_id"]

    short = await client.get(
        f"{P}/studio/coding/test-cases/{hidden_id}/content", params={"reason": "short"}, headers=author
    )
    assert short.status_code == 400
    sample = await client.get(
        f"{P}/studio/coding/test-cases/{cases[0]['test_case_id']}/content",
        params={"reason": "checking the sample case"},
        headers=author,
    )
    assert sample.status_code == 400
    tok = await client.get(
        f"{P}/studio/coding/test-cases/{hidden_id}/content",
        params={"reason": "learner reported a wrong expected output"},
        headers=author,
    )
    assert tok.status_code == 200, tok.text
    assert tok.headers["cache-control"] == "no-store"
    _no_hidden(tok.text)
    # the token is bound to its requester
    stranger = await client.get(tok.json()["input_url"], headers=reviewer)
    assert stranger.status_code == 404
    dl = await client.get(tok.json()["input_url"], headers=author)
    assert dl.status_code == 200 and dl.text == f"0{HIDDEN_INPUT}"
    assert (await client.get(tok.json()["input_url"], headers=author)).status_code == 404  # single use
    # two concurrent redeems of the other part: exactly one succeeds
    both = await asyncio.gather(*[client.get(tok.json()["expected_url"], headers=author) for _ in range(2)])
    assert sorted(r.status_code for r in both) == [200, 404]
    assert next(r for r in both if r.status_code == 200).text == f"0{HIDDEN_EXPECTED}"

    # learner activity, then erasure
    student = make_principal(is_minor=False)
    hs = auth.login(student)
    await client.put(
        f"{P}/coding/problems/{pid}/drafts/python3", json={"source_code": "print(9)"}, headers=hs
    )
    r1 = await client.post(
        f"{P}/coding/problems/{pid}/run",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\nprint(6)", "custom_input": "1"},
        headers=_idem(hs),
    )
    assert r1.status_code == 202, r1.text
    await worker.process_pending(fake_judge)
    out = await privacy.erase_user(NO_POSTGRES, student.user_id)  # type: ignore[arg-type]
    assert out == {"coding_drafts_deleted": 1, "code_submissions_cleared": 1, "submission_outputs_cleared": 2}
    assert await privacy.erase_user(NO_POSTGRES, student.user_id) == {  # type: ignore[arg-type]
        "coding_drafts_deleted": 0,
        "code_submissions_cleared": 0,
        "submission_outputs_cleared": 0,
    }
    s = await system_repo("test.read").get_submission(uuid.UUID(r1.json()["submission_id"]))
    assert s.source_code == privacy.ERASED and s.custom_input is None and s.normalized_sha256 is None
    assert s.verdict == "AC"  # verdicts are kept
    assert (await client.get(f"{P}/coding/problems/{pid}/drafts/python3", headers=hs)).status_code == 404
    view = (await client.get(f"{P}/coding/submissions/{r1.json()['submission_id']}", headers=hs)).json()
    assert all(c.get("stdout_excerpt") is None for c in view["cases"])


async def test_concurrent_submits_take_the_request_lock(
    fs_http: Any,  # noqa: F811
    make_principal: Any,
    fake_judge: Any,
    access: Any,
) -> None:
    """``pg_advisory_xact_lock(coding.submit:user)`` -> request lock: of 3 concurrent submits with
    different keys exactly one is accepted, the others see it in flight."""
    client, _rec, auth = fs_http
    await seed_languages()
    _a, author = _staff(make_principal, auth)
    _r, reviewer = _staff(make_principal, auth)
    pid = await _author_problem(client, author, reviewer, "lock-test")
    hs = auth.login(make_principal(is_minor=False))
    rs = await asyncio.gather(
        *[
            client.post(
                f"{P}/coding/problems/{pid}/submit",
                json={"language_key": "python3", "source_code": f"# FAKE_VERDICT: AC\n#{i}"},
                headers=_idem(hs),
            )
            for i in range(3)
        ]
    )
    codes = sorted(r.status_code for r in rs)
    assert codes == [202, 409, 409], [r.text for r in rs]
    assert all(r.json()["code"] == "submission_in_flight" for r in rs if r.status_code == 409)
