"""Central login hub: module rules and the website bridge (no database, Firebase faked)."""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from typing import Any

import pytest

from app.core.firestore import website as web
from app.core.principal import Principal, RoleGrant
from app.modules.hub.router import can_open_colleges, lms_landing


def _p(*roles: str) -> Principal:
    return Principal(
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        grants=tuple(RoleGrant(r, "platform") for r in roles),
    )


def test_lms_landing_is_the_most_privileged_portal() -> None:
    assert lms_landing(_p()) == "/app"
    assert lms_landing(_p("student")) == "/app"
    assert lms_landing(_p("trainer")) == "/trainer"
    assert lms_landing(_p("trainer", "super_admin")) == "/admin"


def test_only_admins_open_colleges_management() -> None:
    assert can_open_colleges(_p("super_admin"))
    for roles in [(), ("student",), ("trainer",), ("evaluator",), ("content_manager",)]:
        assert not can_open_colleges(_p(*roles))


class _Snap:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self.exists = data is not None
        self._d = data

    def to_dict(self) -> dict[str, Any] | None:
        return self._d


class _FakeClient:
    """Records which collection/document is read; returns the configured web_team entries."""

    def __init__(self, team: dict[str, dict[str, Any]]) -> None:
        self.team = team
        self.reads: list[tuple[str, str]] = []

    def collection(self, name: str) -> Any:
        client = self

        class _Coll:
            def document(self, doc_id: str) -> Any:
                class _Doc:
                    async def get(self) -> _Snap:
                        client.reads.append((name, doc_id))
                        return _Snap(client.team.get(doc_id) if name == "web_team" else None)

                return _Doc()

        return _Coll()


@pytest.fixture
def fake_team(monkeypatch: pytest.MonkeyPatch) -> _FakeClient:
    c = _FakeClient(
        {
            "owner@x.com": {"role": "owner", "active": True, "name": "Owner"},
            "gone@x.com": {"role": "staff", "active": False},
            "odd@x.com": {"role": "superuser", "active": True},
        }
    )
    monkeypatch.setattr(web.client_mod, "get_client", lambda: c)
    return c


def test_website_member_reads_exactly_one_web_team_entry(fake_team: _FakeClient) -> None:
    m = asyncio.run(web.website_member("  Owner@X.com "))
    assert m is not None and (m.email, m.role, m.name) == ("owner@x.com", "owner", "Owner")
    assert fake_team.reads == [("web_team", "owner@x.com")]  # lower-cased id, the website's own key


@pytest.mark.parametrize("email", ["gone@x.com", "odd@x.com", "nobody@x.com"])
def test_inactive_unknown_or_odd_roles_are_not_members(fake_team: _FakeClient, email: str) -> None:
    assert asyncio.run(web.website_member(email)) is None


@pytest.mark.parametrize("email", ["", "no-at-sign", "a/b@x.com", "x" * 250 + "@x.com"])
def test_path_like_or_invalid_emails_never_hit_firestore(fake_team: _FakeClient, email: str) -> None:
    assert asyncio.run(web.website_member(email)) is None
    assert fake_team.reads == []


class _FakeAuth:
    class UserNotFoundError(Exception):
        pass

    def __init__(self, existing: dict[str, Any] | None) -> None:
        self.existing = existing
        self.calls: list[tuple[str, Any]] = []

    def get_user_by_email(self, email: str, app: Any = None) -> Any:
        self.calls.append(("get", email))
        if self.existing is None:
            raise self.UserNotFoundError(email)
        return SimpleNamespace(**self.existing)

    def create_user(self, **kw: Any) -> Any:
        self.calls.append(("create", kw))
        return SimpleNamespace(uid="new-uid", disabled=False, email_verified=kw["email_verified"])

    def update_user(self, uid: str, **kw: Any) -> None:
        self.calls.append(("update", (uid, kw)))

    def create_custom_token(self, uid: str, claims: dict[str, Any], app: Any = None) -> bytes:
        self.calls.append(("token", (uid, claims)))
        return f"tok-{uid}".encode()


def _mint_with(monkeypatch: pytest.MonkeyPatch, existing: dict[str, Any] | None) -> tuple[str, _FakeAuth]:
    import firebase_admin

    fake = _FakeAuth(existing)
    monkeypatch.setattr(firebase_admin, "auth", fake, raising=False)
    monkeypatch.setitem(__import__("sys").modules, "firebase_admin.auth", fake)
    monkeypatch.setattr(web.client_mod, "admin_app", lambda s=None: object())
    return web._mint("owner@x.com", "Owner"), fake


def test_mint_reuses_the_existing_user_and_marks_the_sso_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    tok, fake = _mint_with(monkeypatch, {"uid": "u1", "disabled": False, "email_verified": True})
    assert tok == "tok-u1"
    assert ("token", ("u1", {"td_sso": "lms"})) in fake.calls
    assert not any(c[0] in {"create", "update"} for c in fake.calls)


def test_mint_creates_a_missing_user_and_verifies_an_unverified_one(monkeypatch: pytest.MonkeyPatch) -> None:
    tok, fake = _mint_with(monkeypatch, None)
    assert (
        tok == "tok-new-uid" and fake.calls[1][0] == "create" and fake.calls[1][1]["email_verified"] is True
    )
    _, fake = _mint_with(monkeypatch, {"uid": "u2", "disabled": False, "email_verified": False})
    assert ("update", ("u2", {"email_verified": True, "app": fake.calls[1][1][1]["app"]})) in fake.calls


def test_mint_refuses_a_disabled_account(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(PermissionError):
        _mint_with(monkeypatch, {"uid": "u3", "disabled": True, "email_verified": True})


def test_mint_is_refused_on_the_emulator(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.firestore.errors import FirestoreUnavailableError

    monkeypatch.setattr(
        web.client_mod, "get_settings", lambda: SimpleNamespace(FIRESTORE_EMULATOR_HOST="127.0.0.1:18080")
    )
    with pytest.raises(FirestoreUnavailableError):
        asyncio.run(web.mint_website_token("owner@x.com"))


def test_integration_status_reports_booleans_only() -> None:
    """Owner rule 2026-11-12: the UI asks which services are really connected. The test settings
    use the local mail sink, console SMS and fake providers, so all of those report False."""
    from app.modules.hub.router import integration_status

    st = integration_status()
    assert set(st) == {"email", "sms", "payments", "ai", "code_judge", "video", "website_sso"}
    assert all(v in (True, False, None) for v in st.values())
    assert st["email"] is False and st["sms"] is False and st["code_judge"] is False


def test_website_sso_requires_a_fresh_staff_step_up() -> None:
    """POST /sso/website mints a token into another system's admin panel: it carries the staff
    step-up dependency (S10, 600 s), so a stale session gets 401 step_up_required."""
    from datetime import timedelta

    from app.core.errors import ProblemError
    from app.core.time import utcnow
    from app.modules.hub.router import sso_r

    route = next(r for r in sso_r.routes if getattr(r, "path", "").endswith("/website"))
    deps = [d.call for d in route.dependant.dependencies]  # type: ignore[attr-defined]
    step = [d for d in deps if getattr(d, "__name__", "") == "require_step_up_600"]
    assert len(step) == 1

    stale = Principal(user_id=uuid.uuid4(), session_id=uuid.uuid4(), tier="staff")
    with pytest.raises(ProblemError) as exc:
        asyncio.run(step[0](stale))
    assert exc.value.code == "step_up_required"
    fresh = Principal(
        user_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        tier="staff",
        last_step_up_at=utcnow() - timedelta(seconds=30),
    )
    assert asyncio.run(step[0](fresh)) is fresh
