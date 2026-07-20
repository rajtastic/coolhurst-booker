import logging
import re

from playwright.sync_api import Page

from coolhurst_booker.config import Settings
from coolhurst_booker.scraper.browser import read_page_date, wait_for_grid

logger = logging.getLogger(__name__)

COURT_NUMBER_PATTERN = re.compile(r"^([1-9]|1[0-4])\b")


def select_booking_area(page: Page, settings: Settings) -> None:
    area_name = settings.coolhurst_booking_area
    logger.info("Selecting booking area: %s", area_name)

    area_select = page.locator("#soeg_omraede")
    if area_select.count() > 0:
        area_select.select_option(label=area_name)
        page.wait_for_timeout(2500)
        wait_for_grid(page)
        if _area_selected(page, area_name):
            return

    # Fallback: generic select
    select = page.locator("select[name='soeg_omraede'], select").first
    if select.count() > 0:
        try:
            select.select_option(label=area_name)
            page.wait_for_timeout(2500)
            wait_for_grid(page)
            if _area_selected(page, area_name):
                return
        except Exception as exc:
            logger.debug("Select dropdown failed: %s", exc)

    raise RuntimeError(f"Failed to select booking area '{area_name}'")


def _area_selected(page: Page, area_name: str) -> bool:
    body = page.locator("body").inner_text()
    if area_name.lower() in body.lower():
        return True
    # Outdoor tennis courts have distinctive headers
    if area_name == "Outdoor Tennis":
        return bool(re.search(r"\b1\s*-\s*Clay\b", body, re.I))
    return False


def advance_one_day(page: Page) -> str | None:
    """Click forward one day and return new date as YYYY-MM-DD."""
    before = read_page_date(page)

    forward_selectors = [
        "[onclick*=\"dagfrem\"]",
        ".daypaging [onclick*=\"dagfrem\"]",
        ".daypaging span:has-text('1 day')",
    ]

    def _click_forward() -> None:
        for selector in forward_selectors:
            try:
                target = page.locator(selector).last
                if target.count() > 0 and target.is_visible(timeout=2000):
                    target.click()
                    return
            except Exception:
                continue
        raise RuntimeError("Could not find '1 day' forward navigation control")

    _click_forward()
    page.wait_for_timeout(2000)
    try:
        wait_for_grid(page)
    except Exception:
        logger.warning("Grid wait failed after day advance; retrying forward click once")
        _click_forward()
        page.wait_for_timeout(2000)
        wait_for_grid(page)

    after = read_page_date(page)
    if after and before and after == before:
        page.wait_for_timeout(2000)
        after = read_page_date(page)

    logger.debug("Advanced date from %s to %s", before, after)
    return after


def scrape_days(page: Page, settings: Settings, parse_fn) -> list:
    """Navigate through days and collect parsed slots."""
    all_slots = []
    days = settings.coolhurst_days_ahead

    for day_offset in range(days):
        current_date = read_page_date(page)
        logger.info("Scraping day %d/%d (%s)", day_offset + 1, days, current_date)

        day_slots = parse_fn(page, current_date)
        all_slots.extend(day_slots)

        if day_offset < days - 1:
            advance_one_day(page)

    return all_slots
