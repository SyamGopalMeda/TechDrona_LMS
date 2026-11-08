"""Fork probe: does the dev S3 (seaweedfs) enforce the presigned POST policy? One presign per case,
then only the violating POST is sent; the parent checks the filer for what was stored."""
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from fork_client import login  # noqa: E402
from fork_signup import PW  # noqa: E402

c = login("audit-buyer-a", PW, "audit-buyer-a@audit.techdrona.local")


def presign(size=16):
    r = c.post("media/uploads/file", {"purpose": "support_attachment", "filename": "AUDIT-pol.txt", "content_type": "text/plain", "size_bytes": size})
    up = r.json()
    return up["upload"]["url"].replace("http://s3:8333", "http://localhost:9000"), dict(up["upload"]["fields"]), up["s3_key"]


url, f, key = presign()
f["Content-Type"] = "text/html"
r = httpx.post(url, data=f, files={"file": ("f", b"<b>AUDIT</b>1234", "text/html")}, timeout=30)
print("CT-mismatch", r.status_code, r.headers.get("location"), key.split("/")[-2])
url, f, key = presign()
r = httpx.post(url, data=f, files={"file": ("f", b"A" * 4000, "text/plain")}, timeout=30)
print("oversize", r.status_code, key.split("/")[-2])
url, f, key = presign()
f["key"] = key.rsplit("/", 1)[0] + "/AUDIT-renamed.html"
r = httpx.post(url, data=f, files={"file": ("f", b"AUDIT-1234567890", "text/plain")}, timeout=30)
print("key-mismatch", r.status_code, key.split("/")[-2])
url, f, key = presign()
f["policy"] = f["policy"][:-4] + "AAAA"
r = httpx.post(url, data=f, files={"file": ("f", b"AUDIT-1234567890", "text/plain")}, timeout=30)
print("bad-policy-sig", r.status_code, key.split("/")[-2])
