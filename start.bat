@echo off
REM ===================================================================
REM  Quantum Green Fleet - one-click local launcher (Windows)
REM
REM  Sets up the Python venv, installs dependencies, trains the model
REM  if needed, then starts the API and the UI in two new windows.
REM  Safe to run repeatedly - it skips work that is already done.
REM ===================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  ==========================================================
echo   Quantum Green Fleet - starting local development stack
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
    python train_model.py --generate 10000
) else (
    if not exist "backend\prediction\saved_models\xgboost_model.pkl" (
        echo [4/6] Training the fuel-prediction model...
        python train_model.py
    ) else (
        echo [4/6] Dataset and model present.
        echo       ^(If /predict returns a format-version error, run: python train_model.py^)
    )
)

REM ---- 5. Backend ------------------------------------------------------
echo [5/6] Starting the API on http://localhost:8000 ...
start "Quantum Green Fleet API" cmd /k "cd /d "%~dp0backend" && "%~dp0venv\Scripts\python.exe" -m uvicorn main:app --reload --port 8000"

REM ---- 6. Frontend -----------------------------------------------------
where npm >nul 2>nul
if errorlevel 1 (
    echo.
    echo [WARN] npm is not on your PATH, so the UI was not started.
    echo        Install Node.js from https://nodejs.org, then run:
    echo            cd frontend ^&^& npm install ^&^& npm run dev
    echo.
    echo The API is still starting at http://localhost:8000/docs
    pause
    exit /b 0
)

if not exist "frontend\node_modules" (
    echo [6/6] Installing frontend dependencies...
    pushd frontend
    call npm install
    popd
) else (
    echo [6/6] Frontend dependencies already installed.
)

start "Quantum Green Fleet UI" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo  ==========================================================
echo   Both servers are starting in their own windows.
echo.
echo     UI       http://localhost:5173
echo     API      http://localhost:8000
echo     API docs http://localhost:8000/docs
echo.
echo   Close those two windows to stop the servers.
echo  ==========================================================
echo.

timeout /t 12 /nobreak >nul
start "" http://localhost:5173
exit /b 0
