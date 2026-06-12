#!/usr/bin/env bash
# init.sh — Reproducible environment setup for the Water Network Operations Plan Generator
# Run once after cloning the repo on a new machine.
# Usage: bash init.sh [--skip-venv] [--skip-install] [--bootstrap-db]

set -euo pipefail

SKIP_VENV=false
SKIP_INSTALL=false
BOOTSTRAP_DB=false

for arg in "$@"; do
  case $arg in
    --skip-venv)     SKIP_VENV=true ;;
    --skip-install)  SKIP_INSTALL=true ;;
    --bootstrap-db)  BOOTSTRAP_DB=true ;;
  esac
done

echo "=== Water Network Ops Generator — Environment Setup ==="
echo ""

# 1. Check Python version
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 12 ]; }; then
  echo "ERROR: Python 3.12+ required. Found $PYTHON_VERSION"
  exit 1
fi
echo "✓ Python $PYTHON_VERSION"

# 2. Create virtual environment
if [ "$SKIP_VENV" = false ]; then
  if [ ! -d ".venv" ]; then
    echo "→ Creating virtual environment (.venv)..."
    python3 -m venv .venv
    echo "✓ Virtual environment created"
  else
    echo "✓ Virtual environment already exists"
  fi
  echo "→ Activating virtual environment..."
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

# 3. Install dependencies
if [ "$SKIP_INSTALL" = false ]; then
  echo "→ Installing dependencies from requirements.txt..."
  pip install --upgrade pip --quiet
  pip install -r requirements.txt --quiet
  echo "✓ Dependencies installed"
fi

# 4. Check for .env file
if [ ! -f ".env" ]; then
  echo ""
  echo "⚠  No .env file found. Creating from .env.example..."
  cp .env.example .env
  echo "   IMPORTANT: Edit .env and fill in your actual credentials before running the app:"
  echo "   - ANTHROPIC_API_KEY"
  echo "   - TOGETHER_API_KEY"
  echo "   - NEO4J_URI (format: neo4j+s://xxxx.databases.neo4j.io)"
  echo "   - NEO4J_USERNAME"
  echo "   - NEO4J_PASSWORD"
  echo ""
else
  echo "✓ .env file found"
fi

# 5. Verify required env vars are set (non-empty)
source .env 2>/dev/null || true

MISSING=()
for var in ANTHROPIC_API_KEY TOGETHER_API_KEY NEO4J_URI NEO4J_USERNAME NEO4J_PASSWORD; do
  if [ -z "${!var:-}" ]; then
    MISSING+=("$var")
  fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
  echo ""
  echo "⚠  The following required env vars are not set in .env:"
  for var in "${MISSING[@]}"; do
    echo "   - $var"
  done
  echo "   Fill these in before running the application."
  echo ""
fi

# 6. Create data directories if missing
mkdir -p data/seed/sop_documents
mkdir -p data/seed/historical_plans
mkdir -p data/chroma_db
echo "✓ Data directories ready"

# 7. Optional: bootstrap databases
if [ "$BOOTSTRAP_DB" = true ]; then
  echo ""
  echo "→ Bootstrapping databases..."

  if [ ${#MISSING[@]} -gt 0 ]; then
    echo "ERROR: Cannot bootstrap databases — missing env vars listed above."
    exit 1
  fi

  python scripts/verify_connections.py
  python scripts/bootstrap_db.py
  echo "✓ Databases bootstrapped"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Ensure .env has all credentials filled in"
echo "  2. Drop SOP files into:        data/seed/sop_documents/"
echo "  3. Drop historical plans into:  data/seed/historical_plans/"
echo "  4. Run:  python scripts/verify_connections.py"
echo "  5. Run:  python scripts/bootstrap_db.py"
echo "  6. Start API:  uvicorn api.main:app --reload --host 0.0.0.0 --port 8000"
echo "  7. Start UI:   streamlit run ui/streamlit_app.py"
echo ""
