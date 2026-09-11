#!/usr/bin/env bash
# ===================================================================
#  QFleet - one-click launcher (macOS / Linux / WSL)
#
#  Brings up the API and the web UI together. Ctrl+C stops both.
#  Pass --api-only to skip the web UI.
# ===================================================================
set -euo pipefail
cd "$(dirname "$0")"

say() { printf '\n\033[1;36m%s\033[0m\n' "$*"; }
die() { printf '\n\033[1;31m[ERROR] %s\033[0m\n' "$*" >&2; exit 1; }

API_ONLY=0
[ "${1:-}" = "--api-only" ] && API_ONLY=1

say "QFleet - starting"

PYTHON="$(command -v python3 || command -v python || true)"
[ -n "$PYTHON" ] || die "Python 3.9+ is required but was not found on PATH."
echo "[1/5] $($PYTHON --version)"

if [ ! -d venv ]; then
  echo "[2/5] Creating virtual environment..."
  "$PYTHON" -m venv venv
else
  echo "[2/5] Virtual environment already exists."
fi
# shellcheck disable=SC1091
source venv/bin/activate

if ! python -c "import fastapi, xgboost, sklearn, pandas" >/dev/null 2>&1; then
  echo "[3/5] Installing Python dependencies (this takes a few minutes)..."
  python -m pip install --upgrade pip --quiet
  python -m pip install -r backend/requirements.txt
else
  echo "[3/5] Python dependencies already installed."
fi

if [ ! -f backend/data/datasets/voyage_data.csv ]; then
  echo "[4/5] Generating the voyage dataset and training the model..."
  python train_model.py --generate 20000
elif [ ! -f backend/prediction/saved_models/xgboost_model.pkl ]; then
  echo "[4/5] Training the fuel-prediction model..."
  python train_model.py
else
  echo "[4/5] Dataset and model present."
fi

# --host is explicit on purpose: both servers bind to localhost only, so
# nothing on the venue Wi-Fi can reach them. Change to 0.0.0.0 only for a
# deliberate deployment behind a reverse proxy, never on a shared network.
echo "[5/5] Starting the API..."
(cd backend && python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000) &
API_PID=$!

# Kill the API (and the UI, if started) on Ctrl+C rather than orphaning them.
UI_PID=""
cleanup() {
  trap - INT TERM EXIT
  [ -n "$UI_PID" ] && kill "$UI_PID" 2>/dev/null || true
  kill "$API_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

if [ "$API_ONLY" -eq 1 ] || ! command -v npm >/dev/null 2>&1; then
  if [ "$API_ONLY" -eq 0 ]; then
    printf '\n\033[1;33m[WARN] npm not found, so the web UI is not starting. Install Node 18+.\033[0m\n'
  fi
  say "API      http://localhost:8000
API docs http://localhost:8000/docs
Health   http://localhost:8000/api/health

Press Ctrl+C to stop."
  wait "$API_PID"
  exit 0
fi

if [ ! -d frontend/node_modules ]; then
  echo "      Installing frontend packages (first run only)..."
  (cd frontend && npm install)
fi

sleep 4
say "Web UI   http://localhost:5173     <-- open this
API      http://localhost:8000
API docs http://localhost:8000/docs

Press Ctrl+C to stop both."

(cd frontend && npm run dev) &
UI_PID=$!
wait "$UI_PID"
