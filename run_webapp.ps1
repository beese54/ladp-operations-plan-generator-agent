# run_webapp.ps1 — one-command launcher for the Water Network Ops webapp.
#   FastAPI backend → http://localhost:8001   (Swagger docs at /docs)
#   React frontend  → http://localhost:5174   (open this one)
#
# First launch takes ~60-90s: the backend downloads/loads the all-MiniLM-L6-v2
# embedding model (ChromaDB pre-warm) before it accepts connections. That's normal.
#
# Usage:  powershell -ExecutionPolicy Bypass -File .\run_webapp.ps1

$root = $PSScriptRoot

# Backend — uvicorn with --reload so code edits hot-reload during development.
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$root'; `$env:PYTHONPATH = '.'; uvicorn api.main:app --reload --host 0.0.0.0 --port 8001" `
    -WindowStyle Normal

# Frontend — Vite dev server (HMR).
Start-Process powershell -ArgumentList "-NoExit", "-Command", `
    "cd '$root\frontend'; npm run dev" `
    -WindowStyle Normal

Write-Host ""
Write-Host "Starting Water Network Ops webapp..." -ForegroundColor Cyan
Write-Host "  Backend  : http://localhost:8001  (docs: http://localhost:8001/docs)"
Write-Host "  Frontend : http://localhost:5174  <- open this"
Write-Host ""
Write-Host "First launch is slow (~60-90s): the backend loads the embedding model" -ForegroundColor Yellow
Write-Host "before it accepts connections. The browser may show an error until then." -ForegroundColor Yellow
Write-Host ""

# Give the frontend a moment to bind its port, then open the browser.
Start-Sleep -Seconds 4
Start-Process 'http://localhost:5174'
