"""Creates synthetic AUDIT- fixtures in batch B (DEMO-FS-26) via normal API actions. Writes ids
to .state/fixtures.json. Idempotent-ish: reuses ids already saved."""
import json, sys, datetime as dt
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from td_client import login, STATE

A = "01a1af17-d9dd-74bb-8928-44d9e97c6528"
B = "01a1b605-da36-73f1-a6a7-1327330a1d58"
TEST = "01a1b606-a939-74fb-aa66-e86969099f68"
f = STATE / "fixtures.json"
fx = json.loads(f.read_text()) if f.exists() else {}
now = dt.datetime.now(dt.timezone.utc)
iso = lambda d: d.isoformat()

admin = login("finance"); ravi = login("ravi.student"); student = login("asha.student")

def show(tag, r):
    print(tag, r.status_code, (r.json().get("code") if r.headers.get("content-type","").startswith("application/problem") else ""))
    return r

if False:
    r = show("create asg B", admin.post("assignments", {"title": "AUDIT-SecB text assignment", "submission_type": "text", "max_score": 10, "batch_id": B, "due_at": iso(now + dt.timedelta(days=7)), "instructions_md": "AUDIT security probe"}))
    if r.status_code < 300:
        fx["asg_b"] = r.json()["id"]
if False:
    r = show("ravi submit", ravi.post(f"me/assignments/{fx['asg_b']}/submissions", {"body_text": "AUDIT-ravi private answer"}))
    if r.status_code < 300:
        fx["sub_b"] = r.json().get("id")
if "ta_b" not in fx:
    r = show("assign test to B", admin.post(f"tests/{TEST}/assignments", {"batch_id": B, "available_from": iso(now - dt.timedelta(minutes=5)), "available_until": iso(now + dt.timedelta(days=7)), "release_mode": "immediate"}))
    if r.status_code < 300:
        fx["ta_b"] = r.json()["id"]
if "ta_b" in fx and "att_b" not in fx:
    r = show("ravi start attempt", ravi.post("attempts", {"test_id": TEST, "test_assignment_id": fx["ta_b"], "instructions_agreed": True, "integrity_consent": True}))
    if r.status_code < 300:
        j = r.json(); fx["att_b"] = j.get("attempt_id") or j.get("id") or (j.get("attempt") or {}).get("id")
    else:
        print(r.text[:300])
if "att_a" not in fx:
    r = show("student start attempt (batch A)", student.post("attempts", {"test_id": TEST, "instructions_agreed": True, "integrity_consent": True}))
    if r.status_code < 300:
        j = r.json(); fx["att_a"] = j.get("attempt_id") or j.get("id") or (j.get("attempt") or {}).get("id")
    else:
        print(r.text[:300])
if "tkt_ravi" not in fx:
    r = show("ravi ticket", ravi.post("support/tickets", {"category": "other", "subject": "AUDIT-ravi ticket", "body": "AUDIT security probe ticket, please ignore."}))
    if r.status_code < 300:
        fx["tkt_ravi"] = r.json().get("ticket_id")
if "palloc_b" not in fx:
    r = show("admin allocates path to B", admin.post("paths/01a1b606-c76c-7027-b9f5-29109562c20d/allocations", {"target_type": "batch", "batch_id": B, "pace": {"mode": "every_day", "hours_per_day": 1}}))
    if r.status_code < 300:
        j = r.json(); fx["palloc_b"] = j.get("id") or j.get("allocation_id")
    else: print(r.text[:400])
if "prv_ravi" not in fx:
    r = show("ravi privacy export request", ravi.post("me/privacy-requests", {"request_type": "access_export", "details": "AUDIT- security probe", "confirm": True}))
    if r.status_code < 300:
        j = r.json(); fx["prv_ravi"] = j.get("id") or j.get("request_id")
    else: print(r.text[:400])
f.write_text(json.dumps(fx, indent=1))
print(json.dumps(fx, indent=1))
