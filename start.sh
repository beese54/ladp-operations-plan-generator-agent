#!/usr/bin/env bash
# Start all app services: FastAPI backend + React graph UI
# FastAPI   → http://localhost:8001  (health: /api/v1/health)
# React UI  → http://localhost:5174
#
# The backend loads a SentenceTransformer model on startup (~30s), so this
# script waits for /api/v1/health to respond before reporting ready.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_URL="http://localhost:8001"
FRONTEND_URL="http://localhost:5174"
HEALTH_URL="$BACKEND_URL/api/v1/health"

cleanup() {
    echo "Shutting down..."
    kill "${FASTAPI_PID:-}" "${VITE_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

PYTHONPATH=. uvicorn api.main:app --reload --host 0.0.0.0 --port 8001 &
FASTAPI_PID=$!

(cd "$SCRIPT_DIR/frontend" && npm run dev) &
VITE_PID=$!

echo "FastAPI PID $FASTAPI_PID → $BACKEND_URL"
echo "React UI PID $VITE_PID  → $FRONTEND_URL"
echo "Waiting for backend to finish loading (model load ~30s)..."

# Poll health until the API responds (200 OK or 503 DEGRADED both mean "up").
ready=0
for _ in $(seq 1 60); do
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$HEALTH_URL" || true)
    if [ "$code" = "200" ] || [ "$code" = "503" ]; then
        ready=1
        break
    fi
    sleep 2
done

if [ "$ready" = "1" ]; then
    echo "Backend is up:"
    curl -s "$HEALTH_URL" || true
    echo
else
    echo "Backend did not respond in time — check the logs above." >&2
fi

# Open the app where a desktop session is available.
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$FRONTEND_URL" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
    open "$FRONTEND_URL" >/dev/null 2>&1 || true
fi

wait
