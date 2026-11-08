"""Dual control (maker != checker) with two different Admins, live through the BFF.
Every request created here is REJECTED by the second admin at the end (no policy/role change)."""
import sys, json
sys.path.insert(0, __file__.rsplit("\\", 1)[0].rsplit("/", 1)[0])
from td_client import login, step_up

out = []
def rec(tag, r):
    code = ""
    try: code = r.json().get("code") or r.json().get("status")
    except Exception: pass
    out.append((tag, r.status_code, code)); print(tag, r.status_code, code)
    return r

mk = login("finance"); ck = login("security2")
rec("maker step-up", step_up(mk, "finance"))
r = rec("maker proposes policy change (playback.otp_ttl_seconds=301)", mk.post("admin/policy-settings/playback.otp_ttl_seconds/changes", {"value": 301, "change_reason": "AUDIT- dual control probe, will be rejected"}))
pid = (r.json() or {}).get("approval_request_id")
if pid:
    rec("maker approves own policy change via admin/approvals", mk.post(f"admin/approvals/{pid}/approve", {"note": "AUDIT"}))
    rec("maker rejects own policy change via admin/approvals", mk.post(f"admin/approvals/{pid}/reject", {"note": "AUDIT"}))
# role grant of super_admin (DUAL_ROLES)
target = "01a1b62a-0000-0000-0000-000000000000"
import subprocess
uid = subprocess.run(["docker","exec","techdrona-postgres-1","sh","-c","psql -U \"$POSTGRES_USER\" -d techdrona -Atc \"select id from users where email='audit-buyer-b@audit.techdrona.local'\""],capture_output=True,text=True).stdout.strip()
r = rec("maker requests super_admin grant for AUDIT user", mk.post("rbac/grants", {"user_id": uid, "role_key": "super_admin", "scope_type": "platform", "reason": "AUDIT- dual control probe, will be rejected"}))
gid = (r.json() or {}).get("approval_request_id")
if gid:
    rec("maker approves own grant via rbac/approval-requests", mk.post(f"rbac/approval-requests/{gid}/approve", {"note": "AUDIT"}))
    rec("maker approves own grant via admin/approvals", mk.post(f"admin/approvals/{gid}/approve", {"note": "AUDIT"}))
rec("checker step-up", step_up(ck, "security2"))
if pid:
    rec("checker (different admin) rejects policy change", ck.post(f"admin/approvals/{pid}/reject", {"note": "AUDIT cleanup"}))
if gid:
    rec("checker (different admin) rejects grant", ck.post(f"rbac/approval-requests/{gid}/reject", {"note": "AUDIT cleanup"}))
# non-admin cannot approve
tr = login("trainer")
rec("trainer lists admin approvals", tr.get("admin/approvals"))
json.dump(out, open(__file__.replace(".py", ".out.json"), "w"), indent=1)
