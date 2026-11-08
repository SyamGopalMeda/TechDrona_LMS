"""Shared helpers for identity/sessions/rbac/orgs/notifications tests (Stage 4).

* ``Browser`` — simulates the BFF hop for one browser profile: keeps the session/device
  cookies the API sets and forwards them as ``X-TD-Session``/``X-TD-Device`` with the service
  token, a User-Agent and a client IP.
* ``make_user`` / ``make_org`` / ``make_batch`` / ``grant`` — direct DB factories (system
  context on the test connection; everything is rolled back after the test).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import system_context
from app.core.ids import uuid7
from app.core.security import hash_password
from app.modules.identity import totp
from app.modules.identity.crypto import encrypt_secret
from app.modules.identity.models import Consent, MfaFactor, User, UserCredential, UserProfile
from tests.conftest import SERVICE_TOKEN

CHROME_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
FIREFOX_LINUX = "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0"
ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"
GOOD_PASSWORD = "violet-harbour-lantern-92"
NOTICE = "2026-11-01"
REQUIRED_CONSENTS = [
    {"purpose": "terms", "notice_version": NOTICE, "granted": True},
    {"purpose": "privacy_notice", "notice_version": NOTICE, "granted": True},
    {"purpose": "core_service", "notice_version": NOTICE, "granted": True},
]

_HASH_CACHE: dict[str, str] = {}


def pw_hash(pw: str) -> str:
    if pw not in _HASH_CACHE:
        _HASH_CACHE[pw] = hash_password(pw)
    return _HASH_CACHE[pw]


@dataclass
class Browser:
    client: Any
    ua: str = CHROME_WIN
    ip: str = "203.0.113.10"
    session: str | None = None
    device: str | None = None
    remember: str | None = None
    activity: str | None = None
    last: Any = None

    def headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        h = {"Authorization": f"Service {SERVICE_TOKEN}", "User-Agent": self.ua, "X-TD-Client-IP": self.ip}
        if self.session:
            h["X-TD-Session"] = self.session
        if self.device:
            h["X-TD-Device"] = self.device
        if self.activity:
            h["X-TD-Activity"] = self.activity
        h.update(extra or {})
        return h

    def absorb(self, resp: Any) -> None:
        for raw in resp.headers.get_list("set-cookie"):
            name, _, rest = raw.partition("=")
            value = rest.split(";", 1)[0]
            if name == "__Host-td_session":
                self.session = value or None
            elif name == "__Host-td_device":
                self.device = value or None
            elif name == "__Host-td_remember":
                self.remember = value or None

    async def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = path if path.startswith("/api/") else f"/api/v1{path}"
        resp = await self.client.request(method, url, json=json, headers=self.headers(headers), params=params)
        self.absorb(resp)
        self.last = resp
        return resp

    async def get(self, path: str, **kw: Any) -> Any:
        return await self.request("GET", path, **kw)

    async def post(self, path: str, json: Any = None, **kw: Any) -> Any:
        return await self.request("POST", path, json=json if json is not None else {}, **kw)

    async def patch(self, path: str, json: Any = None, **kw: Any) -> Any:
        return await self.request("PATCH", path, json=json or {}, **kw)

    async def delete(self, path: str, **kw: Any) -> Any:
        return await self.request("DELETE", path, **kw)

    def fork(self, **kw: Any) -> Browser:
        """Another browser profile (new device cookie) of the same person."""
        return Browser(self.client, **kw)

    async def login(self, email: str, password: str = GOOD_PASSWORD, **kw: Any) -> Any:
        return await self.post("/auth/login", {"identifier": email, "password": password, **kw})


@dataclass
class UserHandle:
    id: uuid.UUID
    email: str
    password: str = GOOD_PASSWORD
    totp_secret: str | None = None
    used_steps: set[int] = field(default_factory=set)

    def code(self) -> str:
        """A TOTP code for a step not yet used in this test (replay guard is per step)."""
        assert self.totp_secret
        step = totp.current_step()
        while step in self.used_steps or (self.used_steps and step <= max(self.used_steps)):
            step += 1
        self.used_steps.add(step)
        return totp.hotp(self.totp_secret, step)


async def make_user(
    db: AsyncSession,
    *,
    email: str | None = None,
    password: str = GOOD_PASSWORD,
    minor: bool = False,
    status: str = "active",
    with_totp: bool = False,
    consents: bool = True,
    full_name: str = "Test User",
    phone: str | None = None,
) -> UserHandle:
    await system_context(db, "test.factory")
    uid = uuid7()
    email = email or f"u{uid.hex[-10:]}@example.com"
    from app.modules.identity import clock

    now = clock.now()
    db.add(
        User(
            id=uid,
            email=email,
            email_verified_at=now,
            phone_e164=phone,
            phone_verified_at=now if phone else None,
            status=status,
            is_minor=minor,
            age_verified_at=now,
            age_verification_method="self_declared",
        )
    )
    await db.flush()
    db.add(
        UserProfile(
            user_id=uid, full_name=full_name, date_of_birth=date(2010, 1, 1) if minor else date(2000, 1, 1)
        )
    )
    db.add(UserCredential(user_id=uid, password_hash=pw_hash(password)))
    if consents:
        for c in REQUIRED_CONSENTS:
            db.add(
                Consent(
                    id=uuid7(),
                    user_id=uid,
                    purpose=c["purpose"],
                    action="granted",
                    notice_version=NOTICE,
                    channel="web",
                )
            )
    secret = None
    if with_totp:
        secret = totp.random_base32()
        ct, wrapped = encrypt_secret(secret)
        db.add(
            MfaFactor(
                id=uuid7(),
                user_id=uid,
                factor_type="totp",
                totp_secret_encrypted=ct,
                totp_wrapped_key=wrapped,
                totp_confirmed_at=now,
                is_primary=True,
            )
        )
    await db.flush()
    return UserHandle(uid, email, password, secret)


def company_org() -> uuid.UUID:
    """The single company organization (inserted by migration orgs_0002). Use this for new
    tests: batches, memberships and org-owned rows all belong to it."""
    from app.core.company import COMPANY_ORG_ID

    return COMPANY_ORG_ID


async def make_batch(
    db: AsyncSession, org_id: uuid.UUID, created_by: uuid.UUID, code: str | None = None
) -> uuid.UUID:
    from app.modules.orgs.models import Batch

    await system_context(db, "test.factory")
    bid = uuid7()
    db.add(
        Batch(
            id=bid,
            organization_id=org_id,
            name="CSE 2027",
            code=code or f"B{bid.hex[-6:]}",
            created_by=created_by,
        )
    )
    await db.flush()
    return bid


async def add_member(
    db: AsyncSession,
    org_id: uuid.UUID,
    user_id: uuid.UUID,
    member_type: str = "student",
    batch_id: uuid.UUID | None = None,
) -> None:
    from app.modules.orgs.models import BatchMember, OrgMembership

    await system_context(db, "test.factory")
    db.add(
        OrgMembership(
            id=uuid7(),
            organization_id=org_id,
            user_id=user_id,
            member_type=member_type,
            status="active",
            source="staff",
        )
    )
    if batch_id:
        db.add(
            BatchMember(
                id=uuid7(),
                batch_id=batch_id,
                organization_id=org_id,
                user_id=user_id,
                member_role="student" if member_type == "student" else "trainer",
            )
        )
    await db.flush()


async def grant(
    db: AsyncSession,
    user_id: uuid.UUID,
    role: str,
    scope_type: str = "platform",
    scope_id: uuid.UUID | None = None,
    granted_by: uuid.UUID | None = None,
) -> uuid.UUID:
    from sqlalchemy import select

    from app.modules.rbac.models import Role, RoleGrant
    from app.modules.rbac.service import batch_org

    await system_context(db, "test.factory")
    role_id = (await db.execute(select(Role.id).where(Role.role_key == role))).scalar_one()
    org = (
        scope_id
        if scope_type == "organization"
        else (await batch_org(db, scope_id) if scope_type == "batch" and scope_id else None)
    )
    if granted_by is None:
        granter = await make_user(db, email=f"granter{uuid7().hex[-8:]}@example.com")
        granted_by = granter.id
    gid = uuid7()
    db.add(
        RoleGrant(
            id=gid,
            user_id=user_id,
            role_id=role_id,
            scope_type=scope_type,
            scope_id=scope_id,
            organization_id=org,
            granted_by=granted_by,
        )
    )
    await db.flush()
    return gid


async def staff_login(browser: Browser, user: UserHandle) -> Any:
    """Full staff login: password -> TOTP (MFA) -> active (first device is trusted)."""
    r = await browser.login(user.email, user.password)
    assert r.status_code == 200, r.text
    if r.json()["result"] == "mfa_required":
        r = await browser.post("/auth/mfa/verify", {"method": "totp", "code": user.code()})
    assert r.status_code == 200 and r.json()["result"] == "authenticated", r.text
    return r


async def step_up(browser: Browser, user: UserHandle) -> None:
    r = await browser.post("/auth/step-up", {"method": "totp", "code": user.code()})
    assert r.status_code == 200, r.text
