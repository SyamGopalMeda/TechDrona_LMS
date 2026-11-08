<#
.SYNOPSIS
  Run the FastAPI app on the host with auto-reload (local development).

.DESCRIPTION
  Creates apps/api/.venv and installs `-e ".[dev]"` on first run (or with -Install),
  optionally applies migrations (-Migrate), then starts uvicorn with the app factory.
  Settings come from the root .env (pydantic-settings / python-dotenv).
  Port: -Port, else TD_API_PORT from .env, else 8000. Keep TD_API_INTERNAL_URL in .env in sync.

.EXAMPLE
  ./scripts/run-api.ps1 -Migrate
  ./scripts/run-api.ps1 -Port 8010
#>
[CmdletBinding()]
param(
    [int]$Port = 0,
    [switch]$Install,
    [switch]$Migrate,
    [switch]$NoReload
)

# Native tools (docker, npm, alembic) write progress to stderr; with 'Stop' Windows PowerShell 5.1
# would turn that into terminating errors. Failures are detected via $LASTEXITCODE instead.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$api = Join-Path $root 'apps/api'
if (-not (Test-Path (Join-Path $api 'pyproject.toml'))) { throw 'apps/api/pyproject.toml not found.' }

function Get-DotEnvValue([string]$Name) {
    $f = Join-Path $root '.env'
    if (-not (Test-Path $f)) { return $null }
    $line = Get-Content $f | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -Last 1
    if ($line) { return ($line -split '=', 2)[1].Trim() } else { return $null }
}

if ($Port -eq 0) {
    $fromEnv = Get-DotEnvValue 'TD_API_PORT'
    if ($fromEnv) { $Port = [int]$fromEnv } else { $Port = 8000 }
}

Push-Location $api
try {
    $py = Join-Path $api '.venv/Scripts/python.exe'
    if (-not (Test-Path $py)) {
        $launcher = Get-Command py -ErrorAction SilentlyContinue
        if ($launcher) { & py -3.12 -m venv .venv 2>$null; if ($LASTEXITCODE -ne 0) { & py -3 -m venv .venv } }
        else { & python -m venv .venv }
        $Install = $true
    }
    if ($Install) {
        & $py -m pip install --upgrade pip
        & $py -m pip install -e ".[dev]"
        if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }
    }
    if ($Migrate) {
        & (Join-Path $api '.venv/Scripts/alembic.exe') upgrade heads
        if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade heads failed' }
    }

    $busy = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($busy) { Write-Warning "Port $Port is already in use; pass -Port <n> (and update TD_API_INTERNAL_URL in .env)." }

    $uvArgs = @('-m', 'uvicorn', '--factory', 'app.main:create_app', '--host', '127.0.0.1', '--port', "$Port", '--env-file', (Join-Path $root '.env'))
    if (-not $NoReload) { $uvArgs += @('--reload', '--reload-dir', 'app') }
    Write-Host "API on http://127.0.0.1:$Port" -ForegroundColor Green
    & $py @uvArgs
}
finally { Pop-Location }
