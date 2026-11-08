"""Phase-A audit probes: support + orgs scoping."""
from __future__ import annotations

from tests.placement.world import World, idem

API = "/api/v1"


async def _ticket(client, who, org=None, cat="technical"):
    body = {"category": cat, "subject": "Video not loading", "body": "The lesson video does not load at all."}
    if org:
        body["organization_id"] = str(org)
    r = await client.post(f"{API}/support/tickets", json=body, headers=who.headers)
    assert r.status_code == 201, r.text
    return r.json()["ticket_id"]


async def test_support_coordinator_sees_internal_notes(client, world: World, db) -> None:
    stu = world.personas["student"]
    coord = world.personas["coordinator_a"]
    agent = await world.persona("agent", grants=(("support_agent", "platform", None),), is_platform=True, tier="staff")
    tid = await _ticket(client, stu, world.org_a)
    r = await client.post(f"{API}/support/tickets/{tid}/messages", json={"body": "INTERNAL: suspect account sharing, see case", "visibility": "internal"}, headers=agent.headers)
    print("AGENT_INTERNAL_NOTE", r.status_code)
    r = await client.get(f"{API}/support/tickets/{tid}", headers=stu.headers)
    print("STUDENT_VIEW", r.status_code, r.json().get("viewer"), [m.get("visibility") for m in r.json().get("messages", [])])
    r = await client.get(f"{API}/support/tickets/{tid}", headers=coord.headers)
    j = r.json()
    print("COORD_VIEW", r.status_code, j.get("viewer"), [(m.get("visibility"), m.get("body", "")[:20]) for m in j.get("messages", [])])
    r = await client.get(f"{API}/support/queue", headers=coord.headers)
    print("COORD_QUEUE", r.status_code, r.text[:300])
    r = await client.post(f"{API}/support/tickets/{tid}/messages", json={"body": "coord internal", "visibility": "internal"}, headers=coord.headers)
    print("COORD_INTERNAL_POST", r.status_code)
    tb = await _ticket(client, world.personas["student_b"], world.org_b)
    r = await client.get(f"{API}/support/tickets/{tb}", headers=coord.headers)
    print("COORD_CROSS_ORG", r.status_code, r.json().get("code"))
    r = await client.get(f"{API}/support/tickets/{tid}", headers=world.personas["student_b"].headers)
    print("OTHER_STUDENT", r.status_code)
    r = await client.post(f"{API}/support/tickets/{tid}/messages", json={"body": "x", "visibility": "internal"}, headers=stu.headers)
    print("STUDENT_INTERNAL", r.status_code, r.json().get("code"))
    r = await client.post(f"{API}/support/tickets", json={"category": "technical", "subject": "abc", "body": "0123456789", "organization_id": str(world.org_b)}, headers=stu.headers)
    print("SUPPORT_VF_NOT_MEMBER", r.status_code, r.json().get("code"))
    r = await client.post(f"{API}/support/tickets", json={"category": "technical", "subject": "a"}, headers=stu.headers)
    print("SUPPORT_VF_PYDANTIC", r.status_code, r.json().get("code"))
    r = await client.post(f"{API}/support/tickets", json={"category": "technical", "subject": "abc", "body": "0123456789", "attachments": []}, headers=stu.headers)
    print("SUPPORT_ATTACHMENTS", r.status_code, r.json().get("code"))
    r = await client.get(f"{API}/me/support/tickets?limit=101", headers=stu.headers)
    print("SUPPORT_LIMIT_101", r.status_code)


async def test_support_student_sets_status(client, world: World, db) -> None:
    stu = world.personas["student"]
    tid = await _ticket(client, stu, None)
    r = await client.patch(f"{API}/support/tickets/{tid}", json={"status": "closed"}, headers=stu.headers)
    print("STUDENT_PATCH_STATUS", r.status_code, r.json().get("code"))
    r = await client.post(f"{API}/support/tickets/{tid}/reopen", json={}, headers=stu.headers)
    print("REOPEN_OPEN", r.status_code, r.json().get("code"))
    r = await client.post(f"{API}/support/tickets/{tid}/csat", json={"score": 5}, headers=stu.headers)
    print("CSAT_OPEN", r.status_code, r.json().get("code"))


async def test_orgs_coordinator_scoping(client, world: World, db) -> None:
    c = world.personas["coordinator_a"]
    ob, bb = str(world.org_b), str(world.batch_b)
    for path in (f"/orgs/{ob}", f"/orgs/{ob}/members", f"/orgs/{ob}/batches",
                 f"/batches/{bb}", f"/batches/{bb}/members", f"/orgs/{ob}/invitations"):
        r = await client.get(f"{API}{path}", headers=c.headers)
        print("COORD_GET", path.replace(ob, "ORGB").replace(bb, "BATCHB"), r.status_code, r.json().get("code"))
    r = await client.patch(f"{API}/batches/{bb}", json={"name": "pwn"}, headers=c.headers)
    print("COORD_PATCH_B", r.status_code)
    r = await client.post(f"{API}/batches/{world.batch_a}/members", json={"user_ids": [str(world.personas["student_b"].id)]}, headers=c.headers)
    print("COORD_ADD_FOREIGN_STUDENT", r.status_code, r.json().get("code"))
    r = await client.post(f"{API}/batches/{world.batch_a}/members", json={"user_ids": [str(world.personas["student"].id)], "move_from_batch_id": bb}, headers=c.headers)
    print("COORD_MOVE_FROM_B", r.status_code, r.json().get("code"))
    r = await client.get(f"{API}/orgs", headers=c.headers)
    print("COORD_LIST_ORGS", r.status_code, [o["id"] == str(world.org_a) for o in r.json()["data"]])
    r = await client.post(f"{API}/batches/{world.batch_a2}/archive", headers=c.headers)
    print("ARCHIVE", r.status_code, r.json().get("status"))
    r = await client.post(f"{API}/batches/{world.batch_a2}/archive", headers=c.headers)
    print("ARCHIVE_AGAIN", r.status_code, r.json().get("status"))
    r = await client.post(f"{API}/batches/{world.batch_a2}/members", json={"user_ids": [str(world.personas["student"].id)]}, headers=c.headers)
    print("ADD_TO_ARCHIVED", r.status_code, r.json())
    r = await client.patch(f"{API}/batches/{world.batch_a2}", json={"status": "active"}, headers=c.headers)
    print("UNARCHIVE_VIA_PATCH", r.status_code, r.json().get("status"))
    r = await client.post(f"{API}/orgs/{world.org_a}/batches", json={"name": "x", "code": "C1", "starts_on": "2026-12-01", "ends_on": "2026-01-01"}, headers=c.headers)
    print("BATCH_VF", r.status_code, r.json().get("code"))
    r = await client.post(f"{API}/orgs/{world.org_a}/batches", json={"name": "x", "code": "bad code!"}, headers=c.headers)
    print("BATCH_VF_PYD", r.status_code, r.json().get("code"))
    tr = world.personas["trainer_a"]
    r = await client.get(f"{API}/orgs/{world.org_a}/members?batch_id={world.batch_a}", headers=tr.headers)
    print("TRAINER_ORG_MEMBERS", r.status_code, r.json().get("code"))
    r = await client.get(f"{API}/batches/{world.batch_a2}/members", headers=tr.headers)
    print("TRAINER_OTHER_BATCH", r.status_code, r.json().get("code"))
    s = world.personas["student"]
    r = await client.get(f"{API}/orgs/{world.org_a}/members", headers=s.headers)
    print("STUDENT_ROSTER", r.status_code, r.json().get("code"))


async def test_orgs_trainer_remove_member(client, world: World, db) -> None:
    tr = world.personas["trainer_a"]
    s = world.personas["student"]
    r = await client.delete(f"{API}/batches/{world.batch_a}/members/{s.id}", headers=tr.headers)
    print("TRAINER_REMOVE_BATCH_MEMBER", r.status_code, r.text[:120])


def test_csv_import_parse() -> None:
    from app.modules.orgs.csv_import import parse_roster

    csv = (
        "full_name,email,roll_number\n"
        "+SUM(1+1)*cmd,a@x.com,R1\n"
        "-2+3,b@x.com,R2\n"
        '"\t=HYPERLINK(""http://e"")",c@x.com,R3\n'
        "Ok Name,d@x.com,R4\n"
    )
    v, res = parse_roster(csv)
    print("CSV_NAMES", [r.full_name for r in v])


async def test_csv_import_api(client, world: World, db) -> None:
    c = world.personas["coordinator_a"]
    csv = "full_name,email,roll_number\nA One,a1@example.com,R1\nA Two,bad-email,R2\nA Three,a1@example.com,R3\n"
    r = await client.post(f"{API}/orgs/{world.org_a}/imports", json={"csv_text": csv}, headers={**c.headers, **idem()})
    print("IMPORT", r.status_code, r.json().get("row_results"))
    r = await client.post(f"{API}/orgs/{world.org_a}/imports", json={"csv_text": "foo,bar\n1,2\n"}, headers={**c.headers, **idem()})
    print("IMPORT_BADHDR", r.status_code, r.json().get("code"))
    r = await client.post(f"{API}/orgs/{world.org_b}/imports", json={"csv_text": csv}, headers={**c.headers, **idem()})
    print("IMPORT_CROSS_ORG", r.status_code, r.json().get("code"))
    r = await client.post(f"{API}/orgs/{world.org_a}/imports", json={"csv_text": csv, "batch_id": str(world.batch_b)}, headers={**c.headers, **idem()})
    print("IMPORT_FOREIGN_BATCH", r.status_code, r.json().get("code"))
