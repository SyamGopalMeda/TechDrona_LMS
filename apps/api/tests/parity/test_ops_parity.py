"""Parity: support, admin accounts / flags, hub and notifications over HTTP on the Firebase stack.

VM expectations (``tests/support``, ``tests/admin``, ``tests/hub``, ``tests/notifications``):
SUP ticket 201 (with a related paid order / attempt), staff view 200, message 201, patch 200,
learner list 200; ADM dashboard 200, user search/detail 200, deactivate/reactivate 200, flag
patch 200; support user 360 200; hub modules / integrations 200; notifications inbox 200,
read-all 200.
"""

from __future__ import annotations

from tests.parity.harness import World


async def _seed_flag() -> None:
    from app.core.firestore.store import ScopedStore
    from app.core.ids import uuid7
    from app.modules.admin import store_specs as sp

    await ScopedStore.system("firestore.backfill").import_documents(
        sp.FLAGS,
        [
            (
                "x.parity",
                {
                    "id": str(uuid7()),
                    "flag_key": "x.parity",
                    "description": "parity",
                    "is_enabled": False,
                    "rollout_percent": 0,
                    "user_allowlist": [],
                    "updated_by": None,
                },
            )
        ],
    )


async def test_support_ticket_flow(web: World) -> None:
    w = web
    student, sh = await w.learner("asker")
    _, staff = await w.staff("agent")
    body = {"category": "assessment", "subject": "Test stuck", "body": "My test froze in section two."}
    r = await w.call("POST", "/support/tickets", sh, expect=201, json=body)
    tid = r.json()["id"] if "id" in r.json() else r.json()["ticket_id"]
    await w.call("POST", "/support/tickets", sh, expect=201, json={**body, "category": "billing"})
    await w.call("GET", "/me/support/tickets", sh)
    await w.call("GET", f"/support/tickets/{tid}", sh)
    await w.call("GET", "/support/queue", staff)
    await w.call("GET", f"/support/tickets/{tid}", staff)
    await w.call("PATCH", f"/support/tickets/{tid}", staff, json={"assign_to_me": True, "priority": "high"})
    await w.call(
        "POST", f"/support/tickets/{tid}/messages", staff, expect=201, json={"body": "Looking into it."}
    )
    await w.call("POST", f"/support/tickets/{tid}/messages", sh, expect=201, json={"body": "Thanks!"})
    await w.call(
        "GET", f"/support/users/{student.user_id}", staff, params={"reason_code": "ticket", "ticket_id": tid}
    )
    await w.relay()  # outbox consumers, as the Firebase worker runs them


async def test_admin_accounts_and_flags(web: World) -> None:
    w = web
    await _seed_flag()
    target, _ = await w.learner("managed")
    _, ah = await w.staff("adm")
    await w.call("GET", "/admin/dashboard", ah)
    await w.call("GET", "/admin/users", ah)
    await w.call("GET", f"/admin/users/{target.user_id}", ah)
    await w.call(
        "POST", f"/admin/users/{target.user_id}/deactivate", ah, idem=True, json={"reason": "Parity check"}
    )
    await w.call(
        "POST", f"/admin/users/{target.user_id}/reactivate", ah, idem=True, json={"reason": "Parity check"}
    )
    await w.call("GET", "/admin/feature-flags", ah)
    r = await w.call(
        "PATCH", "/admin/feature-flags/x.parity", ah, json={"is_enabled": True, "rollout_percent": 50}
    )
    assert r.json()["is_enabled"] is True
    await w.call("GET", "/admin/courses/overview", ah)
    await w.relay()  # outbox consumers, as the Firebase worker runs them


async def test_hub_and_notifications(web: World) -> None:
    w = web
    _, sh = await w.learner("reader")
    await w.call("GET", "/me/modules", sh)
    await w.call("GET", "/public/integrations", {})
    r = await w.call("GET", "/me/notifications", sh)
    await w.call("POST", "/me/notifications/read-all", sh)
    for n in r.json().get("data", []):
        await w.call("POST", f"/me/notifications/{n['id']}/read", sh)
