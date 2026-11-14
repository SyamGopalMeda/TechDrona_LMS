"""Firestore-emulator tests of the access modules (identity, sessions, rbac, orgs).

These tests need **only** the Firestore emulator: the root ``migrated_database`` fixture is
overridden with a no-op so they also run while Postgres is down. The Postgres-side parity runs
(existing suites with ``backend_fixture``) live next to the module tests and need the database.

``fs`` switches ``TD_STORE_{IDENTITY,SESSIONS,RBAC,ORGS}=firestore`` on a wiped emulator project
(``demo-<TD_TEST_DB_NAME>``), installs the client and a policy resolver returning the documented
defaults (policy rows belong to admin), and restores everything afterwards.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

from tests.firestore.conftest import firestore_emulator, fs_client  # noqa: F401

ACCESS_MODULES = ("identity", "sessions", "rbac", "orgs")


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    """No Postgres needed in this directory."""
    yield None


@pytest.fixture(autouse=True)
def real_auth() -> None:
    """The parent ``tests/identity`` autouse fixture builds the whole app; not needed here."""
    return None


@pytest.fixture
async def fs(fs_client: Any, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:  # noqa: F811
    from app.core.firestore import client as client_mod
    from app.core.firestore.backend import reset_store_backends
    from app.modules.identity import policy
    from app.modules.rbac.service import reset_role_permission_cache
    from app.modules.sessions import hooks

    for m in ACCESS_MODULES:
        monkeypatch.setenv(f"TD_STORE_{m.upper()}", "firestore")
    reset_store_backends()
    client_mod.set_client(fs_client)

    async def _defaults(_s: Any, key: str, _o: Any, _u: Any) -> Any:
        return policy.DEFAULTS.get(key)

    monkeypatch.setattr(policy, "_resolver", _defaults)
    monkeypatch.setattr(hooks, "_security_events", None)
    reset_role_permission_cache()
    try:
        yield fs_client
    finally:
        client_mod.set_client(None)
        for m in ACCESS_MODULES:
            monkeypatch.delenv(f"TD_STORE_{m.upper()}", raising=False)
        reset_store_backends()
        reset_role_permission_cache()


class FakePgSession:
    """Stands in for the Postgres session the backfill reads (``SELECT * FROM <table>``).

    ``tables`` maps a table name (or the mapping's SQL source) to rows; ``where`` clauses of the
    mappings are applied by ``predicates`` (table -> row filter) so the tests mirror Postgres."""

    def __init__(self, tables: dict[str, list[dict[str, Any]]], predicates: dict[str, Any] | None = None):
        self.tables = tables
        self.predicates = predicates or {}

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        sql = str(stmt)
        outer = self

        class _R:
            def one(self) -> tuple[str, ...]:
                return ("", "", "", "", "", "")

            def mappings(self) -> Any:
                class _M:
                    def all(self_inner) -> list[dict[str, Any]]:
                        return outer._select(sql)

                return _M()

            def scalar(self) -> Any:
                return None

        return _R()

    def _select(self, sql: str) -> list[dict[str, Any]]:
        if not sql.startswith("SELECT * FROM "):
            return []
        body = sql[len("SELECT * FROM ") :]
        source, _, _rest = body.partition(" ORDER BY ")
        where = None
        if " WHERE " in source:
            source, _, where = source.partition(" WHERE ")
        rows = list(self.tables.get(source.strip(), []))
        if where is not None and rows:
            pred = self.predicates.get(where.strip())
            assert pred is not None, f"no predicate for WHERE {where!r}"
            rows = [r for r in rows if pred(r)]
        return rows


# --------------------------------------------------------------------------- HTTP on Firestore

HTTP_FS_MODULES = (*ACCESS_MODULES, "audit", "core")
PASSWORD = "Correct-horse-battery-9"


@pytest.fixture
async def http(fs: Any, monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Any]:
    """A ``Browser`` (tests.identity.factory) on the real FastAPI app with **no Postgres at all**:
    ``DATABASE_URL`` is empty, so every request session is ``NO_POSTGRES`` and any Postgres use
    by these routes fails the test. identity/sessions/rbac/orgs + audit + core (idempotency)
    run on the emulator; rate limits in memory; email/SMS captured (``http.mail`` /
    ``http.sms``). Hooks owned by other modules (security restriction lookup and signal sink,
    assessments attempt lookup, catalog course-org lookup, admin policy resolver) are detached
    so the test exercises only the access modules; their own agents test those hooks."""
    import httpx

    from app.core import auth as core_auth
    from app.core import ratelimit
    from app.core.config import reset_settings_cache
    from app.core.firestore.backend import reset_store_backends
    from app.modules.notifications.adapters import (
        ConsoleSmsAdapter,
        MemoryEmailAdapter,
        get_email_adapter,
        get_sms_adapter,
        set_email_adapter,
        set_sms_adapter,
    )
    from tests.identity.factory import Browser

    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("TD_CACHE_BACKEND", "firestore")
    for m in HTTP_FS_MODULES:
        monkeypatch.setenv(f"TD_STORE_{m.upper()}", "firestore")
    reset_settings_cache()
    reset_store_backends()
    from app.core import db as core_db

    assert core_db._sessionmaker is None, "a Postgres engine was already built in this process"
    from app.main import create_app

    app = create_app()
    from app.modules.identity import policy
    from app.modules.identity import router as identity_router
    from app.modules.rbac import service as rbac_service
    from app.modules.rbac.service import RbacPermissionChecker
    from app.modules.sessions import hooks
    from app.modules.sessions import service as sessions_service
    from app.modules.sessions.resolver import SessionsResolver

    async def _defaults(_s: Any, key: str, _o: Any, _u: Any) -> Any:
        return policy.DEFAULTS.get(key)

    monkeypatch.setattr(policy, "_resolver", _defaults)
    monkeypatch.setattr(hooks, "_security_events", None)
    monkeypatch.setattr(hooks, "_restriction_lookup", None)
    monkeypatch.setattr(sessions_service, "_active_attempt_lookup", None)
    monkeypatch.setattr(rbac_service, "_course_org_lookup", None)
    monkeypatch.setattr(identity_router, "SIGNUP_MIN_SECONDS", 0.0)
    prev_r, prev_c = core_auth.get_session_resolver(), core_auth._permission_checker
    core_auth.register_session_resolver(SessionsResolver())
    core_auth.register_permission_checker(RbacPermissionChecker())
    prev_rl = ratelimit.set_backend(ratelimit.MemoryBackend())
    prev_mail, prev_sms = get_email_adapter(), get_sms_adapter()
    mail, sms = MemoryEmailAdapter(), ConsoleSmsAdapter()
    set_email_adapter(mail)
    set_sms_adapter(sms)
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            b = Browser(client)
            b.mail = mail  # type: ignore[attr-defined]
            b.sms = sms  # type: ignore[attr-defined]
            yield b
    finally:
        set_email_adapter(prev_mail)
        set_sms_adapter(prev_sms)
        ratelimit.set_backend(prev_rl)
        core_auth.register_session_resolver(prev_r)
        core_auth.register_permission_checker(prev_c)
        monkeypatch.undo()
        reset_settings_cache()
        reset_store_backends()


async def fs_user(
    email: str,
    password: str = PASSWORD,
    *,
    roles: tuple[str, ...] = (),
    full_name: str = "Test User",
    totp_secret: str | None = None,
    phone: str | None = None,
) -> Any:
    """An active, verified user with the sign-up consents (and platform grants) on Firestore."""
    from app.core.ids import uuid7
    from app.core.security import hash_password
    from app.modules.identity import clock
    from app.modules.identity.models import Consent, MfaFactor, User, UserCredential, UserProfile
    from app.modules.identity.repo_firestore import system_repo as irepo
    from tests.identity.factory import UserHandle

    now = clock.now()
    uid = uuid7()
    repo = irepo()
    await repo.create_user(
        User(
            id=uid,
            email=email,
            email_verified_at=now,
            phone_e164=phone,
            phone_verified_at=now if phone else None,
            status="active",
            is_minor=False,
            age_verified_at=now,
            age_verification_method="self_declared",
            account_origin="seed",
            created_at=now,
        ),
        UserProfile(user_id=uid, full_name=full_name),
    )
    await repo.save_credential(
        UserCredential(user_id=uid, password_hash=hash_password(password), password_set_at=now)
    )
    for p in ("terms", "privacy_notice", "core_service"):
        await repo.add_consent(
            Consent(
                id=uuid7(),
                user_id=uid,
                purpose=p,
                action="granted",
                notice_version="v1",
                channel="web",
                created_at=now,
            )
        )
    if totp_secret:
        from app.modules.identity.crypto import encrypt_secret

        ct, wrapped = encrypt_secret(totp_secret)
        await repo.save_factor(
            MfaFactor(
                id=uuid7(),
                user_id=uid,
                factor_type="totp",
                totp_secret_encrypted=ct,
                totp_wrapped_key=wrapped,
                totp_confirmed_at=now,
                created_at=now,
            )
        )
    if roles:
        await seed_catalogue()
        from app.modules.rbac.models import RoleGrant
        from app.modules.rbac.repo_firestore import system_repo as rrepo

        for r in roles:
            role = await rrepo().role_by_key(r)
            assert role is not None, r
            grant = RoleGrant(
                id=uuid7(),
                user_id=uid,
                role_id=role.id,
                scope_type="platform",
                granted_by=uuid7(),
                granted_at=now,
            )
            await rrepo().create_grant(grant, r)
    return UserHandle(uid, email, password, totp_secret=totp_secret)


async def seed_catalogue() -> None:
    """Roles, permissions and role_permissions from ``rbac.catalogue`` (what rbac_0002+ seed)."""
    import uuid as _uuid

    import app.modules.orgs.store_specs
    import app.modules.rbac.store_specs
    import app.modules.sessions.store_specs  # noqa: F401 - registers the collections
    from app.core.firestore.ids import compose_id
    from app.core.firestore.store import ScopedStore
    from app.modules.identity import clock
    from app.modules.identity.fs_codec import obj_doc
    from app.modules.rbac import catalogue
    from app.modules.rbac.models import Permission, Role, RolePermission

    st = ScopedStore.system("test.seed")
    rid = {k: _uuid.uuid5(_uuid.NAMESPACE_URL, "role:" + k) for k in catalogue.ROLES}
    if await st.get("roles", str(rid["student"])) is not None:
        return
    now = clock.now()
    pid = {k: _uuid.uuid5(_uuid.NAMESPACE_URL, "perm:" + k) for k in catalogue.PERMISSIONS}
    perms = [
        (
            str(pid[k]),
            obj_doc(
                Permission(
                    id=pid[k],
                    permission_key=k,
                    module=p.module,
                    description=p.description,
                    is_sensitive=p.is_sensitive,
                    created_at=now,
                )
            ),
        )
        for k, p in catalogue.PERMISSIONS.items()
    ]
    roles = [
        (
            str(rid[k]),
            obj_doc(
                Role(
                    id=rid[k],
                    role_key=k,
                    name=r.name,
                    session_tier=r.session_tier,
                    mfa_required=r.mfa_required,
                    allowed_scope_types=list(r.allowed_scope_types),
                    is_system=True,
                    created_at=now,
                    updated_at=now,
                )
            ),
        )
        for k, r in catalogue.ROLES.items()
    ]
    links = [
        (
            compose_id(str(rid[r]), str(pid[p])),
            obj_doc(RolePermission(role_id=rid[r], permission_id=pid[p], created_at=now)),
        )
        for r, p in catalogue.role_permission_pairs()
        if r in rid
    ]
    await st.import_documents("permissions", perms)
    await st.import_documents("roles", roles)
    await st.import_documents("role_permissions", links)
