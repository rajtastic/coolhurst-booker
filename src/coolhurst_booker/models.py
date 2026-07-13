from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class CourtSlot:
    date: str
    court: str
    start_time: str
    end_time: str
    price: str | None
    booking_token: str | None
    scraped_at: str


@dataclass
class ScrapeResult:
    slots: list[CourtSlot]
    days_scraped: int
    started_at: str
    finished_at: str

    @classmethod
    def start(cls) -> "ScrapeResult":
        now = datetime.now(UTC).isoformat()
        return cls(slots=[], days_scraped=0, started_at=now, finished_at=now)

    def finish(self, days_scraped: int) -> None:
        self.days_scraped = days_scraped
        self.finished_at = datetime.now(UTC).isoformat()
