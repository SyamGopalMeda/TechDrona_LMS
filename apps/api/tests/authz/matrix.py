"""Generator for the authorisation matrix suite (TS-AUTHZ, testing-and-acceptance §2.5).

Inputs (never hand-written per route):

* the **route table** of the real app (``iter_api_routes``) — method, path, route tag and the
  static permissions declared through ``require_permission`` dependencies;
* the **role catalogue** (``app.modules.rbac.catalogue``, generated from
  role-permission-matrix.md §2/§3/§5) — which role holds which permission.

Principals: anonymous, a user with no grants, the 5 single-company roles (Student, Evaluator,
Trainer, Content manager, Admin = ``super_admin``; at their default scope), an L3
``restricted`` and an L4 ``status_only`` principal, and an *other-tenant* trainer and
evaluator (batch B of org B) — 11 in total. Path parameters named ``org_id`` / ``batch_id`` point at
org A / batch A (the "home" tenant of the scoped roles); every other id is a fresh UUID.

Expected outcome per (route, principal):

* every principal: never ``5xx``;
* anonymous: ``401`` on every non-public route;
* L3 ``restricted``: ``403 account_restricted`` on ``default`` routes; L4 ``status_only``:
  also on ``l3_readonly`` routes; never on the routes their scope allows;
* routes with a static permission: holders (role holds the permission per the catalogue *and*
  the grant's scope covers the target) are never refused with ``permission_denied``/401;
  non-holders get ``403 permission_denied`` — or ``404 not_found`` when the target belongs to
  another tenant (TI-02);
* other-tenant principals: never ``2xx`` on an org-A-scoped route, and no ``2xx`` body sent to
  them ever contains an org-A identifier (cross-tenant leak check);
* routes with in-handler checks (no static permission): student / no-grant principals never
  get ``2xx`` on a staff surface (see ``STAFF_PREFIXES``).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from fastapi.routing import APIRoute

from app.core.routing import IDLE_KEY, ROUTE_TAG_KEY, iter_api_routes, scope_allows
from app.modules.rbac.catalogue import permissions_for_role

API = "/api/v1"

ROLES = (
    "student",
    "evaluator",
    "trainer",
    "content_manager",
    "super_admin",
)

# Staff surfaces: a student / no-grant principal must never get 2xx here, whatever the
# handler's in-body check looks like. ``(method or None, path prefix)``.
STAFF_PREFIXES: tuple[tuple[str | None, str], ...] = (
    (None, "/admin/"),
    (None, "/audit/"),
    (None, "/finance/"),
    (None, "/studio/"),
    (None, "/mentor/"),
    (None, "/security/cases"),
    (None, "/security/review/"),
    (None, "/security/rule"),
    (None, "/security/engine"),
    (None, "/security/evaluations"),
    (None, "/security/incidents"),
    (None, "/security/restrictions"),
    (None, "/security/trusted-networks"),
    (None, "/security/users/"),
    (None, "/security/dashboard"),
    (None, "/security/reports"),
    (None, "/security/pii-reveals"),
    (None, "/support/queue"),
    (None, "/support/macros"),
    (None, "/support/users/"),
    (None, "/support/unblock-requests"),
    (None, "/rbac/grants"),
    (None, "/rbac/permissions"),
    (None, "/rbac/approval-requests"),
    (None, "/users/"),
    (None, "/orgs/"),
    (None, "/batches/"),
    (None, "/analytics/reports"),
    (None, "/analytics/ingest-health"),
    (None, "/assignment-submissions/{submission_id}/grade"),
    (None, "/assignments"),
    (None, "/tests/"),
    (None, "/test-assignments/"),
    (None, "/integrity/"),
    (None, "/progress"),
    (None, "/certificates"),
    (None, "/entitlements/grants"),
    (None, "/entitlements/{entitlement_id}/revoke"),
    ("GET", "/enrolments"),
    ("POST", "/enrolments"),
    ("POST", "/orgs"),
    ("POST", "/attempts/{attempt_id}/integrity-decision"),
    ("POST", "/attempts/{attempt_id}/invalidate"),
    ("POST", "/attempts/{attempt_id}/rebind-override"),
    ("POST", "/media/uploads/"),
    ("PATCH", "/support/tickets/"),
    ("POST", "/support/tickets/{ticket_id}/escalate"),
    ("POST", "/support/tickets/{ticket_id}/merge"),
)


# Routes whose permission scope comes from a required query parameter (LRN-22, LRN-24): the
# generator supplies it (pointing at batch A) so the permission decision is exercised. Single
# company (WS4): ``organization_id`` is no longer a parameter; without ``batch_id`` the scope is
# platform.
SCOPE_QUERY: dict[tuple[str, str], tuple[str, ...]] = {
    ("GET", "/enrolments"): ("batch_id",),
    ("GET", "/progress"): ("batch_id",),
}


@dataclass(frozen=True)
class RouteCase:
    method: str
    path: str  # full template, e.g. /api/v1/orgs/{org_id}
    tag: str
    idle: str | None
    perms: tuple[str, ...]
    path_params: tuple[tuple[str, Any], ...]  # (name, annotation)

    @property
    def short(self) -> str:
        return self.path[len(API) :] if self.path.startswith(API) else self.path

    @property
    def target(self) -> str:
        """Which tenant relation the substituted path points at."""
        names = {n for n, _ in self.path_params} | set(SCOPE_QUERY.get((self.method, self.short), ()))
        if "batch_id" in names:
            return "batch"
        if "org_id" in names:
            return "org"
        return "none"

    def is_staff_surface(self) -> bool:
        s = self.short
        return any((m is None or m == self.method) and s.startswith(p) for m, p in STAFF_PREFIXES)

    def __str__(self) -> str:
        return f"{self.method} {self.short}"


def _static_perms(route: APIRoute) -> tuple[str, ...]:
    out: list[str] = []
    stack = [route.dependant]
    while stack:
        d = stack.pop()
        p = getattr(d.call, "td_permission", None)
        if p and p not in out:
            out.append(p)
        stack.extend(d.dependencies)
    return tuple(out)


def route_cases(app: Any) -> list[RouteCase]:
    cases: list[RouteCase] = []
    for route, path in iter_api_routes(app):
        extra = route.openapi_extra or {}
        tag = str(extra.get(ROUTE_TAG_KEY))
        if tag == "public":
            continue
        params = tuple((f.name, f.field_info.annotation) for f in route.dependant.path_params)
        for m in sorted(route.methods or ()):
            if m in ("HEAD", "OPTIONS"):
                continue
            cases.append(RouteCase(m, path, tag, extra.get(IDLE_KEY), _static_perms(route), params))
    # Session-ending routes run last so they cannot invalidate the principal's session row
    # for the routes after them.
    return sorted(cases, key=lambda c: c.tag == "login_continuation" or c.short.endswith("revoke-others"))


# --------------------------------------------------------------------------- principals


@dataclass
class Who:
    name: str
    roles: tuple[str, ...]
    headers: dict[str, str] | None  # None = anonymous
    scope: str = "full"
    home: str = "a"  # tenant of its scoped grants: "a", "b" or "platform"
    grant_scopes: tuple[tuple[str, str, uuid.UUID | None], ...] = ()
    user_id: uuid.UUID | None = None

    @property
    def anonymous(self) -> bool:
        return self.headers is None

    @property
    def other_tenant(self) -> bool:
        return self.home == "b"

    @property
    def learner_like(self) -> bool:
        return not self.anonymous and set(self.roles) <= {"student"}


@dataclass
class Tenancy:
    org_a: uuid.UUID
    batch_a: uuid.UUID
    org_b: uuid.UUID
    batch_b: uuid.UUID
    a_markers: tuple[str, ...] = field(default_factory=tuple)


def target_chain(case: RouteCase, t: Tenancy) -> set[tuple[str, uuid.UUID | None]]:
    chain: set[tuple[str, uuid.UUID | None]] = {("platform", None)}
    if case.target in ("org", "batch"):
        chain.add(("organization", t.org_a))
    if case.target == "batch":
        chain.add(("batch", t.batch_a))
    return chain


def holds(who: Who, perm: str, chain: set[tuple[str, uuid.UUID | None]]) -> bool:
    return any(perm in permissions_for_role(r) and (st, sid) in chain for r, st, sid in who.grant_scopes)


def fill_query(case: RouteCase, t: Tenancy) -> dict[str, str]:
    if (case.method, case.short) in SCOPE_QUERY:
        return {"batch_id": str(t.batch_a)}
    return {}


def fill_path(case: RouteCase, t: Tenancy) -> str:
    values: dict[str, str] = {}
    for name, ann in case.path_params:
        if name == "org_id":
            values[name] = str(t.org_a)
        elif name == "batch_id":
            values[name] = str(t.batch_a)
        elif ann is int:
            values[name] = "1"
        elif ann is uuid.UUID:
            values[name] = str(uuid.uuid4())
        else:
            values[name] = "zz-authz-probe"
    return case.path.format(**values)


# --------------------------------------------------------------------------- outcome checks


@dataclass
class Outcome:
    case: RouteCase
    who: Who
    status: int
    code: str | None
    body: Any


def _problem_code(body: Any) -> str | None:
    return body.get("code") if isinstance(body, dict) else None


def check(o: Outcome, t: Tenancy) -> list[str]:
    """Violations for one (route, principal) outcome; empty = as expected."""
    c, w, st, code = o.case, o.who, o.status, o.code
    v: list[str] = []
    where = f"{c} as {w.name}: {st} {code}"
    if st >= 500:
        v.append(f"5xx {where} body={str(o.body)[:300]}")
        return v
    if w.anonymous:
        if st != 401:
            v.append(f"anonymous not 401 {where}")
        return v
    if st == 401 and code != "step_up_required" and c.tag != "login_continuation":
        v.append(f"authenticated principal got 401 {where}")
    # restriction scope gate
    if not scope_allows(w.scope, c.tag):
        if not (st == 403 and code == "account_restricted"):
            v.append(f"restriction gate missing ({w.scope} on {c.tag}) {where}")
        return v
    if code == "account_restricted":
        v.append(f"restriction gate over-blocks ({w.scope} on {c.tag}) {where}")
    # cross-tenant: never 2xx on an org-A-scoped route; never an org-A id in a 2xx body
    if w.other_tenant and c.target != "none" and 200 <= st < 300:
        v.append(f"cross-tenant 2xx {where}")
    if w.other_tenant and 200 <= st < 300:
        text = str(o.body)
        leaked = [m for m in t.a_markers if m in text]
        if leaked:
            v.append(f"cross-tenant data leak {where} markers={leaked}")
    # static permission matrix
    if c.perms:
        chain = target_chain(c, t)
        allowed = all(holds(w, p, chain) for p in c.perms)
        if allowed:
            refused = o.body.get("permission") if isinstance(o.body, dict) else None
            # A refusal naming a *different* permission is an additional in-handler check
            # (e.g. GST export download also needs report.export.request): not a matrix miss.
            if st == 403 and code == "permission_denied" and (refused is None or refused in c.perms):
                v.append(f"holder refused {where} perms={c.perms}")
        else:
            if w.other_tenant and c.target != "none":
                if t.org_a == t.org_b:
                    # Single company: "B" is another batch of the same organization. A batch
                    # the principal holds no grant on is refused like any non-holder (403) or
                    # hidden (404); it is never served (the 2xx check above).
                    if not (
                        (st == 403 and code == "permission_denied") or (st == 404 and code == "not_found")
                    ):
                        v.append(f"cross-batch probe not denied {where} perms={c.perms}")
                elif not (st == 404 and code == "not_found"):
                    v.append(f"cross-tenant probe not 404 {where} perms={c.perms}")
            elif not (st == 403 and code == "permission_denied"):
                v.append(f"non-holder not 403 {where} perms={c.perms}")
    elif w.learner_like or w.name == "no_grants":
        if c.is_staff_surface() and 200 <= st < 300:
            v.append(f"learner 2xx on staff surface {where}")
    return v


def summarize(outcomes: Iterable[Outcome]) -> dict[str, int]:
    out: dict[str, int] = {}
    for o in outcomes:
        k = f"{o.status // 100}xx"
        out[k] = out.get(k, 0) + 1
    return out
