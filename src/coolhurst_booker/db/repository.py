import logging
import sqlite3
from pathlib import Path

from coolhurst_booker.config import Settings, get_settings
from coolhurst_booker.models import CourtSlot, PersonSlot

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

CREATE TABLE IF NOT EXISTS person_slots (
    date TEXT NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    scraped_at TEXT NOT NULL,
    PRIMARY KEY (date, start_time)
);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    days_scraped INTEGER,
    slots_found INTEGER,
    status TEXT NOT NULL,
    error TEXT,
    source TEXT NOT NULL DEFAULT 'coolhurst'
);
"""


def _time_to_minutes(value: str) -> int:
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def intervals_overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    return _time_to_minutes(a_start) < _time_to_minutes(b_end) and _time_to_minutes(
        a_end
    ) > _time_to_minutes(b_start)


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
            cols = {
                row["name"]
                for row in conn.execute("PRAGMA table_info(scrape_runs)").fetchall()
            }
            if "source" not in cols:
                conn.execute(
                    "ALTER TABLE scrape_runs ADD COLUMN source TEXT NOT NULL DEFAULT 'coolhurst'"
                )
            conn.commit()

    def start_scrape_run(self, started_at: str, source: str = "coolhurst") -> int:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO scrape_runs (started_at, status, source) VALUES (?, 'running', ?)",
                (started_at, source),
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

    def abandon_running_scrapes(
        self,
        finished_at: str,
        error: str = "abandoned: scrape timeout",
    ) -> int:
        """Mark any in-flight scrape_runs as errors so they cannot block forever."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE scrape_runs
                SET finished_at = ?, days_scraped = 0, slots_found = 0,
                    status = 'error', error = ?
                WHERE status = 'running'
                """,
                (finished_at, error),
            )
            conn.commit()
            return int(cursor.rowcount)

    def upsert_slots(
        self,
        slots: list[CourtSlot],
        dates: list[str],
        *,
        prune_before: str | None = None,
    ) -> None:
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
            if prune_before:
                conn.execute("DELETE FROM court_slots WHERE date < ?", (prune_before,))
            conn.commit()

    def replace_person_slots(self, slots: list[PersonSlot]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM person_slots")
            conn.executemany(
                """
                INSERT OR REPLACE INTO person_slots
                (date, start_time, end_time, scraped_at)
                VALUES (?, ?, ?, ?)
                """,
                [(s.date, s.start_time, s.end_time, s.scraped_at) for s in slots],
            )
            conn.commit()

    def count_person_slots(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM person_slots").fetchone()
            return int(row["n"]) if row else 0

    def get_person_slots(self, date: str | None = None) -> list[dict]:
        query = "SELECT * FROM person_slots WHERE 1=1"
        params: list[str] = []
        if date:
            query += " AND date = ?"
            params.append(date)
        query += " ORDER BY date, start_time"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]

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
            slots = [dict(row) for row in rows]
            person_slots = [dict(row) for row in conn.execute("SELECT * FROM person_slots").fetchall()]

        by_date: dict[str, list[dict]] = {}
        for person in person_slots:
            by_date.setdefault(person["date"], []).append(person)

        for slot in slots:
            candidates = by_date.get(slot["date"], [])
            slot["person_available"] = any(
                intervals_overlap(
                    slot["start_time"],
                    slot["end_time"],
                    person["start_time"],
                    person["end_time"],
                )
                for person in candidates
            )

        return slots

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

    def get_last_scrape(self, source: str = "coolhurst") -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM scrape_runs
                WHERE status = 'ok' AND source = ?
                ORDER BY finished_at DESC
                LIMIT 1
                """,
                (source,),
            ).fetchone()
            return dict(row) if row else None

    def get_latest_scrape_run(self, source: str = "coolhurst") -> dict | None:
        """Most recent finished scrape for a source (ok or error)."""
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM scrape_runs
                WHERE source = ?
                  AND status IN ('ok', 'error')
                  AND finished_at IS NOT NULL
                ORDER BY finished_at DESC
                LIMIT 1
                """,
                (source,),
            ).fetchone()
            return dict(row) if row else None


def get_repository(settings: Settings | None = None) -> CourtRepository:
    settings = settings or get_settings()
    return CourtRepository(settings.coolhurst_db_path)
