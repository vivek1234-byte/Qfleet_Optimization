@echo off
REM ===================================================================
REM  QFleet - one-click launcher (Windows)
REM
REM  Sets up the Python venv, installs dependencies, trains the model
REM  if needed, installs the frontend packages, then starts the API in
REM  its own window and the web UI in this one. Safe to run repeatedly.
REM
REM  Run start-backend-only.bat instead if you just want the API.
REM ===================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  ==========================================================
echo   QFleet - starting API + web UI
echo  ==========================================================
echo.

REM ---- 1. Python -----------------------------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python is not on your PATH.
    echo         Install Python 3.9+ from https://python.org and re-run.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [1/6] Python %PYVER% found.

REM ---- 2. Virtual environment ----------------------------------------
if not exist "venv\Scripts\activate.bat" (
    echo [2/6] Creating virtual environment...
    python -m venv venv
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
) else (
    echo [2/6] Virtual environment already exists.
)
call venv\Scripts\activate.bat

REM ---- 3. Python dependencies ----------------------------------------
python -c "import fastapi, xgboost, sklearn, pandas" >nul 2>nul
if errorlevel 1 (
    echo [3/6] Installing Python dependencies ^(this takes a few minutes^)...
    python -m pip install --upgrade pip --quiet
    python -m pip install -r backend\requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed. See the output above.
        pause
        exit /b 1
    )
) else (
    echo [3/6] Python dependencies already installed.
)

REM ---- 4. Dataset and model ------------------------------------------
if not exist "backend\data\datasets\voyage_data.csv" (
    echo [4/6] Generating the voyage dataset and training the model...
    python train_model.py --generate 20000
) else (
    if not exist "backend\prediction\saved_models\xgboost_model.pkl" (
        echo [4/6] Training the fuel-prediction model...
        python train_model.py
    ) else (
        echo [4/6] Dataset and model present.
    )
)

REM ---- 5. Frontend dependencies --------------------------------------
where npm >nul 2>nul
if errorlevel 1 (
    echo.
    echo [WARN] Node.js / npm is not on your PATH, so the web UI cannot start.
    echo        Install Node 18+ from https://nodejs.org and re-run, or use
    echo        start-backend-only.bat and the API docs at /docs.
    echo.
    set SKIP_UI=1
) else (
    if not exist "frontend\node_modules" (
        echo [5/6] Installing frontend packages ^(first run only, a minute or two^)...
        pushd frontend
        call npm install
        if errorlevel 1 (
            echo [ERROR] npm install failed. See the output above.
            popd
            pause
            exit /b 1
        )
        popd
    ) else (
        echo [5/6] Frontend packages already installed.
    )
)

REM ---- 6. Start ------------------------------------------------------
REM --host is explicit on purpose: both servers bind to localhost only, so
REM nothing on the venue Wi-Fi can reach them. Change to 0.0.0.0 only for a
REM deliberate deployment behind a reverse proxy, never on a shared network.
echo [6/6] Starting the API in a separate window...
start "QFleet API" cmd /k "cd /d "%~dp0" && call venv\Scripts\activate.bat && cd backend && python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000"

if defined SKIP_UI (
    echo.
    echo  ==========================================================
    echo     API      http://localhost:8000
    echo     API docs http://localhost:8000/docs
    echo  ==========================================================
    pause
    exit /b 0
)

echo     Waiting for the API to come up...
timeout /t 6 /nobreak >nul

echo.
echo  ==========================================================
echo     Web UI   http://localhost:5173     ^<-- open this
echo     API      http://localhost:8000
echo     API docs http://localhost:8000/docs
echo.
echo   Close this window or press Ctrl+C to stop the web UI.
echo   The API runs in the other window.
echo  ==========================================================
echo.

cd frontend
call npm run dev
