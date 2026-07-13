import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from coolhurst_booker.config import get_settings
from coolhurst_booker.db.repository import get_repository
from coolhurst_booker.jobs.scrape_job import run_scrape

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_scrape_lock = threading.Lock()
_scheduler: BackgroundScheduler | None = None


def _scheduled_scrape() -> None:
    if not _scrape_lock.acquire(blocking=False):
        logger.info("Skipping scrape: previous run still in progress")
        return
    try:
        run_scrape()
    except Exception:
        logger.exception("Scheduled scrape failed")
    finally:
        _scrape_lock.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    settings = get_settings()

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        _scheduler = BackgroundScheduler()
        _scheduler.add_job(
            _scheduled_scrape,
            "interval",
            seconds=settings.scrape_interval_seconds,
            id="court_scrape",
            max_instances=1,
            coalesce=True,
        )
        _scheduler.start()
        logger.info("Scheduler started (interval=%ss)", settings.scrape_interval_seconds)
        threading.Thread(target=_scheduled_scrape, daemon=True).start()

    yield

    if _scheduler:
        _scheduler.shutdown(wait=False)


app = FastAPI(
    title="Coolhurst Booker PoC",
    description="Court availability scraper API",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health")
def health() -> dict:
    repo = get_repository()
    last = repo.get_last_scrape()
    return {
        "status": "ok",
        "last_scrape": last,
    }


@app.get("/slots")
def list_slots(
    date: str | None = Query(None, description="Filter by date YYYY-MM-DD"),
    court: str | None = Query(None, description="Filter by court number prefix, e.g. 3"),
) -> dict:
    repo = get_repository()
    slots = repo.get_slots(date=date, court=court)
    return {"count": len(slots), "slots": slots}


@app.get("/slots/summary")
def slots_summary() -> dict:
    repo = get_repository()
    summary = repo.get_summary()
    return {"days": len(summary), "summary": summary}


@app.post("/scrape")
def trigger_scrape() -> dict:
    if not _scrape_lock.acquire(blocking=False):
        return {"status": "skipped", "message": "Scrape already in progress"}

    def _run() -> None:
        try:
            count = run_scrape()
            logger.info("Manual scrape found %d slots", count)
        except Exception:
            logger.exception("Manual scrape failed")
        finally:
            _scrape_lock.release()

    threading.Thread(target=_run, daemon=True).start()
    return {"status": "started"}
