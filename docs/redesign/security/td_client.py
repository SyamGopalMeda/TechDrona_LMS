"""Security-audit probe client (docs/redesign/security). Talks to the live dev stack through the
web BFF (http://localhost:13000/api/v1/*) exactly like a browser: CSRF double-submit cookie,
Fetch-Metadata, session/device cookies. Never prints secrets, OTPs or tokens.

Run with the api venv:  apps/api/.venv/Scripts/python.exe docs/redesign/security/td_client.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

import httpx
import pyotp

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "apps" / "api"))
from app.seeds.dev_users import DEV_PASSWORD, DEV_TOTP_SECRETS  # noqa: E402

WEB = os.environ.get("TD_WEB", "http://localhost:13000")
MAILPIT = "http://localhost:8025"
STATE = Path(os.environ.get("TD_PROBE_STATE", str(Path(__file__).parent / ".state")))
STATE.mkdir(exist_ok=True)


class Client:
    """Manual cookie jar: the BFF sets `__Host-` Secure cookies even on http://localhost (browsers
    treat localhost as a secure context; httpx does not), so cookies are tracked by hand."""

    def __init__(self, name: str):
        self.name = name
        self.h = httpx.Client(base_url=WEB, timeout=30, follow_redirects=False)
        self.jar: dict[str, str] = {}
        f = STATE / f"{name}.cookies.json"
        if f.exists():
            self.jar = json.loads(f.read_text())
        self.last_set_cookies: list[str] = []

    def save(self) -> None:
        (STATE / f"{self.name}.cookies.json").write_text(json.dumps(self.jar))

    def _absorb(self, r: httpx.Response) -> None:
        self.last_set_cookies = r.headers.get_list("set-cookie")
        for sc in self.last_set_cookies:
            pair = sc.split(";", 1)[0]
            k, _, v = pair.partition("=")
            k = k.strip()
            low = sc.lower()
            if v == "" or "max-age=0" in low or "expires=thu, 01 jan 1970" in low:
                self.jar.pop(k, None)
            else:
                self.jar[k] = v

    def _cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.jar.items())

    def csrf(self) -> str | None:
        r = self.h.get("/api/v1/_bff/csrf", headers={"cookie": self._cookie_header()})
        self._absorb(r)
        for k, v in self.jar.items():
            if k.endswith("td_csrf"):
                return v
        return None

    def has(self, suffix: str) -> bool:
        return any(k.endswith(suffix) for k in self.jar)

    def req(self, method: str, path: str, body=None, *, csrf=True, idem=True, headers=None, params=None):
        hd = {"accept": "application/json", "sec-fetch-site": "same-origin"}
        if method != "GET":
            if csrf:
                tok = self.csrf()
                if tok:
                    hd["x-csrf-token"] = tok
            if idem:
                hd["idempotency-key"] = str(uuid.uuid4())
        if headers:
            hd.update(headers)
        hd["cookie"] = self._cookie_header()
        r = self.h.request(method, f"/api/v1/{path.lstrip('/')}", json=body, headers=hd, params=params)
        self._absorb(r)
        return r

    def get(self, path, **kw):
        return self.req("GET", path, **kw)

    def post(self, path, body=None, **kw):
        return self.req("POST", path, body if body is not None else {}, **kw)


def latest_otp(to: str, after: float) -> str:
    for _ in range(30):
        r = httpx.get(f"{MAILPIT}/api/v1/search", params={"query": f"to:{to}"})
        msgs = r.json().get("messages") or []
        for m in sorted(msgs, key=lambda m: m["Created"], reverse=True):
            from datetime import datetime
            ts = datetime.fromisoformat(m["Created"].replace("Z", "+00:00")).timestamp()
            if ts >= after - 2:
                body = httpx.get(f"{MAILPIT}/api/v1/message/{m['ID']}").json()
                mm = re.search(r"\b(\d{6})\b", body.get("Text") or "")
                if mm:
                    return mm.group(1)
        time.sleep(1)
    raise RuntimeError("no otp mail")


_last_step: dict[str, int] = {}


def fresh_totp(secret: str) -> str:
    step = int(time.time() // 30)
    f = STATE / f"totp_{abs(hash(secret)) % 10**8}.step"
    last = int(f.read_text()) if f.exists() else -1
    if step <= last:
        time.sleep((last + 1) * 30 - time.time() + 0.5)
        step = int(time.time() // 30)
    f.write_text(str(step))
    return pyotp.TOTP(secret).at(step * 30)


def login(local: str, *, email: str | None = None, password: str = DEV_PASSWORD) -> Client:
    """Signs in (reusing a saved session if still valid). Refuses to evict other sessions."""
    email = email or f"{local}@dev.techdrona.local"
    c = Client(local)
    if c.has("td_session"):
        if c.get("me").status_code == 200:
            return c
    r = c.post("auth/login", {"identifier": email, "password": password}, idem=False)
    data = r.json() if r.headers.get("content-type", "").startswith("application") else {}
    for _ in range(4):
        nxt = (data or {}).get("next") or (data or {}).get("status") or ""
        code = (data or {}).get("code", "")
        if r.status_code == 200 and nxt in ("", "ok", "authenticated", None) and "mfa" not in json.dumps(data):
            break
        blob = json.dumps(data)
        if "mfa" in blob and local in DEV_TOTP_SECRETS:
            r = c.post("auth/mfa/verify", {"method": "totp", "code": fresh_totp(DEV_TOTP_SECRETS[local])}, idem=False)
        elif "device" in blob and "verif" in blob:
            t0 = time.time()
            c.post("auth/device-verification/send", {"channel": "email"}, idem=False)
            r = c.post("auth/device-verification/verify", {"method": "otp", "code": latest_otp(email, t0)})
        elif code == "session_cap_reached":
            raise RuntimeError(f"{local}: session cap reached - refusing to evict another session")
        else:
            break
        data = r.json() if r.content else {}
    c.save()
    me = c.get("me")
    if me.status_code != 200:
        raise RuntimeError(f"{local}: login incomplete status={r.status_code} code={data.get('code')} keys={list(data)[:8]}")
    return c


def anon() -> Client:
    c = Client("anon")
    c.jar = {}
    return c


if __name__ == "__main__":
    who = sys.argv[1] if len(sys.argv) > 1 else "student"
    c = login(who)
    me = c.get("me").json()
    print(who, "ok", {k: me.get(k) for k in ("id", "session_tier", "roles") if k in me}, list(me)[:15])


def step_up(c: Client, local: str):
    """P5 step-up with TOTP (never prints the code)."""
    return c.post("auth/step-up", {"method": "totp", "code": fresh_totp(DEV_TOTP_SECRETS[local])}, idem=False)
