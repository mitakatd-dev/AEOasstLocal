# AEO Insights — Local

Self-hosted, fully local brand-visibility tracker. Submit prompts to LLMs (GPT-4o, Gemini, Perplexity), analyse how often and how positively your brand is mentioned, and surface trends, share of voice, sentiment, and competitive positioning — all from your own machine.

No cloud account, no Firebase, no auth. Data stays on disk in SQLite.

---

## What It Does

- **Brand visibility tracking** across OpenAI GPT-4o, Google Gemini, and Perplexity Sonar
- **Share of voice** — your brand vs competitors, per LLM
- **Narrative analysis** — how LLMs describe your brand, what descriptors they use
- **Positioning gaps** — words competitors get that you don't
- **Blind spots** — prompts where your brand is never mentioned
- **Trend tracking** — mention rate, sentiment, and per-LLM visibility over time
- **Experiment framework** — test prompt variants to understand what influences LLM output
- **Browser research** — run headless Chromium sessions (ChatGPT, Gemini, Perplexity web)
- **Cost management** — per-model token usage and spend tracking
- **Action log** — log external events and overlay on trend charts

---

## Quick Start

### Option A — Automated setup

```bash
git clone git@github.com:mitakatd-dev/AEOasstLocal.git
cd AEOasstLocal
./setup.sh        # creates .env, installs deps
```

Then edit `.env` with your API keys and brand name, and start:

```bash
# Terminal 1 — Backend
cd backend && source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Terminal 2 — Frontend
cd frontend && npm run dev
```

Open **http://localhost:3001**

### Option B — Manual setup

```bash
git clone git@github.com:mitakatd-dev/AEOasstLocal.git
cd AEOasstLocal

# 1. Create .env
cp .env.example .env
# Edit .env — fill in TARGET_COMPANY and at least one API key

# 2. Backend
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 &

# 3. Frontend
cd ../frontend
npm install
npm run dev
```

Open **http://localhost:3001**

---

## Configuration

Edit `.env` in the project root (or use the **Settings** page in the UI):

```
TARGET_COMPANY=YourBrandName
COMPETITORS=Competitor1,Competitor2,Competitor3
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AI...
PERPLEXITY_API_KEY=pplx-...
```

All settings can also be changed live via **Settings → Brand Config** and **Settings → API Keys** in the UI. Changes take effect immediately and persist to the local SQLite database.

---

## Architecture

```
AEOasstLocal/
├── backend/              Python 3.11, FastAPI, SQLAlchemy (SQLite)
│   ├── app/
│   │   ├── main.py       App entry, router registration
│   │   ├── models.py     DB models: Prompt, Run, Result, Experiment, AppSetting, ...
│   │   ├── auth.py       No-op auth — every request is treated as admin
│   │   ├── database.py   SQLite engine (data/db.sqlite), init_db()
│   │   ├── routers/      prompts, runs, stats, trends, events, experiments,
│   │   │                 settings, runner, accounts, costs, extension, seed
│   │   ├── services/     analyzer, runner, insights, narrative
│   │   └── adapters/     openai, gemini, perplexity
│   └── requirements.txt
├── frontend/             React 18, Vite, Tailwind CSS, Chart.js
│   ├── src/
│   │   ├── api.js        apiFetch wrapper — always use this, never raw fetch()
│   │   ├── contexts/
│   │   │   └── AuthContext.jsx   Always-admin stub (no login)
│   │   └── views/        Dashboard, Prompts, PromptDetail, Research,
│   │                     Experiments, Costs, Settings, ...
│   └── vite.config.js    Proxies /api → localhost:8000
├── runner/               Headless browser runner (Playwright + Camoufox)
├── extension/            Chrome Extension (Manifest V3, optional)
├── scripts/              Utility scripts
├── data/                 SQLite database (data/db.sqlite, gitignored)
├── .env.example          Template for environment variables
├── setup.sh              One-shot setup script
└── CLAUDE.md             Developer context
```

---

## Browser Research (Headless)

Run prompts through the actual ChatGPT, Gemini, and Perplexity web interfaces using headless Chromium — zero API cost.

1. Go to **Research** in the UI
2. Select **Browser** mode
3. Click **Launch** — a headless browser opens, logs in, and starts submitting prompts
4. Watch live progress in the worker panel

First run may open a visible browser window for manual login. After logging in, the session is saved locally and subsequent runs are fully headless.

---

## Chrome Extension (Alternative)

Capture responses from web portals using your own logged-in browser session:

1. Go to `chrome://extensions/` in Chrome
2. Enable **Developer mode**
3. **Load unpacked** → select the `extension/` folder
4. Open ChatGPT, Gemini, and Perplexity, log in
5. Click the AEO extension icon → connect to backend → load queue → start

---

## Data

All data is stored in `data/db.sqlite`. To reset everything:

```bash
rm data/db.sqlite
# Restart the backend — it recreates the schema automatically
```

To back up: just copy `data/db.sqlite`.

---

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/stats/` | Aggregated mention stats with date/batch filter |
| `GET /api/trends/dashboard` | Mention rate trend over time |
| `GET /api/trends/share-of-voice` | Brand vs competitor mention rates |
| `GET /api/prompts/` | List prompts |
| `POST /api/prompts/` | Create prompt |
| `POST /api/runs/` | Trigger API runs |
| `GET /api/runs/batches` | Auto-detected run batches |
| `GET /api/runs/export/csv` | Export results as CSV |
| `POST /api/runner/launch` | Launch browser runner |
| `GET /api/settings/` | Read settings |
| `PUT /api/settings/` | Update settings and LLM keys |
| `GET /api/costs/summary` | Total spend for a time window |

---

## Cost Estimate (API mode, 750 prompts)

| Model | ~Cost |
|-------|-------|
| GPT-4o | $5–8 |
| Gemini Flash | $0.50 |
| Perplexity Sonar | $2–3 |
| **Total** | **~$8–12** |

Browser / Chrome extension mode has **zero API cost**.
