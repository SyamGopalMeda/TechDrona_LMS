"""RBAC audit 2026-11-13 (docs/firebase/agents/role-api-audit.md): authorization regressions on
the Firebase stack (every module on Firestore, no Postgres) with the REAL permission checker
(``RbacPermissionChecker`` over the role catalogue) instead of the harness' allow-all staff.

* admissions: ``/me/admissions*`` matched website registrations by an UNVERIFIED account email.
* paths: a batch-A trainer could archive a path (revoking batch B's allocations) and publish /
  unpublish / edit articles aimed at batch B.
* learning: a batch-A grade grant covered allocations of a batch-A structured assignment to batch B.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.core.company import COMPANY_ORG_ID
from app.core.principal import Principal, RoleGrant


@pytest.fixture
async def rw(web: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """``web`` with the real RBAC checker (role catalogue = deployed rbac collections)."""
    import app.modules.orgs.store_specs  # noqa: F401  (register the collections)
    from app.core.firestore.store import ScopedStore
    from app.core.time import utcnow
    from app.modules.identity.fs_codec import obj_doc
    from app.modules.orgs.models import Organization
    from app.modules.rbac.service import RbacPermissionChecker, reset_role_permission_cache

    now = utcnow()
    org = Organization(
        id=COMPANY_ORG_ID,
        name="Tech Drona",
        slug="techdrona",
        org_type="company",
        status="active",
        is_synthetic=False,
        created_at=now,
        updated_at=now,
    )
    await ScopedStore.system("test.seed").import_documents("organizations", [(str(org.id), obj_doc(org))])
    reset_role_permission_cache()
    monkeypatch.setattr(web.auth, "has_permission", RbacPermissionChecker().has_permission)
    return web


async def _batch(w: Any, ah: dict[str, str], code: str) -> uuid.UUID:
    r = await w.call("POST", "/batches", ah, expect=201, json={"name": f"Batch {code}", "code": code})
    return uuid.UUID(r.json()["id"])


async def _trainer(w: Any, batch_id: uuid.UUID, name: str = "trainer") -> tuple[Principal, dict[str, str]]:
    from app.core.ids import uuid7
    from app.core.time import utcnow

    now = utcnow()
    p = Principal(
        user_id=uuid7(),
        session_id=uuid7(),
        tier="staff",
        org_ids=(COMPANY_ORG_ID,),
        grants=(RoleGrant("trainer", "batch", batch_id),),
        aal=2,
        mfa_level="totp",
        auth_time=now,
        last_step_up_at=now,
        is_minor=False,
        device_id=uuid.uuid4(),
    )
    await w._user(p, name=name)
    return p, w.auth.login(p)


# --------------------------------------------------------------------------- admissions


async def test_me_admissions_ignores_unverified_email(rw: Any) -> None:
    from app.core.db import NO_POSTGRES
    from app.modules.identity import public as idp
    from app.modules.identity.models import User
    from tests.admissions.firestore.test_admissions_store import _registration
    from tests.commerce.firestore.conftest import FakeSession

    w = rw
    victim_email = f"victim-{uuid.uuid4().hex[:8]}@example.test"
    reg = await _registration(FakeSession().as_platform(), email=victim_email)

    # An attacker self-signs up with the website registrant's address: email NOT verified.
    p = w.make_principal(roles=("student",), is_minor=False, device_id=uuid.uuid4())
    await idp.create_user(
        NO_POSTGRES,
        User(id=p.user_id, email=victim_email, status="pending_verification", is_minor=False),
    )
    h = w.auth.login(p)

    r = await w.call("GET", "/me/admissions", h)
    assert r.json() == {"data": []}, r.text
    r = await w.call("GET", f"/me/admissions/plans/{reg.course_slug}", h)
    assert r.json()["registration"] is None and r.json()["past"] == [], r.text

    # The genuine owner (verified address) still sees it.
    owner = w.make_principal(roles=("student",), is_minor=False, device_id=uuid.uuid4())
    from app.core.time import utcnow

    other_email = f"owner-{uuid.uuid4().hex[:8]}@example.test"
    reg2 = await _registration(FakeSession().as_platform(), email=other_email)
    await idp.create_user(
        NO_POSTGRES,
        User(
            id=owner.user_id,
            email=other_email,
            email_verified_at=utcnow(),
            status="active",
            is_minor=False,
        ),
    )
    r = await w.call("GET", "/me/admissions", w.auth.login(owner))
    assert [d["registration_id"] for d in r.json()["data"]] == [str(reg2.id)], r.text


# --------------------------------------------------------------------------- paths


async def _allocation(path_id: uuid.UUID, batch_id: uuid.UUID, by: uuid.UUID) -> uuid.UUID:
    from app.core.db import NO_POSTGRES
    from app.core.ids import uuid7
    from app.modules.paths import store as st
    from app.modules.paths.models import PathAllocation

    a = PathAllocation(
        id=uuid7(),
        organization_id=COMPANY_ORG_ID,
        path_id=path_id,
        path_version_id=uuid7(),
        target_type="batch",
        batch_id=batch_id,
        user_ids=[],
        flow="lenient",
        sequential=False,
        start_date=date.today(),
        pace={"mode": "auto"},
        weekly_hours=Decimal("5"),
        total_hours=Decimal("5"),
        finish_date=date.today() + timedelta(days=7),
        status="active",
        created_by=by,
    )
    await st.insert_allocation(NO_POSTGRES, a)  # type: ignore[arg-type]
    return a.id


async def test_trainer_cannot_archive_path_allocated_to_other_batch(rw: Any) -> None:
    from app.core.db import NO_POSTGRES
    from app.modules.paths import store as st

    w = rw
    admin, ah = await w.staff()
    ba, bb = await _batch(w, ah, "A-1"), await _batch(w, ah, "B-1")
    _, th = await _trainer(w, ba)
    pid = uuid.UUID(
        (await w.call("POST", "/paths", ah, expect=201, json={"title": "Company path"})).json()["id"]
    )
    alloc_b = await _allocation(pid, bb, admin.user_id)

    # batch-A trainer: cannot revoke batch B's allocation directly, nor by archiving the path
    await w.call("DELETE", f"/path-allocations/{alloc_b}", th, expect=403)
    await w.call("DELETE", f"/paths/{pid}", th, expect=403)
    a = await st.get_allocation(NO_POSTGRES, alloc_b)  # type: ignore[arg-type]
    assert a is not None and a.status == "active"
    assert (await st.get_path(NO_POSTGRES, pid)).status != "archived"  # type: ignore[arg-type,union-attr]

    # a path allocated only to the trainer's own batch can still be archived by them
    pid2 = uuid.UUID((await w.call("POST", "/paths", th, expect=201, json={"title": "Mine"})).json()["id"])
    alloc_a = await _allocation(pid2, ba, admin.user_id)
    await w.call("DELETE", f"/paths/{pid2}", th, expect=204)
    a = await st.get_allocation(NO_POSTGRES, alloc_a)  # type: ignore[arg-type]
    assert a is not None and a.status == "revoked"
    # the admin (platform) archives the cross-batch path
    await w.call("DELETE", f"/paths/{pid}", ah, expect=204)


async def test_trainer_article_audience_limited_to_own_batches(rw: Any) -> None:
    w = rw
    _, ah = await w.staff()
    ba, bb = await _batch(w, ah, "A-2"), await _batch(w, ah, "B-2")
    _, th = await _trainer(w, ba)
    body = {"title": "Notes", "body_md": "hello"}
    art = (await w.call("POST", "/path-articles", th, expect=201, json=body)).json()["id"]

    await w.call(
        "POST",
        f"/path-articles/{art}/publish",
        th,
        expect=403,
        json={"audience": "batches", "batch_ids": [str(ba), str(bb)]},
    )
    await w.call(
        "POST", f"/path-articles/{art}/publish", th, json={"audience": "batches", "batch_ids": [str(ba)]}
    )
    await w.call("PATCH", f"/path-articles/{art}", th, json={"title": "Notes v2"})

    # an admin's article published to batch B: the batch-A trainer cannot touch it
    adm = (await w.call("POST", "/path-articles", ah, expect=201, json=body)).json()["id"]
    await w.call(
        "POST", f"/path-articles/{adm}/publish", ah, json={"audience": "batches", "batch_ids": [str(bb)]}
    )
    await w.call("PATCH", f"/path-articles/{adm}", th, expect=403, json={"title": "defaced"})
    await w.call("POST", f"/path-articles/{adm}/unpublish", th, expect=403)
    await w.call("DELETE", f"/path-articles/{adm}", th, expect=403)
    await w.call("POST", f"/path-articles/{adm}/unpublish", ah)


# --------------------------------------------------------------------------- learning (structured)


async def test_batch_grade_grant_does_not_cover_other_batch_allocation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_ensure_grade``: a grade grant on the assignment's batch A covers its batch-A and
    user-list allocations, not an allocation of the same assignment to batch B."""
    from types import SimpleNamespace

    from app.core.auth import ScopeRef
    from app.core.errors import ProblemError
    from app.modules.learning import structured_api as sa

    ba, bb = uuid.uuid4(), uuid.uuid4()
    aid = uuid.uuid4()
    al_a = SimpleNamespace(id=uuid.uuid4(), batch_id=ba, evaluator_ids=[])
    al_b = SimpleNamespace(id=uuid.uuid4(), batch_id=bb, evaluator_ids=[])
    al_u = SimpleNamespace(id=uuid.uuid4(), batch_id=None, evaluator_ids=[])
    allocs = {x.id: x for x in (al_a, al_b, al_u)}
    held: set[uuid.UUID | None] = {ba}
    who = SimpleNamespace(user_id=uuid.uuid4(), grants=())

    async def scope(_s: Any, _p: Any, _id: Any) -> Any:
        return ScopeRef("batch", ba), None

    async def get(_s: Any, _m: Any, _id: Any) -> Any:
        return SimpleNamespace(id=aid, submission_type="structured")

    async def may(_r: Any, _p: Any, _perm: str, ref: ScopeRef) -> bool:
        return ref.scope_id in held

    async def _allocs(_s: Any, _id: Any) -> Any:
        return allocs

    class _Ctx:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *a: Any) -> None:
            return None

    monkeypatch.setattr(sa.base, "_assignment_scope", scope)
    monkeypatch.setattr(sa.base, "_may", may)
    monkeypatch.setattr(sa.fss, "get", get)
    monkeypatch.setattr(sa, "_allocs", _allocs)
    monkeypatch.setattr(sa, "system_context", lambda *_a, **_k: _Ctx())

    _a, gradable = await sa._ensure_grade(None, None, who, aid)  # type: ignore[arg-type]
    assert gradable == frozenset({al_a.id, al_u.id})
    assert not sa._in_gradable(gradable, al_b.id)
    held.add(bb)  # holds both batches -> every allocation (None = all)
    assert (await sa._ensure_grade(None, None, who, aid))[1] is None  # type: ignore[arg-type]
    held.clear()
    with pytest.raises(ProblemError):
        await sa._ensure_grade(None, None, who, aid)  # type: ignore[arg-type]
