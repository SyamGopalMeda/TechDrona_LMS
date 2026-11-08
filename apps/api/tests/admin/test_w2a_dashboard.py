"""w2a (rest of ADM-22): the admin dashboard pending-approvals count skips requests whose
per-request SoD check blocks the viewer (e.g. a change to the viewer's own roles)."""

from __future__ import annotations

from typing import Any

from tests.security.helpers import idem, staff, staff_browser


async def test_adm22_count_excludes_requests_the_viewer_is_the_subject_of(client, db) -> None:
    sa1, sa2, sa3 = (
        await staff(db, "super_admin"),
        await staff(db, "super_admin"),
        await staff(db, "super_admin"),
    )
    b1 = await staff_browser(client, sa1, ip="198.18.4.1")
    b2 = await staff_browser(client, sa2, ip="198.18.4.2")
    b3 = await staff_browser(client, sa3, ip="198.18.4.3")

    async def pending(b: Any) -> int:
        d = await b.get("/admin/dashboard")
        assert d.status_code == 200, d.text
        return int(d.json()["approvals"]["pending"])

    c2, c3 = await pending(b2), await pending(b3)
    r = await b1.post(
        "/rbac/grants",
        {"user_id": str(sa2.id), "role_key": "super_admin", "scope_type": "platform", "reason": "cover"},
        headers=idem(),
    )
    assert r.status_code == 202, r.text
    aid = r.json()["approval_request_id"]
    assert await pending(b2) == c2  # grantee: SoD-05 blocks the decision, so not counted
    assert await pending(b3) == c3 + 1
    denied = await b2.post(f"/admin/approvals/{aid}/approve", {}, headers=idem())
    assert denied.status_code == 403 and denied.json()["code"] == "sod_violation", denied.text
