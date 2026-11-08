"""Create synthetic AUDIT- students via public signup + email verification (Mailpit), so the
payment/upload probes do not use shared demo accounts. Prints no secrets/tokens.
Usage: fork_signup.py signup|verify <local>..."""
import re
import sys

import httpx

from td_client import MAILPIT, Client

PW = "AUDIT-probe-Passw0rd-" + "x7Lq"
DOMAIN = "audit.techdrona.local"


def mail_token(to: str) -> str | None:
    msgs = httpx.get(f"{MAILPIT}/api/v1/search", params={"query": f"to:{to}"}).json().get("messages") or []
    for m in msgs:
        body = httpx.get(f"{MAILPIT}/api/v1/message/{m['ID']}").json()
        mm = re.search(r"/verify/email/([A-Za-z0-9_\-.~%]+)", body.get("Text") or "")
        if mm:
            return mm.group(1)
    return None


def main() -> None:
    mode, locals_ = sys.argv[1], sys.argv[2:]
    for local in locals_:
        email = f"{local}@{DOMAIN}"
        c = Client("fork_" + local)
        if mode == "signup":
            c.jar = {}
            consents = [{"purpose": p, "notice_version": "2026-11-01", "granted": True} for p in ("terms", "privacy_notice", "core_service", "security_monitoring")]
            r = c.post("auth/signup", {"full_name": f"AUDIT {local}", "date_of_birth": "1999-01-01", "password": PW, "email": email, "consents": consents})
            print(local, "signup", r.status_code, (r.json() or {}).get("code") if r.content else "", flush=True)
        tok = mail_token(email)
        if tok:
            v = c.post("auth/verify/email", {"token": tok}, idem=False)
            print(local, "verify", v.status_code, (v.json() or {}).get("code") if v.content else "", flush=True)
        c.save()


if __name__ == "__main__":
    main()
