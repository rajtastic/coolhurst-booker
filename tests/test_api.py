import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from coolhurst_booker.api.main import app
from coolhurst_booker.db.repository import CourtRepository
from coolhurst_booker.jobs import scrape_job
from coolhurst_booker.models import CourtSlot, PersonSlot


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("COOLHURST_DB_PATH", db_path)
    monkeypatch.setenv("BOOKER_NAME", "Roshan")
    monkeypatch.setenv(
        "GOOGLE_APPOINTMENT_URL",
        "https://calendar.google.com/calendar/u/0/appointments/example=",
    )
    monkeypatch.setenv(
        "COOLHURST_BOOK_URL",
        "https://coolhurst.clubsolution.co.uk/newlook/proc_baner.asp",
    )
    return TestClient(app)


def test_health_endpoint_degraded_when_no_scrapes(client):
    response = client.get("/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert "message" in data
    assert data["scrapers"]["coolhurst"]["ok"] is False
    assert data["scrapers"]["google"]["ok"] is False
    assert "last_google_scrape" in data


def test_health_endpoint_ok_when_scrapes_fresh(client, tmp_path, monkeypatch):
    from datetime import UTC, datetime

    db_path = str(tmp_path / "health_ok.db")
    monkeypatch.setenv("COOLHURST_DB_PATH", db_path)
    monkeypatch.setenv("HEALTH_STALE_AFTER_SECONDS", "900")
    repo = CourtRepository(db_path)
    now = datetime.now(UTC).isoformat()
    for source in ("coolhurst", "google"):
        run_id = repo.start_scrape_run(now, source=source)
        repo.finish_scrape_run(
            run_id=run_id,
            finished_at=now,
            days_scraped=14,
            slots_found=1,
            status="ok",
        )

    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["message"] == "Both scrapers healthy"
    assert data["scrapers"]["coolhurst"]["ok"] is True
    assert data["scrapers"]["google"]["ok"] is True


def test_health_endpoint_degraded_when_one_scraper_stale(client, tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    db_path = str(tmp_path / "health_stale.db")
    monkeypatch.setenv("COOLHURST_DB_PATH", db_path)
    monkeypatch.setenv("HEALTH_STALE_AFTER_SECONDS", "60")
    repo = CourtRepository(db_path)
    fresh = datetime.now(UTC).isoformat()
    stale = (datetime.now(UTC) - timedelta(hours=2)).isoformat()

    run_g = repo.start_scrape_run(fresh, source="google")
    repo.finish_scrape_run(
        run_id=run_g,
        finished_at=fresh,
        days_scraped=14,
        slots_found=1,
        status="ok",
    )
    run_c = repo.start_scrape_run(stale, source="coolhurst")
    repo.finish_scrape_run(
        run_id=run_c,
        finished_at=stale,
        days_scraped=14,
        slots_found=1,
        status="ok",
    )

    response = client.get("/health")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "degraded"
    assert data["scrapers"]["coolhurst"]["ok"] is False
    assert data["scrapers"]["google"]["ok"] is True
    assert "coolhurst" in data["message"]


def test_config_endpoint(client):
    response = client.get("/config")
    assert response.status_code == 200
    data = response.json()
    assert data["booker_name"] == "Roshan"
    assert "appointments" in data["appointment_url"]
    assert data["scrape_interval_seconds"] == 300
    assert data["health_warn_after_seconds"] == 300
    assert data["health_stale_after_seconds"] == 3600
    assert data["show_public_court_calendar_link"] is True


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Calendar" in response.text
    assert 'data-calendar="both"' in response.text
    assert "book-modal" in response.text
    assert "last-updated-courts" in response.text
    assert "public-calendar-link" in response.text


def test_slots_empty(client):
    response = client.get("/slots")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert data["slots"] == []
    assert data["person_slots"] == []


def test_person_slots_empty(client):
    response = client.get("/person-slots")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert data["slots"] == []


def test_person_slots_list(tmp_path, monkeypatch):
    db_path = str(tmp_path / "person.db")
    monkeypatch.setenv("COOLHURST_DB_PATH", db_path)
    repo = CourtRepository(db_path)
    repo.replace_person_slots(
        [
            PersonSlot(
                date="2026-07-15",
                start_time="20:00",
                end_time="21:00",
                scraped_at="2026-07-13T12:00:00+00:00",
            )
        ]
    )
    client = TestClient(app)
    response = client.get("/person-slots")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["slots"][0]["start_time"] == "20:00"


def test_slots_summary_empty(client):
    response = client.get("/slots/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["days"] == 0


def test_slots_include_person_available(tmp_path, monkeypatch):
    db_path = str(tmp_path / "overlap.db")
    monkeypatch.setenv("COOLHURST_DB_PATH", db_path)
    repo = CourtRepository(db_path)
    repo.upsert_slots(
        [
            CourtSlot(
                date="2026-07-15",
                court="3 - Clay",
                start_time="11:00",
                end_time="11:45",
                price=None,
                booking_token=None,
                scraped_at="2026-07-13T12:00:00+00:00",
            ),
            CourtSlot(
                date="2026-07-15",
                court="4 - Clay",
                start_time="09:00",
                end_time="09:45",
                price=None,
                booking_token=None,
                scraped_at="2026-07-13T12:00:00+00:00",
            ),
        ],
        dates=["2026-07-15"],
    )
    repo.replace_person_slots(
        [
            PersonSlot(
                date="2026-07-15",
                start_time="11:00",
                end_time="12:00",
                scraped_at="2026-07-13T12:00:00+00:00",
            )
        ]
    )

    client = TestClient(app)
    response = client.get("/slots")
    assert response.status_code == 200
    slots = {(s["court"], s["person_available"]) for s in response.json()["slots"]}
    assert ("3 - Clay", True) in slots
    assert ("4 - Clay", False) in slots


def test_upsert_slots_prunes_past_dates(tmp_path):
    repo = CourtRepository(str(tmp_path / "prune.db"))
    repo.upsert_slots(
        [
            CourtSlot(
                date="2026-07-10",
                court="1 - Clay",
                start_time="10:00",
                end_time="11:00",
                price=None,
                booking_token=None,
                scraped_at="2026-07-10T12:00:00+00:00",
            ),
            CourtSlot(
                date="2026-07-19",
                court="2 - Clay",
                start_time="10:00",
                end_time="11:00",
                price=None,
                booking_token=None,
                scraped_at="2026-07-19T12:00:00+00:00",
            ),
        ],
        dates=["2026-07-10", "2026-07-19"],
    )
    assert len(repo.get_slots()) == 2

    repo.upsert_slots(
        [
            CourtSlot(
                date="2026-07-19",
                court="2 - Clay",
                start_time="12:00",
                end_time="13:00",
                price=None,
                booking_token=None,
                scraped_at="2026-07-19T13:00:00+00:00",
            ),
        ],
        dates=["2026-07-19"],
        prune_before="2026-07-19",
    )
    slots = repo.get_slots()
    assert len(slots) == 1
    assert slots[0]["date"] == "2026-07-19"
    assert slots[0]["start_time"] == "12:00"


def test_google_empty_scrape_preserves_person_slots(tmp_path, monkeypatch):
    db_path = str(tmp_path / "preserve.db")
    monkeypatch.setenv("COOLHURST_DB_PATH", db_path)
    monkeypatch.setenv("GOOGLE_APPOINTMENT_URL", "https://example.com/appointments")
    monkeypatch.setenv("COOLHURST_DAYS_AHEAD", "14")
    monkeypatch.setenv("PLAYWRIGHT_HEADLESS", "true")

    repo = CourtRepository(db_path)
    repo.replace_person_slots(
        [
            PersonSlot(
                date="2026-07-22",
                start_time="19:00",
                end_time="20:00",
                scraped_at="2026-07-19T10:00:00+00:00",
            )
        ]
    )
    assert repo.count_person_slots() == 1

    fake_page = MagicMock()
    fake_cm = MagicMock()
    fake_cm.__enter__.return_value = (None, None, None, fake_page)
    fake_cm.__exit__.return_value = None

    with (
        patch.object(scrape_job, "browser_session", return_value=fake_cm),
        patch.object(scrape_job, "scrape_google_appointments", return_value=[]),
    ):
        kept = scrape_job.run_google_scrape(once=True)

    assert kept == 1
    assert repo.count_person_slots() == 1
    assert repo.get_person_slots()[0]["start_time"] == "19:00"
    latest = repo.get_latest_scrape_run(source="google")
    assert latest is not None
    assert latest["status"] == "error"
    assert "preserved" in (latest["error"] or "").lower()
