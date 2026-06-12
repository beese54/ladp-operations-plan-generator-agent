#!/usr/bin/env bash
# Start all app services: FastAPI backend + React graph UI
# React UI → http://localhost:5174
# FastAPI   → http://localhost:8001

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHONPATH=. uvicorn api.main:app --reload --host 0.0.0.0 --port 8001 &
FASTAPI_PID=$!

(cd "$SCRIPT_DIR/frontend" && npm run dev) &
VITE_PID=$!

echo "FastAPI PID $FASTAPI_PID → http://localhost:8001"
echo "React UI PID $VITE_PID  → http://localhost:5174"

wait
