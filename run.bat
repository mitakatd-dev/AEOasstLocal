@echo off
REM ── AEO Insights Local — One-click run (Windows) ───────────────────
REM Usage:  run.bat          Start the app
REM         run.bat stop     Stop all services
REM ───────────────────────────────────────────────────────────────────
setlocal enabledelayedexpansion
cd /d "%~dp0"

set PORT_BE=8000
set PORT_FE=3001
set PIDFILE_BE=data\.backend.pid
set PIDFILE_FE=data\.frontend.pid

if /i "%1"=="stop" goto :stop_all

echo.
echo   ======================================
echo        AEO Insights Local
echo   ======================================
echo.

REM ── 1. Ensure prerequisites (auto-install) ─────────────────────────

REM Check Python
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo   Python not found. Installing...
    where winget >nul 2>nul
    if %errorlevel% neq 0 (
        echo.
        echo   ERROR: Please install Python 3.11+ manually from:
        echo   https://www.python.org/downloads/
        echo   IMPORTANT: Check "Add Python to PATH" during install.
        echo.
        pause
        exit /b 1
    )
    winget install Python.Python.3.11 --accept-package-agreements --accept-source-agreements
    echo.
    echo   Python installed. Please CLOSE this window and run run.bat again
    echo   so that Python is on your PATH.
    echo.
    pause
    exit /b 0
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo   OK %%v

REM Check Node.js
where node >nul 2>nul
if %errorlevel% neq 0 (
    echo   Node.js not found. Installing...
    where winget >nul 2>nul
    if %errorlevel% neq 0 (
        echo.
        echo   ERROR: Please install Node.js 18+ manually from:
        echo   https://nodejs.org/
        echo.
        pause
        exit /b 1
    )
    winget install OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
    echo.
    echo   Node.js installed. Please CLOSE this window and run run.bat again
    echo   so that Node is on your PATH.
    echo.
    pause
    exit /b 0
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do echo   OK Node %%v

REM ── 2. First-time setup (brand name) ───────────────────────────────
if not exist data mkdir data

if not exist .env (
    copy .env.example .env >nul
    echo.
    echo   First-time setup — what brand are you tracking?
    echo.
    set "BRAND=YourBrandName"
    set /p "BRAND=  Brand name [YourBrandName]: "
    set "COMPS=Competitor1,Competitor2,Competitor3"
    set /p "COMPS=  Competitors (comma-separated) [Competitor1,Competitor2,Competitor3]: "

    REM Write .env with user values
    (
        echo TARGET_COMPANY=!BRAND!
        echo COMPETITORS=!COMPS!
        echo OPENAI_API_KEY=
        echo GEMINI_API_KEY=
        echo PERPLEXITY_API_KEY=
    ) > .env
    echo.
    echo   OK Saved to .env
)

for /f "tokens=1,* delims==" %%a in ('findstr /b "TARGET_COMPANY" .env') do set BRAND=%%b
echo   Brand: %BRAND%

REM ── 3. Install app dependencies (first run only) ───────────────────
if not exist backend\venv (
    echo   Installing Python dependencies (first run only)...
    python -m venv backend\venv
    backend\venv\Scripts\pip install -q -r backend\requirements.txt
    backend\venv\Scripts\pip install -q -r runner\requirements.txt
    echo   OK Python deps ready
)

if not exist frontend\node_modules (
    echo   Installing frontend dependencies (first run only)...
    cd frontend
    call npm install --silent
    cd ..
    echo   OK Frontend deps ready
)

REM ── 4. Stop anything already running ────────────────────────────────
taskkill /f /fi "WINDOWTITLE eq AEO-Backend" >nul 2>nul
taskkill /f /fi "WINDOWTITLE eq AEO-Frontend" >nul 2>nul

REM ── 5. Start backend ───────────────────────────────────────────────
echo.
echo   Starting backend on :%PORT_BE% ...
start "AEO-Backend" /min cmd /c "cd backend && venv\Scripts\activate && python -m uvicorn app.main:app --host 0.0.0.0 --port %PORT_BE%"

echo   Waiting for backend...
set /a tries=0
:healthloop
if %tries% geq 30 goto :backend_ready
powershell -Command "try { (Invoke-WebRequest -Uri 'http://localhost:%PORT_BE%/api/health' -UseBasicParsing -TimeoutSec 2).StatusCode } catch { exit 1 }" >nul 2>nul
if %errorlevel%==0 goto :backend_ready
timeout /t 1 /nobreak >nul
set /a tries+=1
goto :healthloop

:backend_ready
echo   OK Backend ready

REM ── 6. Start frontend ──────────────────────────────────────────────
echo   Starting frontend on :%PORT_FE% ...
start "AEO-Frontend" /min cmd /c "cd frontend && npx vite --port %PORT_FE% --host 0.0.0.0"

timeout /t 3 /nobreak >nul
echo   OK Frontend ready

REM ── 7. Open browser ────────────────────────────────────────────────
set URL=http://localhost:%PORT_FE%
start %URL%

echo.
echo   ----------------------------------------
echo   App:   %URL%
echo   Brand: %BRAND%
echo.
echo   Stop:  run.bat stop
echo   Or:    close this window
echo   ----------------------------------------
echo.
echo   Services are running in background.
echo   Press any key to stop all services...
pause >nul
goto :stop_all

REM ── Stop ───────────────────────────────────────────────────────────
:stop_all
echo.
echo   Stopping services...
taskkill /f /fi "WINDOWTITLE eq AEO-Backend" >nul 2>nul && echo   OK Backend stopped
taskkill /f /fi "WINDOWTITLE eq AEO-Frontend" >nul 2>nul && echo   OK Frontend stopped
echo   Done.
if /i not "%1"=="stop" pause
exit /b 0
