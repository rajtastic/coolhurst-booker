"""Scrape open slots from a public Google Calendar appointment booking page."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
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
JUMP_BOOKABLE_RE = re.compile(r"Jump to the next bookable", re.I)
NEXT_DAY_RE = re.compile(r"^Next day$", re.I)
NEXT_MONTH_RE = re.compile(r"^Next month$", re.I)
SCHEDULE_UI_MARKERS = (
    "Select an appointment time",
    "appointment scheduling",
    "No availability during these days",
    "Jump to the next bookable",
)


@dataclass
class GoogleAppointmentResult:
    """Outcome of a Google appointment page scrape."""

    slots: list[PersonSlot] = field(default_factory=list)
    rpc_captured: bool = False
    page_ok: bool = False
    note: str = ""

    @property
    def trusted(self) -> bool:
        """True when empty/non-empty results are safe to persist."""
        return self.rpc_captured or self.page_ok


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
          const timeButtons = [...document.querySelectorAll('button')].filter(b =>
            /\\d{1,2}:\\d{2}\\s*(am|pm)/i.test((b.innerText || '').trim())
          );
          for (const btn of timeButtons) {
            const time = (btn.innerText || '').trim();
            let dateLabel = '';
            let node = btn.parentElement;
            for (let i = 0; i < 6 && node; i++) {
              const text = (node.innerText || '').split('\\n').map(s => s.trim()).filter(Boolean);
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


def _page_looks_like_schedule(page: Page) -> bool:
    try:
        text = page.locator("body").inner_text(timeout=5000)
    except Exception:
        return False
    return any(marker.lower() in text.lower() for marker in SCHEDULE_UI_MARKERS)


def _click_first(page: Page, pattern: re.Pattern[str]) -> bool:
    btn = page.get_by_role("button", name=pattern)
    try:
        if btn.count() == 0:
            return False
        btn.first.click(timeout=3000)
        return True
    except Exception:
        logger.debug("Could not click button matching %s", pattern.pattern, exc_info=True)
        return False


def _max_slot_date(raw: list[tuple[int, int]], tz_name: str = DEFAULT_TZ):
    if not raw:
        return None
    tz = ZoneInfo(tz_name)
    latest = max(raw, key=lambda pair: pair[0])
    return datetime.fromtimestamp(latest[0], tz=UTC).astimezone(tz).date()


def _log_empty_capture(bodies: list[str], urls: list[str]) -> None:
    if not bodies and not urls:
        logger.warning("Google ListAvailableSlots: no responses captured")
        return
    for idx, body in enumerate(bodies[:3]):
        url = urls[idx] if idx < len(urls) else "?"
        logger.info(
            "Google ListAvailableSlots[%d] url=%s len=%d preview=%r",
            idx,
            url[:160],
            len(body),
            body[:240],
        )


def scrape_google_appointments(page: Page, settings: Settings) -> GoogleAppointmentResult:
    if not settings.google_appointment_url:
        logger.warning("GOOGLE_APPOINTMENT_URL not set; skipping person availability scrape")
        return GoogleAppointmentResult(note="GOOGLE_APPOINTMENT_URL not set")

    captured: list[str] = []
    captured_urls: list[str] = []
    days_ahead = settings.coolhurst_days_ahead
    tz = ZoneInfo(DEFAULT_TZ)
    cutoff = datetime.now(tz).date() + timedelta(days=days_ahead)

    def on_response(response: Response) -> None:
        if LIST_AVAILABLE_SLOTS not in response.url:
            return
        try:
            if response.status == 200:
                body = response.text()
                captured.append(body)
                captured_urls.append(response.url)
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

    # Wait briefly for the initial RPC.
    deadline = datetime.now(UTC) + timedelta(seconds=12)
    while not captured and datetime.now(UTC) < deadline:
        page.wait_for_timeout(500)

    page_ok = _page_looks_like_schedule(page)

    # When the visible window has no times, Google offers a jump control that
    # advances to the next bookable range (and fires a fresh ListAvailableSlots).
    if _click_first(page, JUMP_BOOKABLE_RE):
        logger.info("Clicked 'Jump to the next bookable date'")
        page.wait_for_timeout(2500)
        page_ok = page_ok or _page_looks_like_schedule(page)

    # Paginate forward across the horizon so later weeks are included.
    # Cap iterations to avoid infinite loops if navigation stalls.
    max_steps = max(days_ahead, 7)
    stagnant = 0
    prev_count = len(captured)
    for step in range(max_steps):
        raw_so_far: list[tuple[int, int]] = []
        for body in captured:
            raw_so_far.extend(_parse_slot_list_payload(body))
        farthest = _max_slot_date(raw_so_far)
        if farthest is not None and farthest >= cutoff:
            logger.info(
                "Google scrape horizon covered (farthest=%s cutoff=%s) after %d nav steps",
                farthest,
                cutoff,
                step,
            )
            break

        clicked = _click_first(page, NEXT_DAY_RE)
        if not clicked:
            clicked = _click_first(page, NEXT_MONTH_RE)
        if not clicked:
            logger.info("Google schedule: no further Next day/month control at step %d", step)
            break

        page.wait_for_timeout(1500)
        if len(captured) == prev_count:
            stagnant += 1
            if stagnant >= 3:
                logger.info("Google schedule: navigation produced no new RPCs; stopping")
                break
        else:
            stagnant = 0
            prev_count = len(captured)

    rpc_captured = bool(captured)
    raw_slots: list[tuple[int, int]] = []
    for body in captured:
        raw_slots.extend(_parse_slot_list_payload(body))

    slots = _to_person_slots(
        raw_slots,
        scraped_at=scraped_at,
        days_ahead=days_ahead,
    )

    if not slots:
        logger.info("ListAvailableSlots empty/missed; trying DOM fallback")
        slots = _dom_fallback_slots(page, scraped_at=scraped_at)
        if days_ahead:
            now = datetime.now(tz).date()
            slots = [
                s
                for s in slots
                if now <= datetime.strptime(s.date, "%Y-%m-%d").date() <= cutoff
            ]

    if not slots:
        _log_empty_capture(captured, captured_urls)

    note = ""
    if rpc_captured and not slots:
        note = "RPC captured but no open slots in horizon"
    elif page_ok and not rpc_captured and not slots:
        note = "Schedule UI loaded but ListAvailableSlots not captured"
    elif not page_ok and not rpc_captured:
        note = "Appointment page did not look like a schedule and no RPC captured"

    logger.info(
        "Google appointments scrape found %d person slots (rpc=%s page_ok=%s note=%s)",
        len(slots),
        rpc_captured,
        page_ok,
        note or "ok",
    )
    return GoogleAppointmentResult(
        slots=slots,
        rpc_captured=rpc_captured,
        page_ok=page_ok,
        note=note,
    )


def run_google_appointment_scrape(settings: Settings) -> GoogleAppointmentResult:
    with browser_session(settings) as (_, __, ___, page):
        return scrape_google_appointments(page, settings)
