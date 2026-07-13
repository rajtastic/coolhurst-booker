import logging
import re
from contextlib import contextmanager
from typing import Generator

from playwright.sync_api import Browser, BrowserContext, Page, Playwright, sync_playwright

from coolhurst_booker.config import Settings

logger = logging.getLogger(__name__)

COOKIE_ACCEPT_SELECTORS = [
    ".cc_btn_accept_all",
    "button.cc_btn_accept_all",
    "[data-cc-action='accept']",
    "button:has-text('Accept')",
    "button:has-text('Accept all')",
]


@contextmanager
def browser_session(settings: Settings) -> Generator[tuple[Playwright, Browser, BrowserContext, Page], None, None]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=settings.playwright_headless)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        try:
            yield playwright, browser, context, page
        finally:
            context.close()
            browser.close()


def dismiss_cookie_banner(page: Page) -> None:
    for selector in COOKIE_ACCEPT_SELECTORS:
        try:
            button = page.locator(selector).first
            if button.is_visible(timeout=2000):
                button.click()
                page.wait_for_timeout(500)
                logger.debug("Dismissed cookie banner via %s", selector)
                return
        except Exception:
            continue


def wait_for_grid(page: Page, timeout: int = 30000) -> None:
    page.wait_for_selector(".bane, .banefelt, .baneoversigt", timeout=timeout)


def read_page_date(page: Page) -> str | None:
    """Return date as YYYY-MM-DD from page text."""
    body_text = page.locator("body").inner_text()

    dashed = re.search(r"\b(\d{2})-(\d{2})-(\d{4})\b", body_text)
    if dashed:
        day, month, year = dashed.groups()
        return f"{year}-{month}-{day}"

    dotted = re.search(
        r"\b(\d{1,2})\.\s*(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})\b",
        body_text,
        re.I,
    )
    if dotted:
        from datetime import datetime

        day, month_name, year = dotted.groups()
        parsed = datetime.strptime(f"{day} {month_name} {year}", "%d %B %Y")
        return parsed.strftime("%Y-%m-%d")

    return None
