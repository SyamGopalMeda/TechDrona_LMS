"""Smoke-test the emulated Firebase stack THROUGH HOSTING (http://127.0.0.1:5000), no Postgres.

    apps/api/.venv/Scripts/python functions-lms/tools/smoke_emulator.py [--base http://127.0.0.1:5000] [--json out.json]

1. The SPA loads (``/`` and a deep link serve index.html).
2. ``/api/v1/health/ready``, ``/api/v1/_bff/csrf`` and ``/api/v1/_bff/session`` (packed ``__session``).
3. Sign in as the seeded admin and student (``seed_emulator.py``) with the CSRF double submit.
4. As each user, GET every parameter-free ``/api/v1`` route of the app (list taken from the
   FastAPI app itself) and record the status: 2xx = works; 401/403/404/409/422 = answered by the
   app (a business answer); 5xx = broken, usually a module whose code still needs Postgres
   (``PostgresDisabledError``; the function log shows which).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import httpx

API = Path(__file__).resolve().parents[2] / "apps" / "api"


def get_routes() -> list[str]:
    sys.path.insert(0, str(API))
    os.environ.setdefault("APP_ENV", "local")
    os.environ["TD_ROUTER_SET"] = "user"
    from app.main import create_app

    # FastAPI includes routers lazily (no flat .routes list): read the OpenAPI paths instead.
    paths = create_app().openapi().get("paths", {})
    out = {p for p, ops in paths.items() if "get" in ops and "{" not in p and p.startswith("/api/v1/")}
    return sorted(out)


def login(c: httpx.Client, base: str, email: str, password: str) -> dict[str, Any]:
    c.get(f"{base}/api/v1/_bff/csrf")
    tok = c.cookies.get("td_csrf") or c.cookies.get("__Host-td_csrf") or ""
    r = c.post(
        f"{base}/api/v1/auth/login",
        json={"identifier": email, "password": password},
        headers={"x-csrf-token": tok, "origin": base, "sec-fetch-site": "same-origin"},
    )
    body = r.json() if r.headers.get("content-type", "").startswith("application/") else r.text[:200]
    return {"status": r.status_code, "body": body}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5000")
    ap.add_argument("--json", default="")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    report: dict[str, Any] = {}
    with httpx.Client(timeout=60) as c:
        r = c.get(f"{base}/")
        report["spa_index"] = (r.status_code, "<div id=" in r.text or "<script" in r.text)
        r = c.get(f"{base}/app/learn/some/deep/link")
        report["spa_deep_link"] = (r.status_code, r.headers.get("content-type"))
        r = c.get(f"{base}/api/v1/health/ready")
        report["health_ready"] = (r.status_code, r.json())
        r = c.get(f"{base}/api/v1/_bff/csrf")
        report["bff_csrf"] = (r.status_code, sorted(c.cookies.keys()))
        r = c.get(f"{base}/api/v1/_bff/session", headers={"sec-fetch-site": "same-origin"})
        report["bff_session_anon"] = (r.status_code, r.json())

    sys.path.insert(0, str(API))
    from app.seeds.dev_users import DEV_PASSWORD

    routes = get_routes()
    for who in ("admin", "student"):
        with httpx.Client(timeout=60) as c:
            res = login(c, base, f"{who}@dev.techdrona.local", DEV_PASSWORD)
            report[f"login_{who}"] = res
            r = c.get(f"{base}/api/v1/_bff/session", headers={"sec-fetch-site": "same-origin"})
            report[f"session_{who}"] = (r.status_code, r.json())
            statuses: dict[str, int] = {}
            for path in routes:
                try:
                    statuses[path] = c.get(
                        f"{base}{path}", headers={"sec-fetch-site": "same-origin"}
                    ).status_code
                except httpx.HTTPError as e:
                    statuses[path] = -1
                    print(f"{who} {path}: {type(e).__name__}")  # noqa: T201
            report[f"routes_{who}"] = statuses
            report[f"summary_{who}"] = dict(sorted(Counter(str(s) for s in statuses.values()).items()))

    for k, v in report.items():
        if not k.startswith("routes_"):
            print(f"{k}: {v}")  # noqa: T201
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"full report: {args.json}")  # noqa: T201


if __name__ == "__main__":
    main()
