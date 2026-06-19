# Start all app services: FastAPI backend + React graph UI
# FastAPI   → http://localhost:8001  (health: /api/v1/health)
# React UI  → http://localhost:5174
#
# The backend loads a SentenceTransformer model on startup (~30s), so this
# script waits for /api/v1/health to respond before opening the browser.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

$backendUrl  = "http://localhost:8001"
$frontendUrl = "http://localhost:5174"
$healthUrl   = "$backendUrl/api/v1/health"

# --- Launch backend (separate window so logs are visible) ---
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$root'; `$env:PYTHONPATH = '.'; uvicorn api.main:app --reload --host 0.0.0.0 --port 8001" `
    -WindowStyle Normal

# --- Launch frontend (separate window) ---
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$root\frontend'; npm run dev" `
    -WindowStyle Normal

Write-Host "Launched FastAPI ($backendUrl) and React UI ($frontendUrl)." -ForegroundColor Cyan
Write-Host "Waiting for backend to finish loading (model load ~30s)..." -ForegroundColor Yellow

# --- Poll the backend health endpoint until it responds ---
$timeoutSec = 120
$deadline   = (Get-Date).AddSeconds($timeoutSec)
$ready      = $false

while ((Get-Date) -lt $deadline) {
    try {
        # 200 = all backends OK; 503 = DEGRADED but the API is up and serving.
        $resp = Invoke-WebRequest -Uri $healthUrl -TimeoutSec 5 -UseBasicParsing
        $ready = $true
        break
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
        if ($code -eq 503) {
            # API is up; one or more dependencies are degraded.
            $resp  = $_.Exception.Response
            $ready = $true
            break
        }
        Start-Sleep -Seconds 2
    }
}

if (-not $ready) {
    Write-Host "Backend did not respond within $timeoutSec s. Check the backend window for errors." -ForegroundColor Red
    Write-Host "Frontend is still available at $frontendUrl" -ForegroundColor Yellow
    exit 1
}

# --- Report health detail if we got a JSON body ---
try {
    $health = ($resp.Content | ConvertFrom-Json)
    Write-Host "Backend status: $($health.status)" -ForegroundColor Green
    Write-Host ("  neo4j={0}  chromadb={1}  sqlite={2}  azure_openai={3}" -f `
        $health.neo4j, $health.chromadb, $health.sqlite, $health.azure_openai)
} catch {
    Write-Host "Backend is up." -ForegroundColor Green
}

# --- Open the app ---
Start-Process $frontendUrl
Write-Host "Opened $frontendUrl in your browser." -ForegroundColor Cyan
