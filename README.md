# Coolhurst Court Scraper PoC

Scrapes Outdoor Tennis court availability from [Coolhurst ClubSolution](https://coolhurst.clubsolution.co.uk/newlook/proc_baner.asp) and your public [Google Calendar Tennis Availability schedule](https://calendar.google.com/calendar/u/0/appointments/schedules/AcZssZ1UyZ4YQe7yyIkB-Cy9BKUym6-10oCEzUgur_8dU9-zC6t0Qv50TcAZAs-D9oWZq4hc1jefxdKX), then exposes results via a local JSON API.

There is no supported Google API for listing open Appointment Schedule slots, so availability is scraped from the public booking page (Playwright). Soften expectations: Google UI/RPC changes can break that scrape.

## Quick start

```bash
cp .env.example .env
# Edit .env with COOLHURST_USERNAME, COOLHURST_PASSWORD, BOOKER_NAME, GOOGLE_APPOINTMENT_URL

python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
playwright install chromium

# One-shot smoke test (Coolhurst + Google appointments)
python -m coolhurst_booker.jobs.scrape_job --once

# API + 5-minute scheduler
uvicorn coolhurst_booker.api.main:app --host 0.0.0.0 --port 8080
```

Or use the helper scripts:

```bash
./scripts/start.sh      # start if not already running
./scripts/restart.sh    # stop + reinstall package + start (latest code)
./scripts/status.sh     # health check
./scripts/stop.sh       # stop
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
| `GET /health` | Service status and last successful scrapes |
| `GET /config` | Public UI config (booker name, booking URLs, interval) |
| `GET /slots` | Available court slots (`?date=YYYY-MM-DD&court=3`); each slot includes `person_available` |
| `GET /person-slots` | Scraped Google appointment open windows |
| `GET /slots/summary` | Slot counts per day |

Manual scrapes are not exposed over HTTP (so bots cannot trigger them). Use the CLI instead:

```bash
python -m coolhurst_booker.jobs.scrape_job --once
```

The API process still runs the Coolhurst + Google scrapers on `SCRAPE_INTERVAL_SECONDS` (default 5 minutes).

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COOLHURST_USERNAME` | — | Club login username |
| `COOLHURST_PASSWORD` | — | Club login password |
| `COOLHURST_BOOKING_AREA` | `Outdoor Tennis` | Booking area to scrape |
| `COOLHURST_DAYS_AHEAD` | `14` | Days of availability to scan |
| `COOLHURST_DB_PATH` | `./data/courts.db` | SQLite database path |
| `COOLHURST_BOOK_URL` | Coolhurst `proc_baner.asp` | Outbound court booking link |
| `BOOKER_NAME` | `Roshan` | Name shown in the UI / Calendar filter |
| `GOOGLE_APPOINTMENT_URL` | — | Public Google appointment booking page to scrape + link |
| `GOOGLE_USERNAME` | — | Optional Google login (rarely needed for public pages) |
| `GOOGLE_PASSWORD` | — | Optional Google login password |
| `PLAYWRIGHT_HEADLESS` | `true` | Set `false` to watch the browser |
| `SCRAPE_INTERVAL_SECONDS` | `300` | Scrape interval when running API (5 minutes) |

## Bazzite / Quadlet

You need a container **image** — cloning alone is not enough. On the NUC:

1. `podman build -t localhost/coolhurst-booker:latest .`
2. Put secrets in `~/.config/coolhurst-booker/coolhurst-booker.env` (mode `600`); do not commit them.
3. Run as a rootless Quadlet on Traefik’s `web` network (`Network=web` + labels). Do **not** publish host port `8080` — Traefik already owns it.

Agents should follow [`.cursor/skills/bazzite-quadlet-deploy/`](.cursor/skills/bazzite-quadlet-deploy/) (and homelab-infra’s `nuc-quadlet` skill for conventions). The Quadlet unit lives in **homelab-infra** as `nuc/containers/coolhurst-booker.container`.
## Tests

```bash
pytest
RUN_LIVE_SCRAPE=1 pytest -k integration   # requires credentials in .env
```
