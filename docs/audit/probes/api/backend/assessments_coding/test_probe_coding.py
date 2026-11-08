"""Audit probes for coding (Phase A). Assertions encode EXPECTED behaviour; failure = finding."""

from __future__ import annotations

import uuid

from app.core.db import system_context
from app.modules.coding.worker import judge_submission
from tests.coding.conftest import idem, seed_problem
from tests.identity.factory import make_org

SECRETS = ("SECRET_HIDDEN_INPUT", "SECRET_HIDDEN_EXPECTED", "424242")


async def test_probe_draft_save_without_entitlement(client, db, actors, access) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    access.allow = False
    r = await client.put(
        f"/api/v1/coding/problems/{p.id}/drafts/python3",
        json={"source_code": "print(1)"},
        headers=st.headers,
    )
    print("DRAFT unentitled", r.status_code, r.text[:150])
    assert r.status_code == 403


async def test_probe_attempt_submit_other_users_attempt(client, db, actors, access) -> None:
    from app.modules.coding import service

    print("validator registered:", service._attempt_validator is not None)
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "python3", "source_code": "x", "attempt_id": str(uuid.uuid4())},
        headers=idem(st.headers),
    )
    print("SUBMIT foreign attempt", r.status_code, r.text[:200])
    assert r.status_code in (404, 409)


async def test_probe_pagination_limits_and_cursor(client, db, actors, access) -> None:
    st = await actors()
    r = await client.get("/api/v1/coding/problems?limit=1000", headers=st.headers)
    print("LIMIT 1000", r.status_code, r.headers.get("content-type"))
    assert r.status_code == 400 and "problem+json" in r.headers["content-type"]
    r = await client.get("/api/v1/coding/problems?cursor=garbage", headers=st.headers)
    print("BAD CURSOR", r.status_code, r.json().get("code"))
    assert r.status_code == 400 and r.json()["code"] == "invalid_cursor"


async def test_probe_org_private_problem_visible_to_outsider(client, db, actors, access, fake_judge) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    org = await make_org(db, "Private College")
    await system_context(db, "test.factory")
    p.organization_id = org
    await db.flush()
    outsider = await actors()  # no org membership
    r = await client.get(f"/api/v1/coding/problems/{p.slug}", headers=outsider.headers)
    print("ORG-PRIVATE detail for outsider", r.status_code)
    lst = (await client.get("/api/v1/coding/problems?limit=100", headers=outsider.headers)).json()["data"]
    print("in listing:", any(i["problem_id"] == str(p.id) for i in lst))
    assert r.status_code == 404


async def test_probe_hidden_never_in_submit_view(client, db, actors, access, fake_judge) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC,WA,AC\n"},
        headers=idem(st.headers),
    )
    sid = r.json()["submission_id"]
    await judge_submission(db, uuid.UUID(sid), fake_judge, budget_s=1)
    g = await client.get(f"/api/v1/coding/submissions/{sid}", headers=st.headers)
    h = await client.get("/api/v1/me/coding/submissions", headers=st.headers)
    d = await client.get(f"/api/v1/coding/problems/{p.slug}", headers=st.headers)
    for t in (r.text, g.text, h.text, d.text):
        for s in SECRETS:
            assert s not in t
    print("SUBMIT VIEW hidden cases:", [c for c in g.json()["cases"] if not c["is_sample"]])


async def test_probe_submission_org_attribution_multi_org(client, db, actors, access, fake_judge) -> None:
    """code_submissions.organization_id = principal.org_ids[0] only when exactly one org; else NULL
    -> a student in two colleges is invisible to both colleges' staff (scope_for(None) = platform)."""
    author = await actors()
    p = await seed_problem(db, author.id)
    o1, o2 = await make_org(db, "C1"), await make_org(db, "C2")
    st = await actors(org_ids=(o1, o2))
    r = await client.post(
        f"/api/v1/coding/problems/{p.id}/submit",
        json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\n"},
        headers=idem(st.headers),
    )
    from app.modules.coding.models import CodeSubmission

    await system_context(db, "test")
    sub = await db.get(CodeSubmission, uuid.UUID(r.json()["submission_id"]))
    print("multi-org submission organization_id:", sub.organization_id)
    assert sub.organization_id is not None
