"""Fork probe: Razorpay webhook signature + replay handling on the live dev stack (fake provider).
Uses an unhandled synthetic event type (``AUDIT.probe``), so nothing is applied to orders."""
import hashlib
import hmac
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "apps" / "api"))
from app.modules.commerce.gateway import FakePaymentProvider as F  # noqa: E402  (dev-only constant)

h = httpx.Client(timeout=60)


def show(label, r):
    try:
        c = r.json().get("code") or r.json().get("status")
    except Exception:
        c = r.text[:80]
    print(f"{label}: {r.status_code} {c}", flush=True)


WH = "http://127.0.0.1:18001/api/v1/webhooks/razorpay"
body = json.dumps({"event": "AUDIT.probe", "created_at": int(time.time()), "payload": {}}).encode()
ct = {"content-type": "application/json"}
show("W1 no signature", h.post(WH, content=body, headers=ct))
show("W2 bad signature", h.post(WH, content=body, headers={**ct, "x-razorpay-signature": "0" * 64}))
good = hmac.new(F.WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
evid = f"AUDIT-evt-{uuid.uuid4()}"
hd = {**ct, "x-razorpay-signature": good, "x-razorpay-event-id": evid}
show("W3 valid (dev fake secret)", h.post(WH, content=body, headers=hd))
show("W4 replay same event id", h.post(WH, content=body, headers=hd))
show("W5 tampered body, same sig", h.post(WH, content=body + b" ", headers=hd))
show("W6 via BFF :13000", h.post("http://localhost:13000/api/v1/webhooks/razorpay", content=body, headers=hd))
show("W7 via main api :18000", h.post("http://127.0.0.1:18000/api/v1/webhooks/razorpay", content=body, headers=hd))
show("W8 unknown provider", h.post("http://127.0.0.1:18001/api/v1/webhooks/stripe", content=body, headers=hd))
print("event id:", evid)
