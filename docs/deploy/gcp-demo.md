# Tech Drona LMS — GCP demo deployment

Status: **live demo** since 2026-11-09. Owner-approved, demo data only, budget ₹3k–8k/month.
Live URL: **https://35-244-50-26.sslip.io/** (sign-in: `/login`). Wildcard DNS by sslip.io; switch to a real domain later (§7).

This is a DEMO environment (`APP_ENV=staging`). Payments (Razorpay fake), coding judge, AI, video (VdoCipher stub) and SMS run on fake adapters, and no e-mail leaves the VM. The production startup gate (`apps/api/app/core/startup_checks.py`) would refuse these settings, and that is intended. Do not use this deployment for real learners or real money.

## 1. Architecture

| Item | Value |
|---|---|
| GCP project | `billing-f4fe3` ("TechDrona Full LMS", Blaze). The Firebase Hosting showcase at https://billing-f4fe3.web.app is separate and unchanged. |
| VM | `td-lms-demo`, zone `asia-south1-a`, **e2-standard-2** (2 vCPU / 8 GB), Debian 12, 40 GB pd-balanced, 4 GB swap file, Shielded VM. **No service account** (the VM has no GCP API access). |
| Static IP | `td-lms-demo-ip` = 35.244.50.26 (regional, asia-south1) |
| Stack | Docker Compose project `techdrona` from `infra/gcp-demo/docker-compose.yml`: postgres 16 (+pg_partman), redis (cache), redis-queue, seaweedfs S3, mailpit (internal SMTP sink), migrate (one-shot), api, api-webhooks, worker, worker-maintenance, scheduler (beat), worker-judge (fake judge), audit-sealer, web (Next.js BFF), **caddy** (TLS edge) |
| TLS | Caddy with automatic Let's Encrypt certificates for `35-244-50-26.sslip.io` and `files.35-244-50-26.sslip.io`. HTTP is redirected to HTTPS (308), and HSTS is set. |
| Request path | browser → Caddy :443 → `web:3000` (BFF) → `api:8000` on the internal network. The API is never routed directly. Caddy sets `CloudFront-Viewer-Address` to the real peer, and the BFF trusts exactly 1 hop (`TD_TRUSTED_PROXY_HOPS=1`). |
| Files | `files.35-244-50-26.sslip.io` → seaweedfs S3 (credentials required; anonymous requests get 403). Presigned upload and download URLs need a browser-reachable S3 host. Containers reach the same name internally through a Docker network alias on Caddy. CORS is limited to the app origin. |
| Images | built **on the VM** (`techdrona/td-api:gcp-demo`, `techdrona/td-web:gcp-demo`, `techdrona/postgres:16-gcp-demo`). No Artifact Registry and no Cloud Build. Nothing was built on the owner's PC. |
| Not used | `infra/terraform` (archived 2026-11-14 to `docs/archive/aws-terraform/terraform/`) targets **AWS** (ECS, ElastiCache, RDS, CloudFront). It was not applied. |

Files in the repo (no secrets): `infra/gcp-demo/docker-compose.yml`, `Caddyfile`, `db-init/01-roles.sh` (creates the DB roles from env passwords), `vm.sh` (helper run on the VM), `rotate_demo_accounts.py` (credential rotation and owner admin).

Settings worth knowing (full list in the server env file): `APP_ENV=staging`, `TD_COOKIE_SECURE=true` (`__Host-` cookies), `TD_DISABLE_API_DOCS=true`, `TD_PUBLIC_BASE_URL`/`TD_ALLOWED_ORIGINS`/`WEB_BASE_URL` = the sslip.io origin, `TD_WEBAUTHN_RP_ID` = the host, `EMAIL_PROVIDER=smtp` → mailpit, `NEXT_PUBLIC_APP_NAME="Tech Drona (Demo)"`. The app has no separate demo banner, so the "(Demo)" suffix on the app name is the visible marker. Low-memory sizing: 2 uvicorn workers, Celery concurrency 2/1.

## 2. Where secrets live (paths only)

| What | Where |
|---|---|
| Server env (every secret: service token, CSRF key, HMAC/AEAD keyrings, envelope/testcase/analytics keys, Postgres superuser and `td_owner`/`td_app`/`td_readonly`/`td_audit_sealer`/`td_maintenance` passwords, both Redis passwords, S3 keys) | VM: `/opt/techdrona/server.env` (root, 0600). PC copy: `C:\Users\SYAM\.secrets\techdrona-full-lms\server.env` |
| SeaweedFS S3 identity | VM: `/opt/techdrona/s3.json` (root, 0600). PC: `C:\Users\SYAM\.secrets\techdrona-full-lms\s3.json` |
| Demo and owner account credentials | PC only: `C:\Users\SYAM\.secrets\techdrona-full-lms\demo-accounts.txt` |

All values were freshly generated (`secrets.token_hex`). None reuse `.env` or `.env.example`. The secrets folder on the PC is ACL-restricted to the owner's user and SYSTEM. Nothing secret is in instance metadata (the startup script only installs Docker and swap), in the repo or in Git. Copies used during transfer were removed with `shred`.

## 3. Demo accounts

- The seeds ran once (`rbac_seed dev_users catalog_demo placement_demo coding_demo commerce_demo security_demo e2e_demo company_demo`), with `APP_ENV=dev` set only in that one-off container.
- Right after seeding, `rotate_demo_accounts.py` used `identity.service.set_password` and `sessions.service.revoke_all_sessions`. It gave **every** synthetic account a new random password. On every staff account it revoked the public `DEV_TOTP_SECRETS` factor and enrolled a new random TOTP secret. The public `dev-only-…` password and the repo TOTP secrets no longer work (tested).
- `security@`, `security2@` and `finance@` (extra Admins) are **deactivated** and their grants revoked. The active Admins are `admin@`, `admin2@` (kept for maker/checker dual control) and the owner.
- **Owner Admin:** `syamgopalmeda@gmail.com` (super_admin, platform). Since 2026-11-10 (owner request): password set to an owner-chosen value with `vm.sh set-login` (`infra/gcp-demo/set_login.py`, password on STDIN), which bypasses the app's password policy (that value is on the breached-password list), Then, also on owner request (warned twice about the risk), **password-only sign-in**: `TD_MFA_EXEMPT_EMAILS=syamgopalmeda@gmail.com` in `server.env` (api: `Settings.mfa_exempt`, ignored when `APP_ENV` is production) skips mandatory MFA enrolment (`sessions/resolver.py`) and the new-device e-mail code (`sessions/login.py`) for that account, and `vm.sh set-login --no-totp` revoked its TOTP factor. Verified in a fresh browser: e-mail + password → `/admin` → College Data Portal. Admin actions that demand a fresh TOTP step-up (deactivate/reactivate user, MFA reset, break-glass, …) are not possible for this account; use another Admin. To restore MFA: remove the line from `server.env`, `vm.sh up`, sign in and enrol TOTP.
- **Extra Admin (2026-11-10, owner request):** `techdrona.admin@dev.techdrona.local` ("Tech Drona Admin", super_admin, platform, not synthetic so `rotate` leaves it alone), with a password and a confirmed TOTP factor. Credentials: PC only, `C:\Users\SYAM\.secrets\techdrona-full-lms\admin-techdrona.admin.json`. Verified: browser sign-in → `/admin` → College Data Portal (171 colleges). More can be added with `$SSH 'cd /tmp && sudo bash /opt/techdrona/src/infra/gcp-demo/vm.sh create-admin --email <email> --name "<name>"' > <PC secrets file>` (`infra/gcp-demo/create_admin.py`; refuses an existing e-mail).
- **Owner login changed (2026-11-10, owner request):** `syamgopalmeda@gmail.com` password set to the owner's chosen value with `vm.sh set-login` (`infra/gcp-demo/set_login.py`, password on STDIN; this bypasses the app's password policy, the value is on the common-password list) plus a pre-enrolled TOTP factor so the password alone cannot sign in. TOTP secret: PC only, `C:\Users\SYAM\.secrets\techdrona-full-lms\owner-syamgopalmeda.json`. Verified: browser sign-in → College Data Portal.
- **E-mail codes (important):** mail never leaves the VM. When a sign-in from a new browser asks for an e-mail code (students always do; the owner does on his first new device), read it on the VM:

  ```bash
  gcloud compute ssh td-lms-demo --zone asia-south1-a --project billing-f4fe3 --tunnel-through-iap \
    --command "sudo bash /opt/techdrona/src/infra/gcp-demo/vm.sh otp student@dev.techdrona.local"
  ```

  Staff with TOTP can pick "use authenticator" instead. A trusted browser does not ask again.
- **Google sign-in:** `35-244-50-26.sslip.io` was added to Firebase Auth authorized domains (Identity Toolkit admin API, additive: localhost, firebaseapp.com and web.app were kept). The **Google provider must be enabled by the owner** in Firebase console → Authentication → Sign-in method. If the Firebase browser API key has HTTP-referrer restrictions, add the sslip.io host there as well (not checked).

## 4. Firewall

| Rule | Direction / priority | Source | Ports | Target tag |
|---|---|---|---|---|
| `td-lms-allow-web` | ingress / 1000 | 0.0.0.0/0 | tcp:80, 443 | `td-lms-demo` |
| `td-lms-allow-ssh-iap` | ingress / 800 | 35.235.240.0/20 (IAP) | tcp:22 | `td-lms-demo` |
| `td-lms-deny-ssh-rdp-public` | ingress / 900 **DENY** | 0.0.0.0/0 | tcp:22, 3389 | `td-lms-demo` |

The deny rule overrides the project's pre-existing `default-allow-ssh` and `default-allow-rdp` (0.0.0.0/0) for this VM. Those defaults were left in place for other uses. Postgres, Redis, S3 :8333, Mailpit and the API publish **no** host ports at all. SSH works only through IAP: `gcloud compute ssh … --tunnel-through-iap`.

## 5. Operations (always pass `--project billing-f4fe3`; never change the gcloud default project)

```bash
Z="--zone asia-south1-a --project billing-f4fe3"
SSH="gcloud compute ssh td-lms-demo $Z --tunnel-through-iap --command"

# Status / logs
$SSH "sudo bash /opt/techdrona/src/infra/gcp-demo/vm.sh ps"
$SSH "sudo bash /opt/techdrona/src/infra/gcp-demo/vm.sh logs api"

# Stop to save cost (disk + static IP are still billed, about Rs 1k/month)
gcloud compute instances stop td-lms-demo $Z
# Start again: Docker restarts the whole stack automatically (tested: /login 200 about 1 min after start)
gcloud compute instances start td-lms-demo $Z
```

**Update or redeploy code** (from the repo root on the PC, Git Bash). Images are built on the VM.

```bash
git ls-files -co --exclude-standard \
 | grep -vE '^(backups/|docs/redesign/shots/|research/|research_notes/|reports/|tests/)|(^|/)node_modules/|(^|/)\.next/|(^|/)\.venv/|(^|/)\.env($|\.)|(^|/)(test-results|playwright-report|out)/' \
 > /tmp/td-files.txt
tar --ignore-failed-read -czf /tmp/td-src.tgz -T /tmp/td-files.txt
gcloud compute scp /tmp/td-src.tgz td-lms-demo:td-src.tgz $Z --tunnel-through-iap
$SSH 'set -e; sudo rm -rf /opt/techdrona/src.new && sudo mkdir /opt/techdrona/src.new &&
  sudo tar -xzf td-src.tgz -C /opt/techdrona/src.new --no-same-owner && rm td-src.tgz &&
  sudo rm -rf /opt/techdrona/src.old && sudo mv /opt/techdrona/src /opt/techdrona/src.old &&
  sudo mv /opt/techdrona/src.new /opt/techdrona/src && sudo chmod -R a+rX /opt/techdrona/src &&
  cd /tmp && sudo bash /opt/techdrona/src/infra/gcp-demo/vm.sh build && sudo bash /opt/techdrona/src/infra/gcp-demo/vm.sh up'
```

**College Data Portal** (`college-portal` service, served at `/college-portal/`, opened from Admin › College Data Portal): needs `TD_COLLEGE_PORTAL_SECRET` in `server.env`, and its SQLite DB is not part of the source tarball (`*.db` is git-ignored). Import it once with `vm.sh portal-import <file.db>` and back it up with `vm.sh portal-backup`. See [`docs/college-data-portal.md`](../college-data-portal.md) §5.

`up` runs `alembic upgrade heads` (the `migrate` service) before the app starts. The Next.js build takes about 6–8 minutes on e2-standard-2. Data volumes (`techdrona_pgdata`, `techdrona_s3-data`, …) survive redeploys.

**Rotate credentials again** (the output goes straight to the PC file and is never shown on screen):

```bash
$SSH "sudo bash /opt/techdrona/src/infra/gcp-demo/vm.sh rotate --owner-email syamgopalmeda@gmail.com" \
  > /c/Users/SYAM/.secrets/techdrona-full-lms/demo-accounts.json   # add --reset-owner to reset the owner too
```

**Changing a server secret:** edit `/opt/techdrona/server.env` and the PC copy, then `vm.sh up`. Postgres role passwords are set only on the first database init. To change one, use `ALTER ROLE … PASSWORD` too. Redis passwords take effect on `up`.

**Tear down everything** (irreversible: demo data is lost):

```bash
gcloud compute instances delete td-lms-demo $Z
gcloud compute addresses delete td-lms-demo-ip --region asia-south1 --project billing-f4fe3
gcloud compute firewall-rules delete td-lms-allow-web td-lms-allow-ssh-iap td-lms-deny-ssh-rdp-public --project billing-f4fe3
```

Backups: there are none (demo). Before relying on the data, take a disk snapshot: `gcloud compute disks snapshot td-lms-demo --zone asia-south1-a --project billing-f4fe3`.

## 6. Verification (2026-11-09, from the owner's PC)

| Check | Result | Label |
|---|---|---|
| `https://35-244-50-26.sslip.io/` and `/login` | 200. Valid Let's Encrypt cert (TLS 1.3, expires 2027-02-07, auto-renews). `http://` → 308 to https | automated |
| Admin login via the BFF (CSRF bootstrap → `auth/login` → `auth/mfa/verify` with the rotated TOTP) | `mfa_required` → `authenticated`. `/api/v1/me` 200, `/api/v1/admin/dashboard` 200, `/admin` page 200. Re-tested after a VM stop/start | automated (API-level) |
| Trainer login (rotated password + TOTP) | authenticated, `/trainer` 200 | automated |
| Student login | first device `authenticated`. New device → e-mail OTP read from internal Mailpit → `authenticated`. `/app/learning` 200, `/api/v1/me/enrolments` 200 (0 items for `student@`) | automated |
| Owner admin | login OK, then restricted (`login_incomplete`) until TOTP enrolment | automated |
| Old public password `dev-only-lantern-harbour-2026` | 401 `invalid_credentials` (admin, student, retired security@) | automated |
| Secrets in served HTML/JS (5 pages + 17 JS chunks checked against all 30 server secrets and all account passwords/TOTP secrets) | 0 hits. Dev password and dev TOTP also absent | automated |
| Security headers on `/login` | HSTS, CSP, X-Frame-Options, X-Content-Type-Options, COOP present | automated |
| External ports 22, 1025, 3000, 5432, 6379, 6380, 8000, 8025, 8333, 9000, 9333, 13000, 18000, 18001 | all closed (only 80/443 open). SSH only via IAP | automated |
| `/api/v1/healthz` via the BFF | 404. Health is not exposed publicly by design (API `/healthz` is internal and used by container health checks; all 14 long-running containers are healthy) | automated |
| S3 files host | anonymous 403. CORS preflight from the app origin 204 with the correct `Access-Control-Allow-Origin` | automated |
| A real file upload or download in the browser (presigned POST via the files host) | not tested | not-verifiable here |
| Browser UI walkthrough (rendering, Google sign-in popup) | not done in a browser. The Google provider must be enabled by the owner first | not-verifiable here |
| E-mail delivery to real inboxes | none by design (Mailpit internal) | n/a |

Resource use at idle: about 1.4 GB RAM for containers (8 GB VM) and 16 GB of 40 GB disk (including build cache).

## 7. Cost (estimate, asia-south1 list prices, not a quote)

| Item | Monthly |
|---|---|
| e2-standard-2 VM, 730 h (E2 gets no sustained-use discount) | about US$58 (about Rs 4,900) |
| 40 GB pd-balanced | about US$5 (about Rs 400) |
| Static external IPv4 in use | about US$3.7 (about Rs 310) |
| Internet egress (demo traffic, about 10–20 GB at about US$0.12/GB) | about US$1–3 (about Rs 100–250) |
| **Total running 24×7** | **about US$68–70 (about Rs 5,700–5,900)** |
| VM stopped (disk + reserved IP about US$7.3) | about US$12 (about Rs 1,000) |

Cheaper options: stop the VM outside demo hours. You can also switch to **e2-medium** (4 GB) after building (`gcloud compute instances set-machine-type td-lms-demo $Z --machine-type e2-medium` while stopped). That is about Rs 2,500/month less, but rebuild the web image on e2-standard-2 because the Next.js build needs the memory. A real domain later means pointing an A record at 35.244.50.26 (the static IP), then updating `TD_HOST`, `TD_FILES_HOST`, `TD_PUBLIC_BASE_URL`, `WEB_BASE_URL`, `TD_ALLOWED_ORIGINS`, `NEXT_PUBLIC_BASE_URL`, `TD_CSP_UPLOAD_ORIGINS`, `S3_ENDPOINT_URL` and `TD_WEBAUTHN_RP_ID` in `server.env`, rebuilding web, running `up`, and adding the domain to the Firebase authorized domains.

## 8. Company website on the main host (2026-11-11, owner request)

| Address | Serves |
|---|---|
| `https://35-244-50-26.sslip.io/` (`TD_SITE_HOST`) | The Tech Drona **company website** (React build from the `tech drona` repo), static files in `/opt/techdrona/website`, served by Caddy. `/admin` here is the **Website Admin**, `/learn` the website's student portal, `/teach` its Teacher Portal, `/verify` its certificate checks. |
| `https://lms.35-244-50-26.sslip.io/` (`TD_HOST`) | The **LMS** (web BFF): `/login` (central login), `/modules`, `/app`, `/trainer`, `/studio`, `/admin` (LMS admin), `/admin/college-data` (Colleges Management). |
| `https://files.35-244-50-26.sslip.io/` (`TD_FILES_HOST`) | SeaweedFS S3 (unchanged). |

Old LMS links on the main host (`/login`, `/app`, `/studio`, `/modules`, `/sso/*`, `/college-portal/*`, `/api/v1/*`, …) redirect (302) to the same path on the LMS host; see the `@lms` matcher in `Caddyfile`.

`server.env`: `TD_SITE_HOST=35-244-50-26.sslip.io`, `TD_WEBSITE_URL=https://35-244-50-26.sslip.io` (website SSO target), and `TD_HOST`, `TD_PUBLIC_BASE_URL`, `WEB_BASE_URL`, `TD_ALLOWED_ORIGINS`, `NEXT_PUBLIC_BASE_URL`, `TD_WEBAUTHN_RP_ID` on `lms.35-244-50-26.sslip.io`. `NEXT_PUBLIC_BASE_URL` is baked into the web image, so changing it needs `vm.sh build`. Firebase Auth authorised domains include both hosts.

**Update the website** (its build needs more memory than the owner's PC has): upload `src index.html package*.json vite.config.js .env scripts/check-brand.mjs brochures/{courses,*.mjs} public` to the VM, build in `node:22-bookworm-slim` (`npm ci && node node_modules/vite/bin/vite.js build`), then copy `dist` INTO the existing `/opt/techdrona/website` (`rsync -a --delete dist/ /opt/techdrona/website/`). Do not delete and re-create the folder: Caddy's bind mount keeps pointing at the old (deleted) folder and the site returns 404 until `docker restart techdrona-caddy-1`.

On the LMS host, visitors who are not signed in are redirected away from the LMS marketing pages (`/`, `/courses`, `/pricing`, `/placement`, `/companies`, `/free-resources`, `/enquiries`, `/status`) to the main website; signed-in users (session cookie present) still get the in-app catalogue and checkout. The LMS host sends `X-Robots-Tag: noindex` and a `Disallow: /` robots.txt, so the only indexed website is the main one. The same `dist` can also be deployed to Firebase Hosting (`techdrona-website.web.app`).
