import logging
import re

from playwright.sync_api import Page

from coolhurst_booker.config import Settings

logger = logging.getLogger(__name__)


def login(page: Page, settings: Settings) -> None:
    if not settings.coolhurst_username or not settings.coolhurst_password:
        raise ValueError("COOLHURST_USERNAME and COOLHURST_PASSWORD must be set")

    if "proc_baner.asp" not in page.url:
        page.goto(settings.proc_baner_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

    response = page.context.request.post(
        settings.ajax_url,
        form={
            "funktion": "login",
            "value1": settings.coolhurst_username,
            "value2": settings.coolhurst_password,
        },
        headers={"Referer": settings.proc_baner_url},
    )
    logger.info("Login AJAX status: %s", response.status)

    if response.status != 200:
        raise RuntimeError(f"Login request failed with HTTP {response.status}")

    page.goto(settings.proc_baner_url, wait_until="domcontentloaded")
    page.wait_for_timeout(1500)

    if _is_two_factor_required(page):
        raise RuntimeError(
            "Two-factor authentication required. Complete 2FA manually or disable it for the PoC account."
        )

    if not _has_session_cookie(page):
        raise RuntimeError("Login failed: no session cookie received")

    if not is_logged_in(page):
        logger.info(
            "Login POST succeeded (session cookie set). "
            "ClubSolution may not expose logged-in UI markers in headless mode."
        )


def is_logged_in(page: Page) -> bool:
    if page.locator("#tofaktorkode").is_visible(timeout=500):
        return False

    if not _has_session_cookie(page):
        return False

    if page.locator("a[href*='logout'], a:has-text('Log out'), a:has-text('Logout')").count() > 0:
        return True

    if page.locator(".navbar, nav").get_by_text(re.compile(r"[A-Z][a-z]+\s+[A-Z]\.")).count() > 0:
        return True

    html = page.content().lower()
    if "log out" in html or "logout" in html:
        return True

    return False


def _has_session_cookie(page: Page) -> bool:
    return any(c["name"] == "session" and c["value"] for c in page.context.cookies())


def _is_two_factor_required(page: Page) -> bool:
    try:
        return page.locator("#tofaktorkode, #tofaktorgensend").first.is_visible(timeout=1000)
    except Exception:
        return False
