"""Problem authoring: permissions, hidden-case protection, versioning, publish rules."""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import system_context
from app.modules.coding.models import CodingProblem, CodingTestCase
from tests.coding.conftest import HIDDEN_EXPECTED, HIDDEN_INPUT

MANAGE = "coding_problem.manage"
HIDDEN = "coding_test_case.hidden.read"
PROBLEM = {
    "slug": "reverse-words",
    "title": "Reverse the words",
    "statement_md": "Reverse the order of words in a line.",
    "difficulty": 2,
    "time_limit_ms": 1000,
    "allowed_languages": ["python3", "cpp17"],
}


async def test_studio_flow_with_hidden_protection_and_versioning(client, db, actors, fake_judge) -> None:
    author = await actors(MANAGE, HIDDEN, is_platform=True)
    reviewer = await actors(MANAGE, is_platform=True)

    r = await client.post("/api/v1/studio/coding/problems", json=PROBLEM, headers=author.headers)
    assert r.status_code == 201, r.text
    p = r.json()
    pid = p["problem_id"]
    assert p["status"] == "draft" and p["version_no"] == 1 and p["limits"]["wall_limit_ms"] == 3000

    dup = await client.post("/api/v1/studio/coding/problems", json=PROBLEM, headers=author.headers)
    assert dup.status_code == 400 and dup.json()["code"] == "validation_failed"

    base = f"/api/v1/studio/coding/problems/{pid}"
    s = await client.post(
        f"{base}/test-cases",
        json={"kind": "sample", "input": "a b\n", "expected_output": "b a\n"},
        headers=author.headers,
    )
    assert s.status_code == 201, s.text
    # Reviewer lacks coding_test_case.hidden.read -> cannot add hidden cases.
    denied = await client.post(
        f"{base}/test-cases",
        json={"kind": "hidden", "input": HIDDEN_INPUT, "expected_output": HIDDEN_EXPECTED},
        headers=reviewer.headers,
    )
    assert denied.status_code == 403 and denied.json()["permission"] == HIDDEN
    h = await client.post(
        f"{base}/test-cases",
        json={"kind": "hidden", "input": HIDDEN_INPUT, "expected_output": HIDDEN_EXPECTED, "weight": "5"},
        headers=author.headers,
    )
    assert h.status_code == 201, h.text
    assert set(h.json()) == {
        "test_case_id",
        "ordinal",
        "is_sample",
        "weight",
        "size_bytes",
        "input_sha256",
        "expected_sha256",
        "problem_version",
    }

    listed = await client.get(f"{base}/test-cases", headers=reviewer.headers)
    assert listed.status_code == 200
    data = listed.json()["data"]
    assert data[0]["input"] == "a b\n" and data[1]["is_sample"] is False and data[1]["weight"] == 5.0
    assert "input" not in data[1] and "expected_output" not in data[1]
    for resp in (h, listed):
        assert "SECRET_HIDDEN" not in resp.text and "424242" not in resp.text

    # Separation of duties: the author cannot publish a platform problem.
    # COD-18: publish requires a passing validation of the current case set.
    unvalidated = await client.post(f"{base}/publish", headers=reviewer.headers)
    assert unvalidated.status_code == 409 and unvalidated.json()["reason"] == "validation_required"
    val = await client.post(
        f"{base}/validate",
        json={"reference_solutions": [{"language_key": "python3", "source_code": "# FAKE_VERDICT: AC"}]},
        headers=author.headers,
    )
    assert val.status_code == 200 and val.json()["status"] == "passed", val.text
    sod = await client.post(f"{base}/publish", headers=author.headers)
    assert sod.status_code == 403 and sod.json()["code"] == "sod_violation"
    pub = await client.post(f"{base}/publish", headers=reviewer.headers)
    assert pub.status_code == 200 and pub.json()["status"] == "published"
    again = await client.post(f"{base}/publish", headers=reviewer.headers)
    assert again.status_code == 409

    # Draft edits are in place; after publish, limit/case changes create a new version.
    patched = await client.patch(base, json={"title": "Reverse words"}, headers=author.headers)
    assert patched.json()["version_no"] == 1
    patched = await client.patch(base, json={"time_limit_ms": 1500}, headers=author.headers)
    assert patched.status_code == 200 and patched.json()["version_no"] == 2
    bad = await client.patch(
        base, json={"time_limit_ms": 4000, "wall_limit_ms": 3000}, headers=author.headers
    )
    assert bad.status_code == 400
    add = await client.post(
        f"{base}/test-cases",
        json={"kind": "sample", "input": "x\n", "expected_output": "x\n"},
        headers=author.headers,
    )
    assert add.json()["problem_version"] == 3 and add.json()["ordinal"] == 3

    await system_context(db, "test.check")
    rows = (
        await db.execute(
            select(CodingTestCase.problem_version, CodingTestCase.ordinal).where(
                CodingTestCase.coding_problem_id == CodingProblem.id, CodingProblem.slug == "reverse-words"
            )
        )
    ).all()
    versions = sorted(rows)
    assert versions == [(1, 1), (1, 2), (2, 1), (2, 2), (3, 1), (3, 2), (3, 3)]


async def test_studio_permission_denials(client, db, actors) -> None:
    student = await actors()
    r = await client.post("/api/v1/studio/coding/problems", json=PROBLEM, headers=student.headers)
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"
    author = await actors(MANAGE, is_platform=True)
    r = await client.post(
        "/api/v1/studio/coding/problems", json={**PROBLEM, "slug": "denials-1"}, headers=author.headers
    )
    pid = r.json()["problem_id"]
    for call in (
        client.get(f"/api/v1/studio/coding/problems/{pid}/test-cases", headers=student.headers),
        client.patch(
            f"/api/v1/studio/coding/problems/{pid}", json={"title": "Hacked title"}, headers=student.headers
        ),
        client.post(f"/api/v1/studio/coding/problems/{pid}/publish", headers=student.headers),
    ):
        resp = await call
        assert resp.status_code in (403, 404), resp.text
    bad_lang = await client.post(
        "/api/v1/studio/coding/problems",
        json={**PROBLEM, "slug": "denials-2", "allowed_languages": ["cobol"]},
        headers=author.headers,
    )
    assert bad_lang.status_code == 400
    publish_empty = await client.post(
        f"/api/v1/studio/coding/problems/{pid}/publish",
        headers=(await actors(MANAGE, is_platform=True)).headers,
    )
    assert publish_empty.status_code == 409


async def test_languages_listing(client, db, actors) -> None:
    st = await actors()
    r = await client.get("/api/v1/coding/languages", headers=st.headers)
    assert r.status_code == 200
    keys = {x["language_key"] for x in r.json()["data"]}
    assert {"c", "cpp17", "java17", "python3"} <= keys
