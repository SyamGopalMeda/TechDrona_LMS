"""Local smoke test of the deployed entry points WITHOUT deploying (functions venv + Firestore emulator).

    functions-lms/venv/Scripts/python functions-lms/tools/smoke_local.py functions-lms

Calls main.lmsApi through a Flask test client (the same Request object Cloud Functions passes) and
prints the discovered Firebase endpoints. Dummy keys only."""

import os
import sys

os.environ.update(
    {
        "TD_CSRF_KEY": "k" * 40,
        "TD_SERVICE_TOKEN": "s" * 48,
        "FIRESTORE_EMULATOR_HOST": "127.0.0.1:18080",
        "FIREBASE_PROJECT_ID": "demo-platform-test",
        "APP_ENV": "test",
        "TD_PUBLIC_BASE_URL": "https://lms.example",
        "LOG_LEVEL": "WARNING",
    }
)
sys.path.insert(0, sys.argv[1])
import main
from flask import Flask, request

fl = Flask("t")


@fl.route("/", defaults={"p": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@fl.route("/<path:p>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
def h(p):
    return main.lmsApi(request)


c = fl.test_client()
for path in [
    "/healthz",
    "/api/v1/health/live",
    "/api/v1/_bff/csrf",
    "/api/v1/nope/x",
    "/api/v1/webhooks/razorpay",
    "/other",
]:
    r = c.get(path)
    print(
        path,
        r.status_code,
        r.headers.get("content-type"),
        r.get_data()[:120],
        r.headers.getlist("Set-Cookie"),
    )
r = c.post(
    "/api/v1/auth/login", json={"email": "a@b.c", "password": "x"}, headers={"Sec-Fetch-Site": "same-origin"}
)
print("login no csrf", r.status_code, r.get_json()["code"])
r = c.post("/api/public/admissions/status", json={}, headers={"Origin": "https://evil.example"})
print("public evil", r.status_code, r.get_json()["code"])
names = [n for n in dir(main) if n.startswith("lms")]
print(len(names), names[:6])
print(
    hasattr(main.lmsApi, "__firebase_endpoint__"),
    main.lmsScheduler.__firebase_endpoint__.scheduleTrigger,
)
