<#
.SYNOPSIS
  Load DEV/DEMO data into the local database (Windows PowerShell).

.DESCRIPTION
  Runs, in dependency order: rbac_seed (reference data, idempotent) -> dev_users ->
  catalog_demo -> placement_demo -> coding_demo -> commerce_demo -> security_demo ->
  e2e_demo (E2E learner/trainer fixtures) -> company_demo (batch path, article, engage
  activity, question bank, assignments, corporate enquiry).
  Every seed is idempotent, so re-running is safe. Refuses when APP_ENV (process env or the
  root .env) is prod/production. Runs on the host with apps/api/.venv: the td-api image ships
  no demo seeds (G-21).

.EXAMPLE
  ./scripts/seed-dev.ps1 -Migrate
  ./scripts/seed-dev.ps1 -Only catalog_demo,coding_demo
#>
[CmdletBinding()]
param(
    [switch]$Migrate,
    [string[]]$Only
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$api = Join-Path $root 'apps/api'

function Get-DotEnvValue([string]$Name) {
    $f = Join-Path $root '.env'
    if (-not (Test-Path $f)) { return $null }
    $line = Get-Content $f | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -Last 1
    if ($line) { return ($line -split '=', 2)[1].Trim().Trim('"') } else { return $null }
}

$appEnv = $env:APP_ENV
if (-not $appEnv) { $appEnv = Get-DotEnvValue 'APP_ENV' }
if ($appEnv -and @('prod', 'production') -contains $appEnv.ToLowerInvariant()) {
    Write-Error "REFUSED: APP_ENV=$appEnv - demo seeds never run against production."
    exit 3
}

$py = Join-Path $api '.venv/Scripts/python.exe'
if (-not (Test-Path $py)) { Write-Error 'apps/api/.venv not found - run ./scripts/run-api.ps1 -Install once.'; exit 1 }

# Preload every module's models so cross-module FKs resolve (a seed may import only its own).
$runner = 'import runpy, sys; from app.core.models_registry import import_all_models; import_all_models(); m = sys.argv[1]; sys.argv = [m]; runpy.run_module(m, run_name=''__main__'', alter_sys=True)'
$seeds = @('rbac_seed', 'dev_users', 'catalog_demo', 'placement_demo', 'coding_demo', 'commerce_demo', 'security_demo', 'e2e_demo', 'company_demo')
if ($Only) { $seeds = $Only | ForEach-Object { $_ -split ',' } | Where-Object { $_ } }

Push-Location $api
try {
    if ($Migrate) {
        Write-Host '==> alembic upgrade heads' -ForegroundColor Cyan
        & $py -m alembic upgrade heads
        if ($LASTEXITCODE -ne 0) { Write-Error 'alembic upgrade heads failed'; exit 1 }
    }
    foreach ($s in $seeds) {
        Write-Host "==> python -m app.seeds.$s" -ForegroundColor Cyan
        & $py -c $runner "app.seeds.$s"
        if ($LASTEXITCODE -ne 0) {
            Write-Error "seed $s FAILED (earlier seeds were committed; fix and re-run - seeds are idempotent)"
            exit 1
        }
    }
    Write-Host "All seeds completed: $($seeds -join ', ')" -ForegroundColor Green
}
finally { Pop-Location }
