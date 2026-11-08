<#
.SYNOPSIS
  DESTROY and recreate the LOCAL Postgres volume, then re-run scripts/db-init/ and migrations.

.DESCRIPTION
  Local docker-compose only. Removes the `pgdata` volume (all local data in techdrona and
  techdrona_test), starts Postgres again (init scripts recreate roles, extensions and the test
  database), then runs `alembic upgrade heads` against techdrona (and techdrona_test unless
  -SkipTestDb) if apps/api is set up.

.EXAMPLE
  ./scripts/reset-db.ps1 -Force
#>
[CmdletBinding()]
param(
    [switch]$Force,
    [switch]$SkipMigrations,
    [switch]$SkipTestDb
)

# Native tools (docker, npm, alembic) write progress to stderr; with 'Stop' Windows PowerShell 5.1
# would turn that into terminating errors. Failures are detected via $LASTEXITCODE instead.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not $Force) {
    $answer = Read-Host 'This deletes ALL local Postgres data (techdrona + techdrona_test). Type yes to continue'
    if ($answer -ne 'yes') { Write-Host 'Aborted.'; exit 1 }
}

$project = 'techdrona'
docker compose stop postgres | Out-Null
docker compose rm -f postgres | Out-Null
docker volume rm "${project}_pgdata" 2>$null | Out-Null
Write-Host 'Removed volume techdrona_pgdata.' -ForegroundColor Yellow

docker compose up -d --wait postgres
if ($LASTEXITCODE -ne 0) { throw 'Postgres did not become healthy. See: docker compose logs postgres' }

if ($SkipMigrations) { exit 0 }

$alembic = Join-Path $root 'apps/api/.venv/Scripts/alembic.exe'
if (-not (Test-Path $alembic)) {
    Write-Warning 'apps/api/.venv not found; skipping migrations (see docs/local-development.md).'
    exit 0
}

function Get-DotEnvValue([string]$Name) {
    $line = Get-Content (Join-Path $root '.env') | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -Last 1
    if ($line) { return ($line -split '=', 2)[1].Trim() } else { return $null }
}

Push-Location (Join-Path $root 'apps/api')
try {
    Write-Host 'alembic upgrade heads (techdrona)' -ForegroundColor Cyan
    & $alembic upgrade heads
    if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade heads failed (techdrona)' }

    if (-not $SkipTestDb) {
        $testUrl = Get-DotEnvValue 'TEST_DATABASE_MIGRATION_URL'
        if (-not $testUrl) {
            $mig = Get-DotEnvValue 'DATABASE_MIGRATION_URL'
            if ($mig) { $testUrl = $mig -replace '/techdrona$', '/techdrona_test' }
        }
        if ($testUrl) {
            Write-Host 'alembic upgrade heads (techdrona_test)' -ForegroundColor Cyan
            $prev = $env:DATABASE_MIGRATION_URL
            $env:DATABASE_MIGRATION_URL = $testUrl
            try { & $alembic upgrade heads } finally { $env:DATABASE_MIGRATION_URL = $prev }
            if ($LASTEXITCODE -ne 0) { throw 'alembic upgrade heads failed (techdrona_test)' }
        }
    }
}
finally { Pop-Location }
Write-Host 'Database reset complete.' -ForegroundColor Green
