"""functions-lms/tools/sync_hosting.py keeps rules other agents added to the lms hosting entry."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
_spec = importlib.util.spec_from_file_location(
    "sync_hosting", ROOT / "functions-lms" / "tools" / "sync_hosting.py"
)
assert _spec and _spec.loader
sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync)


def test_sync_is_idempotent_on_the_current_firebase_json() -> None:
    cfg = json.loads((ROOT / "firebase.json").read_text(encoding="utf-8"))
    current = next(h for h in cfg["hosting"] if h.get("target") == "lms")
    assert sync.lms_hosting("https://techdrona-website.web.app", current) == current


def test_sync_keeps_foreign_rewrites_and_headers() -> None:
    existing = {
        "rewrites": [
            {"source": "/api/**", "function": {"functionId": "old"}},
            {"source": "/robots.txt", "destination": "/robots.txt"},
            {"source": "**", "destination": "/index.html"},
        ],
        "headers": [
            {"source": "**", "headers": [{"key": "X-Extra", "value": "1"}]},
            {"source": "/special", "headers": [{"key": "X-Special", "value": "1"}]},
        ],
    }
    out = sync.lms_hosting("https://site.example", existing)
    sources = [r["source"] for r in out["rewrites"]]
    # /college-portal{,/**} -> lmsApi (College Data Portal on Cloud Run, 2026-11-14) precede foreign rewrites.
    assert sources == ["/api/**", "/sitemap.xml", "/college-portal", "/college-portal/**", "/robots.txt", "**"]
    assert out["rewrites"][0]["function"]["functionId"] == "lmsApi"
    star = next(r for r in out["headers"] if r["source"] == "**")
    keys = [h["key"] for h in star["headers"]]
    assert keys[:2] == ["Strict-Transport-Security", "X-Robots-Tag"] and "X-Extra" in keys
    assert any(r["source"] == "/special" for r in out["headers"])
