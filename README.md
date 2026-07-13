# Coolhurst Court Scraper PoC

Scrapes Outdoor Tennis court availability from [Coolhurst ClubSolution](https://coolhurst.clubsolution.co.uk/newlook/proc_baner.asp) and exposes results via a local JSON API.

## Quick start

```bash
cp .env.example .env
# Edit .env with COOLHURST_USERNAME and COOLHURST_PASSWORD

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

# One-shot smoke test
python -m coolhurst_booker.jobs.scrape_job --once

# API + 1-minute scheduler
uvicorn coolhurst_booker.api.main:app --host 0.0.0.0 --port 8080
```

Open http://localhost:8080 for the booking UI, or http://localhost:8080/docs for the API.

## Docker

```bash
cp .env.example .env
docker compose up --build
```

## API endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Service status and last successful scrape |
| `GET /slots` | Available slots (`?date=YYYY-MM-DD&court=3`) |
| `GET /slots/summary` | Slot counts per day |
| `POST /scrape` | Trigger scrape manually |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COOLHURST_USERNAME` | — | Club login username |
| `COOLHURST_PASSWORD` | — | Club login password |
| `COOLHURST_BOOKING_AREA` | `Outdoor Tennis` | Booking area to scrape |
| `COOLHURST_DAYS_AHEAD` | `14` | Days of availability to scan |
| `COOLHURST_DB_PATH` | `./data/courts.db` | SQLite database path |
| `PLAYWRIGHT_HEADLESS` | `true` | Set `false` to watch the browser |
| `SCRAPE_INTERVAL_SECONDS` | `60` | Scrape interval when running API |

## Bazzite / Quadlet (example)

```ini
[Container]
ContainerName=coolhurst-booker
Image=localhost/coolhurst-booker:latest
PublishPort=8080:8080
EnvironmentFile=/etc/coolhurst-booker.env
Volume=coolhurst-data:/data:Z

[Service]
Restart=always
```

## Tests

```bash
pytest
RUN_LIVE_SCRAPE=1 pytest -k integration   # requires credentials in .env
```
