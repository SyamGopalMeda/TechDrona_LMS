"""Restricted principals (restriction_lookup hook), route-tag scope gate, consent gate,
principal contents, route guard."""

from __future__ import annotations

import pytest

from app.core.routing import find_route_guard_violations
from app.modules.sessions import hooks
from app.modules.sessions.hooks import RestrictionState
from tests.identity.factory import add_member, company_org, make_user


@pytest.fixture
def restriction():
    state = {"level": 0}

    async def lookup(session, user_id):
        return RestrictionState(level=state["level"], case_ref="SEC-2611-7KQ4MZ")

    hooks.register_restriction_lookup(lookup)
    yield state
    hooks.register_restriction_lookup(None)


async def test_l3_restricted_scope(browser, db, restriction) -> None:
    org = company_org()
    u = await make_user(db)
    await add_member(db, org, u.id)
    restriction["level"] = 3
    r = await browser.login(u.email)
    assert r.json()["session"]["scope"] == "restricted" and r.json()["redirect"] == "/app/account-status"
    assert r.json()["restriction"]["case_ref"] == "SEC-2611-7KQ4MZ"
    assert (await browser.get("/me")).json()["restriction"]["level"] == 3  # account_status
    assert (await browser.get("/me/enrolments")).status_code == 200  # l3_readonly allowed at L3
    r = await browser.patch("/me/profile", {"branch": "CSE"})  # default tag
    assert r.status_code == 403 and r.json()["code"] == "account_restricted" and r.json()["level"] == 3
    restriction["level"] = 4  # derived per request: L4 -> status_only
    assert (await browser.get("/me/enrolments")).status_code == 403
    assert (await browser.get("/me/sessions")).status_code == 200
    assert (await browser.post("/auth/logout")).status_code == 200


async def test_missing_required_consent_blocks_default_routes(browser, db) -> None:
    u = await make_user(db, consents=False)
    await browser.login(u.email)
    r = await browser.patch("/me/profile", {"branch": "CSE"})
    assert r.status_code == 403 and r.json()["code"] == "consent_required"
    assert set(r.json()["purposes"]) == {"terms", "privacy_notice", "core_service"}
    assert (await browser.get("/me/consents")).status_code == 200  # consent tag
    for p in ("terms", "privacy_notice", "core_service"):
        await browser.post(
            "/me/consents", {"purpose": p, "action": "granted", "notice_version": "2026-11-01"}
        )
    assert (await browser.patch("/me/profile", {"branch": "CSE"})).status_code == 200


async def test_principal_carries_minor_flag_and_hides_orgs(browser, db) -> None:
    org = company_org()
    kid = await make_user(db, minor=True)
    await add_member(db, org, kid.id)
    await browser.login(kid.email)
    me = (await browser.get("/me")).json()
    assert me["user"]["is_minor"] is True and me["user"]["privacy_tier"] == "minor"
    assert "organizations" not in me  # the company org is an internal tenancy key


def test_route_guard_still_green(app) -> None:
    assert find_route_guard_violations(app) == []
