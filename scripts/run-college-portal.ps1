<#
.SYNOPSIS
  Run the College Data Portal server (apps/college-data/portal) on the host for local development.

.DESCRIPTION
  The portal is opened from the LMS at Admin > College Data Portal (/admin/college-data); the web
  BFF proxies /college-portal/* to this server. It reads TD_COLLEGE_PORTAL_SECRET from the root
  .env and starts in proxy mode (PORTAL_PROXY_SECRET), so it answers only requests coming
  through the LMS. Use -Standalone to run it on its own (old behaviour, http://localhost:4173).
  Needs Node 24 (node:sqlite). Data: apps/college-data/portal/data/techdrona.db (not committed).

.EXAMPLE
  ./scripts/run-college-portal.ps1
  ./scripts/run-college-portal.ps1 -Standalone
#>
[CmdletBinding()]
param(
    [int]$Port = 4173,
    [switch]$Standalone
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$portal = Join-Path $root 'apps/college-data/portal'
if (-not (Test-Path (Join-Path $portal 'server/server.js'))) { throw 'apps/college-data/portal/server/server.js not found.' }

$major = [int]((node -p "process.versions.node.split('.')[0]") 2>$null)
if ($major -lt 24) { throw "Node 24 or newer is required (found $(node -v))." }

$envFile = Join-Path $root '.env'
$secret = ''
if (Test-Path $envFile) {
    foreach ($line in Get-Content $envFile) {
        if ($line -match '^\s*TD_COLLEGE_PORTAL_SECRET\s*=(.*)$') { $secret = $Matches[1].Trim() }
    }
}
if ($env:TD_COLLEGE_PORTAL_SECRET) { $secret = $env:TD_COLLEGE_PORTAL_SECRET }

$env:PORT = "$Port"
$env:HOST = '127.0.0.1'
if ($Standalone) {
    Remove-Item Env:PORTAL_PROXY_SECRET -ErrorAction SilentlyContinue
    Write-Host "College Data Portal (standalone): http://localhost:$Port"
} else {
    if ($secret.Length -lt 32) { throw 'TD_COLLEGE_PORTAL_SECRET (>= 32 chars) is missing from the root .env; see .env.example section 19.' }
    $env:PORTAL_PROXY_SECRET = $secret
    Write-Host "College Data Portal (proxy mode) on 127.0.0.1:$Port - open it in the LMS: http://localhost:3000/admin/college-data"
}

Push-Location $portal
try { node server/server.js } finally { Pop-Location }
