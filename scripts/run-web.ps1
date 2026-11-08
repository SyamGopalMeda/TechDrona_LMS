<#
.SYNOPSIS
  Run the Next.js web app (BFF) on the host.

.DESCRIPTION
  Installs dependencies on first run (npm ci when a lockfile exists, else npm install), then runs
  `npm run dev` (default) or `npm run build; npm run start` with -Prod. Next.js reads
  apps/web/.env*.local; the root .env values needed by the BFF (TD_API_INTERNAL_URL,
  TD_SERVICE_TOKEN, TD_CSRF_KEY, NEXT_PUBLIC_*) are exported into the process from the root .env.

.EXAMPLE
  ./scripts/run-web.ps1
  ./scripts/run-web.ps1 -Prod -Port 3001
#>
[CmdletBinding()]
param(
    [int]$Port = 3000,
    [switch]$Install,
    [switch]$Prod
)

# Native tools (docker, npm, alembic) write progress to stderr; with 'Stop' Windows PowerShell 5.1
# would turn that into terminating errors. Failures are detected via $LASTEXITCODE instead.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root 'apps/web'
if (-not (Test-Path (Join-Path $web 'package.json'))) { throw 'apps/web/package.json not found.' }

# Export root .env into this process (does not override variables already set in the shell).
$envFile = Join-Path $root '.env'
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$') {
            $name = $Matches[1]; $value = $Matches[2].Trim()
            if (-not [Environment]::GetEnvironmentVariable($name, 'Process')) {
                [Environment]::SetEnvironmentVariable($name, $value, 'Process')
            }
        }
    }
}
$env:PORT = "$Port"
$env:NEXT_TELEMETRY_DISABLED = '1'

Push-Location $web
try {
    if ($Install -or -not (Test-Path (Join-Path $web 'node_modules'))) {
        if (Test-Path (Join-Path $web 'package-lock.json')) { npm ci --no-audit --no-fund } else { npm install --no-audit --no-fund }
        if ($LASTEXITCODE -ne 0) { throw 'npm install failed' }
    }
    $busy = Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue
    if ($busy) { Write-Warning "Port $Port is already in use; pass -Port <n>." }

    Write-Host "Web on http://localhost:$Port" -ForegroundColor Green
    if ($Prod) {
        $env:NODE_ENV = 'production'
        npm run build
        if ($LASTEXITCODE -ne 0) { throw 'npm run build failed' }
        npm run start -- --port $Port
    }
    else {
        $env:NODE_ENV = 'development'
        npm run dev -- --port $Port
    }
}
finally { Pop-Location }
