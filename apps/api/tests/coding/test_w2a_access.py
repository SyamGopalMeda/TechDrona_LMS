"""Wave-2 (w2a) coding fixes: COD-03 by problem id, in-attempt access without a standalone
entitlement, and batch-scoped ``submission.code.read`` for trainers (own batches only)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.core import auth as core_auth
from app.core.errors import ProblemError
from app.core.ids import uuid7
from app.core.principal import Principal, RoleGrant
from app.modules.coding import service
from app.modules.rbac.service import RbacPermissionChecker
from tests.coding.conftest import idem, seed_problem
from tests.identity.factory import add_member, company_org, make_batch, make_user


@pytest.fixture
def attempt_validator() -> Any:
    """Stand-in for assessments' validator: only (ATTEMPT, problem in ``allowed``) passes."""
    state: dict[str, Any] = {"attempt": uuid7(), "problems": set()}

    async def _v(session: Any, principal: Any, attempt_id: uuid.UUID, problem_id: uuid.UUID) -> None:
        if attempt_id != state["attempt"]:
            raise ProblemError("not_found")
        if problem_id not in state["problems"]:
            raise ProblemError("not_found", detail="This coding problem is not part of your attempt.")

    prev = service._attempt_validator
    service.register_attempt_validator(_v)
    yield state
    service.register_attempt_validator(prev)


async def test_get_problem_by_id_or_slug(client, db, actors, access) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    st = await actors()
    by_id = await client.get(f"/api/v1/coding/problems/{p.id}", headers=st.headers)
    by_slug = await client.get(f"/api/v1/coding/problems/{p.slug}", headers=st.headers)
    assert by_id.status_code == 200, by_id.text
    assert by_id.json()["problem_id"] == by_slug.json()["problem_id"] == str(p.id)
    assert (await client.get(f"/api/v1/coding/problems/{uuid7()}", headers=st.headers)).status_code == 404


async def test_in_attempt_access_without_entitlement(
    client, db, actors, access, attempt_validator, fake_judge
) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    other = await seed_problem(db, author.id)
    attempt_validator["problems"].add(p.id)
    att = attempt_validator["attempt"]
    st = await actors()
    access.allow = False

    url = f"/api/v1/coding/problems/{p.id}"
    assert (await client.get(url, headers=st.headers)).status_code == 403
    r = await client.get(url, params={"attempt_id": str(att)}, headers=st.headers)
    assert r.status_code == 200, r.text
    # problem not in the attempt / foreign attempt -> still denied
    assert (
        await client.get(
            f"/api/v1/coding/problems/{other.id}", params={"attempt_id": str(att)}, headers=st.headers
        )
    ).status_code == 404
    assert (await client.get(url, params={"attempt_id": str(uuid7())}, headers=st.headers)).status_code == 404

    d = f"{url}/drafts/python3"
    assert (await client.put(d, json={"source_code": "x"}, headers=st.headers)).status_code == 403
    r = await client.put(d, params={"attempt_id": str(att)}, json={"source_code": "x"}, headers=st.headers)
    assert r.status_code == 200, r.text
    assert (await client.get(d, params={"attempt_id": str(att)}, headers=st.headers)).status_code == 200

    body = {"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\n"}
    assert (await client.post(f"{url}/run", json=body, headers=idem(st.headers))).status_code == 403
    r = await client.post(f"{url}/run", json={**body, "attempt_id": str(att)}, headers=idem(st.headers))
    assert r.status_code == 202, r.text


async def test_batch_trainer_reads_own_batch_submissions_only(
    client, db, auth, actors, access, fake_judge
) -> None:
    author = await actors()
    p = await seed_problem(db, author.id)
    org = company_org()
    creator = await make_user(db)
    b_mine = await make_batch(db, org, creator.id)
    b_other = await make_batch(db, org, creator.id)

    async def learner(batch: uuid.UUID) -> str:
        st = await actors(org_ids=(org,))
        await add_member(db, org, st.id, batch_id=batch)
        r = await client.post(
            f"/api/v1/coding/problems/{p.id}/submit",
            json={"language_key": "python3", "source_code": "# FAKE_VERDICT: AC\n"},
            headers=idem(st.headers),
        )
        assert r.status_code == 202, r.text
        return r.json()["submission_id"]

    mine, theirs = await learner(b_mine), await learner(b_other)
    tu = await make_user(db)
    trainer = Principal(
        user_id=tu.id, session_id=uuid7(), org_ids=(org,), grants=(RoleGrant("trainer", "batch", b_mine),)
    )
    headers = auth.login(trainer)
    prev = core_auth._permission_checker
    core_auth.register_permission_checker(RbacPermissionChecker())
    try:
        ok = await client.get(f"/api/v1/coding/submissions/{mine}", headers=headers)
        assert ok.status_code == 200, ok.text
        assert ok.json()["source_code"] is not None
        assert (await client.get(f"/api/v1/coding/submissions/{theirs}", headers=headers)).status_code == 404
    finally:
        core_auth.register_permission_checker(prev)


async def test_studio_published_problems_picker_for_test_authors(client, db, actors) -> None:
    """w3be (w3web request 2): COD-24 ``GET /studio/coding/problems/published`` lists published
    problems (metadata only) to anyone who can author tests; drafts are excluded; callers
    without ``test.create`` get 403. The route does not shadow ``/studio/coding/problems/{id}``."""
    author = await actors()
    pub = await seed_problem(db, author.id, slug=f"pick-{uuid.uuid4().hex[:8]}")
    draft = await seed_problem(db, author.id, slug=f"pickd-{uuid.uuid4().hex[:8]}", publish=False)
    builder = await actors("test.create")
    url = "/api/v1/studio/coding/problems/published"
    r = await client.get(url, params={"q": pub.slug, "limit": 100}, headers=builder.headers)
    assert r.status_code == 200, r.text
    rows = r.json()["data"]
    assert [x["problem_id"] for x in rows] == [str(pub.id)]
    assert set(rows[0]) == {"problem_id", "slug", "title", "difficulty", "version_no", "organization_id"}
    r = await client.get(url, params={"q": draft.slug}, headers=builder.headers)
    assert r.status_code == 200 and r.json()["data"] == []
    nobody = await actors()
    r = await client.get(url, headers=nobody.headers)
    assert r.status_code == 403 and r.json()["code"] == "permission_denied"
