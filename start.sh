#!/usr/bin/env bash
# ===================================================================
#  Quantum Green Fleet - one-click local launcher (macOS / Linux / WSL)
#
#  Sets up the Python venv, installs dependencies, trains the model if
#  needed, then runs the API and the UI together. Ctrl-C stops both.
# ===================================================================
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m[ERROR] %s\033[0m\n' "$*" >&2; exit 1; }

say "Quantum Green Fleet - starting local development stack"

# ---- 1. Python -------------------------------------------------------
PYTHON="$(command -v python3 || command -v python || true)"
[ -n "$PYTHON" ] || die "Python 3.9+ is required but was not found on PATH."
echo "[1/6] $($PYTHON --version)"

# ---- 2. Virtual environment -----------------------------------------
if [ ! -d venv ]; then
  echo "[2/6] Creating virtual environment..."
  "$PYTHON" -m venv venv
else
  echo "[2/6] Virtual environment already exists."
fi
# shellcheck disable=SC1091
source venv/bin/activate

# ---- 3. Python dependencies -----------------------------------------
if ! python -c "import fastapi, xgboost, sklearn, pandas" >/dev/null 2>&1; then
  echo "[3/6] Installing Python dependencies (this takes a few minutes)..."
  python -m pip install --upgrade pip --quiet
  python -m pip install -r backend/requirements.txt
else
  echo "[3/6] Python dependencies already installed."
fi

# ---- 4. Dataset and model -------------------------------------------
if [ ! -f backend/data/datasets/voyage_data.csv ]; then
  echo "[4/6] Generating the voyage dataset and training the model..."
  python train_model.py --generate 10000
elif [ ! -f backend/prediction/saved_models/xgboost_model.pkl ]; then
  echo "[4/6] Training the fuel-prediction model..."
  python train_model.py
else
  echo "[4/6] Dataset and model present."
fi

# ---- 5 & 6. Servers --------------------------------------------------
cleanup() { echo; echo "Stopping servers..."; kill 0 2>/dev/null || true; }
trap cleanup EXIT INT TERM

echo "[5/6] Starting the API on http://localhost:8000 ..."
( cd backend && python -m uvicorn main:app --reload --port 8000 ) &

if command -v npm >/dev/null 2>&1; then
  [ -d frontend/node_modules ] || ( echo "[6/6] Installing frontend dependencies..." && cd frontend && npm install )
  echo "[6/6] Starting the UI on http://localhost:5173 ..."
  ( cd frontend && npm run dev ) &
else
  echo "[WARN] npm not found - the UI was not started. Install Node.js from https://nodejs.org"
fi

say "UI       http://localhost:5173
API      http://localhost:8000
API docs http://localhost:8000/docs

Press Ctrl-C to stop both servers."

wait
