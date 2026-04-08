@echo off
REM ── AEO Insights Local ─────────────────────────────────────────────
REM Double-click to start. Press any key to stop.
REM ───────────────────────────────────────────────────────────────────
cd /d "%~dp0"

set PORT_BE=8000
set PORT_FE=3001

if /i "%~1"=="stop" goto :stop_all

echo.
echo   ========================================
echo        AEO Insights Local
echo   ========================================
echo.

REM ── Check prerequisites ────────────────────────────────────────────
echo   [1/7] Checking prerequisites...

where python >nul 2>nul
if errorlevel 1 (
    echo         [FAIL] Python not found on PATH.
    echo         Ask your IT team to install Python 3.11+ and add it to PATH.
    echo.
    pause
    exit /b 1
)
echo         [OK] Python found

where node >nul 2>nul
if errorlevel 1 (
    echo         [FAIL] Node.js not found on PATH.
    echo         Ask your IT team to install Node.js 18+ and add it to PATH.
    echo.
    pause
    exit /b 1
)
echo         [OK] Node.js found

REM ── Configuration ──────────────────────────────────────────────────
echo   [2/7] Checking configuration...

if not exist data mkdir data

if exist .env goto :env_exists

copy .env.example .env >nul
echo.
echo         First-time setup - what brand are you tracking?
echo.
set "BRAND=YourBrandName"
set /p "BRAND=        Brand name [YourBrandName]: "
set "COMPS=Competitor1,Competitor2,Competitor3"
set /p "COMPS=        Competitors, comma-separated [Competitor1,Competitor2,Competitor3]: "

echo TARGET_COMPANY=%BRAND%> .env
echo COMPETITORS=%COMPS%>> .env
echo OPENAI_API_KEY=>> .env
echo GEMINI_API_KEY=>> .env
echo PERPLEXITY_API_KEY=>> .env

echo         [OK] Configuration saved
goto :env_done

:env_exists
echo         [OK] .env found

:env_done
for /f "tokens=1,* delims==" %%a in ('findstr /b "TARGET_COMPANY" .env') do set "BRAND=%%b"
echo         Brand: %BRAND%

REM ── Python dependencies ────────────────────────────────────────────
if exist backend\venv (
    echo   [3/7] Python dependencies    [OK] installed
    goto :node_deps
)

echo   [3/7] Installing Python dependencies (first run, 1-2 min)...
python -m venv backend\venv
call backend\venv\Scripts\pip install -q -r backend\requirements.txt
call backend\venv\Scripts\pip install -q -r runner\requirements.txt
echo         Downloading browser engine (one-time, ~80MB)...
call backend\venv\Scripts\python -m camoufox fetch
echo         [OK] Done

REM ── Node dependencies ──────────────────────────────────────────────
:node_deps
if exist frontend\node_modules (
    echo   [4/7] Frontend dependencies   [OK] installed
    goto :start_services
)

echo   [4/7] Installing frontend dependencies (first run, 1-2 min)...
cd frontend
call npm install --silent
cd ..
echo         [OK] Done

REM ── Start services ─────────────────────────────────────────────────
:start_services

REM Kill any leftover instances
taskkill /f /fi "WINDOWTITLE eq AEO-Backend" >nul 2>nul
taskkill /f /fi "WINDOWTITLE eq AEO-Frontend" >nul 2>nul
timeout /t 1 /nobreak >nul

echo   [5/7] Starting backend...
start "AEO-Backend" /min cmd /c "cd /d "%~dp0backend" && call venv\Scripts\activate.bat && python -m uvicorn app.main:app --host 0.0.0.0 --port %PORT_BE%"

REM Wait for backend health check
set /a TRIES=0
:health_wait
if %TRIES% geq 30 goto :health_fail
powershell -NoProfile -Command "try{[void](Invoke-WebRequest http://localhost:%PORT_BE%/api/health -UseBasicParsing -TimeoutSec 2);exit 0}catch{exit 1}" >nul 2>nul
if not errorlevel 1 goto :health_ok
timeout /t 1 /nobreak >nul
set /a TRIES+=1
goto :health_wait

:health_fail
echo         [FAIL] Backend did not respond after 30s
echo         Check the minimized "AEO-Backend" window for errors.
pause
exit /b 1

:health_ok
echo         [OK] Backend running on port %PORT_BE%

echo   [6/7] Starting frontend...
start "AEO-Frontend" /min cmd /c "cd /d "%~dp0frontend" && call npx vite --port %PORT_FE% --host 0.0.0.0"
timeout /t 3 /nobreak >nul
echo         [OK] Frontend running on port %PORT_FE%

echo   [7/7] Opening browser...
start "" http://localhost:%PORT_FE%

echo.
echo   ========================================
echo.
echo     READY   http://localhost:%PORT_FE%
echo     Brand:  %BRAND%
echo.
echo     Backend  [RUNNING]  port %PORT_BE%
echo     Frontend [RUNNING]  port %PORT_FE%
echo.
echo   ========================================
echo.
echo   Press any key to STOP everything.
echo.
pause >nul

REM ── Stop ───────────────────────────────────────────────────────────
:stop_all
echo.
echo   Stopping...
taskkill /f /fi "WINDOWTITLE eq AEO-Backend" >nul 2>nul
echo     Backend  [STOPPED]
taskkill /f /fi "WINDOWTITLE eq AEO-Frontend" >nul 2>nul
echo     Frontend [STOPPED]
echo.
echo   All services stopped.
echo.
if /i not "%~1"=="stop" pause
exit /b 0
