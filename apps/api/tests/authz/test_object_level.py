"""TS-AUTHZ object level (BOLA / cross-tenant, RPM TI-02, SCN-18): real org-A objects, probed
through every route of the route table whose path parameters can all be bound to them.

Org A holds a batch, an assignment with a learner submission, an org-private question, an
org-private published test with a running attempt and an org-private course. Principals of
org B (evaluator, trainer, learner — batch B) call every such route; none may get ``2xx``,
none may get ``5xx``, and no response body sent to them may contain an org-A identifier.

Single company (orgs_0003): "B" is a second batch of the company org, so this is the
cross-batch / cross-user check. Batch-bound objects (batch A, its assignment and submission,
learner A's attempt, learner A) must never be served to batch-B principals. Company-wide content
(the company question, test and course) is shared by design with every company staff member
(ADM-41: any batch trainer authors company courses and questions) and its definition is
readable; for those routes the check is: no 5xx, and no batch-A / learner-A identifier in any
body (the test's attempts, overrides and report are filtered to the caller's own batches).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest

from app.core.access import AccessDecision, get_access_checker, register_access_checker
from app.core.db import system_context
from app.core.ids import uuid7
from app.modules.learning.models import Assignment, AssignmentSubmission
from tests.authz.matrix import API, route_cases
from tests.catalog.factory import make_published_course
from tests.placement.world import World, build_world, question, topic


class _AllowAll:
    async def check(self, *a: Any, **kw: Any) -> AccessDecision:
        return AccessDecision(True, "entitlement")


@pytest.fixture
def rbac_auth(auth: Any) -> Iterator[Any]:
    from app.core import auth as core_auth
    from app.modules.rbac.service import RbacPermissionChecker, reset_role_permission_cache

    prev = core_auth._permission_checker
    prev_access = get_access_checker()
    reset_role_permission_cache()
    core_auth.register_permission_checker(RbacPermissionChecker())
    register_access_checker(_AllowAll())  # entitlements never mask the authorisation decision
    yield auth
    core_auth.register_permission_checker(prev)
    register_access_checker(prev_access)


async def _org_a_objects(db: Any, w: World, client: Any) -> dict[str, uuid.UUID]:
    from tests.assessments.test_attempts import assign, fixed, make_test, start

    student = w.personas["student"]
    await system_context(db, "test.factory")
    aid, sid = uuid7(), uuid7()
    db.add(
        Assignment(
            id=aid,
            organization_id=w.org_a,
            batch_id=w.batch_a,
            title="Org A worksheet",
            instructions_md="Do it.",
            submission_type="text",
            max_score=Decimal(10),
            allowed_file_types=["pdf"],
            created_by=w.personas["trainer_a"].id,
        )
    )
    await db.flush()
    db.add(
        AssignmentSubmission(
            id=sid,
            assignment_id=aid,
            user_id=student.id,
            organization_id=w.org_a,
            body_text="org A answer",
            status="submitted",
        )
    )
    await db.flush()
    t = await topic(db, "quant/percentages")
    q = await question(db, w.personas["author"], w.personas["reviewer"], t, org=w.org_a, stem="Org A only")
    test_id = await make_test(db, w, [("Quant", None, [fixed(q)])], duration_seconds=1800, org=w.org_a)
    await assign(db, w, test_id)
    r = await start(client, student, test_id)
    assert r.status_code == 201, r.text
    attempt_id = uuid.UUID(r.json()["attempt_id"])
    course = await make_published_course(db, w.personas["author"].id, org_id=w.org_a, visibility="private")
    return {
        "org_id": w.org_a,
        "batch_id": w.batch_a,
        "assignment_id": aid,
        "submission_id": sid,
        "question_id": q.question_id,
        "test_id": test_id,
        "attempt_id": attempt_id,
        "course_id": course.course_id,
        "user_id": student.id,
    }


def _report(probed: int, violations: list[str]) -> None:
    import json
    import os
    from pathlib import Path

    if d := os.environ.get("TD_AUTHZ_REPORT_DIR"):
        Path(d).mkdir(parents=True, exist_ok=True)
        (Path(d) / "object_level.json").write_text(json.dumps({"probes": probed, "violations": violations}))


async def test_org_b_principals_never_reach_org_a_objects(
    app: Any, client: Any, db: Any, rbac_auth: Any
) -> None:
    w = await build_world(db, rbac_auth)
    objs = await _org_a_objects(db, w, client)
    eval_b = await w.persona(
        "evaluator_b",
        grants=(("evaluator", "batch", w.batch_b),),
        org_ids=(w.org_b,),
        tier="staff",
    )
    outsiders = {
        "evaluator_b": eval_b.headers,
        "trainer_b": w.personas["trainer_b"].headers,
        "student_b": w.personas["student_b"].headers,
    }
    shared = {"org_id", "question_id", "test_id", "course_id"} if w.org_a == w.org_b else set()
    markers = {str(v) for k, v in objs.items() if k not in shared}
    probed = 0
    violations: list[str] = []
    for case in route_cases(app):
        names = [n for n, _ in case.path_params]
        if not names or not all(n in objs for n in names):
            continue
        company_wide = all(n in shared for n in names)
        url = case.path.format(**{n: str(objs[n]) for n in names})
        for who, headers in outsiders.items():
            kwargs: dict[str, Any] = {"headers": {**headers, "Idempotency-Key": uuid7().hex}}
            if case.method in ("POST", "PUT", "PATCH"):
                kwargs["json"] = {}
            r = await client.request(case.method, url, **kwargs)
            probed += 1
            where = f"{case} as {who}: {r.status_code} {r.text[:160]}"
            if r.status_code >= 500:
                violations.append(f"5xx {where}")
            elif 200 <= r.status_code < 300 and not company_wide:
                violations.append(f"cross-tenant 2xx {where}")
            elif any(m in r.text for m in markers - {url.rsplit("/", 1)[-1]} if m not in url):
                violations.append(f"org-A identifier echoed in error body {where}")
    _report(probed, violations)
    assert probed >= 150, f"too few object-level probes ({probed}); route table or bindings changed?"
    assert not violations, f"{len(violations)} object-level violations:\n" + "\n".join(violations[:60])
    assert API  # route prefix constant shared with the matrix generator
