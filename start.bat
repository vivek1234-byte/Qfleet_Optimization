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
echo [1/7] Python %PYVER% found.

REM ---- 2. Virtual environment ----------------------------------------
REM Everything below runs "%PY%", the venv's interpreter by absolute path,
REM rather than relying on `call activate.bat` and a bare `python`.
REM
REM That is not belt and braces. A venv bakes its absolute path into
REM activate.bat when it is created, so copying or renaming the project
REM folder leaves activate.bat prepending a directory that no longer holds a
REM python.exe. Activation then appears to succeed, `python` quietly falls
REM through to the system interpreter, and you get "No module named alembic"
REM from an environment where alembic is installed. Calling the interpreter
REM by path cannot go wrong that way: python.exe finds pyvenv.cfg next to
REM itself and uses the right site-packages wherever the folder has moved to.
set "VENV=%~dp0venv"
set "PY=%VENV%\Scripts\python.exe"

if not exist "%PY%" (
    echo [2/7] Creating virtual environment...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo [ERROR] Could not create the virtual environment.
        pause
        exit /b 1
    )
) else (
    REM Repair a venv that was created somewhere else and copied here.
    REM Re-running venv over an existing directory rewrites the activation
    REM scripts and pyvenv.cfg and keeps every installed package, so this
    REM costs a second and saves the confusion described above.
    findstr /i /c:"VIRTUAL_ENV=%VENV%" "%VENV%\Scripts\activate.bat" >nul 2>nul
    if errorlevel 1 (
        echo [2/7] Virtual environment was created under a different path - repairing...
        python -m venv "%VENV%"
    ) else (
        echo [2/7] Virtual environment already exists.
    )
)

REM ---- 3. Python dependencies ----------------------------------------
REM Name every package the application needs at startup, the account ones
REM included. A check that only asks about fastapi and pandas passes on an
REM environment built before accounts existed, skips the install, and leaves
REM the failure to surface three steps later as a missing alembic.
"%PY%" -c "import fastapi, xgboost, sklearn, pandas, sqlalchemy, alembic, bcrypt, jwt" >nul 2>nul
if errorlevel 1 (
    echo [3/7] Installing Python dependencies ^(this takes a few minutes^)...
    "%PY%" -m pip install --upgrade pip --quiet
    "%PY%" -m pip install -r backend\requirements.txt
    if errorlevel 1 (
        echo [ERROR] Dependency installation failed. See the output above.
        pause
        exit /b 1
    )
) else (
    echo [3/7] Python dependencies already installed.
)

REM ---- 4. Dataset and model ------------------------------------------
if not exist "backend\data\datasets\voyage_data.csv" (
    echo [4/7] Generating the voyage dataset and training the model...
    "%PY%" train_model.py --generate 20000
) else (
    if not exist "backend\prediction\saved_models\xgboost_model.pkl" (
        echo [4/7] Training the fuel-prediction model...
        "%PY%" train_model.py
    ) else (
        echo [4/7] Dataset and model present.
    )
)

REM ---- 5. Accounts database ------------------------------------------
REM All three steps are safe to repeat: `env` only fills in a placeholder,
REM alembic is a no-op once the schema is current, and `seed` leaves anyone
REM who already exists alone.
echo [5/7] Accounts...
"%PY%" -m backend.manage env
if errorlevel 1 (
    echo [ERROR] Could not prepare .env. See the output above.
    pause
    exit /b 1
)

echo      Applying database migrations...
"%PY%" -m alembic upgrade head
if errorlevel 1 (
    echo.
    echo [ERROR] Database migration failed. See the output above.
    echo         If it says "No module named alembic", the dependencies are
    echo         not in this project's venv. Install them with:
    echo             "%PY%" -m pip install -r backend\requirements.txt
    echo.
    pause
    exit /b 1
)
"%PY%" -m backend.manage seed

REM ---- 6. Frontend dependencies --------------------------------------
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
        echo [6/7] Installing frontend packages ^(first run only, a minute or two^)...
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
        echo [6/7] Frontend packages already installed.
    )
)

REM ---- 7. Start ------------------------------------------------------
REM --host is explicit on purpose: both servers bind to localhost only, so
REM nothing on the venue Wi-Fi can reach them. Change to 0.0.0.0 only for a
REM deliberate deployment behind a reverse proxy, never on a shared network.
echo [7/7] Starting the API in a separate window...
start "QFleet API" cmd /k "cd /d "%~dp0backend" && "%VENV%\Scripts\python.exe" -m uvicorn main:app --reload --host 127.0.0.1 --port 8000"

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
