<#
Run the LMS Firebase stack locally (no Postgres, no Docker): Hosting "lms" + the Python
functions codebase "lms", against the SHARED Firestore emulator on 127.0.0.1:18080.

    powershell -ExecutionPolicy Bypass -File functions-lms\tools\emulate.ps1            # seed + start (foreground)
    powershell -ExecutionPolicy Bypass -File functions-lms\tools\emulate.ps1 -SeedOnly
    powershell -ExecutionPolicy Bypass -File functions-lms\tools\emulate.ps1 -NoSeed

* Separate emulator config functions-lms\emulator\firebase.json (hosting 5000, functions 5001,
  hub 14402, logging 14502, UI off), so it never clashes with the other emulator instance
  (Firestore 18080, Auth 19099, UI 14000, hub 14400, logging 14500).
* Project demo-platform-emu: offline demo project; its Firestore data is its own namespace in the
  shared emulator.
* Writes functions-lms\.env.local (function env) and functions-lms\.secret.local (DUMMY dev-only
  secrets; both gitignored), then seeds the role catalogue + admin/student (tools\seed_emulator.py).
* Open http://127.0.0.1:5000 ; sign in as admin@dev.techdrona.local or student@dev.techdrona.local
  with the dev password printed by the seed.
#>
param([switch]$SeedOnly, [switch]$NoSeed, [string]$Project = "demo-platform-emu")
$ErrorActionPreference = "Stop"
$Fn = Split-Path -Parent $PSScriptRoot
$Repo = Split-Path -Parent $Fn
$ApiPy = Join-Path $Repo "apps\api\.venv\Scripts\python.exe"
$FsHost = "127.0.0.1:18080"

try { Invoke-WebRequest -UseBasicParsing "http://$FsHost/" -TimeoutSec 3 | Out-Null }
catch { throw "Firestore emulator not reachable on $FsHost (start the shared one: firebase emulators:start --only firestore,auth --project demo-techdrona-lms)" }

if (-not (Test-Path (Join-Path $Repo "apps\lms-spa\dist\index.html"))) { throw "build the SPA first: cd apps\lms-spa; npm run build" }
if (-not (Test-Path (Join-Path $Fn "venv\Scripts\python.exe"))) { throw "functions venv missing: python -m venv functions-lms\venv; functions-lms\venv\Scripts\pip install -r functions-lms\requirements.txt" }

$stores = "admin admissions ai analytics assessments audit catalog coding commerce core engage entitlements hub identity learning media mentoring notifications orgs paths placement rbac security sessions support".Split(" ")
$envLines = @(
  "TD_RUNTIME=firebase", "APP_ENV=local", "TD_PUBLIC_BASE_URL=http://127.0.0.1:5000", "TD_ALLOWED_ORIGINS=http://127.0.0.1:5000",
  "TD_COOKIE_SECURE=false", "TD_EDGE_COOKIE_PACKING=session", "TD_TRUSTED_PROXY_HOPS=1", "TD_SIMPLE_AUTH=true",
  "DATABASE_URL=", "FIRESTORE_EMULATOR_HOST=$FsHost",
  "TD_CACHE_BACKEND=firestore", "TD_TASKS_BACKEND=cloudtasks", "TD_CODING_SEND_TASKS=1", "LOG_FORMAT=console", "LOG_LEVEL=INFO", "LMS_API_MIN_INSTANCES=0"
) + ($stores | ForEach-Object { "TD_STORE_$($_.ToUpper())=firestore" })
Set-Content -Path (Join-Path $Fn ".env.local") -Value $envLines -Encoding ascii

# DUMMY local-only secret values (never real ones; the emulator reads .secret.local for SecretParams).
$secretLines = @(
  "TD_SERVICE_TOKEN=emulator-service-token-$('s' * 40)", "TD_CSRF_KEY=emulator-csrf-key-$('c' * 40)",
  "TD_K_DEVICE_KEY_V1=$('11' * 32)", "TD_K_LOGIN_KEY_V1=$('22' * 32)", "TD_K_TOTP_KEY_V1=$('33' * 32)",
  "TD_FP_HMAC_KEY=$('44' * 32)", "TD_LOCAL_ENVELOPE_KEY=$('55' * 32)", "TD_ANALYTICS_SUBJECT_KEY=$('66' * 32)", "TD_K_TESTCASE_KEY_V1=$('77' * 32)", "RAZORPAY_WEBHOOK_SECRET=emulator-webhook-secret-$('w' * 40)",
  "AWS_ACCESS_KEY_ID=emulator", "AWS_SECRET_ACCESS_KEY=emulator"
)
Set-Content -Path (Join-Path $Fn ".secret.local") -Value $secretLines -Encoding ascii

if (-not $NoSeed) {
  $env:FIRESTORE_EMULATOR_HOST = $FsHost; $env:FIREBASE_PROJECT_ID = $Project; $env:APP_ENV = "local"
  & $ApiPy (Join-Path $Fn "tools\seed_emulator.py")
  if ($LASTEXITCODE -ne 0) { throw "seed failed" }
  Remove-Item Env:FIREBASE_PROJECT_ID
}
if ($SeedOnly) { return }

Push-Location $Repo
try {
  firebase emulators:start --config functions-lms\emulator\firebase.json --project $Project --only "functions,hosting"
} finally { Pop-Location }
