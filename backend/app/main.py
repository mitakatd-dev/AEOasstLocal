from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from app.database import init_db
from app.routers import prompts, runs, settings, experiments, seed, stats, trends, events, extension, runner, accounts, costs

app = FastAPI(title="AEO Insights — Local")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(prompts.router)
app.include_router(runs.router)
app.include_router(settings.router)
app.include_router(experiments.router)
app.include_router(seed.router)
app.include_router(stats.router)
app.include_router(trends.router)
app.include_router(events.router)
app.include_router(extension.router)
app.include_router(runner.router)
app.include_router(accounts.router)
app.include_router(costs.router)


@app.on_event("startup")
def on_startup():
    init_db()
    from app.database import SessionLocal
    from app.routers.settings import load_settings_into_env
    with SessionLocal() as db:
        load_settings_into_env(db)


@app.get("/api/health")
def health():
    return {"status": "ok"}
