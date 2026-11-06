# API only — Missing catalogue from scratch/missing_catalogue_dev.jsonl
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$env:PYTHONPATH = $Root
$env:GCP_PROJECT = "marketmaking-test"
$env:MAPPING_MISSING_BQ_PROJECT = "local"
$env:MAPPING_MISSING_LOCAL_PATH = Join-Path $Root "scratch\missing_catalogue_dev.jsonl"
$env:MAPPING_CP_ADMIN_EMAILS = "joe.luo@whiteswandata.com"
$env:MAPPING_CP_REQUIRE_MAKER_CHECKER = "0"
if (-not $env:MAPPING_CP_API_PORT) { $env:MAPPING_CP_API_PORT = "8001" }
$port = [int]$env:MAPPING_CP_API_PORT
foreach ($c in Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
    Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
# Windows can leave zombie listeners (process gone, port still taken). Try next ports.
for ($try = 0; $try -lt 5; $try++) {
    $busy = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if (-not $busy) { break }
    Write-Host "Port $port still in use (orphan listener?) — trying $($port + 1)"
    $port++
}
$env:MAPPING_CP_API_PORT = "$port"
Write-Host "Missing catalogue: local JSONL at $env:MAPPING_MISSING_LOCAL_PATH"
Write-Host "API http://127.0.0.1:$port"
& "$Root\.venv\Scripts\python.exe" -m uvicorn mappers.control_plane.app:app --host 127.0.0.1 --port $port
