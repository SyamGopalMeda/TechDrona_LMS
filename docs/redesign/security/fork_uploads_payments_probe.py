"""Fork probe (security audit items 4 + 6): uploads and payments against the live dev stack.
Synthetic data only (AUDIT- prefix). Prints status codes / problem codes only, never secrets.
Run: TD_PROBE_STATE=<dir> apps/api/.venv/Scripts/python.exe docs/redesign/security/fork_uploads_payments_probe.py
"""
import hashlib
import hmac
import json
import re
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from fork_client import login  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps" / "api"))
from app.modules.commerce.gateway import FakePaymentProvider as F  # noqa: E402  (dev-only constants)


def code(r):
    try:
        j = r.json()
        return j.get("code") if isinstance(j, dict) else None
    except Exception:
        return None


def show(label, r, extra=""):
    print(f"{label}: {r.status_code} {code(r) or ''} {extra}")


from fork_signup import PW  # noqa: E402
asha = login("audit-buyer-a", PW, "audit-buyer-a@audit.techdrona.local")
ravi = login("audit-buyer-b", PW, "audit-buyer-b@audit.techdrona.local")
me_a = asha.get("me").json()["user"]["id"]

print("== uploads")
show("U1 assignment_submission text/html", asha.post("media/uploads/file", {"purpose": "assignment_submission", "filename": "AUDIT-x.html", "content_type": "text/html", "size_bytes": 10}))
show("U2 assignment_submission 21MB", asha.post("media/uploads/file", {"purpose": "assignment_submission", "filename": "AUDIT-x.pdf", "content_type": "application/pdf", "size_bytes": 21 * 1024 * 1024}))
show("U3 student lesson_file", asha.post("media/uploads/file", {"purpose": "lesson_file", "filename": "AUDIT-x.pdf", "content_type": "application/pdf", "size_bytes": 10, "lesson_id": str(uuid.uuid4())}))
show("U4 student resource_file", asha.post("media/uploads/file", {"purpose": "resource_file", "filename": "AUDIT-x.pdf", "content_type": "application/pdf", "size_bytes": 10}))
show("U5 student question-media upload", asha.post("studio/question-media/uploads", {"filename": "AUDIT-x.png", "content_type": "image/png", "size_bytes": 10}))
r = asha.post("media/uploads/file", {"purpose": "support_attachment", "filename": "AUDIT-note.txt", "content_type": "text/plain", "size_bytes": 16})
show("U6 support_attachment presign", r)
up = r.json()
url = up["upload"]["url"].replace("http://s3:8333", "http://localhost:9000")  # dev endpoint is docker-internal
fields = up["upload"]["fields"]
key = up["s3_key"]
print("   key prefix ok:", key.startswith(f"uploads/support_attachment/{me_a}/"), "url host:", httpx.URL(url).host)


def s3post(flds, content, ctype="text/plain"):
    return httpx.post(url, data=flds, files={"file": ("f", content, ctype)}, timeout=20)


show("U7 S3 POST too large (40B > 16B)", s3post(fields, b"A" * 40))
f2 = dict(fields)
f2["Content-Type"] = "text/html"
show("U8 S3 POST wrong content-type", s3post(f2, b"<b>x</b>xxxxxxxx", "text/html"))
f3 = dict(fields)
f3["key"] = key.replace(me_a, "00000000-0000-0000-0000-000000000000")
show("U9 S3 POST other key", s3post(f3, b"AUDIT-1234567890"))
show("U10 S3 POST valid", s3post(fields, b"AUDIT-1234567890"))
show("U11 anon GET uploaded object", httpx.get(f"{url.rstrip('/')}/{key}"))
other_key = f"uploads/support_attachment/{uuid.uuid4()}/{uuid.uuid4()}/AUDIT.txt"
show("U12 ticket w/ foreign key", asha.post("support/tickets", {"category": "technical", "subject": "AUDIT-probe", "body": "AUDIT-probe body text", "attachments": [{"s3_key": other_key, "filename": "a.txt", "content_type": "text/plain", "size_bytes": 16}]}))

print("== payments")
prods = asha.get("commerce/products").json().get("data", [])
blob = json.dumps(prods)
m = re.search(r'"price_id": "([0-9a-f-]{36})"', blob)
price_id = m and m.group(1)
if not price_id and prods:
    d = asha.get(f"commerce/products/{prods[0]['sku']}").json()
    m = re.search(r'"price_id": "([0-9a-f-]{36})"', json.dumps(d))
    price_id = m and m.group(1)
print("products:", len(prods), "price found:", bool(price_id))
billing = {"name": "AUDIT Buyer A", "state_code": "29"}
q = asha.post("commerce/checkout/quote", {"price_id": price_id, "billing": billing}, idem=False)
show("P1 quote", q, str(q.json().get("total_paise")) if q.status_code == 200 else json.dumps(q.json())[:300])
if q.status_code == 200:
    total = q.json()["total_paise"]
    show("P2 order with tampered quote_total_paise=100", asha.post("commerce/orders", {"price_id": price_id, "billing": billing, "quote_total_paise": 100}))
    o = asha.post("commerce/orders", {"price_id": price_id, "billing": billing, "quote_total_paise": total})
    show("P3 order genuine", o, "" if o.status_code in (200, 201) else json.dumps(o.json())[:300])
    if o.status_code in (200, 201):
        oj = o.json()
        order_id = oj["order_id"]
        gwo = (oj.get("checkout") or {}).get("gateway_order_id")
        print("   checkout amount == quote:", (oj.get("checkout") or {}).get("amount") == total)
        show("P4 ravi GET asha order", ravi.get(f"commerce/orders/{order_id}"))
        show("P5 ravi cancel asha order", ravi.post(f"commerce/orders/{order_id}/cancel"))
        show("P6 ravi confirm asha order", ravi.post(f"commerce/orders/{order_id}/confirm", {"razorpay_order_id": gwo, "razorpay_payment_id": "pay_x", "razorpay_signature": "x"}))
        show("P7 ravi refund-request asha order", ravi.post("me/refund-requests", {"order_id": order_id, "reason_code": "changed_mind"}))
        pid = f"{F.SIMULATED_PREFIX}100_{gwo}"
        sig = hmac.new(F.KEY_SECRET.encode(), f"{gwo}|{pid}".encode(), hashlib.sha256).hexdigest()
        c = asha.post(f"commerce/orders/{order_id}/confirm", {"razorpay_order_id": gwo, "razorpay_payment_id": pid, "razorpay_signature": sig})
        show("P8 confirm with underpaid (1 INR) captured payment", c, json.dumps({k: c.json().get(k) for k in ("status", "code")}) + " ents=" + str(len(c.json().get("entitlements") or [])))
        st = asha.get(f"commerce/orders/{order_id}").json()
        print("   order after underpay:", st.get("status"), "entitlements:", len(st.get("entitlements") or []))
        show("P9 cancel own order (cleanup)", asha.post(f"commerce/orders/{order_id}/cancel"))
        print("   order id:", order_id)

print("== refunds (authz)")
show("R1 student finance refund create", asha.post("finance/refunds", {"order_id": str(uuid.uuid4()), "reason_code": "service_failure", "note": "AUDIT-probe"}))
show("R2 student refund decision", asha.post(f"finance/refunds/{uuid.uuid4()}/decision", {"decision": "approve"}))
show("R3 student list finance refunds", asha.get("finance/refunds"))
show("R4 student refund-request on random order", asha.post("me/refund-requests", {"order_id": str(uuid.uuid4()), "reason_code": "changed_mind"}))

print("== webhooks (api-webhooks :18001)")
WH = "http://localhost:18001/api/v1/webhooks/razorpay"
body = json.dumps({"event": "AUDIT.probe", "created_at": int(time.time()), "payload": {}}).encode()
show("W1 no signature", httpx.post(WH, content=body, headers={"content-type": "application/json"}))
show("W2 bad signature", httpx.post(WH, content=body, headers={"content-type": "application/json", "x-razorpay-signature": "0" * 64}))
good = hmac.new(F.WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
evid = f"AUDIT-evt-{uuid.uuid4()}"
h = {"content-type": "application/json", "x-razorpay-signature": good, "x-razorpay-event-id": evid}
w3 = httpx.post(WH, content=body, headers=h)
show("W3 valid (dev fake secret)", w3, w3.text[:120])
w4 = httpx.post(WH, content=body, headers=h)
show("W4 replay same event id", w4, w4.text[:120])
show("W5 tampered body, same sig", httpx.post(WH, content=body + b" ", headers=h))
show("W6 via BFF :13000", httpx.post("http://localhost:13000/api/v1/webhooks/razorpay", content=body, headers=h))
show("W7 via main api :18000", httpx.post("http://localhost:18000/api/v1/webhooks/razorpay", content=body, headers={**h, "x-razorpay-event-id": evid + "-b"}))
print("event id for DB check:", evid)
