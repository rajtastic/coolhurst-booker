#!/usr/bin/env bash
# Stop the API on PORT (default 8080).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${PORT:-8080}"
PID_FILE="${PID_FILE:-$ROOT/data/uvicorn.pid}"

echo "Stopping processes on port $PORT..."
if command -v lsof >/dev/null 2>&1; then
  if pids="$(lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null || true)"; then
    if [[ -n "${pids}" ]]; then
      # shellcheck disable=SC2086
      kill $pids 2>/dev/null || true
      sleep 0.5
      # shellcheck disable=SC2086
      kill -9 $pids 2>/dev/null || true
    fi
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

if lsof -tiTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "Still something listening on $PORT" >&2
  exit 1
fi

echo "Stopped."
