#!/usr/bin/env bash
# Print whether the API is up and show a short health summary.
set -euo pipefail

PORT="${PORT:-8080}"
URL="http://127.0.0.1:$PORT"

if ! curl -sf "$URL/health" -o /tmp/coolhurst-health.json 2>/dev/null; then
  echo "Down (nothing healthy on $URL)"
  if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "Note: port $PORT is in use but /health failed"
  fi
  exit 1
fi

PORT="$PORT" python3 - <<'PY'
import json, os
from pathlib import Path
port = os.environ["PORT"]
data = json.loads(Path("/tmp/coolhurst-health.json").read_text())
court = data.get("last_scrape") or {}
google = data.get("last_google_scrape") or {}
print(f"Up  http://localhost:{port}")
print(f"  coolhurst: {court.get('status')} slots={court.get('slots_found')} at {court.get('finished_at')}")
print(f"  google:    {google.get('status')} slots={google.get('slots_found')} at {google.get('finished_at')}")
PY
