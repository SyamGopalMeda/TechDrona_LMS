"""Fork login helper: same as td_client.login but understands the ``result`` field of the login
response (device_verification_required / mfa_required / ...). Never prints secrets or OTPs."""
import time

from td_client import DEV_PASSWORD, DEV_TOTP_SECRETS, Client, fresh_totp, latest_otp


def login(local: str, password: str = DEV_PASSWORD, email: str | None = None) -> Client:
    email = email or f"{local}@dev.techdrona.local"
    c = Client("fork_" + local)
    if c.has("td_session") and c.get("me").status_code == 200:
        return c
    r = c.post("auth/login", {"identifier": email, "password": password}, idem=False)
    for _ in range(4):
        d = r.json() if r.content else {}
        res = str(d.get("result") or "")
        if r.status_code == 200 and res in ("", "ok", "authenticated", "signed_in"):
            break
        if d.get("code") == "session_cap_reached" or "session_choice" in res:
            raise RuntimeError(f"{local}: session cap reached - refusing to evict another session")
        if "mfa" in res and local in DEV_TOTP_SECRETS:
            r = c.post("auth/mfa/verify", {"method": "totp", "code": fresh_totp(DEV_TOTP_SECRETS[local])}, idem=False)
        elif "device" in res:
            t0 = time.time()
            c.post("auth/device-verification/send", {"channel": "email"}, idem=False)
            r = c.post("auth/device-verification/verify", {"method": "otp", "code": latest_otp(email, t0)})
        else:
            break
    c.save()
    if c.get("me").status_code != 200:
        d = r.json() if r.content else {}
        raise RuntimeError(f"{local}: login incomplete status={r.status_code} code={d.get('code')} result={d.get('result')}")
    return c
