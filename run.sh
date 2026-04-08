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

# ── 1. Ensure prerequisites (auto-install) ───────────────────────────

# Homebrew (macOS only)
if [[ "$OSTYPE" == darwin* ]] && ! command -v brew &>/dev/null; then
  echo "  Installing Homebrew…"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
fi

# Python 3
if ! command -v python3 &>/dev/null; then
  echo "  Installing Python…"
  if [[ "$OSTYPE" == darwin* ]]; then
    brew install python@3.11
  else
    sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
  fi
fi
echo "  ✓ Python: $(python3 --version)"

# Node.js
if ! command -v node &>/dev/null; then
  echo "  Installing Node.js…"
  if [[ "$OSTYPE" == darwin* ]]; then
    brew install node
  else
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - && sudo apt-get install -y nodejs
  fi
fi
echo "  ✓ Node:   $(node --version)"

# ── 2. First-time setup (brand name) ─────────────────────────────────
mkdir -p data

if [ ! -f .env ]; then
  cp .env.example .env
  BRAND="YourBrandName"
  echo ""
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

# ── 3. Install app dependencies (first run only) ─────────────────────
if [ ! -d backend/venv ]; then
  echo "  Installing Python dependencies (first run only)…"
  python3 -m venv backend/venv
  backend/venv/bin/pip install -q -r backend/requirements.txt
  backend/venv/bin/pip install -q -r runner/requirements.txt
  echo "  ✓ Python deps ready"
fi

if [ ! -d frontend/node_modules ]; then
  echo "  Installing frontend dependencies (first run only)…"
  (cd frontend && npm install --silent)
  echo "  ✓ Frontend deps ready"
fi

# ── 4. Stop anything already running ──────────────────────────────────
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "vite.*--port $PORT_FE" 2>/dev/null || true
sleep 1

# ── 5. Start backend ─────────────────────────────────────────────────
echo ""
echo "  Starting backend on :$PORT_BE …"
(cd backend && source venv/bin/activate && python3 -m uvicorn app.main:app --host 0.0.0.0 --port $PORT_BE &
  echo $! > "$PIDFILE_BE"
) 2>&1 | while read -r line; do echo "    [api] $line"; done &

for i in $(seq 1 20); do
  curl -sf "http://localhost:$PORT_BE/api/health" >/dev/null 2>&1 && break
  sleep 1
done
echo "  ✓ Backend ready"

# ── 6. Start frontend ────────────────────────────────────────────────
echo "  Starting frontend on :$PORT_FE …"
(cd frontend && npx vite --port $PORT_FE --host 0.0.0.0 &
  echo $! > "$PIDFILE_FE"
) 2>&1 | while read -r line; do echo "    [web] $line"; done &

sleep 2
echo "  ✓ Frontend ready"

# ── 7. Open browser ──────────────────────────────────────────────────
URL="http://localhost:$PORT_FE"
echo ""
echo "  ┌──────────────────────────────────────────┐"
echo "  │  App:   $URL                     │"
echo "  │  Brand: $BRAND"
echo "  │                                          │"
echo "  │  Stop:  bash run.sh stop                 │"
echo "  │  Or:    Ctrl+C                           │"
echo "  └──────────────────────────────────────────┘"
echo ""

if command -v open &>/dev/null; then
  open "$URL"
elif command -v xdg-open &>/dev/null; then
  xdg-open "$URL"
fi

echo "  Press Ctrl+C to stop all services."
echo ""

trap 'echo ""; stop_all' INT TERM
wait
