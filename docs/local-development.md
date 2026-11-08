# Local development

Owner: DevOps. Status: Stage 10 (integration). Related: `docs/implementation-conventions.md` §7 (commands), `docs/deployment-and-operations.md` §1.1 (local stack), `.env.example` (variable names).

Everything below runs on a developer laptop only. Nothing here is used in AWS, and every credential in `docker-compose.yml`, `scripts/db-init/` and `.env.example` is a local placeholder.

## 1. What runs where

| Component | How it runs locally | Host port (default) | Override variable in `.env` |
|---|---|---|---|
| PostgreSQL 16 + `pg_partman`, `pgcrypto`, `citext`, `btree_gist`, `pg_stat_statements` | `docker compose` service `postgres` (image built from `infra/docker/postgres/Dockerfile`) | 5432 | `TD_PG_HOST_PORT` |
| Redis 7 `cache` (allkeys-lru) | service `redis` | 6379 | `TD_REDIS_CACHE_HOST_PORT` |
| Redis 7 `queue` (noeviction, AOF) | service `redis-queue` | 6380 | `TD_REDIS_QUEUE_HOST_PORT` |
| Mailpit (SMTP sink + UI) | service `mailpit` | 1025 SMTP / 8025 UI | `TD_SMTP_HOST_PORT` / `TD_MAILPIT_UI_HOST_PORT` |
| S3 emulator (SeaweedFS; buckets `local-td-*` created by `s3-init`) | service `s3` | 9000 | `TD_S3_HOST_PORT` |
| FastAPI (`apps/api`) | on the host: `scripts/run-api.ps1` | 8000 | `-Port` / `TD_API_PORT` |
| Next.js BFF (`apps/web`) | on the host: `scripts/run-web.ps1` | 3000 | `-Port` |
| Full app in containers (api, api-webhooks, Celery worker + worker-maintenance, beat, judge worker, audit sealer, web) | compose profile `app` (§6) | api 18000, web 13000 | `TD_API_HOST_PORT` / `TD_WEB_HOST_PORT` |
| GlitchTip (ADR-0014) | opt-in compose profile `errors-local` | 8001 | — |

The databases created on first start of an empty volume (`scripts/db-init/`):

| Item | Value |
|---|---|
| Bootstrap superuser (init scripts, admin only) | `techdrona` / `techdrona_dev` |
| Databases | `techdrona` (dev) and `techdrona_test` (integration tests) |
| Application roles (LOGIN, NOSUPERUSER, NOBYPASSRLS) | `td_owner` (migrations, CREATEROLE), `td_app` (runtime; tests run as this role), `td_readonly`, `td_audit_sealer`, `td_maintenance` with the `local_*_pw_REPLACE` passwords from `.env.example` |
| Extensions (both databases) | `pgcrypto`, `citext`, `btree_gist`, `pg_stat_statements`, `pg_partman` (schema `partman`) |

Schemas, grants on tables, RLS policies and helper functions are **not** created by the init scripts. They belong to the Alembic `core_base` migration (ADR-0009). That migration must use `IF NOT EXISTS` / `DO` blocks for roles and extensions, because they already exist locally.

MinIO is not used: MinIO no longer publishes images on Docker Hub. SeaweedFS speaks the S3 API on the same host port (`S3_ENDPOINT_URL=http://localhost:9000`) and accepts the `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` placeholders from `.env.example`. Object Lock and versioning are not emulated; they are enforced only in AWS.

## 2. Prerequisites

| Tool | Version | Windows | Linux |
|---|---|---|---|
| Docker | Docker Desktop 4.x (Compose v2.24+) | Docker Desktop with the WSL 2 backend | Docker Engine + compose plugin |
| Git | 2.40+ | Git for Windows | distro package |
| Python | 3.12+ (3.13 works) | python.org installer or `py` launcher | distro package or `pyenv` |
| Node.js | 22 LTS | nodejs.org installer | NodeSource / `nvm` |
| GNU make (optional) | any | not needed: use `scripts/*.ps1` | distro package |

Terraform is not needed locally. `make lint-infra` / `make tf-fmt` run it in a throwaway `hashicorp/terraform:1.9.8` container.

## 3. Windows (PowerShell)

Run these from the repository root (`D:\company website\techdrona LMS`). If script execution is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once.

```powershell
# 1. Data services. Creates .env from .env.example if missing, warns about busy ports, waits for healthy.
./scripts/dev-up.ps1

# 2. API: creates apps/api/.venv, installs -e ".[dev]", applies migrations, starts uvicorn with reload.
./scripts/run-api.ps1 -Install -Migrate

# 3. Web (second terminal): installs node_modules on first run, then runs next dev on :3000.
./scripts/run-web.ps1

# 4. All local gates (ruff, mypy, migrations on techdrona_test, pytest + coverage, route guard, web lint/type/test/build).
./scripts/test-all.ps1

# Reset the local database (DESTROYS local data, re-runs init scripts and migrations).
./scripts/reset-db.ps1 -Force
```

The equivalent manual commands (conventions §7):

```powershell
docker compose up -d
cd apps/api; python -m venv .venv; .venv/Scripts/pip install -e ".[dev]"
.venv/Scripts/alembic upgrade heads
.venv/Scripts/pytest
cd ../web; npm install; npm run dev
```

### 3.1 Port conflicts on Windows (important)

Windows machines often already run a native PostgreSQL service on 5432 and a native Redis on 6379. When that happens, `localhost:5432` resolves to `::1` first and you silently connect to the **wrong** server, which shows up as password authentication failures for `td_app`. Pick free ports and put them in `.env`, which docker-compose also reads:

```dotenv
TD_PG_HOST_PORT=15432
TD_REDIS_CACHE_HOST_PORT=16379
TD_REDIS_QUEUE_HOST_PORT=16380
```

Then change the matching URLs in the same `.env`: `DATABASE_URL`, `DATABASE_READ_URL`, `DATABASE_MIGRATION_URL`, `DATABASE_MAINTENANCE_URL`, `DATABASE_AUDIT_SEALER_URL` → `localhost:15432`; `REDIS_CACHE_URL` → `localhost:16379`; `REDIS_QUEUE_URL` → `localhost:16380`. Restart with `./scripts/dev-up.ps1`.

To see what owns a port: `Get-NetTCPConnection -State Listen -LocalPort 5432 | Select-Object OwningProcess` and `netstat -ano | findstr :5432`.

### 3.2 Line endings

The repository stores LF (`.gitattributes`). Shell scripts and `scripts/db-init/*` are mounted into Linux containers and must stay LF. Do not set `core.autocrlf=true` for this repository; `git init` here set `core.autocrlf=false`.

## 4. Linux / macOS / WSL

```bash
scripts/dev-up.sh                      # data services (creates .env if missing)
cd apps/api && python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade heads
.venv/bin/uvicorn --factory app.main:create_app --reload --env-file ../../.env
# second terminal
cd apps/web && npm ci && npm run dev
# tests
make test            # or: make test-api / make test-web
scripts/reset-db.sh --force
```

`make help` lists all targets.

## 5. Test database

Integration tests use the real Postgres in a separate database (conventions §6). `apps/api/tests/conftest.py` takes `DATABASE_URL`, `DATABASE_MIGRATION_URL` and `DATABASE_AUDIT_SEALER_URL` from the environment or `.env` and swaps the database name to `TD_TEST_DB_NAME` (default `techdrona_test`). It then applies `alembic upgrade heads` to that database itself. To override a single role, set `TEST_DATABASE_URL`, `TEST_MIGRATION_DATABASE_URL` or `TEST_SEALER_DATABASE_URL`. `TD_TEST_RESET_DB=1` drops and recreates the test database first; use a distinct `TD_TEST_DB_NAME` per parallel run so runs do not drop each other's database.

```powershell
cd apps/api
$env:TD_TEST_DB_NAME = 'techdrona_test'; .venv/Scripts/pytest -q
```

Tests must connect as `td_app`, never as the `techdrona` superuser, or RLS `FORCE` would be bypassed.

## 5a. Demo data (seeds)

Run the seeds after `alembic upgrade heads` on the dev database `techdrona`. Every seed is idempotent and refuses to run when `APP_ENV` is `prod` or `production`. The scripts run on the host with `apps/api/.venv`, because the `td-api` image ships no demo seeds (G-21).

```powershell
./scripts/seed-dev.ps1 -Migrate          # or: scripts/seed-dev.sh --migrate  /  make seed
./scripts/seed-dev.ps1 -Only catalog_demo,coding_demo
```

They run in this order: `rbac_seed` (role/permission reference data) → `dev_users` → `catalog_demo` → `placement_demo` → `coding_demo` → `commerce_demo` → `security_demo` → `e2e_demo`. All accounts share the demo password `dev_users` prints; staff accounts get fixed, DEV-ONLY TOTP secrets (`DEV_TOTP_SECRETS` in `app/seeds/dev_users.py`), so they survive a reset. The accounts are `student@` (clean learner with a practice grant), `restricted.student@` (L3, no review request), `reverify.student@` (L3 lifted, re-verification pending), `suspended.student@` (L4 high-risk case with a submitted request), `minor.student@`, `coordinator@`, `trainer@`, `support@`, `security@`, `security2@`, `finance@`, `content@`, `admin@` and `admin2@dev.techdrona.local`.

To start over with a fresh dev database (only `techdrona`; test databases are untouched), all seeds and the Playwright env file `apps/web/.env.e2e.local`:

```powershell
./scripts/reset-dev-data.ps1 -Force
```

## 6. Optional containers

```bash
docker compose --profile app up -d --build --wait   # full app (below); api http://localhost:18000, web http://localhost:13000
docker compose --profile app stop migrate api api-webhooks worker worker-maintenance scheduler worker-judge audit-sealer web
docker compose exec postgres createdb -U techdrona glitchtip
docker compose --profile errors-local up -d       # GlitchTip on http://localhost:8001
```

| Service (profile `app`) | Command | Health |
|---|---|---|
| `migrate` (one-off) | `alembic upgrade heads` | must exit 0 before the others start |
| `api` / `api-webhooks` | uvicorn `app.main:create_app` (`TD_ROUTER_SET=user` / `webhooks`) | `GET /healthz` |
| `worker` | `celery -A app.worker.celery_app worker -Q critical,default,notifications,analytics,reports` | `celery inspect ping` |
| `worker-maintenance` | same, `-Q maintenance` | `celery inspect ping` |
| `scheduler` | `celery -A app.worker.celery_app beat` | — |
| `worker-judge` | `python -m app.modules.coding.worker` (`JUDGE_PROVIDER=fake`) | — |
| `audit-sealer` | `python -m app.modules.audit.sealer` (beat sealing off: `TD_AUDIT_SEALER_BEAT_ENABLED=false`) | — |
| `web` | Next.js standalone `server.js` | `GET /` |

The containers read the root `.env` and then override the host URLs with container-network ones (`x-app-env` in `docker-compose.yml`). The API is published on host port 18000 and the web on 13000, so they do not clash with the host dev loop on 8000/3000 or with other local services on 8000. Change them with `TD_API_HOST_PORT` / `TD_WEB_HOST_PORT`. Load demo data from the host with `scripts/seed-dev.ps1` (§5a). Stop only the app containers with the `stop` command above. The data services keep running.

## 7. Useful commands

| Task | Command |
|---|---|
| Status | `docker compose ps -a` |
| Logs | `docker compose logs -f postgres` |
| psql as superuser | `docker compose exec postgres psql -U techdrona -d techdrona` |
| psql as the app role | `docker compose exec -e PGPASSWORD=local_app_pw_REPLACE postgres psql -h 127.0.0.1 -U td_app -d techdrona_test` |
| Redis CLI | `docker compose exec redis redis-cli` |
| Mail UI | http://localhost:8025 |
| Stop (keep data) | `docker compose down` |
| Wipe everything | `docker compose down -v` |
| Lint workflows | `make actionlint` |
| Terraform fmt/validate | `make lint-infra` |

## 8. CI and deploy

- `.github/workflows/ci.yml` runs the gates (testing-and-acceptance-criteria §10): lint and types, pytest with coverage, migration checks, the route-guard test, Semgrep, CodeQL, gitleaks, pip-audit, npm audit, OSV-Scanner, Trivy, hadolint, actionlint, and Terraform fmt/validate/Checkov. CI starts Postgres and Redis with this same `docker-compose.yml`, so CI and local runs use the same init scripts. The `e2e` job (main pushes, nightly and manual runs) starts the whole `app` profile, runs `scripts/seed-dev.sh`, and then runs Playwright with `E2E_INTEGRATION=1` against `http://localhost:13000`.
- `.github/workflows/deploy.yml` is a **disabled skeleton**: it only runs on manual dispatch and does nothing unless the repository variable `DEPLOY_ENABLED` is `true`. Do not enable it until the AWS accounts, OIDC roles and ECR repositories exist (`infra/terraform`).
