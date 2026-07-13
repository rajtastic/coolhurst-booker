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
2. Ensure the **homelab-infra** workspace is open or its path is known — the Quadlet unit file is written there as `nuc/containers/coolhurst-booker.container`.
3. Follow **homelab-infra** `.cursor/skills/nuc-quadlet/` for shared Quadlet/Traefik conventions when editing that file.

## Key facts

- Quadlets need an **image**. Cloning the repo is not enough.
- Build locally: `podman build -t localhost/coolhurst-booker:latest .` (Playwright base image is large; first build is slow).
- Do **not** use `PublishPort=8080:8080` — Traefik already binds host port 8080. Use `Network=web` + Traefik labels (Dashy pattern).
- Never commit secrets. Host env file: `~/.config/coolhurst-booker/coolhurst-booker.env` (mode `600`).

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

Do not put credentials in the Quadlet file or in git.

### 3. Write Quadlet in homelab-infra

Create `nuc/containers/coolhurst-booker.container` with this template (do not invent a host publish of 8080):

```ini
[Unit]
Description=Coolhurst Booker
After=network-online.target

[Container]
ContainerName=coolhurst-booker
Image=localhost/coolhurst-booker:latest
Network=web
RemapUsers=keep-id
EnvironmentFile=%h/.config/coolhurst-booker/coolhurst-booker.env
Volume=coolhurst-data:/data:Z
ShmSize=1g

Label=traefik.enable=true
Label=traefik.docker.network=web

Label=traefik.http.routers.coolhurst-testbed.rule=Host(`booker.mytestbed.co.uk`)
Label=traefik.http.routers.coolhurst-testbed.entrypoints=websecure
Label=traefik.http.routers.coolhurst-testbed.tls=true
Label=traefik.http.routers.coolhurst-testbed.tls.certresolver=myresolver
Label=traefik.http.routers.coolhurst-testbed.service=coolhurst-svc

Label=traefik.http.routers.coolhurst-tastic.rule=Host(`booker.tastic.uk`)
Label=traefik.http.routers.coolhurst-tastic.entrypoints=websecure
Label=traefik.http.routers.coolhurst-tastic.tls=true
Label=traefik.http.routers.coolhurst-tastic.tls.certresolver=myresolver
Label=traefik.http.routers.coolhurst-tastic.service=coolhurst-svc

Label=traefik.http.services.coolhurst-svc.loadbalancer.server.port=8080

[Service]
Restart=always

[Install]
WantedBy=default.target
```

### 4. Install and start (user Quadlet)

```bash
mkdir -p ~/.config/containers/systemd
# Symlink preferred so repo stays source of truth:
ln -sf /path/to/homelab-infra/nuc/containers/coolhurst-booker.container \
  ~/.config/containers/systemd/coolhurst-booker.container

systemctl --user daemon-reload
systemctl --user enable --now coolhurst-booker.service
```

### 5. Verify

```bash
systemctl --user status coolhurst-booker.service
podman logs coolhurst-booker
podman exec coolhurst-booker curl -fsS http://127.0.0.1:8080/health
```

Do not rely on `curl http://localhost:8080/health` on the host unless a non-conflicting `PublishPort` was added (avoid `:8080`).

### 6. DNS / Traefik (user action)

- Add Cloudflare DNS for `booker.mytestbed.co.uk` and `booker.tastic.uk` the same way other NUC services are pointed.
- Traefik discovers labels via the Podman socket; no static Traefik config change if labels and `Network=web` are correct.
- Optional: add basic-auth middleware labels (see `traefik.container` in homelab-infra) so the UI is not public.
- Oracle Caddy is not required for first bring-up.

### 7. Updates later

```bash
cd ~/src/coolhurst-booker && git pull
podman build -t localhost/coolhurst-booker:latest .
systemctl --user restart coolhurst-booker.service
```

`AutoUpdate=registry` does not apply to `localhost/...` images until this app is published to a registry.

## Manual scrape (ops)

```bash
podman exec coolhurst-booker python -m coolhurst_booker.jobs.scrape_job --once
```
