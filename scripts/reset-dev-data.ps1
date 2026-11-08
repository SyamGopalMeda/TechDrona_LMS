<#
.SYNOPSIS
  DEV ONLY: recreate the local dev database `techdrona`, migrate, load every demo seed and write
  the Playwright E2E env file apps/web/.env.e2e.local (Windows PowerShell).

.DESCRIPTION
  1. Refuses when APP_ENV (process env or the root .env) is prod/production, or when the host
     DATABASE_URL / DATABASE_MIGRATION_URL do not point at the database `techdrona`.
  2. In the docker-compose Postgres (must be running): DROP DATABASE techdrona WITH (FORCE) and
     CREATE it again with the owner, grants and extensions scripts/db-init/ sets up. Only
     `techdrona` is touched: techdrona_test and any techdrona_test_* databases stay as they are.
     Running app containers are restarted at the end (their pooled connections point at the
     dropped database; compose runs the api without pool pre-ping); use -StopApp to stop them for
     the reset instead and start them again afterwards.
  3. scripts/seed-dev.ps1 -Migrate: `alembic upgrade heads`, then all seeds in order
     (rbac_seed, dev_users, catalog_demo, placement_demo, coding_demo, commerce_demo,
     security_demo, e2e_demo, company_demo).
  4. `python -m app.seeds.e2e_env --out apps/web/.env.e2e.local`: KEY=VALUE lines (accounts, the
     shared DEV password, DEV-ONLY TOTP secrets, E2E_L4_CASE_ID, E2E_TEST_ID, ...). The file is
     gitignored (.env.*) and loaded by apps/web/playwright.config.ts when present.
  5. Deletes apps/web/.e2e-devices (device cookies of the previous database).

.EXAMPLE
  ./scripts/reset-dev-data.ps1 -Force
  ./scripts/reset-dev-data.ps1 -Force -StopApp
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$StopApp
)

# Native tools (docker, alembic) write progress to stderr; with 'Stop' Windows PowerShell 5.1
# would turn that into terminating errors. Failures are detected via $LASTEXITCODE instead.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$api = Join-Path $root 'apps/api'
$web = Join-Path $root 'apps/web'
$db = 'techdrona'
$appServices = @('api', 'api-webhooks', 'worker', 'worker-maintenance', 'scheduler', 'worker-judge', 'audit-sealer')

function Get-DotEnvValue([string]$Name) {
    $f = Join-Path $root '.env'
    if (-not (Test-Path $f)) { return $null }
    $line = Get-Content $f | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -Last 1
    if ($line) { return ($line -split '=', 2)[1].Trim().Trim('"') } else { return $null }
}

function Get-Setting([string]$Name) {
    $v = [Environment]::GetEnvironmentVariable($Name)
    if (-not $v) { $v = Get-DotEnvValue $Name }
    return $v
}

# --- refusals -----------------------------------------------------------------------------------
$appEnv = Get-Setting 'APP_ENV'
if ($appEnv -and @('prod', 'production') -contains $appEnv.ToLowerInvariant()) {
    Write-Error "REFUSED: APP_ENV=$appEnv - reset-dev-data never runs against production."
    exit 3
}
foreach ($name in 'DATABASE_URL', 'DATABASE_MIGRATION_URL') {
    $url = Get-Setting $name
    if (-not $url) { Write-Error "$name is not set (root .env)"; exit 1 }
    $dbName = (($url -split '\?')[0] -split '/')[-1]
    if ($dbName -ne $db) {
        Write-Error "REFUSED: $name points at database '$dbName', expected '$db' (dev database only)."
        exit 3
    }
}
$py = Join-Path $api '.venv/Scripts/python.exe'
if (-not (Test-Path $py)) { Write-Error 'apps/api/.venv not found - run ./scripts/run-api.ps1 -Install once.'; exit 1 }

$stopped = @()
Push-Location $root
try {
    $running = docker compose ps --status running --services 2>$null
    if ($LASTEXITCODE -ne 0 -or -not ($running -contains 'postgres')) {
        Write-Error 'The compose postgres service is not running: docker compose up -d --wait postgres'
        exit 1
    }
    if (-not $Force) {
        $answer = Read-Host "This DROPS the local dev database '$db' (all dev data). Type yes to continue"
        if ($answer -ne 'yes') { Write-Host 'Aborted.'; exit 1 }
    }

    if ($StopApp) {
        $stopped = @($appServices | Where-Object { $running -contains $_ })
        if ($stopped.Count) {
            Write-Host "==> docker compose stop $($stopped -join ' ')" -ForegroundColor Cyan
            docker compose stop @stopped | Out-Null
        }
    }

    # --- recreate techdrona (mirrors scripts/db-init/01-init.sql + 02-extensions.sh) ------------
    Write-Host "==> DROP/CREATE DATABASE $db" -ForegroundColor Cyan
    $recreate = @"
DROP DATABASE IF EXISTS $db WITH (FORCE);
CREATE DATABASE $db OWNER techdrona;
GRANT CONNECT, CREATE, TEMPORARY ON DATABASE $db TO td_owner;
GRANT CONNECT ON DATABASE $db TO td_app, td_readonly, td_audit_sealer, td_maintenance;
"@
    $recreate | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U techdrona -d postgres
    if ($LASTEXITCODE -ne 0) { Write-Error "could not recreate database $db"; exit 1 }

    $extensions = @'
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
CREATE SCHEMA IF NOT EXISTS partman;
CREATE EXTENSION IF NOT EXISTS pg_partman SCHEMA partman;
GRANT USAGE, CREATE ON SCHEMA public TO td_owner;
GRANT ALL ON SCHEMA partman TO td_owner;
GRANT ALL ON ALL TABLES IN SCHEMA partman TO td_owner;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA partman TO td_owner;
GRANT EXECUTE ON ALL PROCEDURES IN SCHEMA partman TO td_owner;
'@
    $extensions | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U techdrona -d $db
    if ($LASTEXITCODE -ne 0) { Write-Error "could not prepare extensions in $db"; exit 1 }

    # --- migrate + seed -------------------------------------------------------------------------
    & (Join-Path $PSScriptRoot 'seed-dev.ps1') -Migrate
    if ($LASTEXITCODE -ne 0) { Write-Error 'migrations or seeds failed (see above)'; exit 1 }

    # --- Playwright env -------------------------------------------------------------------------
    $envFile = Join-Path $web '.env.e2e.local'
    Push-Location $api
    try {
        & $py -m app.seeds.e2e_env --out $envFile
        if ($LASTEXITCODE -ne 0) { Write-Error 'could not write the E2E env file'; exit 1 }
    }
    finally { Pop-Location }

    $devices = Join-Path $web '.e2e-devices'
    if (Test-Path $devices) {
        Remove-Item -Recurse -Force $devices
        Write-Host 'Removed apps/web/.e2e-devices (device cookies of the old database).'
    }

    # Pooled DB connections of running app containers point at the dropped database: restart them
    # (and wait until healthy) so the first requests after a reset never fail.
    if (-not $StopApp) {
        $restart = @(($appServices + 'web') | Where-Object { $running -contains $_ })
        if ($restart.Count) {
            Write-Host "==> docker compose restart $($restart -join ' ')" -ForegroundColor Cyan
            docker compose restart @restart | Out-Null
            docker compose up -d --no-build --wait @restart | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Warning 'app containers did not become healthy after restart' }
        }
    }

    Write-Host "Dev data reset complete. E2E env: apps/web/.env.e2e.local" -ForegroundColor Green
}
finally {
    if ($stopped.Count) {
        Write-Host "==> docker compose start $($stopped -join ' ')" -ForegroundColor Cyan
        docker compose start @stopped | Out-Null
    }
    Pop-Location
}
