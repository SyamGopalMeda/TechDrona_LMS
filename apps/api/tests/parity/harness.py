"""Firebase-parity HTTP harness (parity-nopg agent).

* Every module is on Firestore (``TD_STORE_<MODULE>=firestore`` for all of ``backend.MODULES``),
  the cache/rate-limit backend is Firestore (``TD_CACHE_BACKEND=firestore``), and the request
  sessions are ``NO_POSTGRES`` (``install_fake_db``): exactly what ``TD_RUNTIME=firebase`` with no
  ``DATABASE_URL`` gives. A route that still reaches Postgres answers 500 here, as in production.
* Nothing of the application is stubbed except what is external to it: object storage (an
  in-memory document store) and the role catalogue lookup (``rbac.role_permission_map`` returns
  ``rbac.catalogue``, which is what the deployed rbac collections are seeded from). Authentication
  is the root ``FakeAuth``: a session
  token maps to a ``Principal``; staff principals made by ``World.staff`` hold every permission
  (the Admin role), learners hold none. Each principal is also a real identity user (Firestore),
  so profile / e-mail lookups work as on the live stack.

``World.call`` asserts the status code and never accepts a 500, so a parity failure reports the
route and the body.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import httpx
import pytest

from tests.paths.fs.http_harness import install_fake_db, restore_switch, switch_to_firestore

API = "/api/v1"

# Handler failures the VM (Postgres) has identically: not parity bugs. Reported in
# docs/firebase/agents/parity-nopg.md and NOT changed here (the VM behaviour is the spec).
VM_KNOWN_FAILURES: tuple[tuple[str, ...], ...] = (
    # placement emits ``difficulty`` as an int (1..5); analytics.mastery expects easy/medium/hard
    # and calls ``.lower()`` when the item has no calibrated difficulty yet (same on Postgres).
    ("practice.answered", "analytics.consumer", "'int' object has no attribute 'lower'"),
)


@dataclass
class World:
    client: httpx.AsyncClient
    auth: Any
    make_principal: Any
    fs_client: Any = None
    staff_ids: set[uuid.UUID] = field(default_factory=set)

    async def _user(self, p: Any, *, name: str) -> None:
        from app.core.db import NO_POSTGRES
        from app.core.time import utcnow
        from app.modules.identity import public as idp
        from app.modules.identity.models import User

        await idp.create_user(
            NO_POSTGRES,
            User(
                id=p.user_id,
                email=f"{name}-{p.user_id.hex[-10:]}@example.test",
                email_verified_at=utcnow(),
                status="active",
                is_minor=False,
                age_verified_at=utcnow(),
                age_verification_method="self_declared",
            ),
        )

    async def learner(self, name: str = "learner") -> tuple[Any, dict[str, str]]:
        p = self.make_principal(roles=("student",), is_minor=False, device_id=uuid.uuid4())
        await self._user(p, name=name)
        return p, self.auth.login(p)

    async def consent(self, headers: dict[str, str], purpose: str = "security_monitoring") -> None:
        """POST /me/consents (paid plans need ``security_monitoring``)."""
        from app.modules.identity.router import NOTICE_VERSION_DEFAULT

        await self.call(
            "POST",
            "/me/consents",
            headers,
            expect=(200, 201),
            json={"purpose": purpose, "action": "granted", "notice_version": NOTICE_VERSION_DEFAULT},
        )

    async def staff(self, name: str = "admin") -> tuple[Any, dict[str, str]]:
        from app.core.time import utcnow

        now = utcnow()
        p = self.make_principal(
            roles=("super_admin",),
            is_platform=True,
            tier="privileged",
            aal=2,
            amr=("pwd", "otp"),
            mfa_level="totp",
            auth_time=now,
            last_step_up_at=now,
            is_minor=False,
            device_id=uuid.uuid4(),
        )
        self.staff_ids.add(p.user_id)
        await self._user(p, name=name)
        return p, self.auth.login(p)

    async def relay(self) -> int:
        """Dispatch the Firestore outbox the way the Firebase worker does (``app.worker``: every
        module on Firestore -> handlers get ``session=None``). Any failed handler fails the test
        with its traceback."""
        import traceback

        from app.core import outbox
        from app.core.firestore.core_store import relay_pending_firestore

        failures: list[str] = []
        real = outbox.handlers_for

        def wrapped(event_type: str) -> Any:
            def wrap(h: Any) -> Any:
                async def run(session: Any, msg: Any) -> None:
                    try:
                        await h(session, msg)
                    except Exception:
                        where = f"{event_type} -> {h.__module__}.{h.__qualname__}"
                        failures.append(f"{where}:\n{traceback.format_exc()}")
                        raise

                return run

            return [wrap(h) for h in real(event_type)]

        total = 0
        outbox.handlers_for = wrapped
        try:
            for _ in range(10):  # handlers may emit follow-up events
                r = await relay_pending_firestore(batch=200, max_attempts=1)
                total += r.dispatched
                if not r.dispatched and not r.skipped_no_handler:
                    break
        finally:
            outbox.handlers_for = real
        failures = [f for f in failures if not any(all(k in f for k in kn) for kn in VM_KNOWN_FAILURES)]
        assert not failures, "outbox handlers failed on the Firebase path:\n" + "\n".join(failures)
        return total

    async def call(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        *,
        expect: int | tuple[int, ...] = 200,
        idem: bool = False,
        **kw: Any,
    ) -> httpx.Response:
        h = dict(headers)
        if idem:
            h["Idempotency-Key"] = str(uuid.uuid4())
        r = await self.client.request(method, f"{API}{path}", headers=h, **kw)
        want = expect if isinstance(expect, tuple) else (expect,)
        assert r.status_code < 500, f"{method} {path} -> {r.status_code}: {r.text[:2000]}"
        assert r.status_code in want, f"{method} {path} -> {r.status_code} (want {want}): {r.text[:2000]}"
        return r


@pytest.fixture
async def web(
    fs_client: Any, monkeypatch: pytest.MonkeyPatch, auth: Any, make_principal: Any
) -> AsyncIterator[World]:
    from app.core import db as core_db
    from app.core import runtime
    from app.core.config import reset_settings_cache
    from app.core.firestore.backend import MODULES
    from app.main import create_app

    # The Firebase stack: no Postgres engine can ever be built (get_engine raises
    # PostgresDisabledError), so a job/webhook path that opens its own Postgres session fails here
    # exactly as in production instead of reaching the test database.
    monkeypatch.setattr(runtime, "postgres_enabled", lambda: False)
    assert core_db._sessionmaker is None
    from app.core import db as core_db

    monkeypatch.setenv("TD_CACHE_BACKEND", "firestore")
    monkeypatch.setenv("DATABASE_URL", "")  # no Postgres at all: get_engine() raises, as on Firebase
    reset_settings_cache()
    await core_db.dispose_engine()
    await switch_to_firestore(fs_client, monkeypatch, *sorted(MODULES))
    w = World(client=None, auth=auth, make_principal=make_principal, fs_client=fs_client)  # type: ignore[arg-type]

    async def has_permission(principal: Any, permission: str, scope: Any, request: Any) -> bool:
        return principal.user_id in w.staff_ids or (principal.user_id, permission) in auth.perms

    monkeypatch.setattr(auth, "has_permission", has_permission)
    from app.modules.rbac import catalogue
    from app.modules.rbac import service as rbac

    async def role_perms(session: Any) -> dict[str, frozenset[str]]:
        # what the deployed rbac collections hold (seeded from this catalogue)
        return {r: catalogue.permissions_for_role(r) for r in catalogue.ROLE_ORDER}

    monkeypatch.setattr(rbac, "role_permission_map", role_perms)
    from app.modules.commerce.documents import MemoryDocumentStore, set_document_store

    set_document_store(MemoryDocumentStore())  # object storage (S3/GCS) is external: in memory
    app = create_app()
    install_fake_db(app)  # request sessions are NO_POSTGRES, as on the Firebase stack
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
            w.client = c
            yield w
    finally:
        set_document_store(None)
        restore_switch(monkeypatch, *sorted(MODULES))
        monkeypatch.delenv("TD_CACHE_BACKEND", raising=False)
        monkeypatch.undo()
        reset_settings_cache()


# --------------------------------------------------------------------------- flows


@dataclass
class PaidCourse:
    id: str
    slug: str
    lessons: dict[str, dict[str, Any]]  # title -> lesson of the learner's outline (LRN-04)

    async def outline(self, w: World, headers: dict[str, str]) -> dict[str, dict[str, Any]]:
        r = await w.call("GET", f"/me/courses/{self.id}", headers)
        self.lessons = {le["title"]: le for m in r.json()["modules"] for le in m["lessons"]}
        return self.lessons


async def publish_paid_course(w: World, *, lessons: list[dict[str, Any]] | None = None) -> PaidCourse:
    """Admin authors a paid course over HTTP (studio), submits it and a second admin publishes."""
    _, ah = await w.staff("author")
    _, ph = await w.staff("publisher")
    slug = f"paid-{uuid.uuid4().hex[:8]}"
    r = await w.call(
        "POST",
        "/studio/courses",
        ah,
        expect=201,
        json={"title": "Paid parity course", "slug": slug, "visibility": "public", "is_free": False},
    )
    cid = r.json()["id"]
    await w.call(
        "PATCH",
        f"/studio/courses/{cid}/draft",
        ah,
        json={"summary": "Parity", "tags": ["parity"], "level": "beginner", "category": "dsa"},
    )
    specs = lessons or [
        {
            "title": "Intro",
            "lesson_type": "article",
            "article_body": {"doc": "intro"},
            "est_reading_minutes": 3,
            "is_free_preview": True,
        },
        {
            "title": "Paid",
            "lesson_type": "article",
            "article_body": {"doc": "paid"},
            "est_reading_minutes": 3,
        },
        {
            "title": "Paid2",
            "lesson_type": "article",
            "article_body": {"doc": "paid2"},
            "est_reading_minutes": 3,
        },
    ]
    ids = []
    for spec in specs:
        r = await w.call("POST", f"/studio/courses/{cid}/draft/lessons", ah, expect=201, json=spec)
        ids.append(r.json()["id"])
    await w.call(
        "PUT",
        f"/studio/courses/{cid}/draft/outline",
        ah,
        json={"modules": [{"title": "Module 1", "lesson_ids": ids}]},
    )
    await w.call("POST", f"/studio/courses/{cid}/submit-review", ah)
    await w.call("POST", f"/studio/courses/{cid}/publish", ph, idem=True, json={"change_type": "major"})
    return PaidCourse(cid, slug, {})


async def grant_course(w: World, user_id: uuid.UUID, course_id: str) -> str:
    """ENT-06 manual grant by an admin (the 'admin grants' path; purchase is COM-*)."""
    return await grant(w, user_id, {"course_id": course_id})


async def grant(w: World, user_id: uuid.UUID, target: dict[str, Any]) -> str:
    """ENT-06 manual grant of ``target`` (course_id / product_id / feature_key)."""
    from app.core.time import utcnow

    _, ah = await w.staff("granter")
    r = await w.call(
        "POST",
        "/entitlements/grants",
        ah,
        expect=201,
        idem=True,
        json={
            "user_ids": [str(user_id)],
            "target": target,
            "source_type": "admin_grant",
            "ends_at": (utcnow() + timedelta(days=30)).isoformat(),
            "reason": "Parity harness grant",
        },
    )
    return str(r.json()["entitlement_ids"][0])
