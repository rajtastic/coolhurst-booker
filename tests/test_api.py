import pytest
from fastapi.testclient import TestClient

from coolhurst_booker.api.main import app
from coolhurst_booker.db.repository import CourtRepository
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


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "last_google_scrape" in data


def test_config_endpoint(client):
    response = client.get("/config")
    assert response.status_code == 200
    data = response.json()
    assert data["booker_name"] == "Roshan"
    assert "appointments" in data["appointment_url"]
    assert data["scrape_interval_seconds"] == 300


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Calendar" in response.text
    assert 'data-calendar="both"' in response.text
    assert "book-modal" in response.text


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
    slots = { (s["court"], s["person_available"]) for s in response.json()["slots"] }
    assert ("3 - Clay", True) in slots
    assert ("4 - Clay", False) in slots
