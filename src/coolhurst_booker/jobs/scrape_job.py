import argparse
import logging
import sys
import time
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from coolhurst_booker.config import get_settings
from coolhurst_booker.db.repository import get_repository
from coolhurst_booker.scraper.auth import login
from coolhurst_booker.scraper.browser import browser_session, dismiss_cookie_banner, wait_for_grid
from coolhurst_booker.scraper.google_appointments import scrape_google_appointments
from coolhurst_booker.scraper.navigation import scrape_days, select_booking_area
from coolhurst_booker.scraper.parser import parse_page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

LONDON = ZoneInfo("Europe/London")
MAX_ATTEMPTS = 2
RETRY_BACKOFF_SECONDS = 2.0


def _today_london() -> str:
    return datetime.now(LONDON).date().isoformat()


def _is_retryable(exc: BaseException) -> bool:
    msg = str(exc).lower()
    retry_markers = (
        "timeout",
        "err_aborted",
        "err_network",
        "err_connection",
        "err_name_not_resolved",
        "net::",
        "navigation",
        "frame was detached",
        "target closed",
        "browser has been closed",
    )
    return any(m in msg for m in retry_markers)


def _with_retries(label: str, fn, *, once: bool = False):
    last_exc: BaseException | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt >= MAX_ATTEMPTS or not _is_retryable(exc):
                raise
            logger.warning(
                "%s attempt %d/%d failed (%s); retrying in %.0fs",
                label,
                attempt,
                MAX_ATTEMPTS,
                exc,
                RETRY_BACKOFF_SECONDS,
            )
            time.sleep(RETRY_BACKOFF_SECONDS)
    assert last_exc is not None
    raise last_exc


def _run_coolhurst_once(once: bool = False) -> int:
    settings = get_settings()
    repo = get_repository(settings)
    result_started = datetime.now(UTC).isoformat()
    run_id = repo.start_scrape_run(result_started, source="coolhurst")

    try:
        with browser_session(settings) as (_, __, ___, page):
            page.goto(settings.proc_baner_url, wait_until="domcontentloaded")
            dismiss_cookie_banner(page)
            wait_for_grid(page)

            login(page, settings)
            select_booking_area(page, settings)

            slots = scrape_days(page, settings, parse_page)
            dates = sorted({s.date for s in slots if s.date})

            repo.upsert_slots(slots, dates, prune_before=_today_london())
            finished = datetime.now(UTC).isoformat()
            repo.finish_scrape_run(
                run_id=run_id,
                finished_at=finished,
                days_scraped=settings.coolhurst_days_ahead,
                slots_found=len(slots),
                status="ok",
            )

            logger.info(
                "Coolhurst scrape complete: %d slots across %d dates (%d days scanned)",
                len(slots),
                len(dates),
                settings.coolhurst_days_ahead,
            )
            if once:
                print(f"Found {len(slots)} available court slots")
                for slot in slots[:10]:
                    print(f"  {slot.date} {slot.court} {slot.start_time}-{slot.end_time} {slot.price or ''}")
                if len(slots) > 10:
                    print(f"  ... and {len(slots) - 10} more")
            return len(slots)

    except Exception as exc:
        finished = datetime.now(UTC).isoformat()
        repo.finish_scrape_run(
            run_id=run_id,
            finished_at=finished,
            days_scraped=0,
            slots_found=0,
            status="error",
            error=str(exc),
        )
        logger.exception("Coolhurst scrape failed")
        raise


def run_coolhurst_scrape(once: bool = False) -> int:
    return _with_retries("Coolhurst", lambda: _run_coolhurst_once(once=once), once=once)


def _run_google_once(once: bool = False) -> int:
    settings = get_settings()
    repo = get_repository(settings)
    result_started = datetime.now(UTC).isoformat()
    run_id = repo.start_scrape_run(result_started, source="google")

    try:
        with browser_session(settings) as (_, __, ___, page):
            slots = scrape_google_appointments(page, settings)
            previous_count = repo.count_person_slots()
            if not slots and previous_count > 0:
                finished = datetime.now(UTC).isoformat()
                error = (
                    f"Google scrape returned 0 slots but {previous_count} existing "
                    "person slots were preserved"
                )
                repo.finish_scrape_run(
                    run_id=run_id,
                    finished_at=finished,
                    days_scraped=settings.coolhurst_days_ahead,
                    slots_found=0,
                    status="error",
                    error=error,
                )
                logger.warning(error)
                if once:
                    print(f"Preserved {previous_count} existing person slots (empty scrape)")
                return previous_count

            repo.replace_person_slots(slots)
            finished = datetime.now(UTC).isoformat()
            repo.finish_scrape_run(
                run_id=run_id,
                finished_at=finished,
                days_scraped=settings.coolhurst_days_ahead,
                slots_found=len(slots),
                status="ok",
            )
            logger.info("Google appointment scrape complete: %d person slots", len(slots))
            if once:
                print(f"Found {len(slots)} person availability slots")
                for slot in slots[:10]:
                    print(f"  {slot.date} {slot.start_time}-{slot.end_time}")
                if len(slots) > 10:
                    print(f"  ... and {len(slots) - 10} more")
            return len(slots)
    except Exception as exc:
        finished = datetime.now(UTC).isoformat()
        repo.finish_scrape_run(
            run_id=run_id,
            finished_at=finished,
            days_scraped=0,
            slots_found=0,
            status="error",
            error=str(exc),
        )
        logger.exception("Google appointment scrape failed")
        raise


def run_google_scrape(once: bool = False) -> int:
    return _with_retries("Google", lambda: _run_google_once(once=once), once=once)


def run_scrape(once: bool = False) -> dict[str, int | None]:
    """Run Coolhurst and Google scrapes independently; one failure does not block the other."""
    results: dict[str, int | None] = {"coolhurst": None, "google": None}

    try:
        results["coolhurst"] = run_coolhurst_scrape(once=once)
    except Exception:
        logger.exception("Coolhurst scrape failed during combined run")

    try:
        results["google"] = run_google_scrape(once=once)
    except Exception:
        logger.exception("Google scrape failed during combined run")

    if results["coolhurst"] is None and results["google"] is None:
        raise RuntimeError("Both Coolhurst and Google scrapes failed")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Coolhurst + Google appointment availability scraper")
    parser.add_argument("--once", action="store_true", help="Run a single scrape and exit")
    args = parser.parse_args()

    try:
        run_scrape(once=args.once)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
