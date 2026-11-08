"""COD-04/05 drafts, COD-18 validate (+ publish gate), COD-17 audited hidden-case content."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import select, update

from app.core.db import system_context
from app.core.time import utcnow
from app.modules.coding.models import CodingDraft, CodingTestCase, CodingTestCaseContentToken
from tests.coding.conftest import HIDDEN_EXPECTED, HIDDEN_INPUT, seed_problem
from tests.identity.factory import company_org

MANAGE = "coding_problem.manage"
HIDDEN = "coding_test_case.hidden.read"
AC = "# FAKE_VERDICT: AC\nprint(sum(map(int, input().split())))\n"


@pytest.fixture
def audited(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Spy on ``audit()`` in the coding router (td_app cannot read audit_outbox)."""
    import app.modules.coding.router as cr

    calls: list[tuple[str, dict[str, Any]]] = []
    real = cr.audit

    async def spy(session: Any, actor: Any, action: str, *a: Any, **kw: Any) -> Any:
        calls.append((action, kw))
        return await real(session, actor, action, *a, **kw)

    monkeypatch.setattr(cr, "audit", spy)
    return calls


def _no_secrets(text: str) -> None:
    assert "SECRET_HIDDEN" not in text and "424242" not in text


# --------------------------------------------------------------------------- drafts


async def test_drafts_owner_only_size_and_rate_limit(client, db, actors, access) -> None:
    # `access` (allow): drafts now require the same entitlement as run/submit (audit BE-20).
    author = await actors()
    p = await seed_problem(db, author.id)
    me = await actors()
    other = await actors()
    url = f"/api/v1/coding/problems/{p.id}/drafts/python3"

    assert (await client.get(url, headers=me.headers)).status_code == 404
    r = await client.put(url, json={"source_code": "print(1)\n"}, headers=me.headers)
    assert r.status_code == 200, r.text
    assert r.json()["source_code"] == "print(1)\n" and r.json()["language_key"] == "python3"
    r = await client.put(url, json={"source_code": "print(2)\n"}, headers=me.headers)
    got = await client.get(url, headers=me.headers)
    assert got.status_code == 200 and got.json()["source_code"] == "print(2)\n"

    # Owner only: another user sees nothing (RLS O), and their save is a separate row.
    assert (await client.get(url, headers=other.headers)).status_code == 404
    await client.put(url, json={"source_code": "mine\n"}, headers=other.headers)
    assert (await client.get(url, headers=me.headers)).json()["source_code"] == "print(2)\n"

    too_big = await client.put(url, json={"source_code": "x" * (64 * 1024 + 1)}, headers=me.headers)
    assert too_big.status_code == 413 and too_big.json()["code"] == "payload_too_large"
    bad_lang = await client.put(
        f"/api/v1/coding/problems/{p.id}/drafts/cobol", json={"source_code": "x"}, headers=me.headers
    )
    assert bad_lang.status_code == 422 and bad_lang.json()["code"] == "language_not_allowed"
    unpublished = await seed_problem(db, author.id, publish=False)
    r = await client.put(
        f"/api/v1/coding/problems/{unpublished.id}/drafts/python3",
        json={"source_code": "x"},
        headers=me.headers,
    )
    assert r.status_code == 404

    # 20/min: 2 saves so far in the window.
    for i in range(18):
        r = await client.put(url, json={"source_code": f"v{i}"}, headers=me.headers)
        assert r.status_code == 200, (i, r.text)
    limited = await client.put(url, json={"source_code": "one too many"}, headers=me.headers)
    assert limited.status_code == 429 and limited.headers["Retry-After"] == "60"
    # Window rolls over after a minute.
    await system_context(db, "test.clock")
    await db.execute(
        update(CodingDraft)
        .where(CodingDraft.user_id == me.id)
        .values(window_started_at=utcnow() - timedelta(seconds=61))
    )
    r = await client.put(url, json={"source_code": "after window"}, headers=me.headers)
    assert r.status_code == 200


async def test_drafts_restricted_principal_denied(client, db, actors) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    restricted = await actors(scope="restricted", restriction_level=2)
    r = await client.put(
        f"/api/v1/coding/problems/{p.id}/drafts/python3",
        json={"source_code": "x"},
        headers=restricted.headers,
    )
    assert r.status_code == 403 and r.json()["code"] == "account_restricted"


# --------------------------------------------------------------------------- validate + publish gate


async def test_validate_runs_all_cases_and_gates_publish(client, db, actors, fake_judge, audited) -> None:
    author = await actors(MANAGE, HIDDEN, is_platform=True)
    reviewer = await actors(MANAGE, is_platform=True)
    p = await seed_problem(db, author.id, hidden=2, publish=False)
    base = f"/api/v1/studio/coding/problems/{p.id}"

    none = await client.post(f"{base}/validate", headers=author.headers)
    assert none.status_code == 409 and none.json()["reason"] == "no_reference_solution"
    assert (await client.get(f"{base}/validation", headers=author.headers)).status_code == 404

    # A wrong reference solution fails validation; publish stays blocked.
    bad = await client.post(
        f"{base}/validate",
        json={"reference_solutions": [{"language_key": "python3", "source_code": "# FAKE_VERDICT: AC,WA"}]},
        headers=author.headers,
    )
    assert bad.status_code == 200, bad.text
    body = bad.json()
    assert body["status"] == "failed" and body["is_current"] is True
    sol = body["solutions"][0]
    assert sol["verdict"] == "WA" and sol["passed_cases"] == 1 and sol["total_cases"] == 3
    blocked = await client.post(f"{base}/publish", headers=reviewer.headers)
    assert blocked.status_code == 409 and blocked.json()["reason"] == "validation_required"

    put = await client.put(
        f"{base}/reference-solutions/python3", json={"source_code": AC}, headers=author.headers
    )
    assert put.status_code == 200 and "source_code" not in put.json()
    listed = await client.get(f"{base}/reference-solutions", headers=reviewer.headers)
    assert listed.json()["data"][0]["source_code"] == AC

    ok = await client.post(f"{base}/validate", headers=author.headers)
    assert ok.status_code == 200 and ok.json()["status"] == "passed", ok.text
    cases = ok.json()["solutions"][0]["cases"]
    assert [c["is_sample"] for c in cases] == [True, False, False]
    for c in cases:
        assert set(c) == {"ordinal", "is_sample", "verdict", "time_ms", "memory_kb"}
    _no_secrets(ok.text)
    # Every case (samples AND hidden) went to the judge with the decrypted hidden input.
    sent = [j.stdin for j in fake_judge.submitted[-3:]]
    assert sent[0] == "3\n1 2 3\n" and sent[1] == f"0{HIDDEN_INPUT}" and sent[2] == f"1{HIDDEN_INPUT}"
    assert ("coding.problem.validated",) == tuple(a for a, _ in audited if a == "coding.problem.validated")[
        :1
    ]

    latest = await client.get(f"{base}/validation", headers=reviewer.headers)
    assert latest.status_code == 200 and latest.json()["is_current"] is True
    _no_secrets(latest.text)

    # Changing the case set makes the validation stale (draft: no version bump).
    add = await client.post(
        f"{base}/test-cases",
        json={"kind": "hidden", "input": HIDDEN_INPUT, "expected_output": HIDDEN_EXPECTED},
        headers=author.headers,
    )
    assert add.status_code == 201
    stale = await client.get(f"{base}/validation", headers=author.headers)
    assert stale.json()["is_current"] is False
    blocked = await client.post(f"{base}/publish", headers=reviewer.headers)
    assert blocked.status_code == 409 and blocked.json()["reason"] == "validation_required"

    again = await client.post(f"{base}/validate", headers=author.headers)
    assert again.json()["status"] == "passed" and again.json()["solutions"][0]["total_cases"] == 4
    pub = await client.post(f"{base}/publish", headers=reviewer.headers)
    assert pub.status_code == 200 and pub.json()["status"] == "published"


async def test_validate_denials_and_rate_limit(client, db, actors, fake_judge) -> None:
    author = await actors(MANAGE, is_platform=True)
    p = await seed_problem(db, author.id, publish=False)
    base = f"/api/v1/studio/coding/problems/{p.id}"
    student = await actors()
    for call in (
        client.post(f"{base}/validate", headers=student.headers),
        client.get(f"{base}/validation", headers=student.headers),
        client.get(f"{base}/reference-solutions", headers=student.headers),
        client.put(f"{base}/reference-solutions/python3", json={"source_code": AC}, headers=student.headers),
    ):
        r = await call
        assert r.status_code == 403 and r.json()["code"] == "permission_denied", r.text

    # Cross-tenant: a company problem is invisible to a manager outside the company (single
    # company: the only other tenant is "no organization"; RLS -> 404).
    org_a = company_org()
    a_author = await actors(MANAGE, org_ids=(org_a,))
    b_manager = await actors(MANAGE, org_ids=())
    from app.core.principal import Principal
    from app.modules.coding import service
    from app.modules.coding.schemas import ProblemCreateIn

    await system_context(db, "test.factory")
    org_problem = await service.create_problem(
        db,
        Principal(user_id=a_author.id, session_id=a_author.principal.session_id),
        ProblemCreateIn(
            slug="org-a-only", title="Org A problem", statement_md="x", difficulty=1, organization_id=org_a
        ),
    )
    r = await client.post(
        f"/api/v1/studio/coding/problems/{org_problem.id}/validate", headers=b_manager.headers
    )
    assert r.status_code == 404

    bad = await client.post(
        f"{base}/validate",
        json={"reference_solutions": [{"language_key": "cobol", "source_code": "x"}]},
        headers=author.headers,
    )
    assert bad.status_code == 422
    extra = await client.post(f"{base}/validate", json={"unknown": 1}, headers=author.headers)
    assert extra.status_code == 400

    await client.put(f"{base}/reference-solutions/python3", json={"source_code": AC}, headers=author.headers)
    for _ in range(10):
        assert (await client.post(f"{base}/validate", headers=author.headers)).status_code == 200
    limited = await client.post(f"{base}/validate", headers=author.headers)
    assert limited.status_code == 429


# --------------------------------------------------------------------------- hidden content (COD-17)


async def _hidden_case(db, problem_id) -> CodingTestCase:
    await system_context(db, "test.check")
    return (
        (
            await db.execute(
                select(CodingTestCase)
                .where(CodingTestCase.coding_problem_id == problem_id, CodingTestCase.is_hidden.is_(True))
                .order_by(CodingTestCase.ordinal)
            )
        )
        .scalars()
        .first()
    )


async def test_hidden_content_step_up_reason_audit_and_single_use(client, db, actors, audited) -> None:
    owner = await actors(MANAGE, HIDDEN, is_platform=True)
    p = await seed_problem(db, owner.id, publish=False)
    case = await _hidden_case(db, p.id)
    url = f"/api/v1/studio/coding/test-cases/{case.id}/content"
    reason = "fixing reported issue CMS-013-482"

    stale = await actors(MANAGE, HIDDEN, is_platform=True)
    r = await client.get(url, params={"reason": reason}, headers=stale.headers)
    assert r.status_code == 401 and r.json()["code"] == "step_up_required"

    fresh = await actors(MANAGE, HIDDEN, is_platform=True, last_step_up_at=utcnow())
    short = await client.get(url, params={"reason": "because"}, headers=fresh.headers)
    assert short.status_code == 400 and short.json()["code"] == "validation_failed"
    missing = await client.get(url, headers=fresh.headers)
    assert missing.status_code == 400

    ok = await client.get(url, params={"reason": reason}, headers=fresh.headers)
    assert ok.status_code == 200, ok.text
    assert ok.headers["Cache-Control"] == "no-store"
    body = ok.json()
    assert set(body) >= {"input_url", "expected_url", "expires_at", "sha256"}
    assert body["sha256"]["input"] == case.input_sha256.hex()
    _no_secrets(ok.text)
    actions = [(a, kw) for a, kw in audited if a == "coding.testcase.read_hidden"]
    assert len(actions) == 1 and actions[0][1]["reason"] == reason

    # Token hashes only in the DB.
    await system_context(db, "test.check")
    toks = list((await db.execute(select(CodingTestCaseContentToken.token_hash))).scalars())
    assert all(len(t) == 32 for t in toks)
    raw = body["input_url"].rsplit("/", 1)[1]
    assert all(raw.encode() not in t for t in toks)

    # Another user cannot redeem the token.
    other = await actors(MANAGE, HIDDEN, is_platform=True, last_step_up_at=utcnow())
    assert (await client.get(body["input_url"], headers=other.headers)).status_code == 404

    dl = await client.get(body["input_url"], headers=fresh.headers)
    assert dl.status_code == 200 and dl.text == f"0{HIDDEN_INPUT}"
    assert dl.headers["Cache-Control"] == "no-store" and "attachment" in dl.headers["Content-Disposition"]
    exp = await client.get(body["expected_url"], headers=fresh.headers)
    assert exp.text == f"0{HIDDEN_EXPECTED}"
    # Single use.
    assert (await client.get(body["input_url"], headers=fresh.headers)).status_code == 404

    # Expired tokens are refused.
    again = (await client.get(url, params={"reason": reason}, headers=fresh.headers)).json()
    await system_context(db, "test.clock")
    await db.execute(update(CodingTestCaseContentToken).values(expires_at=utcnow() - timedelta(seconds=1)))
    assert (await client.get(again["input_url"], headers=fresh.headers)).status_code == 404


async def test_hidden_content_denials_and_rate_limit(client, db, actors) -> None:
    owner = await actors(MANAGE, HIDDEN, is_platform=True)
    p = await seed_problem(db, owner.id, publish=False)
    case = await _hidden_case(db, p.id)
    url = f"/api/v1/studio/coding/test-cases/{case.id}/content"
    params = {"reason": "investigating a learner dispute"}

    manager_only = await actors(MANAGE, is_platform=True, last_step_up_at=utcnow())
    r = await client.get(url, params=params, headers=manager_only.headers)
    assert r.status_code == 403 and r.json()["permission"] == HIDDEN
    student = await actors(last_step_up_at=utcnow())
    r = await client.get(url, params=params, headers=student.headers)
    assert r.status_code == 403
    restricted = await actors(HIDDEN, scope="restricted", restriction_level=2, last_step_up_at=utcnow())
    r = await client.get(url, params=params, headers=restricted.headers)
    assert r.status_code == 403 and r.json()["code"] == "account_restricted"

    # Sample cases are not served through COD-17.
    await system_context(db, "test.check")
    sample = (
        (
            await db.execute(
                select(CodingTestCase).where(
                    CodingTestCase.coding_problem_id == p.id, CodingTestCase.is_sample.is_(True)
                )
            )
        )
        .scalars()
        .first()
    )
    fresh = await actors(MANAGE, HIDDEN, is_platform=True, last_step_up_at=utcnow())
    r = await client.get(
        f"/api/v1/studio/coding/test-cases/{sample.id}/content", params=params, headers=fresh.headers
    )
    assert r.status_code == 400

    # Cross-tenant: the company's hidden case is invisible to staff outside the company.
    org_a = company_org()
    b_staff = await actors(MANAGE, HIDDEN, org_ids=(), last_step_up_at=utcnow())
    await system_context(db, "test.factory")
    await db.execute(
        update(CodingTestCase).where(CodingTestCase.coding_problem_id == p.id).values(organization_id=org_a)
    )
    from app.modules.coding.models import CodingProblem

    await db.execute(update(CodingProblem).where(CodingProblem.id == p.id).values(organization_id=org_a))
    r = await client.get(url, params=params, headers=b_staff.headers)
    assert r.status_code == 404

    # 30/hour per user.
    for _ in range(30):
        assert (await client.get(url, params=params, headers=fresh.headers)).status_code == 200
    limited = await client.get(url, params=params, headers=fresh.headers)
    assert limited.status_code == 429
