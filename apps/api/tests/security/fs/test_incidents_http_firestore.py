"""SEC-40..42 incident register through the FastAPI app on Firestore (no Postgres)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.modules.identity import clock

FS_MODULES = ("security", "audit", "core", "admin")
P = "/api/v1/security/incidents"


async def test_incident_open_list_update(fs_http: Any, make_principal: Any) -> None:
    client, _rec, auth = fs_http
    p = make_principal(
        is_platform=True, roles=("super_admin",), tier="privileged", last_step_up_at=clock.now()
    )
    for perm in ("security.incident.read", "security.incident.manage"):
        auth.grant(p, perm)
    h = auth.login(p)
    detected = clock.now() - timedelta(hours=1)
    r = await client.post(
        P,
        json={
            "title": "Leaked key",
            "severity": "high",
            "detected_at": detected.isoformat(),
            "is_personal_data_breach": True,
            "certin_reportable": True,
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    inc = r.json()
    assert inc["status"] == "detected" and inc["version"] == 1 and inc["incident_ref"].startswith("INC-")
    assert inc["certin_due_at"] is not None and inc["dpb_report_due_at"] is not None
    future = await client.post(
        P,
        json={
            "title": "Future one",
            "severity": "low",
            "detected_at": (clock.now() + timedelta(hours=1)).isoformat(),
        },
        headers=h,
    )
    assert future.status_code == 422, future.text
    lst = (await client.get(P, headers=h)).json()["data"]
    assert [x["incident_id"] for x in lst] == [inc["incident_id"]]
    up = await client.patch(
        f"{P}/{inc['incident_id']}",
        json={"status": "closed", "timeline_entry": "contained"},
        headers={**h, "If-Match": '"v1"'},
    )
    assert up.status_code == 200, up.text
    assert up.json()["status"] == "closed" and up.json()["version"] == 2
    stale = await client.patch(
        f"{P}/{inc['incident_id']}", json={"status": "detected"}, headers={**h, "If-Match": '"v1"'}
    )
    assert stale.status_code in (409, 412)
    reader = make_principal(is_platform=True)
    assert (await client.get(P, headers=auth.login(reader))).status_code == 403
