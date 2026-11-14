"""Smoke: the HTTP harness on Firestore with no Postgres (login + /me)."""

from __future__ import annotations

from typing import Any

from tests.identity.fs.conftest import fs_user


async def test_login_and_me(http: Any) -> None:
    u = await fs_user("smoke@x.in")
    r = await http.login(u.email, u.password)
    assert r.status_code == 200, r.text
    assert r.json()["result"] == "authenticated", r.text
    me = await http.get("/me")
    assert me.status_code == 200, me.text
    assert me.json()["user"]["email"] == "smoke@x.in"
