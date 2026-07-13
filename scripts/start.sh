#!/usr/bin/env bash
# Start the Coolhurst booker API (no-op if already listening on PORT).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT="${PORT:-8080}"
HOST="${HOST:-0.0.0.0}"
LOG="${LOG:-$ROOT/data/uvicorn.log}"
PID_FILE="${PID_FILE:-$ROOT/data/uvicorn.pid}"

mkdir -p "$ROOT/data"

if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Already running on http://localhost:$PORT"
  curl -sf "http://127.0.0.1:$PORT/health" >/dev/null && echo "Health: ok" || echo "Health: not ready yet"
  exit 0
fi

if [[ ! -d "$ROOT/.venv" ]]; then
  echo "Creating .venv..."
  python3 -m venv "$ROOT/.venv"
fi

# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

if [[ -n "${INSTALL_DEV:-}" ]]; then
  pip install -e ".[dev]" -q
else
  pip install -e . -q
fi

nohup uvicorn coolhurst_booker.api.main:app --host "$HOST" --port "$PORT" \
  >>"$LOG" 2>&1 &
echo $! >"$PID_FILE"

for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "Started http://localhost:$PORT  (pid $(cat "$PID_FILE"), log $LOG)"
    exit 0
  fi
  sleep 0.25
done

echo "Started process but health check timed out — see $LOG" >&2
exit 1
