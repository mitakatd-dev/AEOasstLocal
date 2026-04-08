#!/bin/bash
# ── AEO Insights Local — One-click run ──────────────────────────────
# Usage:  bash run.sh          Start the app
#         bash run.sh stop     Stop all services
# ─────────────────────────────────────────────────────────────────────
set -e
cd "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.nvm/versions/node/*/bin:$PATH"

ROOT="$(pwd)"
PIDFILE_BE="$ROOT/data/.backend.pid"
PIDFILE_FE="$ROOT/data/.frontend.pid"
PORT_BE=8000
PORT_FE=3001

# ── Stop ──────────────────────────────────────────────────────────────
stop_all() {
  echo "  Stopping services…"
  [ -f "$PIDFILE_BE" ] && kill "$(cat "$PIDFILE_BE")" 2>/dev/null && rm -f "$PIDFILE_BE" && echo "  ✓ Backend stopped"
  [ -f "$PIDFILE_FE" ] && kill "$(cat "$PIDFILE_FE")" 2>/dev/null && rm -f "$PIDFILE_FE" && echo "  ✓ Frontend stopped"
  # Catch any stragglers
  pkill -f "uvicorn app.main:app" 2>/dev/null || true
  pkill -f "vite.*--port $PORT_FE" 2>/dev/null || true
  echo "  Done."
  exit 0
}

if [ "${1:-}" = "stop" ]; then stop_all; fi

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║      AEO Insights Local              ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── First-time setup (automatic) ─────────────────────────────────────
mkdir -p data

if [ ! -f .env ]; then
  cp .env.example .env
  BRAND="YourBrandName"
  echo "  First-time setup — what brand are you tracking?"
  printf "  Brand name [%s]: " "$BRAND"
  read -r input
  BRAND="${input:-$BRAND}"
  printf "  Competitors (comma-separated) [Competitor1,Competitor2,Competitor3]: "
  read -r comps
  comps="${comps:-Competitor1,Competitor2,Competitor3}"
  sed -i.bak "s/TARGET_COMPANY=.*/TARGET_COMPANY=$BRAND/" .env
  sed -i.bak "s/COMPETITORS=.*/COMPETITORS=$comps/" .env
  rm -f .env.bak
  echo "  ✓ Saved to .env"
fi

BRAND=$(grep '^TARGET_COMPANY=' .env | cut -d= -f2)
echo "  Brand: $BRAND"

# ── Install dependencies if missing ──────────────────────────────────
if [ ! -d backend/venv ]; then
  echo "  Installing Python dependencies (first run only)…"
  python3 -m venv backend/venv
  backend/venv/bin/pip install -q -r backend/requirements.txt
  backend/venv/bin/pip install -q -r runner/requirements.txt
  echo "  ✓ Python ready"
fi

if [ ! -d frontend/node_modules ]; then
  echo "  Installing frontend dependencies (first run only)…"
  (cd frontend && npm install --silent)
  echo "  ✓ Frontend ready"
fi

# ── Stop anything already running ─────────────────────────────────────
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "vite.*--port $PORT_FE" 2>/dev/null || true
sleep 1

# ── Start backend ─────────────────────────────────────────────────────
echo ""
echo "  Starting backend on :$PORT_BE …"
(cd backend && source venv/bin/activate && python3 -m uvicorn app.main:app --host 0.0.0.0 --port $PORT_BE &
  echo $! > "$PIDFILE_BE"
) 2>&1 | while read -r line; do echo "    [api] $line"; done &

# Wait for backend health
for i in $(seq 1 20); do
  curl -sf "http://localhost:$PORT_BE/api/health" >/dev/null 2>&1 && break
  sleep 1
done
echo "  ✓ Backend ready"

# ── Start frontend ────────────────────────────────────────────────────
echo "  Starting frontend on :$PORT_FE …"
(cd frontend && npx vite --port $PORT_FE --host 0.0.0.0 &
  echo $! > "$PIDFILE_FE"
) 2>&1 | while read -r line; do echo "    [web] $line"; done &

sleep 2
echo "  ✓ Frontend ready"

# ── Open browser ──────────────────────────────────────────────────────
URL="http://localhost:$PORT_FE"
echo ""
echo "  ┌──────────────────────────────────────────┐"
echo "  │  App:   $URL                     │"
echo "  │  Brand: $BRAND"
echo "  │                                          │"
echo "  │  Stop:  bash run.sh stop                 │"
echo "  └──────────────────────────────────────────┘"
echo ""

# Open browser (macOS / Linux)
if command -v open &>/dev/null; then
  open "$URL"
elif command -v xdg-open &>/dev/null; then
  xdg-open "$URL"
fi

echo "  Press Ctrl+C to stop all services."
echo ""

# ── Keep running until Ctrl+C ─────────────────────────────────────────
trap 'echo ""; stop_all' INT TERM
wait
