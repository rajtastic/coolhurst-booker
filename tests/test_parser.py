import os
from pathlib import Path

import pytest

from coolhurst_booker.scraper.parser import parse_available_slots

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_available_slots_from_fixture():
    html = (FIXTURES / "available_slots.html").read_text()
    slots = parse_available_slots(html, date="2026-07-12")

    assert len(slots) >= 1
    courts = {s.court for s in slots}
    assert any(c.startswith("1") for c in courts)
    assert all(s.date == "2026-07-12" for s in slots)

    first = slots[0]
    assert first.start_time == "21:00"
    assert first.end_time == "22:00"
    assert first.price == "£ 3.00"
    assert first.booking_token is not None


def test_court_filter_excludes_15():
    html = (FIXTURES / "available_slots.html").read_text()
    slots = parse_available_slots(html, date="2026-07-12")
    assert not any(s.court.startswith("15") for s in slots)


def test_unavailable_cells_ignored():
    html = (FIXTURES / "available_slots.html").read_text()
    slots = parse_available_slots(html, date="2026-07-12")
    assert not any("Julian" in (s.court or "") for s in slots)
