"""Audit probe: dump every API route with tag, idle, permission and step-up deps."""
from __future__ import annotations
import json, os
from pathlib import Path

def test_dump_routes() -> None:
    from app.main import create_app
    from app.core.routing import iter_api_routes, _dependant_calls, find_route_guard_violations, ROUTE_TAG_KEY, IDLE_KEY
    app = create_app()
    rows = []
    for route, path in iter_api_routes(app):
        calls = list(_dependant_calls(route.dependant))
        perms = sorted({getattr(c, "td_permission") for c in calls if hasattr(c, "td_permission")})
        names = sorted({getattr(c, "__name__", repr(c)) for c in calls})
        stepup = [n for n in names if n.startswith("require_step_up")]
        extra = route.openapi_extra or {}
        rows.append({"m": sorted(route.methods or []), "p": path, "tag": extra.get(ROUTE_TAG_KEY), "idle": extra.get(IDLE_KEY),
                     "perms": perms, "stepup": stepup, "deps": [n for n in names if n.startswith("require") or "principal" in n or "staff" in n.lower() or "perm" in n.lower()]})
    out = Path(os.environ.get("AUDIT_OUT", "route_dump.json"))
    out.write_text(json.dumps(rows, indent=1))
    print("violations", find_route_guard_violations(app))
    print("routes", len(rows))
