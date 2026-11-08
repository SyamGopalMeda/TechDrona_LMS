<#
.SYNOPSIS
  Start the Tech Drona LMS local data services (Postgres 16, Redis cache + queue, Mailpit, S3 emulator)
  and wait until they are healthy.

.DESCRIPTION
  - Creates .env from .env.example if it does not exist (never overwrites).
  - Warns when a host port needed by docker-compose is already taken (common on Windows:
    a native PostgreSQL or Redis service on 5432/6379). Override ports in .env with
    TD_PG_HOST_PORT / TD_REDIS_CACHE_HOST_PORT / TD_REDIS_QUEUE_HOST_PORT and keep
    DATABASE_URL / REDIS_*_URL in .env consistent (see docs/local-development.md).
  - -Build rebuilds images (compose builds missing images automatically).
  - -WithApp also builds and starts the api/web/worker containers (compose profile `app`).

.EXAMPLE
  ./scripts/dev-up.ps1
  ./scripts/dev-up.ps1 -WithApp
#>
[CmdletBinding()]
param(
    [switch]$WithApp,
    [switch]$Build,
    [int]$TimeoutSeconds = 180
)

# Native tools (docker, npm, alembic) write progress to stderr; with 'Stop' Windows PowerShell 5.1
# would turn that into terminating errors. Failures are detected via $LASTEXITCODE instead.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Get-DotEnvValue([string]$Name, [string]$Default) {
    $envFile = Join-Path $root '.env'
    if (Test-Path $envFile) {
        $line = Get-Content $envFile | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -Last 1
        if ($line) { return ($line -split '=', 2)[1].Trim() }
    }
    return $Default
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'docker is not on PATH. Install/start Docker Desktop first.'
}
docker info --format '{{.ServerVersion}}' *> $null
if ($LASTEXITCODE -ne 0) { throw 'Docker daemon is not reachable. Start Docker Desktop.' }

if (-not (Test-Path (Join-Path $root '.env'))) {
    Copy-Item (Join-Path $root '.env.example') (Join-Path $root '.env')
    Write-Host 'Created .env from .env.example (local placeholders only).' -ForegroundColor Yellow
}

# Port pre-flight (only for ports not already owned by our own containers)
$ports = [ordered]@{
    'Postgres'     = [int](Get-DotEnvValue 'TD_PG_HOST_PORT' '5432')
    'Redis cache'  = [int](Get-DotEnvValue 'TD_REDIS_CACHE_HOST_PORT' '6379')
    'Redis queue'  = [int](Get-DotEnvValue 'TD_REDIS_QUEUE_HOST_PORT' '6380')
    'Mailpit SMTP' = [int](Get-DotEnvValue 'TD_SMTP_HOST_PORT' '1025')
    'Mailpit UI'   = [int](Get-DotEnvValue 'TD_MAILPIT_UI_HOST_PORT' '8025')
    'S3 emulator'  = [int](Get-DotEnvValue 'TD_S3_HOST_PORT' '9000')
}
$running = @(docker compose ps -q 2>$null | Where-Object { $_ })
if ($running.Count -eq 0) {
    foreach ($name in $ports.Keys) {
        $p = $ports[$name]
        if (Get-NetTCPConnection -State Listen -LocalPort $p -ErrorAction SilentlyContinue) {
            Write-Warning "$name host port $p is already in use by another process. Set a free port in .env (see docs/local-development.md)."
        }
    }
}

$composeArgs = @('compose')
if ($WithApp) { $composeArgs += @('--profile', 'app') }
$composeArgs += @('up', '-d', '--wait', '--wait-timeout', "$TimeoutSeconds")
if ($Build) { $composeArgs += '--build' }  # rebuild images (e.g. after infra/docker/postgres changes)

Write-Host "docker $($composeArgs -join ' ')" -ForegroundColor Cyan
& docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    docker compose ps -a
    throw 'docker compose up failed (see output above; `docker compose logs <service>`).'
}

docker compose ps --format 'table {{.Service}}\t{{.Status}}\t{{.Ports}}'
Write-Host ''
Write-Host "Postgres : localhost:$($ports['Postgres'])  (db techdrona + techdrona_test; superuser techdrona/techdrona_dev)" -ForegroundColor Green
Write-Host "Redis    : localhost:$($ports['Redis cache']) (cache), localhost:$($ports['Redis queue']) (queue)" -ForegroundColor Green
Write-Host "Mailpit  : smtp localhost:$($ports['Mailpit SMTP']), UI http://localhost:$($ports['Mailpit UI'])" -ForegroundColor Green
Write-Host "S3       : http://localhost:$($ports['S3 emulator']) (buckets local-td-*)" -ForegroundColor Green
