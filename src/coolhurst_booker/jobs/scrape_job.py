import argparse
import logging
import sys
from datetime import UTC, datetime

from coolhurst_booker.config import get_settings
from coolhurst_booker.db.repository import get_repository
from coolhurst_booker.scraper.auth import login
from coolhurst_booker.scraper.browser import browser_session, dismiss_cookie_banner, wait_for_grid
from coolhurst_booker.scraper.navigation import scrape_days, select_booking_area
from coolhurst_booker.scraper.parser import parse_page

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def run_scrape(once: bool = False) -> int:
    settings = get_settings()
    repo = get_repository(settings)
    result_started = datetime.now(UTC).isoformat()
    run_id = repo.start_scrape_run(result_started)

    try:
        with browser_session(settings) as (_, __, ___, page):
            page.goto(settings.proc_baner_url, wait_until="domcontentloaded")
            dismiss_cookie_banner(page)
            wait_for_grid(page)

            login(page, settings)
            select_booking_area(page, settings)

            slots = scrape_days(page, settings, parse_page)
            dates = sorted({s.date for s in slots if s.date})

            repo.upsert_slots(slots, dates)
            finished = datetime.now(UTC).isoformat()
            repo.finish_scrape_run(
                run_id=run_id,
                finished_at=finished,
                days_scraped=settings.coolhurst_days_ahead,
                slots_found=len(slots),
                status="ok",
            )

            logger.info(
                "Scrape complete: %d slots across %d dates (%d days scanned)",
                len(slots),
                len(dates),
                settings.coolhurst_days_ahead,
            )
            if once:
                print(f"Found {len(slots)} available slots")
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
        logger.exception("Scrape failed")
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Coolhurst court availability scraper")
    parser.add_argument("--once", action="store_true", help="Run a single scrape and exit")
    args = parser.parse_args()

    try:
        run_scrape(once=args.once)
    except Exception:
        sys.exit(1)


if __name__ == "__main__":
    main()
