#!/bin/bash
set -e

# Ensure common install paths are on PATH (Homebrew, nvm, etc.)
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.nvm/versions/node/*/bin:$PATH"

echo "=== AEO Insights Generator — Setup ==="
echo ""

# Check for .env
if [ ! -f .env ]; then
  cp .env.example .env
  echo "[1/4] Created .env from .env.example"
  echo "      Edit .env with your API keys and brand name before running."
  echo ""
  echo "      Required:"
  echo "        TARGET_COMPANY=YourBrand"
  echo "        At least one of: OPENAI_API_KEY, GEMINI_API_KEY, PERPLEXITY_API_KEY"
  echo ""
  read -p "      Press Enter after editing .env, or Ctrl+C to abort..."
else
  echo "[1/4] .env already exists"
fi

# Create data directory
mkdir -p data
echo "[2/4] Data directory ready"

# Backend setup
echo "[3/4] Setting up backend..."
cd backend
if [ ! -d venv ]; then
  python3 -m venv venv
fi
source venv/bin/activate
venv/bin/pip install -q -r requirements.txt
venv/bin/pip install -q -r ../runner/requirements.txt
deactivate
cd ..

# Frontend setup
echo "[4/4] Setting up frontend..."
cd frontend
npm install --silent
cd ..

echo ""
echo "=== Setup complete! ==="
echo ""
echo "To start the app:"
echo ""
echo "  Option A — Docker:"
echo "    docker compose up --build"
echo "    Open http://localhost:3000"
echo ""
echo "  Option B — Local dev:"
echo "    # Terminal 1: Backend"
echo "    cd backend && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo ""
echo "    # Terminal 2: Frontend"
echo "    cd frontend && npm run dev"
echo "    Open http://localhost:3001"
echo ""
echo "  Chrome Extension:"
echo "    1. Go to chrome://extensions/"
echo "    2. Enable Developer mode"
echo "    3. Load unpacked → select the extension/ folder"
echo ""
