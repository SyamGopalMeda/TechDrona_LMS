"""Student management on the all-Firestore stack (no Postgres): Excel import dry run + apply
(duplicates, existing account, unknown course / batch, idempotency, temporary passwords shown
once), bulk enrolment of existing accounts, Add user with a student type + generated login,
and the permissions (``user.invite`` + ``enrolment.manage``)."""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

import app.core.firestore.core_store
import app.modules.admin.store_specs
import app.modules.audit.store_specs
import app.modules.catalog.store_specs  # noqa: F401 - registers the collections used below
from app.core.db import NO_POSTGRES
from app.core.firestore.store import ScopedStore
from app.core.ids import uuid7
from app.core.time import utcnow
from tests.firestore.conftest import fs_client  # noqa: F401
from tests.identity.fs.conftest import fs, fs_user, http  # noqa: F401
from tests.identity.fs.test_http_sessions_rbac import admin, sign_in

PATH = "/admin/students/import"


@pytest.fixture
def admin_http(http: Any, monkeypatch: pytest.MonkeyPatch) -> Any:  # noqa: F811
    """Every ``TD_STORE_<MODULE>=firestore`` (no Postgres anywhere)."""
    from app.core.firestore.backend import MODULES, reset_store_backends

    for m in MODULES:
        monkeypatch.setenv(f"TD_STORE_{m.upper()}", "firestore")
    reset_store_backends()
    return http


def _idem() -> dict[str, str]:
    return {"Idempotency-Key": uuid.uuid4().hex}


async def _course(slug: str, title: str, *, published: bool = True) -> uuid.UUID:
    from app.modules.catalog.store_specs import COURSES, VERSIONS

    now = utcnow()
    cid, vid, staff = uuid7(), uuid7(), uuid7()
    base = {"organization_id": None, "created_at": now, "updated_at": now}
    s = ScopedStore.system("firestore.backfill")
    await s.import_documents(
        COURSES,
        [
            (
                str(cid),
                {
                    **base,
                    "id": str(cid),
                    "slug": slug,
                    "title": title,
                    "course_kind": "course",
                    "visibility": "public",
                    "status": "published" if published else "draft",
                    "is_free": False,
                    "current_version_id": str(vid) if published else None,
                    "completeness_pct": "0",
                    "created_by": str(staff),
                    "deleted_at": None,
                },
            )
        ],
    )
    if published:
        await s.import_documents(
            VERSIONS,
            [
                (
                    str(vid),
                    {
                        **base,
                        "id": str(vid),
                        "course_id": str(cid),
                        "version_no": 1,
                        "title": title,
                        "outcomes": [],
                        "language": "en",
                        "tags": [],
                        "status": "published",
                        "created_by": str(staff),
                        "published_at": now,
                        "outline": [],
                        "lesson_count": 0,
                        "duration_seconds": 0,
                    },
                )
            ],
        )
    return cid


async def _enrolled(user_id: uuid.UUID, course_id: uuid.UUID) -> Any:
    from app.modules.learning import service as learning

    return await learning.get_enrolment(NO_POSTGRES, user_id, course_id)


async def _batch_member_ids(http: Any, bid: str) -> set[str]:  # noqa: F811
    r = await http.get(f"/batches/{bid}/members")
    assert r.status_code == 200, r.text
    return {m["user_id"] for m in r.json()["data"]}


async def _audit_actions() -> list[dict[str, Any]]:
    docs = await ScopedStore.system("test.scan").scan("audit_outbox")
    return [json.loads(d.data["record_json"]) for d in docs]


def _row(**kw: Any) -> dict[str, Any]:
    return {"full_name": "Asha Rao", "email": "asha@x.in", "mobile": "9876543210", **kw}


# --------------------------------------------------------------------------- import


async def test_import_end_to_end(admin_http: Any) -> None:
    from app.modules.identity import public as ipub

    http = admin_http  # noqa: F811
    await admin(http, "boss@x.in")
    py = await _course("python-101", "Python Basics")
    await _course("draft-1", "Draft Course", published=False)
    r = await http.post("/batches", {"name": "March Batch", "code": "MAR-26"})
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    existing = await fs_user("old@x.in", full_name="Old Student")

    r = await http.get("/admin/students/import/options")
    assert r.status_code == 200, r.text
    opts = r.json()
    assert [c["slug"] for c in opts["courses"]] == ["python-101"]  # drafts are not offered
    assert [b["name"] for b in opts["batches"]] == ["March Batch"]
    assert opts["max_rows"] == 500 and opts["email_integrated"] is False

    rows = [
        _row(
            row=2,
            course="python-101",
            batch="March Batch",
            student_type="Internship",
            start_date="01-12-2026",
        ),
        _row(row=3, full_name="Bala K", email="BALA@x.in", mobile="", course="Python Basics", batch="mar-26"),
        _row(row=4, full_name="Asha Again", email="asha@x.in", mobile=""),  # duplicate email
        _row(row=5, full_name="Old Student", email="old@x.in", mobile="", course="python-101"),  # existing
        _row(row=6, full_name="Cara", email="cara@x.in", mobile="12", course="nope"),  # bad mobile + course
        _row(row=7, full_name="Dev", email="dev@x.in", mobile="", batch="Unknown"),  # unknown batch
        _row(row=8, full_name="Esha", email="not-an-email", mobile=""),
        _row(row=9, full_name="Farah", email="farah@x.in", mobile="", course="draft-1"),  # unpublished
        _row(
            row=10,
            full_name="Gita",
            email="gita@x.in",
            mobile="",
            end_date="2026-01-01",
            start_date="2026-02-01",
        ),
    ]
    body = {"rows": rows, "confirm_adult": True, "reason": "March intake"}

    # dry run: per-row status, nothing written
    r = await http.post(PATH, body, params={"dry_run": "true"})
    assert r.status_code == 200, r.text
    d = r.json()
    st = {x["row"]: x["status"] for x in d["rows"]}
    assert st == {
        2: "new",
        3: "new",
        4: "error",
        5: "existing",
        6: "error",
        7: "error",
        8: "error",
        9: "error",
        10: "error",
    }
    by = {x["row"]: x for x in d["rows"]}
    assert "Same email as row 2." in by[4]["errors"]
    assert any("mobile" in e for e in by[6]["errors"]) and any("Unknown course" in e for e in by[6]["errors"])
    assert any("Unknown batch" in e for e in by[7]["errors"])
    assert any("published" in e for e in by[9]["errors"])
    assert any("before the start" in e for e in by[10]["errors"])
    assert by[2]["student_type"] == "internship" and by[3]["student_type"] == "course"
    assert d["counts"]["new"] == 2 and d["counts"]["existing"] == 1 and d["counts"]["errors"] == 6
    assert await ipub.find_user(NO_POSTGRES, "email", "asha@x.in") is None

    # apply needs the adult confirmation and an Idempotency-Key
    r = await http.post(PATH, {**body, "confirm_adult": False}, headers=_idem())
    assert r.status_code == 422, r.text
    r = await http.post(PATH, body)
    assert r.status_code == 400, r.text

    key = _idem()
    r = await http.post(PATH, body, headers=key)
    assert r.status_code == 200, r.text
    d = r.json()
    by = {x["row"]: x for x in d["rows"]}
    assert d["credentials_withheld"] is False
    assert by[2]["status"] == "created" and by[3]["status"] == "created" and by[5]["status"] == "existing"
    assert by[4]["status"] == "error" and by[6]["status"] == "error"
    assert d["counts"]["created"] == 2 and d["counts"]["existing"] == 1 and d["counts"]["errors"] == 6
    for n in (2, 3):
        assert by[n]["username"].startswith("td") and len(by[n]["username"]) == 8
        assert by[n]["temporary_password"] and len(by[n]["temporary_password"]) == 10
        assert by[n]["enrolled"] is True and by[n]["added_to_batch"] is True
    assert by[5]["temporary_password"] is None and by[5]["enrolled"] is True

    asha = await ipub.find_user(NO_POSTGRES, "email", "asha@x.in")
    assert asha is not None and asha.account_origin == "staff_created" and asha.must_change_password
    assert asha.phone_e164 == "+919876543210" and asha.username == by[2]["username"]
    bala = await ipub.find_user(NO_POSTGRES, "email", "bala@x.in")
    assert bala is not None
    for uid in (asha.id, bala.id, existing.id):
        enr = await _enrolled(uid, py)
        assert enr is not None and enr.status == "active", uid
    assert (await _enrolled(asha.id, py)).batch_id == uuid.UUID(bid)  # type: ignore[union-attr]
    assert {str(asha.id), str(bala.id)} <= await _batch_member_ids(http, bid)

    # the student record + account view
    r = await http.get(f"/admin/users/{asha.id}")
    assert r.status_code == 200, r.text
    assert r.json()["student"]["student_type"] == "internship"
    assert r.json()["student"]["start_date"] == "2026-12-01"

    # the temporary password works (sign in with the username) and is not in the replay record
    r = await http.post(PATH, body, headers=key)
    assert r.status_code == 200 and r.headers.get("Idempotency-Replayed") == "true", r.text
    replay = r.json()
    assert replay["credentials_withheld"] is True
    assert all(x["temporary_password"] is None for x in replay["rows"])
    stored = [d.data for d in await ScopedStore.system("test.scan").scan("idempotency_keys")]
    assert stored and all(by[2]["temporary_password"] not in json.dumps(x, default=str) for x in stored)

    # audit: counts only, no personal data
    recs = [x for x in await _audit_actions() if x["action"] == "admin.students.imported"]
    assert len(recs) == 1
    blob = json.dumps(recs[0], default=str)
    assert "asha" not in blob.lower() and by[2]["temporary_password"] not in blob
    assert all(by[2]["temporary_password"] not in json.dumps(x, default=str) for x in await _audit_actions())

    # idempotent per email: a new key, the same file -> linked, never duplicated
    r = await http.post(PATH, body, headers=_idem())
    assert r.status_code == 200, r.text
    again = {x["row"]: x for x in r.json()["rows"]}
    assert again[2]["status"] == "existing" and again[3]["status"] == "existing"
    assert again[2]["user_id"] == str(asha.id) and again[2]["enrolled"] is False
    assert any("Already enrolled" in w for w in again[2]["warnings"])
    assert r.json()["counts"]["created"] == 0
    users = await ipub.list_users(NO_POSTGRES)
    assert len([u for u in users if u.email == "asha@x.in"]) == 1

    # privacy erasure removes the student record (registered provider)
    from app.modules.admin import privacy as prv
    from app.modules.admin import students as stu

    assert prv.erasure_providers()["student_records"] is stu.erase_student_record
    assert await stu.erase_student_record(NO_POSTGRES, asha.id) == {"student_records": 1}
    assert await stu.student_record(asha.id) is None


async def test_partial_failure_does_not_abort(admin_http: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.admin import students as stu
    from app.modules.identity import public as ipub

    http = admin_http  # noqa: F811
    await admin(http, "boss3@x.in")
    py = await _course("py-2", "Python Two")
    real = stu.enrol

    async def flaky(session: Any, principal: Any, user_id: uuid.UUID, **kw: Any) -> Any:
        u = await ipub.get_user(session, user_id)
        if u is not None and u.email == "bad@x.in":
            raise RuntimeError("enrolment backend down")
        return await real(session, principal, user_id, **kw)

    monkeypatch.setattr(stu, "enrol", flaky)
    rows = [
        _row(row=2, email="ok1@x.in", mobile="", course="py-2"),
        _row(row=3, email="bad@x.in", mobile="", course="py-2"),
        _row(row=4, email="ok2@x.in", mobile="", course="py-2"),
    ]
    r = await http.post(PATH, {"rows": rows, "confirm_adult": True}, headers=_idem())
    assert r.status_code == 200, r.text
    by = {x["row"]: x for x in r.json()["rows"]}
    assert [by[n]["status"] for n in (2, 3, 4)] == ["created", "created", "created"]
    assert by[3]["enrolled"] is False and any("Enrolment failed" in w for w in by[3]["warnings"])
    assert by[3]["temporary_password"]  # the account exists: its login is still shown
    ok2 = await ipub.find_user(NO_POSTGRES, "email", "ok2@x.in")
    assert ok2 is not None and (await _enrolled(ok2.id, py)) is not None


# --------------------------------------------------------------------------- bulk enrol existing


async def test_bulk_enrol_existing_accounts(admin_http: Any) -> None:
    http = admin_http  # noqa: F811
    await admin(http, "boss4@x.in")
    py = await _course("py-3", "Python Three")
    r = await http.post("/batches", {"name": "April", "code": "APR"})
    bid = r.json()["id"]
    a = await fs_user("a@x.in", full_name="A Student")
    b = await fs_user("b@x.in", full_name="B Student")
    ghost = uuid7()
    body = {"user_ids": [str(a.id), str(b.id), str(ghost)], "course": str(py), "batch": bid}

    r = await http.post(PATH, body, params={"dry_run": "true"})
    assert r.status_code == 200, r.text
    assert [x["status"] for x in r.json()["rows"]] == ["existing", "existing", "error"]

    r = await http.post(PATH, {"user_ids": [str(a.id)]}, headers=_idem())
    assert r.status_code == 422, r.text  # a course or a batch is required

    r = await http.post(PATH, body, headers=_idem())
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["counts"]["enrolled"] == 2 and d["counts"]["added_to_batch"] == 2 and d["counts"]["errors"] == 1
    assert (await _enrolled(a.id, py)) is not None and (await _enrolled(b.id, py)) is not None
    assert {str(a.id), str(b.id)} <= await _batch_member_ids(http, bid)
    assert all(x["temporary_password"] is None for x in d["rows"])
    assert any(x["action"] == "admin.students.enrolled" for x in await _audit_actions())

    r = await http.post(PATH, {"rows": [_row()], "user_ids": [str(a.id)]}, params={"dry_run": "true"})
    assert r.status_code == 400, r.text  # one mode at a time (body schema)


# --------------------------------------------------------------------------- Add user (individual)


async def test_add_user_student_type_generated_login_and_enrolment(admin_http: Any) -> None:
    from app.modules.identity import public as ipub

    http = admin_http  # noqa: F811
    await admin(http, "boss5@x.in")
    py = await _course("py-4", "Python Four")
    r = await http.post("/batches", {"name": "Interns", "code": "INT-1"})
    bid = r.json()["id"]
    body = {
        "full_name": "Ira Intern",
        "email": "ira@x.in",
        "reason": "summer intern",
        "confirm_adult": True,
        "student_type": "internship",
        "course_id": str(py),
        "batch_id": bid,
    }
    key = _idem()
    r = await http.post("/admin/users", body, headers=key)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["username"].startswith("td") and len(d["temporary_password"]) == 10
    assert d["must_change_password"] is True and d["student_type"] == "internship"
    assert d["enrolment"]["enrolled"] is True and d["enrolment"]["added_to_batch"] is True
    uid = uuid.UUID(d["user_id"])
    assert (await _enrolled(uid, py)) is not None
    u = await ipub.get_user(NO_POSTGRES, uid)
    assert u is not None and u.username == d["username"] and u.must_change_password
    r = await http.get(f"/admin/users/{uid}")
    assert r.json()["student"]["student_type"] == "internship"
    replay = await http.post("/admin/users", body, headers=key)
    assert replay.status_code == 201 and replay.json()["temporary_password"] is None

    # a typed password still works as before (no username, nothing generated)
    r = await http.post(
        "/admin/users",
        {
            "full_name": "Typed Pw",
            "email": "typed@x.in",
            "password": "Correct-horse-battery-9",
            "reason": "staff",
            "confirm_adult": True,
        },
        headers=_idem(),
    )
    assert r.status_code == 201, r.text
    assert r.json()["username"] is None and r.json()["temporary_password"] is None

    r = await http.post(
        "/admin/users", {**body, "email": "x2@x.in", "course_id": str(uuid7())}, headers=_idem()
    )
    assert r.status_code == 422, r.text  # unknown course


# --------------------------------------------------------------------------- permissions


async def test_permissions(admin_http: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.identity.fs import test_http_sessions_rbac as rbac_tests

    monkeypatch.setitem(rbac_tests.TIERS, "content_manager", "staff")
    http = admin_http  # noqa: F811
    learner = await fs_user("learner@x.in")
    await sign_in(http, learner)
    body = {"rows": [_row()], "confirm_adult": True}
    r = await http.post(PATH, body, params={"dry_run": "true"})
    assert r.status_code == 403, r.text
    r = await http.get("/admin/students/import/options")
    assert r.status_code == 403, r.text
    r = await http.post("/admin/students/send-login", {"user_ids": [str(learner.id)]}, headers=_idem())
    assert r.status_code == 403, r.text

    cm = await fs_user("cm@x.in", roles=("content_manager",))
    await sign_in(http, cm, role="content_manager")
    r = await http.post(PATH, body, params={"dry_run": "true"})
    assert r.status_code == 403, r.text


async def test_send_login_needs_email(admin_http: Any) -> None:
    http = admin_http  # noqa: F811
    await admin(http, "boss6@x.in")
    s = await fs_user("s@x.in")
    r = await http.post("/admin/students/send-login", {"user_ids": [str(s.id)]}, headers=_idem())
    assert r.status_code == 409 and r.json()["reason"] == "email_not_connected", r.text
