"""TS-AUTHZ: route table x principals, expected outcomes computed from the role catalogue.

See ``tests/authz/matrix.py`` for the generator and the outcome rules. Each test runs every
authenticated route as one principal (11 principals → 11 tests, ~430 routes each). Set
``TD_AUTHZ_REPORT_DIR`` to write a per-principal JSON summary (used for docs/qa-report-backend.md).

Intentional exceptions are listed in ``EXCEPTIONS`` with the reason; anything else that
deviates fails the suite.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.core.ids import uuid7
from app.core.time import utcnow
from tests.authz.matrix import (
    ROLES,
    Outcome,
    Tenancy,
    Who,
    check,
    fill_path,
    fill_query,
    route_cases,
    summarize,
)
from tests.identity.factory import add_member
from tests.placement.world import World, build_world

PRINCIPALS = (
    "anonymous",
    "no_grants",
    *ROLES,
    "restricted_l3",
    "status_only_l4",
    "other_trainer",
    "other_evaluator",
)

# (method, path suffix after /api/v1, principal or "*") -> reason. Keep this list short and
# justified; every entry is reported in docs/qa-report-backend.md.
EXCEPTIONS: dict[tuple[str, str, str], str] = {
    ("GET", "/admin/approvals", "*"): (
        "Requester/approver-scoped list: rows are filtered to approval requests the caller raised "
        "or may decide (apr.can_approve), so a learner gets 200 with an empty list, never others' rows."
    ),
}


@pytest.fixture
def rbac_auth(auth: Any) -> Iterator[Any]:
    from app.core import auth as core_auth
    from app.modules.rbac.service import RbacPermissionChecker, reset_role_permission_cache

    class _StateResolver:
        """FakeAuth + what the real resolver leaves on ``request.state`` (the session row id),
        so handlers that read the current ``auth_sessions`` row (GET /me, /me/sessions) work."""

        async def resolve(self, request: Any, session_token: str, ctx: Any) -> Any:
            p = await auth.resolve(request, session_token, ctx)
            request.state.auth_session_id = p.session_id
            return p

    prev = core_auth._permission_checker
    reset_role_permission_cache()
    core_auth.register_permission_checker(RbacPermissionChecker())
    core_auth.register_session_resolver(_StateResolver())
    yield auth
    core_auth.register_permission_checker(prev)


async def _principals(db: Any, w: World) -> tuple[dict[str, Who], Tenancy]:
    t = Tenancy(w.org_a, w.batch_a, w.org_b, w.batch_b)
    plat: tuple[str, str, uuid.UUID | None]
    specs: dict[
        str, tuple[tuple[tuple[str, str, uuid.UUID | None], ...], tuple[uuid.UUID, ...], str, str, int]
    ] = {
        "no_grants": ((), (w.org_a,), "student", "full", 0),
        # a batch student (company membership); the student role is held at platform scope
        "student": ((("student", "platform", None),), (w.org_a,), "student", "full", 0),
        "evaluator": ((("evaluator", "batch", w.batch_a),), (w.org_a,), "staff", "full", 0),
        "trainer": ((("trainer", "batch", w.batch_a),), (w.org_a,), "staff", "full", 0),
        "restricted_l3": ((("student", "platform", None),), (w.org_a,), "student", "restricted", 3),
        "status_only_l4": ((("student", "platform", None),), (w.org_a,), "student", "status_only", 4),
        "other_trainer": ((("trainer", "batch", w.batch_b),), (w.org_b,), "staff", "full", 0),
        "other_evaluator": ((("evaluator", "batch", w.batch_b),), (w.org_b,), "staff", "full", 0),
    }
    for role, tier in (
        ("content_manager", "staff"),
        ("super_admin", "privileged"),
    ):
        plat = (role, "platform", None)
        specs[role] = ((plat,), (), tier, "full", 0)

    out: dict[str, Who] = {"anonymous": Who("anonymous", (), None, home="platform")}
    now = utcnow()
    for name, (grants, orgs, tier, scope, level) in specs.items():
        persona = await w.persona(
            f"authz_{name}",
            grants=grants,
            org_ids=orgs,
            is_platform=any(g[1] == "platform" and g[0] != "student" for g in grants),
            tier=tier,
            scope=scope,
            restriction_level=level,
        )
        # Fresh step-up + MFA so freshness never masks the permission decision.
        p = replace(persona.principal, last_step_up_at=now, auth_time=now, aal=2, mfa_level="totp")
        headers = w.auth.login(p)
        home = "b" if name.startswith("other_") else ("platform" if not orgs else "a")
        if orgs:
            batch = None
            if any(g[1] == "batch" for g in grants):
                batch = w.batch_b if home == "b" else w.batch_a
            member_role = "student" if tier == "student" else "staff"
            await add_member(db, orgs[0], p.user_id, member_role, batch)
        out[name] = Who(
            name,
            tuple(g[0] for g in grants),
            headers,
            scope=scope,
            home=home,
            grant_scopes=grants,
            user_id=p.user_id,
        )
    # Single company: org A and org B are the same company org, so its id is no secret to
    # batch B; the batch-A and learner-A identifiers still are.
    t.a_markers = (
        *((str(w.org_a),) if w.org_a != w.org_b else ()),
        str(w.batch_a),
        str(out["student"].user_id),
        str(out["evaluator"].user_id),
        str(w.personas["student"].id),
    )
    return out, t


def _report(principal: str, n: int, outcomes: list[Outcome], violations: list[str]) -> None:
    d = os.environ.get("TD_AUTHZ_REPORT_DIR")
    if not d:
        return
    Path(d).mkdir(parents=True, exist_ok=True)
    static = sum(1 for o in outcomes if o.case.perms)
    payload = {
        "principal": principal,
        "routes": n,
        "static_permission_routes": static,
        "status_classes": summarize(outcomes),
        "violations": violations,
        "denied_403": sum(1 for o in outcomes if o.status == 403),
        "denied_404": sum(1 for o in outcomes if o.status == 404),
        "allowed_2xx": sum(1 for o in outcomes if 200 <= o.status < 300),
    }
    (Path(d) / f"{principal}.json").write_text(json.dumps(payload, indent=2))


@pytest.mark.parametrize("principal", PRINCIPALS)
async def test_authz_matrix(principal: str, app: Any, client: Any, db: Any, rbac_auth: Any) -> None:
    w = await build_world(db, rbac_auth)
    whos, tenancy = await _principals(db, w)
    who = whos[principal]
    cases = route_cases(app)
    assert len(cases) > 350, "route table unexpectedly small"
    outcomes: list[Outcome] = []
    violations: list[str] = []
    for case in cases:
        headers = dict(who.headers or {})
        headers["Idempotency-Key"] = f"authz-{uuid7().hex}"
        url = fill_path(case, tenancy)
        kwargs: dict[str, Any] = {"headers": headers, "params": fill_query(case, tenancy)}
        if case.method in ("POST", "PUT", "PATCH"):
            kwargs["json"] = {}
        try:
            r = await client.request(case.method, url, **kwargs)
            status = r.status_code
            try:
                body: Any = r.json()
            except ValueError:
                body = r.text[:500]
        except Exception as e:  # an unhandled exception escaped the app: count as 5xx
            status, body = 599, {"code": "unhandled", "detail": repr(e)[:300]}
        o = Outcome(case, who, status, body.get("code") if isinstance(body, dict) else None, body)
        outcomes.append(o)
        for v in check(o, tenancy):
            if (case.method, case.short, principal) in EXCEPTIONS or (
                case.method,
                case.short,
                "*",
            ) in EXCEPTIONS:
                continue
            violations.append(v)
    _report(principal, len(cases), outcomes, violations)
    assert not violations, f"{len(violations)} authz violations:\n" + "\n".join(violations[:80])


async def test_every_authenticated_route_has_generated_cases(app: Any) -> None:
    """A route with no generated cases fails the suite (§2.5 'Size')."""
    from app.core.routing import iter_api_routes

    cases = {(c.method, c.path) for c in route_cases(app)}
    missing = []
    for route, path in iter_api_routes(app):
        if (route.openapi_extra or {}).get("x-td-route-tag") == "public":
            continue
        for m in route.methods or ():
            if m not in ("HEAD", "OPTIONS") and (m, path) not in cases:
                missing.append(f"{m} {path}")
    assert not missing, missing
