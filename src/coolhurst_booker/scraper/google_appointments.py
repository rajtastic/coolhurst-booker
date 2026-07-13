"""Scrape open slots from a public Google Calendar appointment booking page."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import Page, Response

from coolhurst_booker.config import Settings
from coolhurst_booker.models import PersonSlot
from coolhurst_booker.scraper.browser import browser_session

logger = logging.getLogger(__name__)

LIST_AVAILABLE_SLOTS = "ListAvailableSlots"
DEFAULT_TZ = "Europe/London"
TIME_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*(am|pm)$", re.I)


def _parse_slot_list_payload(body: str) -> list[tuple[int, int]]:
    """Parse ListAvailableSlots body into (unix_start, duration_minutes) pairs."""
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return []

    slots: list[tuple[int, int]] = []

    def walk(node: object) -> None:
        if isinstance(node, list):
            if (
                len(node) >= 2
                and isinstance(node[0], list)
                and len(node[0]) >= 1
                and isinstance(node[0][0], str)
                and node[0][0].isdigit()
                and isinstance(node[1], (int, float))
            ):
                slots.append((int(node[0][0]), int(node[1])))
                return
            for child in node:
                walk(child)

    walk(data)
    return slots


def _to_person_slots(
    raw: list[tuple[int, int]],
    scraped_at: str,
    tz_name: str = DEFAULT_TZ,
    days_ahead: int = 14,
) -> list[PersonSlot]:
    tz = ZoneInfo(tz_name)
    now = datetime.now(tz).date()
    cutoff = now + timedelta(days=days_ahead)
    out: list[PersonSlot] = []
    seen: set[tuple[str, str, str]] = set()

    for start_unix, duration_min in raw:
        start = datetime.fromtimestamp(start_unix, tz=UTC).astimezone(tz)
        end = start + timedelta(minutes=duration_min)
        if start.date() < now or start.date() > cutoff:
            continue
        key = (
            start.strftime("%Y-%m-%d"),
            start.strftime("%H:%M"),
            end.strftime("%H:%M"),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(
            PersonSlot(
                date=key[0],
                start_time=key[1],
                end_time=key[2],
                scraped_at=scraped_at,
            )
        )

    out.sort(key=lambda s: (s.date, s.start_time))
    return out


def _parse_clock(label: str) -> str | None:
    match = TIME_RE.match(label.strip())
    if not match:
        return None
    hour, minute, meridiem = match.groups()
    hour_i = int(hour) % 12
    if meridiem.lower() == "pm":
        hour_i += 12
    return f"{hour_i:02d}:{minute}"


def _dom_fallback_slots(page: Page, scraped_at: str, duration_min: int = 60) -> list[PersonSlot]:
    """Parse the visible day/time strip if RPC capture missed payloads."""
    raw = page.evaluate(
        """() => {
          const out = [];
          const dayCols = [...document.querySelectorAll('[role="list"] > *, .Cf7spc, .qXp4A')];
          // Prefer the horizontal day strip: find elements that contain both weekday labels and time buttons
          const timeButtons = [...document.querySelectorAll('button')].filter(b =>
            /\\d{1,2}:\\d{2}\\s*(am|pm)/i.test((b.innerText || '').trim())
          );
          // Walk up to find date context from nearby headers (e.g. WED 15)
          for (const btn of timeButtons) {
            const time = (btn.innerText || '').trim();
            let dateLabel = '';
            let node = btn.parentElement;
            for (let i = 0; i < 6 && node; i++) {
              const text = (node.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
              // Look for patterns like WED + 15 near this column
              const dowIdx = text.findIndex(t => /^(MON|TUE|WED|THU|FRI|SAT|SUN)$/i.test(t));
              if (dowIdx >= 0 && dowIdx + 1 < text.length && /^\\d{1,2}$/.test(text[dowIdx + 1])) {
                dateLabel = text[dowIdx] + ' ' + text[dowIdx + 1];
                break;
              }
              node = node.parentElement;
            }
            out.push({ time, dateLabel });
          }
          const month = (document.body.innerText.match(
            /(January|February|March|April|May|June|July|August|September|October|November|December)\\s+(\\d{4})/i
          ) || [])[0] || '';
          return { month, items: out };
        }"""
    )

    month = (raw.get("month") or "").strip()
    year = None
    month_name = None
    if month:
        parts = month.split()
        if len(parts) == 2:
            month_name, year = parts[0], parts[1]

    slots: list[PersonSlot] = []
    seen: set[tuple[str, str]] = set()
    now_year = datetime.now().year

    for item in raw.get("items") or []:
        start_time = _parse_clock(item.get("time") or "")
        if not start_time:
            continue
        date_label = (item.get("dateLabel") or "").strip()
        day_match = re.search(r"(\d{1,2})$", date_label)
        if not day_match or not month_name:
            continue
        day = int(day_match.group(1))
        try:
            parsed = datetime.strptime(
                f"{day} {month_name} {year or now_year}", "%d %B %Y"
            )
        except ValueError:
            continue
        date_str = parsed.strftime("%Y-%m-%d")
        key = (date_str, start_time)
        if key in seen:
            continue
        seen.add(key)
        end_dt = datetime.strptime(start_time, "%H:%M") + timedelta(minutes=duration_min)
        slots.append(
            PersonSlot(
                date=date_str,
                start_time=start_time,
                end_time=end_dt.strftime("%H:%M"),
                scraped_at=scraped_at,
            )
        )

    return slots


def scrape_google_appointments(page: Page, settings: Settings) -> list[PersonSlot]:
    if not settings.google_appointment_url:
        logger.warning("GOOGLE_APPOINTMENT_URL not set; skipping person availability scrape")
        return []

    captured: list[str] = []

    def on_response(response: Response) -> None:
        if LIST_AVAILABLE_SLOTS not in response.url:
            return
        try:
            if response.status == 200:
                captured.append(response.text())
        except Exception:
            logger.debug("Could not read ListAvailableSlots body", exc_info=True)

    page.on("response", on_response)
    scraped_at = datetime.now(UTC).isoformat()

    page.goto(settings.google_appointment_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(1500)

    # Landing pages list appointment types — open the first card.
    # Schedule URLs (.../appointments/schedules/...) already show the calendar + slots.
    is_schedule_page = "/appointments/schedules/" in settings.google_appointment_url
    if not is_schedule_page:
        card = page.locator("a.I1TEVb, a:has-text(\"Availability\")").first
        try:
            if card.is_visible(timeout=3000):
                card.click()
                page.wait_for_timeout(2500)
        except Exception:
            logger.debug("No appointment-type card to click; assuming schedule page")

    # Wait briefly for RPC; also try next-day navigation to force loads if needed.
    deadline = datetime.now(UTC) + timedelta(seconds=12)
    while not captured and datetime.now(UTC) < deadline:
        page.wait_for_timeout(500)

    if not captured:
        next_btn = page.get_by_role("button", name=re.compile("Next day", re.I))
        try:
            if next_btn.count():
                next_btn.first.click()
                page.wait_for_timeout(2000)
        except Exception:
            pass

    raw_slots: list[tuple[int, int]] = []
    for body in captured:
        raw_slots.extend(_parse_slot_list_payload(body))

    slots = _to_person_slots(
        raw_slots,
        scraped_at=scraped_at,
        days_ahead=settings.coolhurst_days_ahead,
    )

    if not slots:
        logger.info("ListAvailableSlots empty/missed; trying DOM fallback")
        slots = _dom_fallback_slots(page, scraped_at=scraped_at)

    logger.info("Google appointments scrape found %d person slots", len(slots))
    return slots


def run_google_appointment_scrape(settings: Settings) -> list[PersonSlot]:
    with browser_session(settings) as (_, __, ___, page):
        return scrape_google_appointments(page, settings)
