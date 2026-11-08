import sys, json
sys.path.insert(0, "docs/redesign/security")
from td_client import login
c = login(sys.argv[1]); m = sys.argv[2]; p = sys.argv[3]; b = json.loads(sys.argv[4]) if len(sys.argv) > 4 else None
r = c.req(m, p, b)
print(r.status_code, r.text[:int(__import__("os").environ.get("N","1500"))])
