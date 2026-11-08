"""Live RBAC/object-level matrix through the BFF (read-mostly; mutations use nil/invalid targets).

Roles: anon, asha (student, batch A), ravi (student, batch B), trainer (batch A + AUDIT batch),
evaluator (batch A + AUDIT batch), content (content manager, platform), admin (super_admin; the
'finance' demo admin account). Output: probe_matrix.out.json + console table of anomalies.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from td_client import STATE, anon, login  # noqa: E402

fx = json.loads((STATE / "fixtures.json").read_text())
A = "01a1af17-d9dd-74bb-8928-44d9e97c6528"
B = "01a1b605-da36-73f1-a6a7-1327330a1d58"
ASHA = "01a1b605-d7fa-72b3-a6d6-143c141a7713"
RAVI = "01a1b605-d85e-7151-a329-bc3bfb97e3d5"
SUB_A = "01a1b606-c914-776e-9e45-e388dec8075c"
ASG_A = "01a1b606-c8a1-7368-92ab-d04c2d1c01b9"
TEST = "01a1b606-a939-74fb-aa66-e86969099f68"
ATT_A, ATT_B = fx["att_a"], fx["att_b"]
PALLOC_A = "01a1b606-c848-75d6-a8a7-c3c59c044510"
PALLOC_B = fx["palloc_b"]
TKT_RAVI = fx["tkt_ravi"]
TKT_OTHER = "01a1b63b-ad4b-7156-8b87-25c692273566"
PRV = fx["prv_ravi"]
ORDER_X = "01a1b624-bb66-70a7-810d-03e2cb871300"
INV_X = "01a1b624-ef7b-77d9-9ed8-c609b2a23164"
ENT = "01a1af18-841c-75cd-8c36-771a9cfc2bcf"
Q = "01a1af18-0aae-73e0-a9cd-dcde247d2e83"
CP = "01a1af18-2a54-758b-9f9a-9550be1a77de"
RUN = "01a1b644-110f-71e3-9b59-f85d3ff10f06"
ENQ = "01a1b606-c956-712d-94ad-cce594f32d9f"
NIL = "00000000-0000-7000-8000-000000000000"

ALL = {"asha", "ravi", "trainer", "evaluator", "content", "admin"}
E = [
    ("GET", "admin/users", None, {"admin"}),
    ("GET", f"admin/users/{RAVI}", None, {"admin"}),
    ("GET", f"users/{RAVI}/sessions", None, {"admin"}),
    ("GET", f"users/{RAVI}/devices", None, {"admin"}),
    ("GET", f"users/{RAVI}/entitlements", None, {"admin"}),
    ("GET", f"support/users/{RAVI}", None, {"admin"}),
    ("GET", f"mentor/students/{RAVI}", None, {"admin"}),
    ("GET", "mentor/students", None, {"admin"}),
    ("GET", f"security/users/{RAVI}/timeline", None, {"admin"}),
    ("GET", "batches", None, {"admin", "trainer", "evaluator"}),
    ("GET", f"batches/{B}", None, {"admin"}),
    ("GET", f"batches/{B}/members", None, {"admin"}),
    ("GET", f"batches/{A}/members", None, {"admin", "trainer", "evaluator"}),
    ("GET", "paths/batch-members", None, {"admin", "trainer", "content"}),
    ("GET", "enrolments", None, {"admin"}),
    ("GET", "finance/orders", None, {"admin"}),
    ("GET", f"finance/orders/{ORDER_X}", None, {"admin"}),
    ("GET", f"commerce/orders/{ORDER_X}", None, set()),
    ("GET", "finance/invoices", None, {"admin"}),
    ("GET", f"finance/invoices/{INV_X}/pdf", None, {"admin"}),
    ("GET", f"me/invoices/{INV_X}/pdf", None, set()),
    ("GET", "finance/refunds", None, {"admin"}),
    ("GET", "finance/reports/revenue", None, {"admin"}),
    ("GET", f"entitlements/{ENT}/events", None, {"admin"}),
    ("POST", "entitlements/grants", {"user_id": NIL, "reason": "AUDIT-probe"}, {"admin"}),
    ("POST", f"entitlements/{NIL}/revoke", {"reason": "AUDIT-probe"}, set()),
    ("GET", "me/attempts", None, ALL),
    ("GET", f"attempts/{ATT_B}/state", None, {"ravi"}),
    ("GET", f"attempts/{ATT_B}/time", None, {"ravi"}),
    ("GET", f"attempts/{ATT_B}/result", None, {"ravi"}),
    ("GET", f"attempts/{ATT_B}/review", None, {"ravi"}),
    ("GET", f"attempts/{ATT_B}/evaluation", None, {"admin"}),
    ("GET", f"attempts/{ATT_A}/evaluation", None, {"admin", "trainer", "evaluator"}),
    ("POST", f"attempts/{ATT_B}/autosave", {"responses": []}, {"ravi"}),
    ("POST", f"attempts/{ATT_B}/invalidate", {"reason": "AUDIT-probe x"}, {"admin"}),
    ("POST", f"attempts/{ATT_B}/integrity-decision", {"decision": "no_action", "reason": "AUDIT"}, {"admin"}),
    ("GET", f"tests/{TEST}/attempts", None, {"admin", "trainer", "evaluator"}),
    ("GET", f"tests/{TEST}/evaluation", None, {"admin", "trainer", "evaluator"}),
    ("GET", f"tests/{TEST}/report", None, {"admin", "trainer", "evaluator"}),
    ("GET", f"tests/{TEST}/assignments", None, {"admin", "trainer", "evaluator", "content"}),
    ("GET", f"tests/{TEST}/overrides", None, {"admin", "trainer"}),
    ("GET", f"studio/tests/{TEST}", None, {"admin", "trainer", "content"}),
    ("GET", "integrity/flags", None, {"admin", "trainer", "evaluator"}),
    ("GET", f"assignments/{ASG_A}/submissions", None, {"admin", "trainer", "evaluator"}),
    ("GET", f"assignments/{ASG_A}/evaluation", None, {"admin", "trainer", "evaluator"}),
    ("GET", f"assignment-submissions/{SUB_A}", None, {"admin", "trainer", "evaluator", "asha"}),
    ("GET", f"assignment-submissions/{SUB_A}/review", None, {"admin", "trainer", "evaluator"}),
    ("POST", f"assignment-submissions/{SUB_A}/grade", {"score": "x"}, {"admin", "trainer", "evaluator"}),
    ("GET", f"me/assignments/{ASG_A}", None, {"asha"}),
    ("GET", f"studio/questions/{Q}", None, {"admin", "content", "trainer"}),
    ("GET", "studio/questions", None, {"admin", "content", "trainer"}),
    ("GET", f"studio/coding/problems/{CP}/test-cases", None, {"admin", "content", "trainer"}),
    ("GET", f"studio/coding/problems/{CP}/reference-solutions", None, {"admin", "content", "trainer"}),
    ("GET", f"engage/runs/{RUN}/results", None, {"admin"}),
    ("GET", f"engage/runs/{RUN}/presenter", None, {"admin"}),
    ("GET", f"path-allocations/{PALLOC_B}/progress", None, {"admin"}),
    ("GET", f"path-allocations/{PALLOC_A}/progress", None, {"admin", "trainer"}),
    ("DELETE", f"path-allocations/{PALLOC_B}", None, set()),
    ("GET", f"me/paths/{PALLOC_B}", None, {"ravi"}),
    ("GET", "support/queue", None, {"admin"}),
    ("GET", f"support/tickets/{TKT_RAVI}", None, {"ravi", "admin"}),
    ("GET", f"support/tickets/{TKT_OTHER}", None, {"admin"}),
    ("POST", f"support/tickets/{TKT_RAVI}/messages", {"body": "x" * 0}, {"ravi", "admin"}),
    ("GET", "support/enquiries", None, {"admin"}),
    ("GET", f"support/enquiries/{ENQ}", None, {"admin"}),
    ("GET", "admin/ai-settings", None, {"admin"}),
    ("GET", "admin/ai-usage", None, {"admin"}),
    ("GET", "admin/apps", None, {"admin"}),
    ("PATCH", "admin/apps", {}, {"admin"}),
    ("GET", "admin/policy-settings", None, {"admin"}),
    ("GET", "admin/feature-flags", None, {"admin"}),
    ("GET", "admin/dashboard", None, {"admin"}),
    ("GET", "audit/events", None, {"admin"}),
    ("GET", "audit/chain-status", None, {"admin"}),
    ("GET", "admin/privacy-requests", None, {"admin"}),
    ("GET", f"admin/privacy-requests/{PRV}", None, {"admin"}),
    ("GET", f"me/privacy-requests/{PRV}", None, {"ravi"}),
    ("GET", f"me/privacy-requests/{PRV}/export", None, {"ravi"}),
    ("GET", "security/cases", None, {"admin"}),
    ("GET", "security/dashboard", None, {"admin"}),
    ("GET", "rbac/grants", None, {"admin"}),
    ("POST", "rbac/grants", {"user_id": NIL, "role_key": "trainer", "scope_type": "batch", "scope_id": B, "reason": "AUDIT-probe"}, {"admin"}),
    ("GET", f"analytics/reports/batches/{B}", None, {"admin"}),
    ("GET", f"analytics/reports/batches/{A}", None, {"admin", "trainer", "evaluator"}),
    ("GET", "analytics/reports/platform", None, {"admin"}),
    ("POST", f"batches/{B}/members", {"user_id": NIL}, {"admin"}),
    ("DELETE", f"batches/{B}/members/{NIL}", None, {"admin"}),
    ("POST", f"tests/{TEST}/results/release", {"batch_id": B}, {"admin"}),
]

roles = {"anon": anon()}
for k, local in [("asha", "asha.student"), ("ravi", "ravi.student"), ("trainer", "trainer"),
                 ("evaluator", "evaluator"), ("content", "content"), ("admin", "finance")]:
    roles[k] = login(local)

LEAK = {"ravi-attempt": ATT_B, "ravi-user": RAVI, "ravi-ticket": TKT_RAVI}
only = sys.argv[1:]
res = []
for m, p, body, exp in E:
    if only and not any(o in p for o in only):
        continue
    row = {"ep": f"{m} {p}", "exp": sorted(exp), "got": {}, "leaks": {}}
    for rk, c in roles.items():
        if m == "DELETE" and rk == "admin" and "path-allocations" in p:
            row["got"][rk] = "skip"
            continue
        r = c.req(m, p, body if body is not None else ({} if m != "GET" else None))
        code = ""
        try:
            j = r.json()
            code = j.get("code", "") if isinstance(j, dict) else ""
        except Exception:
            j = None
        row["got"][rk] = f"{r.status_code}{(':' + code) if code else ''}"
        if r.status_code < 300 and rk != "admin":
            hits = [n for n, v in LEAK.items() if v in r.text]
            if rk == "ravi":
                hits = [h for h in hits if h != "ravi-user" and h != "ravi-attempt" and h != "ravi-ticket"]
            if hits:
                row["leaks"][rk] = hits
    res.append(row)

Path(__file__.replace(".py", ".out.json")).write_text(json.dumps(res, indent=1))
order = ["anon", "asha", "ravi", "trainer", "evaluator", "content", "admin"]
for row in res:
    flags = []
    for rk in order:
        g = row["got"].get(rk, "")
        ok2 = g[:1] == "2"
        if rk == "anon":
            if not g.startswith("401"):
                flags.append(f"anon={g}")
        elif ok2 and rk not in row["exp"]:
            flags.append(f"UNEXPECTED-ALLOW {rk}")
        elif not ok2 and rk in row["exp"]:
            flags.append(f"denied {rk}")
    if row["leaks"]:
        flags.append(f"LEAKS {row['leaks']}")
    print(row["ep"], "|", " ".join(f"{rk[:3]}={row['got'].get(rk)}" for rk in order), "|", "; ".join(flags))
