import logging
import re
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from coolhurst_booker.models import CourtSlot

logger = logging.getLogger(__name__)

COURT_NUMBER_PATTERN = re.compile(r"^([1-9]|1[0-4])\b")
TIME_RANGE_PATTERN = re.compile(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})")
PRICE_PATTERN = re.compile(r"£\s*[\d.]+")
BOOKING_ONCLICK_PATTERN = re.compile(
    r"sende\s*\(\s*['\"]proc_straks\.asp['\"]\s*,\s*['\"]opret['\"]\s*,\s*['\"]([^'\"]+)['\"]"
)


def parse_available_slots(html: str, date: str | None = None) -> list[CourtSlot]:
    """Parse available court slots from proc_baner.asp HTML."""
    soup = BeautifulSoup(html, "html.parser")
    scraped_at = datetime.now(UTC).isoformat()

    court_headers = _extract_court_headers(soup)
    if not court_headers:
        logger.warning("No court headers found in HTML")

    slots: list[CourtSlot] = []
    available_cells = soup.select("span.banefelt.btn_ledig, span.btn_ledig.banefelt")

    for cell in available_cells:
        court = _court_for_cell(cell, court_headers)
        if not court or not _is_target_court(court):
            continue

        time_text = _extract_time_text(cell)
        if not time_text:
            continue

        match = TIME_RANGE_PATTERN.search(time_text)
        if not match:
            continue

        start_time, end_time = match.groups()
        price = _extract_price(cell)
        booking_token = _extract_booking_token(cell)

        slot_date = date or scraped_at[:10]
        slots.append(
            CourtSlot(
                date=slot_date,
                court=court,
                start_time=start_time,
                end_time=end_time,
                price=price,
                booking_token=booking_token,
                scraped_at=scraped_at,
            )
        )

    return slots


def parse_page(page, date: str | None) -> list[CourtSlot]:
    """Parse available slots from a live Playwright page."""
    scraped_at = datetime.now(UTC).isoformat()
    slot_date = date
    if not slot_date:
        from coolhurst_booker.scraper.browser import read_page_date

        slot_date = read_page_date(page)

    raw_slots = page.evaluate(
        """() => {
            const results = [];
            document.querySelectorAll('.text-center.bane, .bane.text-center').forEach(col => {
                const headEl = col.querySelector('.banehead');
                const court = headEl ? headEl.innerText.trim().replace(/\\s+/g, ' ') : null;
                if (!court) return;

                col.querySelectorAll('.banefelt.btn_ledig, .btn_ledig.banefelt').forEach(cell => {
                    results.push({
                        court,
                        text: (cell.innerText || '').trim().replace(/\\s+/g, ' '),
                        onclick: cell.getAttribute('onclick') || '',
                    });
                });
            });
            return results;
        }"""
    )

    slots: list[CourtSlot] = []
    for item in raw_slots:
        court = item.get("court")
        if not court or not _is_target_court(court):
            continue

        text = item.get("text", "")
        match = TIME_RANGE_PATTERN.search(text)
        if not match:
            continue

        start_time, end_time = match.groups()
        price_match = PRICE_PATTERN.search(text)
        onclick = item.get("onclick", "")
        token_match = BOOKING_ONCLICK_PATTERN.search(onclick)

        slots.append(
            CourtSlot(
                date=slot_date or scraped_at[:10],
                court=court,
                start_time=start_time,
                end_time=end_time,
                price=price_match.group(0) if price_match else None,
                booking_token=token_match.group(1) if token_match else None,
                scraped_at=scraped_at,
            )
        )

    if not slots:
        html = page.content()
        slots = parse_available_slots(html, slot_date)

    return slots


def _extract_court_headers(soup: BeautifulSoup) -> list[str]:
    headers: list[str] = []
    for el in soup.select(".banefelt.banehead, .banehead, th.banehead"):
        text = _normalize_text(el.get_text(" ", strip=True))
        if text:
            headers.append(text)

    if headers:
        return headers

    # Fallback: scan header row cells
    for el in soup.select(".bane thead td, .bane thead th, .baneheadrow .banefelt"):
        text = _normalize_text(el.get_text(" ", strip=True))
        if text and COURT_NUMBER_PATTERN.match(text):
            headers.append(text)

    return headers


def _court_for_cell(cell, court_headers: list[str]) -> str | None:
    # Walk up to column container and use index
    column = cell.find_parent(class_=re.compile(r"bane|column|col", re.I))
    parent_row = cell.find_parent("tr")

    if parent_row:
        cells = parent_row.find_all(["td", "span"], recursive=False)
        if not cells:
            cells = [c for c in parent_row.find_all(["td", "span"]) if "banefelt" in " ".join(c.get("class", []))]
        try:
            idx = cells.index(cell)
            if idx < len(court_headers):
                return court_headers[idx]
        except ValueError:
            pass

    # Alternative: data attributes
    for attr in ("data-bane", "data-court", "data-banenr"):
        if cell.get(attr):
            num = cell[attr]
            for header in court_headers:
                if header.startswith(f"{num} " ) or header.startswith(f"{num}-"):
                    return header

    # Use sibling index among banefelt cells in same row block
    row_parent = cell.find_parent(class_=re.compile(r"bane"))
    if row_parent:
        all_cells = row_parent.select("span.banefelt")
        try:
            idx = all_cells.index(cell)
            if idx < len(court_headers):
                return court_headers[idx]
        except ValueError:
            pass

    return None


def _is_target_court(court: str) -> bool:
    return bool(COURT_NUMBER_PATTERN.match(court.strip()))


def _extract_time_text(cell) -> str:
    padding = cell.select_one(".padding5")
    if padding:
        divs = padding.find_all("div", recursive=False)
        for div in divs:
            text = _normalize_text(div.get_text(" ", strip=True))
            if TIME_RANGE_PATTERN.search(text):
                return text
    text = _normalize_text(cell.get_text(" ", strip=True))
    return text


def _extract_price(cell) -> str | None:
    text = cell.get_text(" ", strip=True)
    match = PRICE_PATTERN.search(text)
    return match.group(0) if match else None


def _extract_booking_token(cell) -> str | None:
    onclick = cell.get("onclick", "")
    match = BOOKING_ONCLICK_PATTERN.search(onclick)
    return match.group(1) if match else None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
