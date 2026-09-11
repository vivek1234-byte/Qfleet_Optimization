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
echo "[1/6] $($PYTHON --version)"

# Everything below runs "$PY", the venv's interpreter by absolute path,
# rather than activating and relying on a bare `python`. A venv records
# absolute paths when it is created, so a project folder that has been copied
# or renamed activates "successfully" while `python` quietly falls through to
# the system interpreter — which is how you get "No module named alembic"
# out of an environment that has alembic installed. Calling the interpreter
# by path cannot go wrong that way.
VENV="$PWD/venv"
PY="$VENV/bin/python"

if [ ! -x "$PY" ]; then
  echo "[2/6] Creating virtual environment..."
  "$PYTHON" -m venv "$VENV"
elif ! grep -qs "VIRTUAL_ENV=.*$VENV" "$VENV/bin/activate"; then
  # Created somewhere else and copied here. Re-running venv over the existing
  # directory rewrites the activation scripts and keeps installed packages.
  echo "[2/6] Virtual environment was created under a different path - repairing..."
  "$PYTHON" -m venv "$VENV"
else
  echo "[2/6] Virtual environment already exists."
fi

# Name every package needed at startup, the account ones included. A check
# that only asks about fastapi and pandas passes on an environment built
# before accounts existed and skips the install they need.
if ! "$PY" -c "import fastapi, xgboost, sklearn, pandas, sqlalchemy, alembic, bcrypt, jwt" >/dev/null 2>&1; then
  echo "[3/6] Installing Python dependencies (this takes a few minutes)..."
  "$PY" -m pip install --upgrade pip --quiet
  "$PY" -m pip install -r backend/requirements.txt
else
  echo "[3/6] Python dependencies already installed."
fi

if [ ! -f backend/data/datasets/voyage_data.csv ]; then
  echo "[4/6] Generating the voyage dataset and training the model..."
  "$PY" train_model.py --generate 20000
elif [ ! -f backend/prediction/saved_models/xgboost_model.pkl ]; then
  echo "[4/6] Training the fuel-prediction model..."
  "$PY" train_model.py
else
  echo "[4/6] Dataset and model present."
fi

# Accounts. All three steps are safe to repeat: `env` only fills in a
# placeholder, alembic is a no-op once the schema is current, and `seed`
# leaves anyone who already exists alone.
echo "[5/6] Accounts..."
"$PY" -m backend.manage env

echo "      Applying database migrations..."
"$PY" -m alembic upgrade head || die "migration failed. If it says \"No module named alembic\",
        install the dependencies into this project's venv:
            $PY -m pip install -r backend/requirements.txt"
# --force because this launcher IS the development entry point. A real
# deployment uses `bootstrap`, and plain `seed` refuses outside debug.
"$PY" -m backend.manage seed --force

# --host is explicit on purpose: both servers bind to localhost only, so
# nothing on the venue Wi-Fi can reach them. Change to 0.0.0.0 only for a
# deliberate deployment behind a reverse proxy, never on a shared network.
echo "[6/6] Starting the API..."
(cd backend && "$PY" -m uvicorn main:app --reload --host 127.0.0.1 --port 8000) &
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
