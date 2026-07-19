from coolhurst_booker.scraper.google_appointments import (
    _parse_slot_list_payload,
    _to_person_slots,
)


def test_parse_list_available_slots_payload():
    body = (
        "[[[[["
        '"1784109600"'
        "],60]],[[["
        '"1784120400"'
        "],60]]]]"
    )
    parsed = _parse_slot_list_payload(body)
    assert parsed == [(1784109600, 60), (1784120400, 60)]


def test_to_person_slots_filters_and_formats():
    from datetime import UTC, datetime, timedelta
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("Europe/London")
    start = (datetime.now(tz) + timedelta(days=2)).replace(
        hour=11, minute=0, second=0, microsecond=0
    )
    start_unix = int(start.astimezone(UTC).timestamp())
    later_unix = start_unix + 3 * 3600

    slots = _to_person_slots(
        [(start_unix, 60), (later_unix, 60)],
        scraped_at="2026-07-13T12:00:00+00:00",
        tz_name="Europe/London",
        days_ahead=30,
    )
    assert len(slots) == 2
    assert slots[0].date == start.date().isoformat()
    assert slots[0].start_time == "11:00"
    assert slots[0].end_time == "12:00"
    assert slots[1].start_time == "14:00"
