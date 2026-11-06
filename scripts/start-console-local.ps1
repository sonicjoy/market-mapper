# Local mapping console against marketmaking-test
#
# Prerequisites:
#   1. ADC must be able to run BQ jobs in marketmaking-test
#      Check:  python -c "from google.auth import default; ..."
#      Fix:    gcloud auth application-default login
#              (use the same Google account that has BQ access - preferably
#               joe.luo@whiteswandata.com; if ADC is joe.luo@colossusbets.com,
#               that identity needs serviceUsageConsumer + BQ roles on test)
#   2. Node + Python venv installed
#
# Usage (from repo root):
#   powershell -File scripts/start-console-local.ps1

param(
    [int]$ApiPort = 8001,
    [int]$UiPort = 5173,
    [string]$OperatorEmail = $(if ($env:MAPPING_CP_DEV_EMAIL) { $env:MAPPING_CP_DEV_EMAIL } else { "joe.luo@whiteswandata.com" })
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$env:PYTHONPATH = $Root
$env:GCP_PROJECT = "marketmaking-test"
# Missing page: prefer gitignored scratch/missing_catalogue_dev.jsonl (see export script).
$missingLocal = Join-Path $Root "scratch\missing_catalogue_dev.jsonl"
if (-not $env:MAPPING_MISSING_BQ_PROJECT) {
    if (Test-Path $missingLocal) {
        $env:MAPPING_MISSING_BQ_PROJECT = "local"
    } else {
        $env:MAPPING_MISSING_BQ_PROJECT = "rs-marketmaking"
        if (-not $env:MAPPING_MISSING_DEV_MAX_ROWS) {
            $env:MAPPING_MISSING_DEV_MAX_ROWS = "5000"
        }
    }
}
$env:MAPPING_CP_ADMIN_EMAILS = $OperatorEmail
$env:MAPPING_CP_DEV_EMAIL = $OperatorEmail
# Solo local approve (test/dev). Opt into maker/checker with = "1".
if (-not $env:MAPPING_CP_REQUIRE_MAKER_CHECKER) {
    $env:MAPPING_CP_REQUIRE_MAKER_CHECKER = "0"
}

Write-Host "ADC identity check (must have BQ on marketmaking-test)..."
& "$Root\.venv\Scripts\python.exe" -c @"
from google.auth import default
from google.auth.transport.requests import Request
import urllib.request, json
creds, _ = default(scopes=['https://www.googleapis.com/auth/cloud-platform','https://www.googleapis.com/auth/userinfo.email','openid'])
creds.refresh(Request())
info = json.load(urllib.request.urlopen(urllib.request.Request(
    'https://www.googleapis.com/oauth2/v3/userinfo',
    headers={'Authorization': f'Bearer {creds.token}'})))
print('ADC email:', info.get('email'))
from google.cloud import bigquery
c = bigquery.Client(project='marketmaking-test')
print('BQ select 1:', list(c.query('select 1 as ok').result())[0].ok)
"@
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "BigQuery ADC failed. Run:"
    Write-Host "  gcloud auth application-default login"
    Write-Host "Then grant that identity BQ access on marketmaking-test (see console/README.md)."
    exit 1
}

# Free stale listeners on the ports we need
foreach ($port in @($ApiPort, $UiPort)) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        Write-Host "Stopping PID $($c.OwningProcess) on port $port"
        Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Seconds 1

Write-Host ("Starting API on :{0} (operator={1}, env=test, missing_bq={2}, missing_cap={3})..." -f `
    $ApiPort, $OperatorEmail, $env:MAPPING_MISSING_BQ_PROJECT, $env:MAPPING_MISSING_DEV_MAX_ROWS)
$api = Start-Process -PassThru -WindowStyle Minimized -FilePath "$Root\.venv\Scripts\python.exe" `
    -ArgumentList @("-m", "uvicorn", "mappers.control_plane.app:app", "--host", "127.0.0.1", "--port", "$ApiPort", "--reload") `
    -WorkingDirectory $Root

Start-Sleep -Seconds 2
try {
    $h = @{ "X-Goog-Authenticated-User-Email" = "accounts.google.com:$OperatorEmail"; Accept = "application/json" }
    $meta = Invoke-RestMethod -Uri "http://127.0.0.1:$ApiPort/meta" -Headers $h
    Write-Host ("/meta ok - role={0} require_maker_checker={1}" -f $meta.role, $meta.require_maker_checker)
} catch {
    Write-Host "API did not become ready: $_"
    Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue
    exit 1
}

Write-Host "Starting Vite on :$UiPort ..."
Push-Location "$Root\console"
if (-not (Test-Path "node_modules")) { npm install }
$env:MAPPING_CP_DEV_EMAIL = $OperatorEmail
# Keep vite proxy pointed at ApiPort (vite.config.ts default 8001)
npx vite --host 127.0.0.1 --port $UiPort
Pop-Location
