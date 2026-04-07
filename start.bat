@echo off
REM ── AEO Insights Local — Windows Launcher ──────────────────────────
REM Double-click this file to start. Requires Docker Desktop.
REM ───────────────────────────────────────────────────────────────────
cd /d "%~dp0"
setlocal enabledelayedexpansion

set BRAND=YourBrandName
set PORT=3000

echo.
echo   ======================================
echo        AEO Insights Local
echo   ======================================
echo.

REM ── 1. Docker check ────────────────────────────────────────────────
where docker >nul 2>nul
if %errorlevel% neq 0 goto :no_docker

docker info >nul 2>nul
if %errorlevel% neq 0 goto :no_docker
goto :docker_ok

:no_docker
echo   Docker Desktop is required but not running.
echo.
echo   Download it from:
echo   https://www.docker.com/products/docker-desktop
echo.
echo   Install Docker Desktop, start it, then run this script again.
echo.
pause
exit /b 1

:docker_ok
echo   OK Docker is running

REM ── 2. Auto-create .env with brand name prompt ─────────────────────
if exist .env goto :env_exists

echo.
echo   First-time setup — what brand are you tracking?
echo.
set /p "BRAND=  Brand name [%BRAND%]: "
set /p "COMPS=  Competitors (comma-separated) [Competitor1,Competitor2,Competitor3]: "
if "!COMPS!"=="" set COMPS=Competitor1,Competitor2,Competitor3

(
echo TARGET_COMPANY=!BRAND!
echo COMPETITORS=!COMPS!
echo OPENAI_API_KEY=
echo GEMINI_API_KEY=
echo PERPLEXITY_API_KEY=
) > .env

echo.
echo   OK Configuration saved to .env
echo      (Edit .env later to add API keys if you want API-mode research)
goto :env_done

:env_exists
for /f "tokens=1,* delims==" %%a in ('findstr /b "TARGET_COMPANY" .env') do set BRAND=%%b
echo   OK Tracking brand: %BRAND%

:env_done

REM ── 3. Ensure data directory ────────────────────────────────────────
if not exist data mkdir data

REM ── 4. Build and launch ─────────────────────────────────────────────
echo.
echo   Building and starting containers...
echo   (First run downloads dependencies — takes 2-5 minutes)
echo.

docker compose up --build -d

echo.
echo   OK Running!
echo.

REM ── 5. Wait for healthy backend, then open browser ──────────────────
echo   Waiting for backend health check...
set /a tries=0
:healthloop
if %tries% geq 30 goto :openbrowser
curl -sf http://localhost:8080/api/health >nul 2>nul
if %errorlevel%==0 goto :openbrowser
timeout /t 2 /nobreak >nul
set /a tries+=1
goto :healthloop

:openbrowser
start http://localhost:%PORT%

echo.
echo   ----------------------------------------
echo   App:   http://localhost:%PORT%
echo   Brand: %BRAND%
echo.
echo   Stop:  docker compose down
echo   Logs:  docker compose logs -f
echo   ----------------------------------------
echo.
echo   Showing live logs (Ctrl+C to detach)...
echo.

docker compose logs -f
