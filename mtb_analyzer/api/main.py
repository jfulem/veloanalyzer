"""FastAPI application.

Phase 1 deliberately exposes only health checks — it exists so the Fly Machine
has something listening on a port, and so the daily ingest has a process to run
in. The read endpoints land in phase 2.
"""

import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import text

from ..config import console
from ..db import get_engine
from .routes import router

# Same cadence as the GitHub Actions cron this replaces: 12:00 UTC daily.
INGEST_HOUR = int(os.environ.get("INGEST_HOUR", "12"))
# Set to "0" locally or in tests so importing the app never triggers scraping.
RUN_SCHEDULER = os.environ.get("RUN_SCHEDULER", "1") != "0"
CORS_ORIGINS = [
    o.strip() for o in
    os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]


def _run_ingest() -> None:
    """Blocking; APScheduler runs it in a worker thread."""
    from ..ingest import run
    try:
        run()
    except Exception as exc:  # noqa: BLE001 — a failed scrape must not kill the scheduler
        console.print(f"[red]Scheduled ingest failed: {exc}[/red]")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = None
    if RUN_SCHEDULER:
        scheduler = AsyncIOScheduler(timezone="UTC")
        scheduler.add_job(
            _run_ingest,
            CronTrigger(hour=INGEST_HOUR, minute=0),
            id="daily_ingest",
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        console.print(f"[green]Scheduler started — daily ingest at {INGEST_HOUR:02d}:00 UTC[/green]")
    try:
        yield
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)


app = FastAPI(title="VeloAnalyzer API", lifespan=lifespan)

# Neither uvicorn nor Fly's proxy compresses responses, and the race-history
# payload is highly repetitive JSON that gzips to roughly a tenth of its size.
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


app.include_router(router)


@app.get("/health")
def health() -> dict:
    """Liveness only. Deliberately does not touch Postgres: Neon suspends its
    compute after five minutes idle, and a health check that wakes it would
    both burn free-tier compute hours and fail during the resume window."""
    return {"status": "ok"}


@app.get("/health/db")
def health_db() -> dict:
    with get_engine().connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "database": "reachable"}
