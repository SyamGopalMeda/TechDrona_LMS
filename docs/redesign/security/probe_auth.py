"""Auth / session / CSRF / enumeration / rate-limit probes against the live dev stack.

Uses the synthetic accounts created by fork_signup.py (audit-buyer-a/-b@audit.techdrona.local)
plus read-only use of demo sessions. Never prints secrets, codes, tokens or cookie values.
"""
import json
import secrets
import statistics
import sys
import time
from pathlib import Path

import httpx
import pyotp

sys.path.insert(0, str(Path(__file__).parent))
from fork_signup import PW as AUDIT_PW  # noqa: E402
from td_client import DEV_TOTP_SECRETS, WEB, Client, fresh_totp, latest_otp, login  # noqa: E402

out: list[dict] = []


def rec(tag, r=None, **extra):
    row = {"tag": tag}
    if r is not None:
        row["status"] = r.status_code
        try:
            j = r.json()
            row["code"] = j.get("code") or j.get("result")
            row["keys"] = sorted(j)[:12]
        except Exception:
            pass
    row.update(extra)
    out.append(row)
    print(json.dumps(row))


def cookie_attrs(set_cookies):
    """Cookie name + attributes, value redacted."""
    res = []
    for sc in set_cookies:
        name, _, rest = sc.partition("=")
        attrs = [a.strip() for a in rest.split(";")[1:]]
        res.append(f"{name}; " + "; ".join(attrs))
    return res


# 1. Enumeration: unknown identifier vs known identifier + wrong password
a = Client("probe_enum")
a.jar = {}
times = {"unknown": [], "known": []}
for kind, ident in [("unknown", f"audit-nobody-{secrets.token_hex(4)}@audit.techdrona.local"),
                    ("known", "audit-buyer-b@audit.techdrona.local")]:
    t0 = time.perf_counter()
    r = a.post("auth/login", {"identifier": ident, "password": "AUDIT-wrong-password-1"}, idem=False)
    times[kind].append(time.perf_counter() - t0)
    rec(f"login {kind} identifier, wrong password", r, body_sha=hash(r.text.split('"request_id"')[0]) % 10**6,
        ms=round(times[kind][-1] * 1000))

# 2. Forgot password known vs unknown
for kind, ident in [("unknown", f"audit-nobody-{secrets.token_hex(4)}@audit.techdrona.local"),
                    ("known", "audit-buyer-b@audit.techdrona.local")]:
    r = a.post("auth/password/forgot", {"identifier": ident}, idem=False)
    rec(f"forgot-password {kind}", r, text=r.text[:160].split('"request_id"')[0])

# 3. Signup with an existing email vs a new one (response must not reveal registration)
for kind, email in [("existing", "audit-buyer-a@audit.techdrona.local"),
                    ("new", f"audit-enum-{secrets.token_hex(3)}@audit.techdrona.local")]:
    s = Client("probe_signup")
    s.jar = {}
    r = s.post("auth/signup", {"full_name": "AUDIT enum probe", "date_of_birth": "1999-01-01", "password": AUDIT_PW,
                               "email": email, "consents": []}, idem=False)
    rec(f"signup {kind} email", r, text=r.text[:200].split('"request_id"')[0])

# 4. CSRF on the BFF (asha's live session)
c = login("asha.student")
tok = c.csrf()
base = {"accept": "application/json", "content-type": "application/json", "cookie": c._cookie_header()}
h = httpx.Client(base_url=WEB, timeout=20)
cases = {
    "no x-csrf-token": {**base, "sec-fetch-site": "same-origin"},
    "cross-site fetch metadata + valid token": {**base, "sec-fetch-site": "cross-site", "x-csrf-token": tok},
    "evil Origin, no fetch metadata, valid token": {**base, "origin": "https://evil.example", "x-csrf-token": tok},
    "token minted for a different session": {**base, "sec-fetch-site": "same-origin",
                                             "x-csrf-token": login("ravi.student").csrf()},
    "text/plain body (simple request)": {**{k: v for k, v in base.items() if k != "content-type"},
                                         "content-type": "text/plain", "sec-fetch-site": "same-origin",
                                         "x-csrf-token": tok},
    "valid (control)": {**base, "sec-fetch-site": "same-origin", "x-csrf-token": tok},
}
for name, hd in cases.items():
    r = h.post("/api/v1/me/notifications/read-all", headers=hd, content=b"{}")
    rec(f"CSRF: {name}", r)

# 5. Direct API (:18000) without the BFF service token
sess = next(v for k, v in c.jar.items() if k.endswith("td_session"))
api = httpx.Client(base_url="http://localhost:18000", timeout=20)
for name, hd in {
    "X-TD-Session only": {"x-td-session": sess},
    "td_session cookie only": {"cookie": f"td_session={sess}"},
    "__Host-td_session cookie only": {"cookie": f"__Host-td_session={sess}"},
    "wrong service token + X-TD-Session": {"authorization": "Service AUDIT-wrong", "x-td-session": sess},
}.items():
    rec(f"direct API /me: {name}", api.get("/api/v1/me", headers=hd))
rec("direct API webhooks path via main api", api.post("/api/v1/webhooks/razorpay", content=b"{}",
                                                       headers={"content-type": "application/json"}))

# 6. Session cookie flags + logout revocation with a fresh synthetic session
f = Client("probe_fresh")
f.jar = {}
fork_dev = Path(r"C:\Users\SYAM\AppData\Local\Temp\claude\3eb179e72a8561e7\01b010a6-02cb-4a93-a6f8-10046dfb2eb1\scratchpad\fork_state\fork_audit-buyer-b.cookies.json")
if fork_dev.exists():
    f.jar = {k: v for k, v in json.loads(fork_dev.read_text()).items() if k.endswith("td_device")}
r = f.post("auth/login", {"identifier": "audit-buyer-b@audit.techdrona.local", "password": AUDIT_PW}, idem=False)
rec("fresh login (synthetic student)", r, set_cookie=cookie_attrs(f.last_set_cookies))
if (r.json() or {}).get("result") == "device_verification_required":
    t0 = time.time()
    f.post("auth/device-verification/send", {"channel": "email"}, idem=False)
    r = f.post("auth/device-verification/verify", {"method": "otp", "code": latest_otp("audit-buyer-b@audit.techdrona.local", t0)})
    rec("device verification", r, set_cookie=cookie_attrs(f.last_set_cookies))
me = f.get("me")
rec("me after login", me, session=(me.json() or {}).get("session") if me.status_code == 200 else None)
old = dict(f.jar)
r = f.post("auth/logout", {}, idem=False)
rec("logout", r, set_cookie=cookie_attrs(f.last_set_cookies))
g = Client("probe_replay")
g.jar = old
rec("replay pre-logout session cookie", g.get("me"))

# 7. Staff session lifetime + TOTP replay on step-up (security2 admin)
s2 = login("security2")
rec("staff me", s2.get("me"), session=s2.get("me").json().get("session"))
st = int(time.time() // 30)
code = pyotp.TOTP(DEV_TOTP_SECRETS["security2"]).at(st * 30)
r1 = s2.post("auth/step-up", {"method": "totp", "code": code}, idem=False)
r2 = s2.post("auth/step-up", {"method": "totp", "code": code}, idem=False)
rec("step-up totp first use", r1)
rec("step-up same totp replayed", r2)
r3 = s2.post("auth/step-up", {"method": "totp", "code": "000000"}, idem=False)
rec("step-up wrong totp", r3)
time.sleep(31)
rec("step-up valid fresh totp", s2.post("auth/step-up", {"method": "totp", "code": fresh_totp(DEV_TOTP_SECRETS["security2"])}, idem=False))

# 8. Public enquiry rate limit (same email): 3/day per email
p = Client("probe_enq")
p.jar = {}
em = f"audit-enq-{secrets.token_hex(3)}@audit.techdrona.local"
for i in range(5):
    r = p.post("public/enquiries", {"name": "AUDIT enquiry probe", "company": "AUDIT-Co", "email": em,
                                    "message": "AUDIT security rate-limit probe, please ignore.", "consent": True}, idem=False)
    rec(f"enquiry #{i + 1} same email", r)

# 9. Security headers on a page
r = httpx.get(f"{WEB}/login")
rec("page headers /login", r, headers={k: r.headers.get(k, "")[:90] for k in (
    "content-security-policy", "x-frame-options", "x-content-type-options", "referrer-policy",
    "strict-transport-security", "permissions-policy", "cross-origin-opener-policy")})

Path(__file__.replace(".py", ".out.json")).write_text(json.dumps(out, indent=1))
