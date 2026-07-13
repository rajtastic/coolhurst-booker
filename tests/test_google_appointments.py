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
    slots = _to_person_slots(
        [(1784109600, 60), (1784120400, 60)],
        scraped_at="2026-07-13T12:00:00+00:00",
        tz_name="Europe/London",
        days_ahead=30,
    )
    assert len(slots) == 2
    assert slots[0].date == "2026-07-15"
    assert slots[0].start_time == "11:00"
    assert slots[0].end_time == "12:00"
    assert slots[1].start_time == "14:00"
