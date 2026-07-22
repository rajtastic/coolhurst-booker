import logging
import os
import re
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path
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

LAUNCH_TIMEOUT_MS = 30_000
DEFAULT_TIMEOUT_MS = 30_000

_TMP_PROFILE_GLOBS = (
    "playwright_chromiumdev_profile-*",
    "playwright_firefoxdev_profile-*",
    "playwright_webkitdev_profile-*",
)


def reap_child_zombies() -> int:
    """Reap any exited child processes so they cannot accumulate as zombies."""
    reaped = 0
    while True:
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            break
        if pid == 0:
            break
        reaped += 1
    if reaped:
        logger.info("Reaped %d zombie child process(es)", reaped)
    return reaped


def cleanup_playwright_state() -> None:
    """Remove stale Playwright profile directories left under /tmp."""
    tmp = Path("/tmp")
    removed = 0
    for pattern in _TMP_PROFILE_GLOBS:
        for path in tmp.glob(pattern):
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                logger.debug("Could not remove %s", path, exc_info=True)
    if removed:
        logger.info("Removed %d stale Playwright temp path(s)", removed)


def force_kill_playwright_browsers() -> None:
    """Best-effort kill of Chromium/Playwright driver children, then reap zombies."""
    killed_any = False
    for pattern in (
        "chrome-headless-shell",
        "chromium_headless_shell",
        "playwright/driver/node",
        "ms-playwright",
    ):
        try:
            result = subprocess.run(
                ["pkill", "-9", "-f", pattern],
                check=False,
                capture_output=True,
                timeout=5,
            )
            if result.returncode == 0:
                killed_any = True
        except Exception:
            logger.debug("pkill %s failed", pattern, exc_info=True)
    if killed_any:
        logger.warning("Force-killed Playwright/Chromium process(es)")
    reap_child_zombies()
    cleanup_playwright_state()


@contextmanager
def browser_session(settings: Settings) -> Generator[tuple[Playwright, Browser, BrowserContext, Page], None, None]:
    reap_child_zombies()
    cleanup_playwright_state()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=settings.playwright_headless,
            timeout=LAUNCH_TIMEOUT_MS,
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        page.set_default_navigation_timeout(DEFAULT_TIMEOUT_MS)
        try:
            yield playwright, browser, context, page
        finally:
            for closer, label in ((context.close, "context"), (browser.close, "browser")):
                try:
                    closer()
                except Exception:
                    logger.warning("Failed to close Playwright %s", label, exc_info=True)
            reap_child_zombies()


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
