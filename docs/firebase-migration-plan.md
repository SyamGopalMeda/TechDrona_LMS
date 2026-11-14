# Tech Drona LMS: move from the Google VM to Firebase (React + Functions)

Status: **APPROVED by owner 2026-11-12, in progress.** Earlier history: `docs/firebase/MIGRATION-PLAN.md` (2026-11-08), `p0.md`, `p1.md`, `p2.md`, `single-project.md`.

## 1. Owner requirements (2026-11-12)

1. Frontend: **React SPA (Vite)** on **Firebase Hosting**.
2. Backend: **Firebase Cloud Functions**. Database: **Firestore**. No Google VM at the end.
3. **No feature or behaviour changes.** Everything that works today keeps working the same way.
4. Move module by module, using parallel agents to go faster.

## 2. Approach: same backend code, new home

The fastest way to meet requirement 3 is to **keep the existing code and API contract** and change only where it runs and what it stores data in:

| Today (VM) | After (Firebase) | Behaviour change |
|---|---|---|
| Next.js app (204 pages) | The same React components and pages, built with **Vite + React Router**. A small adapter replaces `next/link`, `next/navigation` and `next/dynamic`. Server-side page loads become client-side loads. | None (same UI) |
| Next.js BFF (cookies, CSRF, `/api/v1` proxy) | Done inside the API function. Firebase Hosting forwards only the `__session` cookie, so session and device cookies are packed into it. | None (same API) |
| FastAPI in Docker | The **same FastAPI app** served by a **Python 2nd-gen Cloud Function** (`functions-lms/`, `asia-south1`). Hosting rewrites `/api/**` to it. | None (same 527 endpoints) |
| Postgres (163 tables) | **Firestore** `lms_*`, one module at a time behind `TD_STORE_<MODULE>=firestore` (store layer from P0). Each module flips only after tests pass on both stores. | None (same results) |
| Redis (cache, rate limits) | Firestore-backed implementations behind a runtime switch | None |
| Celery workers + beat | Cloud Tasks queues + scheduled functions | None |
| SeaweedFS S3 | Cloud Storage (S3-compatible interop, so the same boto3 code) | None |
| Caddy TLS | Firebase Hosting | None |

The website is not touched. The LMS gets its own Hosting site and its own functions codebase (`lms`), so website deploys and LMS deploys never overwrite each other.

## 3. Work split (parallel agents, 2026-11-12)

| Agent | Scope |
|---|---|
| platform | `functions-lms/` (FastAPI on Functions), BFF behaviour, Redis → Firestore, Celery → Cloud Tasks/scheduler, S3 → Cloud Storage, `core` tables (outbox, idempotency), Hosting/functions config |
| spa | `apps/lms-spa/`: Vite + React Router port of `apps/web` |
| data-access | identity, sessions, rbac, orgs |
| data-content | catalog (finish), media, entitlements, paths |
| data-learning | learning, engage, mentoring |
| data-assess | assessments, coding, placement |
| data-money | commerce, admissions, notifications, support |
| data-ops | analytics, audit, security, admin (rest), ai (rest), hub |

Each agent reports in `docs/firebase/agents/<agent>.md`.

## 4. Safety rules (protect what runs today)

- Every `TD_STORE_*` stays at its default `postgres`. The live VM keeps running unchanged.
- No deploys, VM changes, website changes or Firestore rules changes during agent work.
- A module flips to Firestore only after its tests pass on **both** stores and are verified on the deployed Firebase stack.
- The VM is deleted only after every module has flipped, the data has been copied and checked, the live Firebase site passes the full test walkthrough, **and the owner approves**. A disk snapshot and `pg_dump` are kept for 30 days.

## 5. Owner decisions still open (not blocking current work)

1. Coding judge: today it is a fake judge (demo). A real judge needs a sandbox service outside Functions.
2. LMS address: `<site>.web.app` for now, or a custom domain later.

## 6. Verification per module

1. Unit and API tests pass on both stores (Postgres and the Firestore emulator).
2. Backfill + verify script: Postgres data → Firestore, row-by-row comparison.
3. Deploy to Firebase, then walk through the module's pages on the live site as each role.
4. Same results as the VM for the same actions.
