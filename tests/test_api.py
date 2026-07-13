import pytest
from fastapi.testclient import TestClient

from coolhurst_booker.api.main import app
from coolhurst_booker.db.repository import get_repository


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setenv("COOLHURST_DB_PATH", db_path)
    return TestClient(app)


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


def test_index_page(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Book a game of tennis" in response.text


def test_slots_empty(client):
    response = client.get("/slots")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert data["slots"] == []


def test_slots_summary_empty(client):
    response = client.get("/slots/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["days"] == 0
