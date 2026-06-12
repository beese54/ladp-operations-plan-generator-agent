# Start all app services: FastAPI backend + React graph UI
# React UI → http://localhost:5174
# FastAPI   → http://localhost:8000

$root = $PSScriptRoot

Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root'; `$env:PYTHONPATH = '.'; uvicorn api.main:app --reload --host 0.0.0.0 --port 8001" -WindowStyle Normal
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev" -WindowStyle Normal

Write-Host "Started FastAPI on http://localhost:8001"
Write-Host "Started React UI on http://localhost:5174"
