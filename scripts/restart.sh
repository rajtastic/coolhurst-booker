#!/usr/bin/env bash
# Stop anything on PORT, reinstall the local package, start fresh so you pick up latest code.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PORT="${PORT:-8080}"
LOG="${LOG:-$ROOT/data/uvicorn.log}"
PID_FILE="${PID_FILE:-$ROOT/data/uvicorn.pid}"

mkdir -p "$ROOT/data"

echo "Stopping processes on port $PORT..."
if pids="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"; then
  if [[ -n "${pids}" ]]; then
    # shellcheck disable=SC2086
    kill $pids 2>/dev/null || true
    sleep 0.5
    # shellcheck disable=SC2086
    kill -9 $pids 2>/dev/null || true
  fi
fi

if [[ -f "$PID_FILE" ]]; then
  old="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "${old}" ]]; then
    kill "$old" 2>/dev/null || true
    kill -9 "$old" 2>/dev/null || true
  fi
  rm -f "$PID_FILE"
fi

: >"$LOG"

echo "Refreshing install from current tree..."
if [[ ! -d "$ROOT/.venv" ]]; then
  python3 -m venv "$ROOT/.venv"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"
if [[ -n "${INSTALL_DEV:-}" ]]; then
  pip install -e ".[dev]" -q
else
  pip install -e . -q
fi

exec "$ROOT/scripts/start.sh"
