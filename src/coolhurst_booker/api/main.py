import logging
import os
import signal
import subprocess
import sys
import tempfile
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
from coolhurst_booker.scraper.browser import force_kill_playwright_browsers, reap_child_zombies

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


def _kill_process_group(proc: subprocess.Popen) -> None:
    if proc.pid is None:
        return
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        logger.warning("Scrape subprocess %s did not exit after killpg", proc.pid)
    force_kill_playwright_browsers()
    reap_child_zombies()


def _log_scrape_tail(log_path: Path, *, limit: int = 40) -> None:
    try:
        if not log_path.is_file():
            return
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-limit:]:
            if line.strip():
                logger.info("[scrape] %s", line)
    except OSError:
        logger.debug("Could not read scrape log %s", log_path, exc_info=True)


def _scheduled_scrape() -> None:
    """Run scrapes in an isolated subprocess so Chromium children are always reaped."""
    if not _scrape_lock.acquire(blocking=False):
        logger.info("Skipping scrape: previous run still in progress")
        return

    settings = get_settings()
    timeout = settings.scrape_timeout_seconds
    cmd = [sys.executable, "-m", "coolhurst_booker.jobs.scrape_job", "--once"]
    proc: subprocess.Popen | None = None
    log_path: Path | None = None
    log_fh = None

    try:
        log_fh = tempfile.NamedTemporaryFile(
            prefix="coolhurst-scrape-",
            suffix=".log",
            delete=False,
            mode="w",
            encoding="utf-8",
        )
        log_path = Path(log_fh.name)
        proc = subprocess.Popen(
            cmd,
            start_new_session=True,
            stdout=log_fh,
            stderr=subprocess.STDOUT,
            text=True,
        )
        # Parent no longer writes; child keeps the fd. Close our handle so wait/unlink is clean.
        log_fh.close()
        log_fh = None
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            logger.error(
                "Scrape subprocess exceeded %ss; killing process group %s",
                timeout,
                proc.pid,
            )
            _kill_process_group(proc)
            _abandon_running("abandoned: scrape timeout")
            return

        if proc.returncode and proc.returncode != 0:
            logger.error("Scrape subprocess exited with code %s", proc.returncode)
    except Exception:
        logger.exception("Scheduled scrape subprocess failed")
        if proc is not None and proc.poll() is None:
            _kill_process_group(proc)
            _abandon_running("abandoned: scrape subprocess error")
    finally:
        if log_fh is not None:
            try:
                log_fh.close()
            except OSError:
                pass
        if log_path is not None:
            _log_scrape_tail(log_path)
            try:
                log_path.unlink(missing_ok=True)
            except OSError:
                logger.debug("Could not delete scrape log %s", log_path, exc_info=True)
        reap_child_zombies()
        _scrape_lock.release()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _scheduler
    settings = get_settings()

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        _abandon_running("abandoned: process restart")
        force_kill_playwright_browsers()
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
            "Scheduler started (interval=%ss, timeout=%ss, mode=subprocess)",
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
