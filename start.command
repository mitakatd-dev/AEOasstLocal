#!/bin/bash
# ── AEO Insights Local — macOS Launcher ──────────────────────────────
# Double-click this file to start. Requires Docker Desktop.
# ─────────────────────────────────────────────────────────────────────
set -e
cd "$(dirname "$0")"

BRAND="YourBrandName"
PORT=3000

echo ""
echo "  ╔══════════════════════════════════════╗"
echo "  ║      AEO Insights Local              ║"
echo "  ╚══════════════════════════════════════╝"
echo ""

# ── 1. Docker check (install if missing) ─────────────────────────────
if ! command -v docker &>/dev/null || ! docker info &>/dev/null 2>&1; then
    echo "  Docker Desktop is required but not running."
    echo ""
    if [ ! -d "/Applications/Docker.app" ]; then
        echo "  Installing Docker Desktop via Homebrew…"
        if ! command -v brew &>/dev/null; then
            echo "  Homebrew not found. Installing Homebrew first…"
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        fi
        brew install --cask docker
        echo ""
        echo "  ✓ Docker Desktop installed"
    fi
    echo "  Starting Docker Desktop…"
    open -a Docker
    echo "  Waiting for Docker to be ready (this takes ~30s on first launch)…"
    while ! docker info &>/dev/null 2>&1; do
        sleep 2
    done
    echo "  ✓ Docker is ready"
else
    echo "  ✓ Docker is running"
fi

# ── 2. Auto-create .env with brand name prompt ───────────────────────
if [ ! -f .env ]; then
    echo ""
    echo "  First-time setup — what brand are you tracking?"
    echo ""
    printf "  Brand name [%s]: " "$BRAND"
    read -r input
    BRAND="${input:-$BRAND}"

    printf "  Competitors (comma-separated) [Competitor1,Competitor2,Competitor3]: "
    read -r comps
    comps="${comps:-Competitor1,Competitor2,Competitor3}"

    cat > .env <<ENVEOF
TARGET_COMPANY=$BRAND
COMPETITORS=$comps
OPENAI_API_KEY=
GEMINI_API_KEY=
PERPLEXITY_API_KEY=
ENVEOF

    echo ""
    echo "  ✓ Configuration saved to .env"
    echo "    (Edit .env later to add API keys if you want API-mode research)"
else
    BRAND=$(grep '^TARGET_COMPANY=' .env | cut -d= -f2)
    echo "  ✓ Tracking brand: $BRAND"
fi

# ── 3. Ensure data directory ──────────────────────────────────────────
mkdir -p data

# ── 4. Build & launch ────────────────────────────────────────────────
echo ""
echo "  Building & starting containers…"
echo "  (First run downloads dependencies — takes 2-5 minutes)"
echo ""

docker compose up --build -d

echo ""
echo "  ✓ Running!"
echo ""

# ── 5. Wait for healthy backend, then open browser ───────────────────
echo "  Waiting for backend health check…"
for i in $(seq 1 30); do
    if curl -sf http://localhost:8080/api/health &>/dev/null; then
        break
    fi
    sleep 2
done

open "http://localhost:$PORT"

echo ""
echo "  ┌──────────────────────────────────────────┐"
echo "  │  App:   http://localhost:$PORT             │"
echo "  │  Brand: $BRAND"
echo "  │                                          │"
echo "  │  Stop:  docker compose down              │"
echo "  │  Logs:  docker compose logs -f           │"
echo "  └──────────────────────────────────────────┘"
echo ""
echo "  Showing live logs (Ctrl+C to detach — app keeps running)…"
echo ""

docker compose logs -f
