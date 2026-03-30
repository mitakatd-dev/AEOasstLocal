# CLAUDE.md — AEO Insights Local

Developer context for Claude Code. Read this before making any changes.

## What This Is

A fully local, self-hosted brand-visibility tracking tool. Submits prompts to LLMs (GPT-4o, Gemini, Perplexity), analyses how often and how positively the target brand is mentioned, and surfaces trends, share of voice, sentiment, and competitive positioning.

**No cloud account, no Firebase, no Docker required.** SQLite on disk, subprocess runner, always-admin.

---

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11, FastAPI, SQLAlchemy ORM |
| Database | SQLite (`data/db.sqlite`) |
| Frontend | React 18, Vite, Tailwind CSS, Chart.js / react-chartjs-2 |
| Auth | None — every request is treated as admin |
| Runner | Subprocess (Playwright + Camoufox) |

---

## Authentication & Roles

There is **no authentication**. Every session is treated as admin.

- `backend/app/auth.py` — no-op stubs; `get_current_user`, `require_viewer`, `require_admin` all return `LOCAL_USER`
- `frontend/src/contexts/AuthContext.jsx` — always returns `{ user: LOCAL_USER, role: 'admin', isAdmin: true }`
- `frontend/src/api.js` — plain fetch wrapper; no Authorization header

All nav items are always visible. No login page, no user management.

---

## Configuration

Settings are stored in the `app_settings` DB table and loaded into `os.environ` on startup. They can be changed via the **Settings** page in the UI.

Root `.env` is also loaded on startup via `python-dotenv` (for initial seed values):

```
TARGET_COMPANY=YourBrandName
COMPETITORS=Competitor1,Competitor2,Competitor3
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=AI...
PERPLEXITY_API_KEY=pplx-...
```

No `VITE_API_URL` is needed — Vite proxies `/api` → `localhost:8000`.

---

## API / Frontend Conventions

### Always use `apiFetch`, never `fetch` directly

```javascript
import { apiFetch } from '../api';
const data = await apiFetch('/api/prompts/');
```

Plain `fetch()` works locally (no auth required), but `apiFetch` handles error parsing and the 204 no-content case uniformly.

**FormData exception:** When uploading files (`FormData`), `apiFetch` detects `options.body instanceof FormData` and skips the `Content-Type: application/json` header — the browser sets the multipart boundary automatically.

### API routes prefix

All backend routes are prefixed `/api/`. The Vite dev server proxies `/api/**` to `localhost:8000`.

---

## Key Files

```
backend/
  app/
    main.py              FastAPI app, router registration, startup (loads DB settings into env)
    models.py            SQLAlchemy models: Prompt, Run, Result, Experiment, AppSetting,
                         ExternalEvent, BrowserWorker, WorkerBatch, BrowserAccount
    auth.py              No-op auth stubs (always admin)
    database.py          SQLite engine + SessionLocal; init_db() calls create_all
    runner_manager.py    Subprocess-only runner (launch/stop/logs via local process)
    routers/
      prompts.py         CRUD for prompts
      runs.py            Run management, batch detection, session reports, CSV export
      stats.py           Aggregated stats with date filtering
      trends.py          Time-series endpoints: dashboard, per-llm, sentiment, share-of-voice, per-prompt
      events.py          External event log (action log on charts)
      experiments.py     Experiment CRUD + variant comparison
      settings.py        App settings CRUD (brand config + LLM keys); DB-backed
      runner.py          Browser runner control (launch/pause/resume/stop/logs/alive)
      accounts.py        Browser account pool (stored Playwright sessions)
      costs.py           Cost summary (API token cost + Brightdata proxy; infra_usd=0)
      extension.py       Chrome extension queue API
      seed.py            Seed data endpoint
    services/
      analyzer.py        LLM response analysis (mention detection, sentiment, position score)
      runner.py          API run orchestration (parallel LLM calls)
      insights.py        Insight generation
      narrative.py       Brand narrative report
    adapters/
      openai_adapter.py  GPT-4o calls
      gemini_adapter.py  Gemini calls
      perplexity_adapter.py  Perplexity calls

frontend/
  src/
    api.js               apiFetch wrapper — always use this, never raw fetch()
    contexts/
      AuthContext.jsx    Always-admin stub (no Firebase, no login)
    views/
      Dashboard.jsx      Main dashboard: KPIs, sparklines, share of voice, sentiment, action log
      Prompts.jsx        Prompt list with CRUD, CSV upload, bulk ops, queue-for-research
      PromptDetail.jsx   Per-prompt trend chart per LLM
      Research.jsx       Run launcher (API + browser), live batch progress, worker status
      RunDetail.jsx      Single run detail with per-LLM responses
      SessionReport.jsx  Post-session summary (all prompts, per-LLM outcome grid)
      Experiments.jsx    Experiment list + create
      ExperimentDetail.jsx  Experiment variant comparison chart
      Costs.jsx          Cost tracking view
      Settings.jsx       Brand config + LLM API keys + browser accounts

runner/               Headless browser runner (Playwright + Camoufox)
extension/            Chrome Extension (Manifest V3, optional)
scripts/              Utility scripts (migrate, capture session)
data/                 SQLite database (data/db.sqlite, gitignored)
.env.example          Template for environment variables
setup.sh              One-shot setup script
```

---

## Local Development

```bash
# Setup (first time)
./setup.sh

# Backend
cd backend && source venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Frontend
cd frontend && npm run dev
# Open http://localhost:3001
```

SQLite DB is created automatically at `data/db.sqlite` on first startup.

---

## Runner (Subprocess Mode)

`backend/app/runner_manager.py` is subprocess-only — no Cloud Run Jobs:

- `launch()` always calls `_launch_subprocess(worker_name, platform, batch_id)`
- `stop()` always calls `_stop_subprocess(worker_name)`
- `get_logs()` reads from `data/logs/<worker_name>.log`

No `_CLOUD` flag, no `google-cloud-run` dependency.

---

## Costs (Local)

`backend/app/routers/costs.py` returns:

- `infra_usd: 0.0`, `infra_source: "local"` — no Cloud Monitoring
- Exact API token cost from Run records
- Brightdata proxy cost if `BRIGHTDATA_API_KEY` is configured

---

## Date Filter Convention

Batch filters pass full datetime strings (e.g. `"2026-03-28 21:49:20"`), not date-only strings. All backend services that apply date filters must check `len(val) > 10` before appending `" 00:00:00"`. The helper `_parse_dt(val, eod=False)` in `stats.py` and `trends.py` does this correctly — use it instead of raw f-string concatenation.

---

## Insight & Trend Layer

All insight/trend features are implemented. Key endpoints:

| Endpoint | Description |
|----------|-------------|
| `GET /api/trends/dashboard` | Overall brand mention rate per day (`period`, `from_date`, `to_date`) |
| `GET /api/trends/prompt/{id}` | Mention rate per LLM per run date for one prompt + run history |
| `GET /api/trends/per-llm` | Per-LLM mention rate over time |
| `GET /api/trends/sentiment` | Positive/neutral/negative % per day |
| `GET /api/trends/share-of-voice` | Brand mention rate vs each competitor |
| `GET /api/events/` | List action log events |
| `POST /api/events/` | Create event `{date, description}` |
| `DELETE /api/events/{id}` | Delete event |

Frontend additions in `Dashboard.jsx`:
- Visibility trend sparkline with event markers
- Prompt coverage grid (5 query types)
- Share of Voice horizontal bar + doughnut chart
- Per-LLM sparklines inside each LLM card
- Sentiment trend (positive/neutral/negative)
- Action log form + event overlay on charts

New view: `PromptDetail.jsx` at `/prompts/:id` — trend chart per LLM, run history table.

---

## Known Issues & Hard-Won Lessons

### 1. Stale worker auto-reconciliation

`GET /api/runner/status` acts as a reconciliation endpoint. On every poll it checks if a `"running"` worker's `last_heartbeat` is older than 5 minutes. If stale:
1. Worker status → `"stopped"`
2. Associated `WorkerBatch` rows → `"error"`
3. Associated `Run` records still `"running"` → `"failed"`

A second pass: `"stopped"` + stale → `"done"` (clears from UI).

### 2. Stop endpoint must persist to DB

`POST /api/runner/stop` kills the subprocess AND updates `BrowserWorker.status = "stopped"` and bulk-updates in-progress `Run` records to `"failed"`. The UI derives all status from DB.

### 3. Batch deletion cascades: Citations → Results → Runs → WorkerBatch

Delete child rows before parent rows. Collect IDs in Python before issuing bulk deletes (`synchronize_session=False`).

### 4. Browser runner subprocess management

Before debugging runner issues:
```bash
pkill -f "runner.run --platform"
curl -X DELETE http://localhost:8000/api/runner/workers
rm -f runner/flags/*.needs_login runner/flags/*.pause
```

### 5. Datetime filter bug

Never append `" 00:00:00"` to an already-full datetime string. Use `_parse_dt()` helper.
