# LMS audit, redesign & optimisation — shared brief (binding for every agent)

Coordinator: lead session, started 2026-11-07. Owner's master prompt: complete page-by-page audit, Tech Drona-branded redesign of the WHOLE LMS UI, extreme simplicity for first-time users, fix verified defects, performance, security, a11y/responsive, tests, honest final report.

## Facts about this project (read first)
- Repo: `D:\company website\techdrona LMS`. Backend FastAPI modular monolith (`apps/api/app/modules/*`), Postgres 16 with RLS, Redis, S3 (seaweedfs), Celery. Web: Next.js 15 App Router (`apps/web/src/app`, features in `src/features`, UI kit `src/components/ui`, BFF in `src/app/api`). **No Firebase in the LMS** — the prompt's Firebase items map to the real Postgres/API/S3 stack.
- Scope decided by the owner: single company (no colleges), B2C students who sign up and buy courses via **Razorpay checkout** (fake adapter in dev; there is no manual receipt upload — do not invent one). Roles: Admin (`super_admin`), Trainer, Evaluator, Content manager, Student. See `docs/single-company/REMOVAL-PLAN.md` §8.
- Recently built features: assignments, exams/integrity, question banks, live engage, learning paths, AI (fake provider in dev). See `docs/wiseman-reference/build/*.md`.
- **Brand source of truth:** the official Tech Drona website source at `D:\company website\tech drona\` (Firebase project `techdrona`, domain https://techdrona.in): `logo-full-navy.svg` (navy `#032269`), `index.html`, `dist/assets/*` CSS, Plus Jakarta Sans, background `#faf8f4`, favicons/icons in `dist/`. `D:\company website\Logo.png` is the GloomDev logo — NOT Tech Drona; never use it.
- Live dev stack (running): web http://localhost:13000, API :18000, Mailpit :8025. Demo accounts (dev only, password `dev-only-lantern-harbour-2026`): admin@, admin2@, trainer@, evaluator@, content@, student@, asha.student@, ravi.student@ `dev.techdrona.local`. Staff need TOTP — dev secrets in `apps/api/app/seeds/dev_users.py` `DEV_TOTP_SECRETS` (pyotp available in the api venv). E2E env: `apps/api -m app.seeds.e2e_env`.
- Tools: CodeGraph (`codegraph_explore` MCP or `codegraph explore "<q>"`) before grep/Read. pnpm is NOT installed — use npx/npm. Playwright 1.64 + chromium-1248 installed (`apps/web/e2e`, configs in apps/web).

## Safety rules
- Never touch production; never print secrets; no git commits/pushes.
- Dev DB `techdrona` may be read and exercised through normal app actions (UI/API) with synthetic data; never drop/reset/restore it, never run `scripts/reset-dev-data.ps1`. Tests use your own DB `TD_TEST_DB_NAME=techdrona_rd_<key>` + `TD_TEST_RESET_DB=1`. Do NOT drop `techdrona_test` (postgres healthcheck needs it).
- Never stop/restart docker containers. Keep disk usage modest (C: has ~38 GB free; clean up your own large temp artifacts).
- Edit only files you own (see your task). Shared files: minimal, additive edits, re-read right before editing.
- Never mark something verified without evidence; label each result: automated-tested / manually-tested (browser/API) / code-reviewed / not-verifiable.

## Output locations
`docs/redesign/<key>.md` per agent. Screenshots (if any) under `docs/redesign/shots/<key>/` (PNG, keep small).
