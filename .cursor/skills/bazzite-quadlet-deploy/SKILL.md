---
name: bazzite-quadlet-deploy
description: >-
  Deploys Coolhurst Booker on a Bazzite/Fedora NUC via rootless Podman Quadlet
  behind Traefik. Use when the user asks to deploy on Bazzite, NUC, Quadlet,
  Podman systemd, Traefik, or to build and run this app as a container on the
  homelab host.
---

# Deploy Coolhurst Booker as a Quadlet (Bazzite NUC)

## Preconditions

1. Confirm the session is on the Bazzite NUC (or warn that build/install steps must run there).
2. Ensure the **homelab** workspace is open — Quadlet unit lives at `nuc12/containers/coolhurst-booker.container`.
3. Follow shared Quadlet/Traefik conventions used by other `nuc12/containers/*.container` units.

## Key facts

- Quadlets need an **image**. Cloning the repo is not enough.
- Build locally: `podman build -t localhost/coolhurst-booker:latest .` (Playwright base image is large; first build is slow).
- Do **not** use `PublishPort=8080:8080` — Traefik already binds host port 8080. Use `Network=web` + Traefik labels, and `PublishPort=8082:8080` for Oracle Caddy / Tailscale.
- Never commit secrets. Host env file: `~/.config/coolhurst-booker/coolhurst-booker.env` (mode `600`).
- Public hostname: **`tennis.tastic.uk`**.

## Steps

### 1. Clone / pull and build

```bash
# If not already present:
git clone <coolhurst-booker-remote> ~/src/coolhurst-booker
cd ~/src/coolhurst-booker   # or the workspace root for this repo
git pull
podman build -t localhost/coolhurst-booker:latest .
```

### 2. Secrets EnvironmentFile

```bash
mkdir -p ~/.config/coolhurst-booker
# Copy from .env.example, then fill required values.
# Path: ~/.config/coolhurst-booker/coolhurst-booker.env
chmod 600 ~/.config/coolhurst-booker/coolhurst-booker.env
```

Required / recommended keys:

| Variable | Notes |
|----------|--------|
| `COOLHURST_USERNAME` | Required for scrape |
| `COOLHURST_PASSWORD` | Required for scrape |
| `GOOGLE_APPOINTMENT_URL` | Strongly recommended |
| `BOOKER_NAME` | e.g. `Roshan` |
| `COOLHURST_DB_PATH` | Must be `/data/courts.db` in the container |
| `PLAYWRIGHT_HEADLESS` | `true` |
| `SCRAPE_INTERVAL_SECONDS` | Prefer `300` (not the Dockerfile default of `60`) |
| `SCRAPE_TIMEOUT_SECONDS` | Prefer `240` — hard watchdog so a hung Playwright scrape cannot block the scheduler forever |
| `HEALTH_STALE_AFTER_SECONDS` | Prefer `3600` (matches UI red / 1h stale tier; yellow warn is `HEALTH_WARN_AFTER_SECONDS=300`) |

Do not put credentials in the Quadlet file or in git.

### 3. Write Quadlet in homelab

Create `nuc12/containers/coolhurst-booker.container` with this template:

```ini
[Unit]
Description=Coolhurst Booker
After=network-online.target traefik.service

[Container]
ContainerName=coolhurst-booker
Image=localhost/coolhurst-booker:latest
Network=web
PublishPort=8082:8080
RemapUsers=keep-id
EnvironmentFile=%h/.config/coolhurst-booker/coolhurst-booker.env
Volume=coolhurst-data:/data:Z
ShmSize=1g

Label=traefik.enable=true
Label=traefik.docker.network=web
Label=traefik.http.routers.coolhurst-tennis.rule=Host(`tennis.tastic.uk`)
Label=traefik.http.routers.coolhurst-tennis.entrypoints=websecure
Label=traefik.http.routers.coolhurst-tennis.tls=true
Label=traefik.http.routers.coolhurst-tennis.tls.certresolver=myresolver
Label=traefik.http.routers.coolhurst-tennis.service=coolhurst-svc
Label=traefik.http.services.coolhurst-svc.loadbalancer.server.port=8080

[Service]
Restart=always

[Install]
WantedBy=default.target
```

Also add Caddy on the Oracle VM (`homelab/vm/Caddyfile`):

```caddy
tennis.tastic.uk {
    reverse_proxy 100.100.61.75:8082
}
```

### 4. Install and start (user Quadlet)

```bash
# nuc12/containers is already symlinked into ~/.config/containers/systemd/containers
systemctl --user daemon-reload
systemctl --user enable --now coolhurst-booker.service
```

### 5. Verify

```bash
systemctl --user status coolhurst-booker.service
podman logs coolhurst-booker
podman exec coolhurst-booker curl -fsS -i http://127.0.0.1:8080/health
curl -ik https://tennis.tastic.uk/health
curl -sS -i http://127.0.0.1:8082/health
```

`/health` returns **200** when both scrapers are fresh, otherwise **503** with a `message`.

### 6. DNS / Traefik

- AdGuard rewrite: `tennis.tastic.uk` → NUC LAN IP (`192.168.7.123`).
- Traefik discovers labels via the Podman socket; no static Traefik config change if labels and `Network=web` are correct.

### 7. Updates later

```bash
cd /path/to/coolhurst-booker && git pull
podman build -t localhost/coolhurst-booker:latest .
systemctl --user restart coolhurst-booker.service
```

`AutoUpdate=registry` does not apply to `localhost/...` images until this app is published to a registry.

## Manual scrape (ops)

```bash
podman exec coolhurst-booker python -m coolhurst_booker.jobs.scrape_job --once
```
