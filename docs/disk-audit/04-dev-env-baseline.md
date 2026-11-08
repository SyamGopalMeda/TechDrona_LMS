# 04 - Dev environment baseline (pre-cleanup)

Taken 2026-11-07, read-only, BEFORE the drive C: cleanup. Nothing was modified, installed or restarted.
Drive state at capture: **C: 8.38 GB free / 360.72 GB used**, D: 7.48 GB free / 98.00 GB used.
(Docker's internal FS is read-only due to the full disk; that is expected and was not touched.)

## 1. Tools: locations and versions

| Tool | Location | Version | On C:? |
|---|---|---|---|
| Python (venv base) | `C:\Python313\python.exe` (pyvenv.cfg `home = C:\Python313`, ~149 MB) | 3.13.7 | **Yes - venv is unusable without it** |
| pip (global) | `C:\Python313\Scripts\pip.exe` | - | Yes |
| py launcher | `C:\Users\SYAM\AppData\Local\Microsoft\WindowsApps\py.exe` | - | Yes |
| node | `C:\Program Files\nodejs\node.exe` (~102 MB) | v24.21.0 | Yes |
| npm / npx | `C:\Program Files\nodejs\npm.ps1`, `npx.ps1` | 11.19.0 | Yes |
| npm global prefix | `C:\Users\SYAM\AppData\Roaming\npm` (~454 MB; contains `@colbymchenry\codegraph`, `firebase-tools`) | - | Yes |
| npm cache | `C:\Users\SYAM\AppData\Local\npm-cache` (~1,020 MB) | - | Yes (safe-ish cache) |
| git | `C:\Program Files\Git\cmd\git.exe` (~410 MB; also provides Git Bash used by `.sh` scripts) | 2.52.0.windows.1 | Yes |
| docker | `C:\Program Files\Docker\Docker\resources\bin\docker.exe` | 29.2.0 | Yes |
| docker compose | plugin | v5.0.2 | Yes |
| ffmpeg | `C:\ProgramData\chocolatey\bin\ffmpeg.exe` (lib ~288 MB) | 7.1 essentials (gyan.dev) | Yes |
| codegraph CLI | `C:\Users\SYAM\AppData\Roaming\npm\codegraph.ps1` -> `...\npm\node_modules\@colbymchenry\codegraph` | 1.6.2 | Yes |
| make, pnpm, yarn, uv, nvm, fnm, volta, psql, pg_dump, curl (PowerShell) | not on PATH | - | - |

Notes:
- No nvm/fnm/volta node managers present - node is a single system install.
- `make` is not installed; on Windows the project uses `scripts\*.ps1` (dev-up, reset-db, reset-dev-data, run-api, run-web, seed-dev, test-all). The Makefile's `tf-fmt`, `lint-infra`, `actionlint` targets use Docker images (`hashicorp/terraform:1.9.8`, `rhysd/actionlint:1.7.7`).
- `psql`/`pg_dump` are not on the host; DB dumps/restores go through `docker compose exec postgres ...`.
- In PowerShell, `curl` is an alias for `Invoke-WebRequest`; use `curl.exe` for real curl.

### CodeGraph index
- `.codegraph\` at repo root: ~102.3 MB (5 files), on D:.
- `codegraph status`: 1,260 files, 25,584 nodes, 74,547 edges, DB 102.21 MB, backend node:sqlite (WAL).

### Playwright (apps/web)
- `@playwright/test` ^1.56.0 in package.json; installed `@playwright/test` / `playwright-core` **1.64.1**.
- Required browsers for 1.64.1: chromium rev **1248**, chromium-headless-shell **1248**, ffmpeg **1013** (firefox 1555 / webkit 2370 are NOT needed - `playwright.config.ts` only defines `chromium` and `mobile` (Pixel 7, Chromium) projects).
- `%LOCALAPPDATA%\ms-playwright` (~718 MB, on C:): `chromium-1248` (436 MB), `chromium_headless_shell-1248` (277 MB), `ffmpeg-1013` (4 MB), `winldd-1007`, `.links`. `PLAYWRIGHT_BROWSERS_PATH` unset. **All required browsers present.** If deleted, restore with `npx playwright install chromium` in apps/web (~700 MB download).

## 2. Project-local dependencies (all on D:)

| Item | State |
|---|---|
| `apps\api\.venv` | 254.1 MB, 12,376 files; `python -c "import fastapi, sqlalchemy, alembic, pytest"` -> **IMPORT OK** (Python 3.13.7, fastapi 0.162.0, sqlalchemy 2.1.6, alembic 1.20.1, pytest 9.2.0) |
| `apps\web\node_modules` | 594.2 MB, 35,682 files; `next`, `.bin\tsc.cmd` present (next 15.5.28, typescript ~5.9.3) |
| `apps\node_modules` | 0.1 MB - only `.vite`, `.vite-temp`, `.vitest-cache` (tool cache, regenerable) |
| `packages\design-tokens` | package.json present, no own node_modules (none expected) |
| root `node_modules` / `package.json` | none (no workspace root) |

## 3. Data that must be preserved

### Backups (`D:\company website\techdrona LMS\backups\`)
| File | Size | Modified | SHA256 |
|---|---|---|---|
| `techdrona-dev-before-college-removal-20261106.dump` | 933,864 bytes | 2026-11-06 15:44:27 | `F7AB542CDDA6946C9B3C7F87F625047A95E5E94FF59DC8358758EB7B173CDA81` |

### .env files (existence only; contents not read)
- `D:\company website\techdrona LMS\.env` - **exists** (root; overrides host ports - e.g. redis is published on 16379/16380)
- `.env.example` - exists
- `apps\api\.env`, `apps\web\.env`, `apps\web\.env.local` - do not exist

### Docker (compose project `techdrona`)
Named volumes (all live inside `C:\Users\SYAM\AppData\Local\Docker\wsl\disk\docker_data.vhdx`, **31.64 GB, on C:**):
- `techdrona_pgdata` - **Postgres data, dev DB `techdrona` (+ `techdrona_test`)** - critical
- `techdrona_s3-data` - SeaweedFS object storage - keep
- `techdrona_redis-queue-data` - Redis AOF (Celery queue) - keep
- `techdrona_redis-cache-data`, `techdrona_mailpit-data` - low value but keep

Bind mounts (on D:, read-only): `./scripts/db-init` -> postgres initdb, `./infra/docker/s3/s3.json`, `./infra/docker/s3/create-buckets.sh`.

Images used: `techdrona/postgres-local:16` (built), `techdrona/td-api:local`, `techdrona/td-web:local`, `redis:7.4-bookworm`, `axllent/mailpit:v1.27`, `chrislusf/seaweedfs:3.80`, `amazon/aws-cli:2.22.35`.

Other projects' volumes also exist in the same vhdx (`enterpriseaiknowledgeplatform_*`, `godavaripushkaralutrail4_*`, `student-security-system_postgres_data`, 4 anonymous) - not ours; ask the user before pruning.

Container status at capture (`docker compose ps -a`, may be stale while Docker is read-only): api, api-webhooks, audit-sealer, scheduler, web, worker, worker-judge, worker-maintenance up (healthy, 4 h); postgres, redis, redis-queue, mailpit, s3 up 24 h; migrate and s3-init exited (0). Ports: api 18000, api-webhooks 18001, web 13000, redis 16379/16380, mailpit 1025/8025, s3 9000.

**NEVER run** `docker system prune --volumes`, `docker volume prune`, `docker compose down -v`, `wsl --unregister docker-desktop*`, or delete/reset `docker_data.vhdx` - this destroys the `techdrona` DB. Only the 0.93 MB backup above exists outside Docker.

## 4. C: items a cleanup agent might mistake for caches

| Path | Size | Verdict |
|---|---|---|
| `C:\Python313` | 149 MB | **KEEP** - base interpreter of `apps\api\.venv` |
| `C:\Program Files\nodejs` | 102 MB | **KEEP** |
| `C:\Program Files\Git` | 410 MB | **KEEP** (git + Git Bash) |
| `C:\Program Files\Docker` | - | **KEEP** |
| `C:\ProgramData\chocolatey` (ffmpeg) | 288 MB | **KEEP** |
| `C:\Users\SYAM\AppData\Roaming\npm` | 454 MB | **KEEP** - global codegraph CLI (+ firebase-tools) |
| `C:\Users\SYAM\AppData\Local\ms-playwright` | 718 MB | **KEEP** (needed for e2e; regenerable but slow) |
| `C:\Users\SYAM\AppData\Local\Docker\wsl\disk\docker_data.vhdx` | 31.64 GB | **KEEP** - contains DB volumes. Compact only via Docker Desktop's supported tools after Docker restarts, never delete |
| `C:\Users\SYAM\AppData\Local\Docker\wsl\main\ext4.vhdx` | 0.1 GB | KEEP |
| `C:\Users\SYAM\.claude` | 2,857 MB (projects 2,806 MB) | **KEEP** - Claude Code state, credentials, settings, memory (`projects\d--company-website-techdrona-LMS\memory`) |
| `C:\Users\SYAM\AppData\Local\Temp\claude` | 5,543 MB | **KEEP whole folder** - holds the ACTIVE session (`3eb179e72a8561e7`, also `96bc413f2bb7cb1e` modified today 14:18). Older dirs (e.g. `c--Users-SYAM-Downloads-colleges-data-main...` 2.58 GB) only with user approval |
| `C:\Users\SYAM\.vscode\extensions` | 1,664 MB | KEEP (IDE) |
| `C:\Users\SYAM\AppData\Local\npm-cache` | 1,020 MB | Safe to clear (`npm cache clean --force`); project node_modules unaffected |
| `C:\Users\SYAM\AppData\Local\pip\cache` | 114 MB | Safe to clear (`pip cache purge`); venv unaffected |
| `C:\Users\SYAM\AppData\Local\node-gyp` | 51 MB | Regenerable |
| `C:\Users\SYAM\.cache` | 3,926 MB (codex-runtimes 2.28 GB, huggingface 1.51 GB, firebase 130 MB) | Not used by this project; other tools' data - ask user |
| `C:\Users\SYAM\AppData\Local\Temp` (total) | 8,329 MB incl. 5.5 GB `claude` | Clean only non-`claude` items |

## 5. Post-cleanup verification checklist

Run from `D:\company website\techdrona LMS` in PowerShell after Docker Desktop has been restarted.

```powershell
# Disk
Get-PSDrive C | % { "{0:N2} GB free" -f ($_.Free/1GB) }

# Tools
python --version                       # Python 3.13.7, C:\Python313
node --version; npm --version          # v24.21.0 / 11.19.0
git --version                          # 2.52.0
docker --version; docker compose version   # 29.2.0 / v5.0.2
ffmpeg -version | Select -First 1      # 7.1
codegraph --version                    # 1.6.2
codegraph status                       # ~1,260 files, ~25.6k nodes

# Python venv
& ".\apps\api\.venv\Scripts\python.exe" -c "import fastapi, sqlalchemy, alembic, pytest; print('OK')"

# Web toolchain
cd apps\web; npx tsc --noEmit; npx playwright --version; cd ..\..   # 1.64.1
Test-Path "$env:LOCALAPPDATA\ms-playwright\chromium-1248","$env:LOCALAPPDATA\ms-playwright\chromium_headless_shell-1248","$env:LOCALAPPDATA\ms-playwright\ffmpeg-1013"

# Docker data
docker volume ls --filter name=techdrona    # 5 volumes: pgdata, s3-data, redis-queue-data, redis-cache-data, mailpit-data
docker compose ps -a
docker compose exec postgres psql -U techdrona -d techdrona -c "select count(*) from alembic_version;"
docker compose exec postgres psql -U techdrona -l     # techdrona, techdrona_test present

# App endpoints
curl.exe -s -o NUL -w "%{http_code}`n" http://localhost:13000/      # expect 200
curl.exe -s http://localhost:18000/healthz                          # expect healthy JSON / 200

# Backup integrity
Get-FileHash ".\backups\techdrona-dev-before-college-removal-20261106.dump" -Algorithm SHA256
# expect F7AB542CDDA6946C9B3C7F87F625047A95E5E94FF59DC8358758EB7B173CDA81

# Config / Claude state
Test-Path .\.env                                   # True
Test-Path "$env:USERPROFILE\.claude\settings.json","$env:USERPROFILE\.claude\.credentials.json"
```
