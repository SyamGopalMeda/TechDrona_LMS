"""Audit probes (Phase A, security area). Each test prints AUDIT lines with observed behaviour;
assertions encode the *expected* (spec) behaviour so a failure = finding."""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import select, text

from app.core.db import system_context
from tests.identity.factory import (
    ANDROID,
    FIREFOX_LINUX,
    GOOD_PASSWORD,
    REQUIRED_CONSENTS,
    add_member,
    make_org,
    make_user,
)
from tests.identity.fixtures import last_code


def _signup_body(email: str) -> dict:
    return {
        "full_name": "Probe User",
        "email": email,
        "password": "quiet-maple-orchard-71",
        "date_of_birth": "2000-02-02",
        "consents": REQUIRED_CONSENTS,
    }


async def test_signup_enumeration(browser, db, mail) -> None:
    u = await make_user(db)
    t0 = time.perf_counter()
    r_new = await browser.post("/auth/signup", _signup_body(f"new{uuid.uuid4().hex[:8]}@example.com"))
    t_new = time.perf_counter() - t0
    b2 = browser.fork()
    t0 = time.perf_counter()
    r_old = await b2.post("/auth/signup", _signup_body(u.email))
    t_old = time.perf_counter() - t0
    new_ck = [c.split("=")[0] for c in r_new.headers.get_list("set-cookie")]
    old_ck = [c.split("=")[0] for c in r_old.headers.get_list("set-cookie")]
    print(f"AUDIT signup new: {r_new.status_code} next={r_new.json().get('next_steps')} session={r_new.json().get('session') is not None} cookies={new_ck} t={t_new:.3f}s")
    print(f"AUDIT signup existing: {r_old.status_code} next={r_old.json().get('next_steps')} session={r_old.json().get('session') is not None} cookies={old_ck} t={t_old:.3f}s")
    assert r_new.json().get("next_steps") == r_old.json().get("next_steps"), "response shape differs"
    assert bool(new_ck) == bool(old_ck), "Set-Cookie presence differs"


async def test_password_change_no_attempt_limit(browser, db) -> None:
    u = await make_user(db)
    assert (await browser.login(u.email)).json()["result"] == "authenticated"
    codes = []
    for i in range(25):
        r = await browser.post(
            "/auth/password/change",
            {"current_password": f"wrong-guess-{i}-xx", "new_password": "brand-new-river-stone-55"},
        )
        codes.append(r.status_code)
    print(f"AUDIT password/change 25 wrong guesses -> statuses {sorted(set(codes))}")
    r = await browser.post(
        "/auth/password/change",
        {"current_password": GOOD_PASSWORD, "new_password": "brand-new-river-stone-55"},
    )
    print(f"AUDIT password/change correct after 25 wrong -> {r.status_code}")
    assert 429 in codes or r.status_code != 200, "no throttling of current-password guesses"


async def test_step_up_password_allowed_for_student(browser, db) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    r = await browser.post("/auth/step-up", {"method": "password", "password": GOOD_PASSWORD})
    print(f"AUDIT student step-up with password -> {r.status_code} {r.text[:120]}")
    assert r.status_code != 200, "api-spec §1.6/AUTH-19: passkey/totp/sms_otp/email_otp only"


async def test_token_not_rotated_after_device_otp(browser, db, mail) -> None:
    u = await make_user(db)
    await browser.login(u.email)
    other = browser.fork(ua=FIREFOX_LINUX)
    r = await other.login(u.email)
    pending_token = other.session
    await other.post("/auth/device-verification/send", {"channel": "email"})
    r = await other.post("/auth/device-verification/verify", {"code": last_code(mail)})
    assert r.json()["result"] == "authenticated"
    print(f"AUDIT session token rotated pending->active after device OTP: {other.session != pending_token}")
    assert other.session != pending_token


async def test_idor_sessions_devices_unblock(browser, db, mail) -> None:
    a = await make_user(db)
    b = await make_user(db)
    ba = browser
    await ba.login(a.email)
    bb = browser.fork(ua=ANDROID, ip="198.51.100.7")
    await bb.login(b.email)
    sid_a = (await ba.get("/me")).json()["session"]["id"]
    devs_a = (await ba.get("/me/devices")).json()["data"]
    r1 = await bb.delete(f"/me/sessions/{sid_a}")
    r2 = await bb.delete(f"/me/devices/{devs_a[0]['user_device_id']}")
    r3 = await bb.patch(f"/me/devices/{devs_a[0]['user_device_id']}", {"user_label": "pwned"})
    print(f"AUDIT B deletes A session -> {r1.status_code}; B deletes A device -> {r2.status_code}; B relabels A device -> {r3.status_code}")
    still = await ba.get("/me")
    print(f"AUDIT A still signed in -> {still.status_code}")
    assert r1.status_code == 404 and r2.status_code == 404 and r3.status_code == 404 and still.status_code == 200


async def test_rls_cross_org_reads(db, app_engine) -> None:
    from app.core.db import tenant_context
    from app.core.principal import Principal
    from app.modules.orgs.models import OrgMembership, Organization

    org_a = await make_org(db, "A College")
    org_b = await make_org(db, "B College")
    ua = await make_user(db)
    ub = await make_user(db)
    await add_member(db, org_a, ua.id)
    await add_member(db, org_b, ub.id)
    await db.flush()
    p = Principal(user_id=ua.id, session_id=uuid.uuid4(), org_ids=(org_a,))
    await tenant_context(db, p)
    orgs = (await db.execute(select(Organization.id))).scalars().all()
    mems = (await db.execute(select(OrgMembership.organization_id))).scalars().all()
    users = (await db.execute(text("select id from users"))).scalars().all()
    sess = (await db.execute(text("select count(*) from auth_sessions where user_id <> :u"), {"u": ua.id})).scalar()
    print(f"AUDIT RLS as A-member: orgs visible={len(orgs)} (B visible={org_b in orgs}); memberships orgs={set(map(str,mems))==({str(org_a)})}; users visible={len(users)} (B visible={ub.id in users}); other users' sessions={sess}")
    assert org_b not in orgs and ub.id not in users and sess == 0
    # write attempt into org B
    try:
        await db.execute(
            text("insert into org_memberships (id, organization_id, user_id, member_type, status, source) values (gen_random_uuid(), :o, :u, 'staff', 'active', 'staff')"),
            {"o": org_b, "u": ua.id},
        )
        wrote = True
    except Exception as e:  # noqa: BLE001
        wrote = False
        print(f"AUDIT RLS write into org B blocked: {type(e).__name__}")
    assert not wrote


def test_prod_gate_accepts_placeholder_hmac_keys(monkeypatch) -> None:
    from app.core import security as sec
    from app.core.config import Settings
    from app.core.startup_checks import production_problems

    placeholder = "local-dev-device-key-REPLACE-ME-0000000000"  # same shape as .env.example (non-hex, >=32 chars)
    monkeypatch.setenv("TD_K_DEVICE_KEY_V1", placeholder)
    monkeypatch.setenv("TD_K_LOGIN_KEY_V1", placeholder.replace("device", "login"))
    sec.reset_keyrings()
    s = Settings(APP_ENV="production")
    probs = production_problems(s)
    hmac_probs = [p for p in probs if "HMAC" in p]
    print(f"AUDIT prod gate HMAC problems with placeholder keys: {hmac_probs}")
    sec.reset_keyrings()
    assert hmac_probs, "placeholder (non-hex) HMAC keys accepted by production gate"


async def test_logs_and_db_never_hold_secrets(browser, db, mail, capsys) -> None:
    """Run signup -> login(new device OTP) -> forgot/reset -> step-up OTP and look for the raw
    password, OTP codes, link tokens and session tokens in captured logs and in persisted rows."""
    import json as _json

    from app.core.logging import configure_logging
    from tests.identity.fixtures import last_link_token

    configure_logging("INFO", "json")
    u = await make_user(db)
    await browser.login(u.email)
    secrets_seen: list[str] = [GOOD_PASSWORD]
    other = browser.fork(ua=FIREFOX_LINUX)
    await other.login(u.email)
    secrets_seen.append(other.session or "")
    await other.post("/auth/device-verification/send", {"channel": "email"})
    otp = last_code(mail)
    secrets_seen.append(otp)
    await other.post("/auth/device-verification/verify", {"code": otp})
    await other.post("/auth/step-up/options", {"purpose": "contact_change", "send_otp_via": "email"})
    otp2 = last_code(mail)
    secrets_seen.append(otp2)
    await other.post("/auth/step-up", {"method": "email_otp", "code": otp2})
    await browser.fork().post("/auth/password/forgot", {"identifier": u.email})
    tok = last_link_token(mail)
    secrets_seen.append(tok)
    await browser.fork().post("/auth/password/reset", {"token": tok, "new_password": "fresh-cedar-window-81"})
    secrets_seen.append("fresh-cedar-window-81")
    out = capsys.readouterr()
    logs = out.out + out.err
    leaked_logs = [i for i, s in enumerate(secrets_seen) if s and s in logs]
    # persisted rows
    await system_context(db, "audit.probe")
    blobs = []
    for tbl, col in (("audit_log", "*"), ("outbox_events", "*"), ("notifications", "*"), ("login_attempts", "*"), ("audit_outbox", "*"), ("verification_tokens", "*"), ("auth_sessions", "*"), ("email_messages", "*")):
        try:
            async with db.begin_nested():
                rows = (await db.execute(text(f"select row_to_json(t)::text from {tbl} t"))).scalars().all()
            blobs.extend(rows)
        except Exception as e:  # noqa: BLE001
            print(f"AUDIT table {tbl} not readable: {type(e).__name__}")
    joined = "\n".join(blobs)
    leaked_db = [i for i, s in enumerate(secrets_seen) if s and s in joined]
    labels = ["password", "session_token", "device_otp", "stepup_otp", "reset_token", "new_password"]
    print(f"AUDIT log lines captured={logs.count(chr(10))}; secrets found in logs: {[labels[i] for i in leaked_logs]}")
    print(f"AUDIT persisted rows scanned={len(blobs)}; secrets found in DB rows: {[labels[i] for i in leaked_db]}")
    assert not leaked_logs and not leaked_db


async def test_td_app_cannot_tamper_audit_log(db) -> None:
    await system_context(db, "audit.probe")
    results = {}
    for name, sql in (
        ("update", "update audit_log set reason = 'x' where seq = (select min(seq) from audit_log)"),
        ("delete", "delete from audit_log where seq = (select min(seq) from audit_log)"),
        ("truncate", "truncate audit_log"),
        ("update_outbox", "update audit_outbox set payload = payload"),
    ):
        try:
            async with db.begin_nested():
                await db.execute(text(sql))
            results[name] = "ALLOWED"
        except Exception as e:  # noqa: BLE001
            results[name] = type(e.orig).__name__ if hasattr(e, "orig") else type(e).__name__
    print(f"AUDIT td_app tamper attempts on audit tables: {results}")
    assert all(v != "ALLOWED" for v in results.values())


async def test_spec_rate_limits_signup_forgot_reset(browser, db, mail) -> None:
    u = await make_user(db)
    sign = []
    for i in range(7):
        r = await browser.fork().post("/auth/signup", _signup_body(f"rl{i}{uuid.uuid4().hex[:6]}@example.com"))
        sign.append(r.status_code)
    same_contact = [
        (await browser.fork().post("/auth/signup", _signup_body(u.email))).status_code for _ in range(5)
    ]
    forgot = [
        (await browser.fork().post("/auth/password/forgot", {"identifier": f"nobody{i}@example.com"})).status_code
        for i in range(7)
    ]
    reset = [
        (await browser.fork().post("/auth/password/reset", {"token": "x" * 43, "new_password": "aaaa-bbbb-cccc-1"})).status_code
        for _ in range(12)
    ]
    verify = [(await browser.fork().post("/auth/verify/email", {"token": "y" * 43})).status_code for _ in range(22)]
    print(f"AUDIT 7 signups same IP -> {sign}; 5 signups same existing contact -> {same_contact} (emails sent to owner: {sum(1 for m in mail.sent if m.to == u.email)})")
    print(f"AUDIT 7 forgot same IP -> {sorted(set(forgot))}; 12 reset same IP -> {sorted(set(reset))}; 22 verify-email same IP -> {sorted(set(verify))}")
    assert 429 in sign and 429 in forgot and 429 in reset and 429 in verify
