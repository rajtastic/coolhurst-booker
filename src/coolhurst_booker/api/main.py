import logging
import os
import threading
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from coolhurst_booker.config import get_settings
from coolhurst_booker.db.repository import get_repository
from coolhurst_booker.jobs.scrape_job import run_scrape
from coolhurst_booker.scraper.browser import force_kill_playwright_browsers

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

_scrape_lock = threading.Lock()
_scheduler: BackgroundScheduler | None = None


def _abandon_running(reason: str) -> None:
    try:
        repo = get_repository()
        n = repo.abandon_running_scrapes(
            finished_at=datetime.now(UTC).isoformat(),
            error=reason,
        )
        if n:
            logger.warning("Abandoned %d running scrape_runs (%s)", n, reason)
    except Exception:
        logger.exception("Failed to abandon running scrape_runs")


def _scheduled_scrape() -> None:
    if not _scrape_lock.acquire(blocking=False):
        logger.info("Skipping scrape: previous run still in progress")
        return

    settings = get_settings()
    timeout = settings.scrape_timeout_seconds
    done = threading.Event()
    errors: list[BaseException] = []

    def _worker() -> None:
        try:
            run_scrape()
        except BaseException as exc:  # noqa: BLE001 — capture for outer logger
            errors.append(exc)
        finally:
            done.set()

    try:
        worker = threading.Thread(target=_worker, name="scrape-worker", daemon=True)
        worker.start()
        if not done.wait(timeout):
            logger.error(
                "Scrape exceeded %ss; abandoning worker and killing Playwright browsers",
                timeout,
            )
            force_kill_playwright_browsers()
            _abandon_running("abandoned: scrape timeout")
            # Brief grace for the worker to notice killed browsers and exit.
            done.wait(2)
            return
        if errors:
            logger.exception("Scheduled scrape failed", exc_info=errors[0])
    finally:
        _scrape_lock.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    settings = get_settings()

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        _abandon_running("abandoned: process restart")
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
        logger.info(
            "Scheduler started (interval=%ss, timeout=%ss)",
            settings.scrape_interval_seconds,
            settings.scrape_timeout_seconds,
        )
        threading.Thread(target=_scheduled_scrape, daemon=True).start()

    yield

    if _scheduler:
        _scheduler.shutdown(wait=False)


app = FastAPI(
    title="Coolhurst Booker PoC",
    description="Court and calendar availability scraper API",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/config")
def public_config() -> dict:
    settings = get_settings()
    return {
        "booker_name": settings.booker_name,
        "appointment_url": settings.google_appointment_url,
        "coolhurst_book_url": settings.coolhurst_book_url,
        "scrape_interval_seconds": settings.scrape_interval_seconds,
        "scrape_timeout_seconds": settings.scrape_timeout_seconds,
        "health_warn_after_seconds": settings.health_warn_after_seconds,
        "health_stale_after_seconds": settings.health_stale_after_seconds,
        "show_public_court_calendar_link": settings.show_public_court_calendar_link,
    }


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _scraper_health(
    source: str,
    *,
    last_ok: dict | None,
    latest: dict | None,
    stale_after_seconds: int,
    now: datetime,
) -> dict:
    label = "coolhurst" if source == "coolhurst" else "google"
    last_success_at = last_ok.get("finished_at") if last_ok else None
    finished = _parse_iso(last_success_at)
    age_seconds: int | None = None
    if finished is not None:
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=UTC)
        age_seconds = max(0, int((now - finished).total_seconds()))

    last_error = None
    if latest and latest.get("status") == "error":
        last_error = latest.get("error") or "unknown error"

    if last_ok is None:
        message = f"{label}: never succeeded"
        if last_error:
            message = f"{label}: never succeeded (last error: {last_error})"
        return {
            "ok": False,
            "last_success_at": None,
            "age_seconds": None,
            "last_error": last_error,
            "message": message,
        }

    assert age_seconds is not None
    if age_seconds > stale_after_seconds:
        message = f"{label}: last success {age_seconds}s ago (stale >{stale_after_seconds}s)"
        if last_error and latest and latest.get("finished_at") != last_success_at:
            message = f"{message}; last error: {last_error}"
        return {
            "ok": False,
            "last_success_at": last_success_at,
            "age_seconds": age_seconds,
            "last_error": last_error,
            "message": message,
        }

    return {
        "ok": True,
        "last_success_at": last_success_at,
        "age_seconds": age_seconds,
        "last_error": last_error,
        "message": f"{label}: ok ({age_seconds}s ago)",
    }


@app.get("/health")
def health():
    settings = get_settings()
    repo = get_repository()
    now = datetime.now(UTC)
    stale_after = settings.health_stale_after_seconds

    last_coolhurst = repo.get_last_scrape(source="coolhurst")
    last_google = repo.get_last_scrape(source="google")
    scrapers = {
        "coolhurst": _scraper_health(
            "coolhurst",
            last_ok=last_coolhurst,
            latest=repo.get_latest_scrape_run(source="coolhurst"),
            stale_after_seconds=stale_after,
            now=now,
        ),
        "google": _scraper_health(
            "google",
            last_ok=last_google,
            latest=repo.get_latest_scrape_run(source="google"),
            stale_after_seconds=stale_after,
            now=now,
        ),
    }
    all_ok = all(s["ok"] for s in scrapers.values())
    status = "ok" if all_ok else "degraded"
    message = (
        "Both scrapers healthy"
        if all_ok
        else "; ".join(s["message"] for s in scrapers.values() if not s["ok"])
    )
    body = {
        "status": status,
        "message": message,
        "scrapers": scrapers,
        "last_scrape": last_coolhurst,
        "last_google_scrape": last_google,
    }
    return JSONResponse(content=body, status_code=200 if all_ok else 503)


@app.get("/slots")
def list_slots(
    date: str | None = Query(None, description="Filter by date YYYY-MM-DD"),
    court: str | None = Query(None, description="Filter by court number prefix, e.g. 3"),
) -> dict:
    repo = get_repository()
    slots = repo.get_slots(date=date, court=court)
    person_slots = repo.get_person_slots(date=date)
    return {"count": len(slots), "slots": slots, "person_slots": person_slots}


@app.get("/person-slots")
def list_person_slots(
    date: str | None = Query(None, description="Filter by date YYYY-MM-DD"),
) -> dict:
    repo = get_repository()
    slots = repo.get_person_slots(date=date)
    return {"count": len(slots), "slots": slots}


@app.get("/slots/summary")
def slots_summary() -> dict:
    repo = get_repository()
    summary = repo.get_summary()
    return {"days": len(summary), "summary": summary}
