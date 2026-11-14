"""Write the ``lms`` Hosting target and the ``lms`` functions codebase into firebase.json.

    python functions-lms/tools/sync_hosting.py [--site-url https://techdrona-website.web.app]

* Headers: apps/lms-spa/hosting-headers.json (the SPA agent's port of next.config.ts headers +
  middleware CSP; regenerate it with the Firebase env first: ``npm run gen-static`` in
  apps/lms-spa) plus the transport headers Caddy added on the LMS host
  (Strict-Transport-Security, X-Robots-Tag "noindex, nofollow").
* Rewrites: ``/api/**`` -> function ``lmsApi`` (asia-south1); everything else -> ``/index.html``.
* Redirects: the Caddy LMS-host redirects that do not depend on a cookie (marketing pages ->
  the company website). ``/`` -> ``/login`` vs ``/modules`` depended on the session cookie and is
  done by the SPA.
* The existing showcase hosting config is kept unchanged as target ``showcase``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
FIREBASE_JSON = REPO / "firebase.json"
SPA_HEADERS = REPO / "apps" / "lms-spa" / "hosting-headers.json"

CADDY_LMS_HEADERS = [
    {"key": "Strict-Transport-Security", "value": "max-age=31536000"},
    {"key": "X-Robots-Tag", "value": "noindex, nofollow"},
]


def _fn(function_id: str) -> dict[str, object]:
    return {"functionId": function_id, "region": "asia-south1", "pinTag": False}


# Rewrites this script owns (order matters: before the SPA fallback). /sitemap.xml goes to the
# function, which answers 404 like Caddy did on the LMS host (added by the SPA agent).
MANAGED_REWRITES: list[dict[str, object]] = [
    {"source": "/api/**", "function": _fn("lmsApi")},
    {"source": "/sitemap.xml", "function": _fn("lmsApi")},
    # College Data Portal: lmsApi checks the LMS admin session and proxies to Cloud Run
    # (lms_edge/college_portal.py; docs/qa/live-audit/fixes-college-portal.md).
    {"source": "/college-portal", "function": _fn("lmsApi")},
    {"source": "/college-portal/**", "function": _fn("lmsApi")},
]
FALLBACK = {"source": "**", "destination": "/index.html"}


def _merge_headers(existing: list[dict[str, Any]], spa_rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Caddy transport headers + the SPA rules; existing rules for other sources are kept, and
    extra keys someone added to the ``**`` rule (e.g. HSTS variants) survive a sync."""
    star_keys = {h["key"] for h in CADDY_LMS_HEADERS}
    extra_star = [
        h
        for r in existing
        if r.get("source") == "**"
        for h in r.get("headers", [])
        if h["key"] not in star_keys
    ]
    out = [{"source": "**", "headers": [*CADDY_LMS_HEADERS, *extra_star]}, *spa_rules]
    produced = {r["source"] for r in out}
    out += [r for r in existing if r.get("source") not in produced]
    return out


def lms_hosting(site_url: str, existing: dict[str, Any] | None = None) -> dict[str, object]:
    existing = existing or {}
    spa_rules = json.loads(SPA_HEADERS.read_text(encoding="utf-8")) if SPA_HEADERS.exists() else []
    headers = _merge_headers(list(existing.get("headers") or []), spa_rules)
    managed = {r["source"] for r in MANAGED_REWRITES} | {FALLBACK["source"]}
    kept = [r for r in existing.get("rewrites") or [] if r.get("source") not in managed]
    rewrites = [*MANAGED_REWRITES, *kept, FALLBACK]
    site = site_url.rstrip("/")
    marketing = ["/pricing", "/placement", "/companies", "/free-resources"]
    redirects = [
        {"source": "/courses{,/**}", "destination": f"{site}/courses", "type": 302},
        {"source": "/enquiries{,/**}", "destination": f"{site}/contact", "type": 302},
        *({"source": f"{p}{{,/**}}", "destination": f"{site}/", "type": 302} for p in marketing),
        {"source": "/status", "destination": f"{site}/", "type": 302},
    ]
    return {
        "target": "lms",
        "public": "apps/lms-spa/dist",
        "ignore": ["firebase.json", "**/.*", "**/node_modules/**"],
        "cleanUrls": False,
        "trailingSlash": False,
        "redirects": redirects,
        "rewrites": rewrites,
        "headers": headers,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-url", default="https://techdrona-website.web.app")
    args = ap.parse_args()
    cfg = json.loads(FIREBASE_JSON.read_text(encoding="utf-8"))
    hosting = cfg.get("hosting")
    entries = hosting if isinstance(hosting, list) else [{"target": "showcase", **hosting}] if hosting else []
    current = next((e for e in entries if e.get("target") == "lms"), None)
    entries = [e for e in entries if e.get("target") != "lms"] + [lms_hosting(args.site_url, current)]
    cfg["hosting"] = entries
    functions = cfg.get("functions") or []
    functions = functions if isinstance(functions, list) else [functions]
    functions = [f for f in functions if f.get("codebase") != "lms"] + [
        {
            "source": "functions-lms",
            "codebase": "lms",
            "runtime": "python313",
            "ignore": ["venv", "__pycache__", "*.pyc", "tools", "deploy", ".env.example", ".gitignore"],
        }
    ]
    cfg["functions"] = functions
    # keep key order readable: firestore, functions, hosting, emulators
    ordered = {k: cfg[k] for k in ("firestore", "functions", "hosting") if k in cfg}
    ordered.update({k: v for k, v in cfg.items() if k not in ordered})
    FIREBASE_JSON.write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")
    print(f"updated {FIREBASE_JSON}")  # noqa: T201


if __name__ == "__main__":
    main()
