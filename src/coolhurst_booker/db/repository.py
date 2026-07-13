import logging
import sqlite3
from pathlib import Path

from coolhurst_booker.config import Settings, get_settings
from coolhurst_booker.models import CourtSlot

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS court_slots (
    date TEXT NOT NULL,
    court TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    price TEXT,
    booking_token TEXT,
    scraped_at TEXT NOT NULL,
    PRIMARY KEY (date, court, start_time)
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    days_scraped INTEGER,
    slots_found INTEGER,
    status TEXT NOT NULL,
    error TEXT
);
"""


class CourtRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def start_scrape_run(self, started_at: str) -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO scrape_runs (started_at, status) VALUES (?, 'running')",
                (started_at,),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def finish_scrape_run(
        self,
        run_id: int,
        finished_at: str,
        days_scraped: int,
        slots_found: int,
        status: str,
        error: str | None = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE scrape_runs
                SET finished_at = ?, days_scraped = ?, slots_found = ?, status = ?, error = ?
                WHERE id = ?
                """,
                (finished_at, days_scraped, slots_found, status, error, run_id),
            )
            conn.commit()

    def upsert_slots(self, slots: list[CourtSlot], dates: list[str]) -> None:
        with self._connect() as conn:
            if dates:
                placeholders = ",".join("?" for _ in dates)
                conn.execute(
                    f"DELETE FROM court_slots WHERE date IN ({placeholders})",
                    dates,
                )
            conn.executemany(
                """
                INSERT OR REPLACE INTO court_slots
                (date, court, start_time, end_time, price, booking_token, scraped_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        s.date,
                        s.court,
                        s.start_time,
                        s.end_time,
                        s.price,
                        s.booking_token,
                        s.scraped_at,
                    )
                    for s in slots
                ],
            )
            conn.commit()

    def get_slots(self, date: str | None = None, court: str | None = None) -> list[dict]:
        query = "SELECT * FROM court_slots WHERE 1=1"
        params: list[str] = []

        if date:
            query += " AND date = ?"
            params.append(date)
        if court:
            query += " AND court LIKE ?"
            params.append(f"{court}%")

        query += " ORDER BY date, court, start_time"

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

    def get_summary(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT date, COUNT(*) AS slot_count, MAX(scraped_at) AS last_scraped
                FROM court_slots
                GROUP BY date
                ORDER BY date
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def get_last_scrape(self) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM scrape_runs
                WHERE status = 'ok'
                ORDER BY finished_at DESC
                LIMIT 1
                """
            ).fetchone()
            return dict(row) if row else None


def get_repository(settings: Settings | None = None) -> CourtRepository:
    settings = settings or get_settings()
    return CourtRepository(settings.coolhurst_db_path)
