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
echo "  bash run.sh          Start everything + open browser"
echo "  bash run.sh stop     Stop all services"
echo ""
