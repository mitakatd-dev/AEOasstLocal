#!/bin/bash
set -e

# Load .env if mounted
if [ -f /app/.env ]; then
    export $(grep -v '^#' /app/.env | xargs)
fi

# Start Xvfb for headless browser (Camoufox needs a display)
Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
export DISPLAY=:99

exec uvicorn app.main:app --host 0.0.0.0 --port 8080
