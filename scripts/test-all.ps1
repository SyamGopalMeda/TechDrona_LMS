<#
.SYNOPSIS
  Run the local equivalent of the CI api + web gates.

.DESCRIPTION
  1. ensures docker-compose data services are healthy
  2. api: ruff check, ruff format --check, mypy, alembic upgrade heads on techdrona_test,
     pytest under coverage (fail-under 85, G-02), route-guard selection (G-05)
  3. web: lint, typecheck, vitest, build (skipped if apps/web has no package.json)
  Exit code is non-zero if any step fails; a summary table is printed at the end.

.EXAMPLE
  ./scripts/test-all.ps1
  ./scripts/test-all.ps1 -SkipWeb -CoverageFailUnder 0
#>
[CmdletBinding()]
param(
    [switch]$SkipApi,
    [switch]$SkipWeb,
    [switch]$SkipLint,
    [int]$CoverageFailUnder = 85
)

# Native tools (docker, npm, alembic) write progress to stderr; with 'Stop' Windows PowerShell 5.1
# would turn that into terminating errors. Failures are detected via $LASTEXITCODE instead.
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$results = New-Object System.Collections.Generic.List[object]

function Invoke-Step([string]$Name, [scriptblock]$Block) {
    Write-Host "==> $Name" -ForegroundColor Cyan
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $ok = $true
    try {
        $global:LASTEXITCODE = 0
        & $Block
        if ($LASTEXITCODE -ne 0) { $ok = $false }
    }
    catch { Write-Host $_ -ForegroundColor Red; $ok = $false }
    $results.Add([pscustomobject]@{ Step = $Name; Result = $(if ($ok) { 'PASS' } else { 'FAIL' }); Seconds = [math]::Round($sw.Elapsed.TotalSeconds, 1) })
}

function Get-DotEnvValue([string]$Name) {
    $f = Join-Path $root '.env'
    if (-not (Test-Path $f)) { return $null }
    $line = Get-Content $f | Where-Object { $_ -match "^\s*$Name\s*=" } | Select-Object -Last 1
    if ($line) { return ($line -split '=', 2)[1].Trim() } else { return $null }
}

Set-Location $root
Invoke-Step 'compose services healthy' { docker compose up -d --wait postgres redis redis-queue mailpit }

if (-not $SkipApi) {
    $api = Join-Path $root 'apps/api'
    $bin = Join-Path $api '.venv/Scripts'
    if (-not (Test-Path (Join-Path $bin 'python.exe'))) {
        Write-Warning 'apps/api/.venv missing: run ./scripts/run-api.ps1 -Install once (or see docs/local-development.md).'
        $results.Add([pscustomobject]@{ Step = 'api'; Result = 'SKIP (no venv)'; Seconds = 0 })
    }
    else {
        Push-Location $api
        try {
            $testMig = Get-DotEnvValue 'TEST_DATABASE_MIGRATION_URL'
            if ($testMig) { $env:DATABASE_MIGRATION_URL = $testMig }
            if (-not $SkipLint) {
                Invoke-Step 'api: ruff check' { & "$bin/ruff.exe" check . }
                Invoke-Step 'api: ruff format --check' { & "$bin/ruff.exe" format --check . }
                Invoke-Step 'api: mypy' { & "$bin/mypy.exe" }
            }
            Invoke-Step 'api: alembic upgrade heads (techdrona_test)' { & "$bin/alembic.exe" upgrade heads }
            Invoke-Step 'api: pytest + coverage' {
                & "$bin/coverage.exe" run -m pytest
                if ($LASTEXITCODE -ne 0) { return }
                & "$bin/coverage.exe" report --fail-under=$CoverageFailUnder
            }
            Invoke-Step 'api: G-05 route guard test' {
                & "$bin/pytest.exe" -q -k 'route_guard or route_guards' -p no:cacheprovider
                if ($LASTEXITCODE -eq 5) { Write-Host 'No route-guard test collected (G-05 requires one).' -ForegroundColor Red }
            }
        }
        finally { Pop-Location; Remove-Item Env:DATABASE_MIGRATION_URL -ErrorAction SilentlyContinue }
    }
}

if (-not $SkipWeb) {
    $web = Join-Path $root 'apps/web'
    if (-not (Test-Path (Join-Path $web 'package.json'))) {
        $results.Add([pscustomobject]@{ Step = 'web'; Result = 'SKIP (no apps/web/package.json)'; Seconds = 0 })
    }
    else {
        Push-Location $web
        try {
            if (-not (Test-Path 'node_modules')) { Invoke-Step 'web: npm ci' { npm ci --no-audit --no-fund } }
            if (-not $SkipLint) {
                Invoke-Step 'web: lint' { npm run lint }
                Invoke-Step 'web: typecheck' { npm run typecheck --if-present; if ($LASTEXITCODE -ne 0) { return }; if (-not (Select-String -Path package.json -Pattern '"typecheck"' -Quiet)) { npx tsc --noEmit } }
            }
            Invoke-Step 'web: vitest' { npm run test --if-present -- --run }
            Invoke-Step 'web: build' { npm run build }
        }
        finally { Pop-Location }
    }
}

Write-Host ''
$results | Format-Table -AutoSize
if ($results | Where-Object { $_.Result -eq 'FAIL' }) { exit 1 } else { exit 0 }
