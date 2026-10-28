#!/usr/bin/env bash
# Start the API and the web dev server together; Ctrl-C stops both.
#
#   ./dev.sh            real models (the ant auth profile)
#   ./dev.sh fake       offline, canned narrator
#   ./dev.sh stop       stop anything still holding the two ports
#
# Any process already listening on 8010 or 5173 is stopped first, so a stale
# server from an earlier run cannot leave a blank page at localhost:5173.
set -euo pipefail
cd "$(dirname "$0")"

API_PORT="${API_PORT:-8010}"
WEB_PORT="${WEB_PORT:-5173}"
export API_PORT                       # vite.config.ts proxies /api to this port

free_port() {
  local pids
  pids=$(lsof -nP -t -iTCP:"$1" -sTCP:LISTEN 2>/dev/null || true)
  if [ -n "$pids" ]; then
    echo "stopping old process on :$1 ($pids)"
    kill $pids 2>/dev/null || true
    sleep 1
  fi
}

free_port "$API_PORT"
free_port "$WEB_PORT"
[ "${1:-}" = "stop" ] && exit 0

if [ "${1:-}" = "fake" ]; then
  export TA_PROVIDER=fake
  echo "offline: TA_PROVIDER=fake"
elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "warning: ANTHROPIC_API_KEY is set and outranks the ant auth profile" >&2
fi

[ -x server/.venv/bin/uvicorn ] || { echo "no server/.venv: run 'cd server && uv sync --extra dev'" >&2; exit 1; }
[ -d web/node_modules ] || { echo "no web/node_modules: run 'cd web && npm install'" >&2; exit 1; }

mkdir -p data/logs
( cd server && exec .venv/bin/uvicorn app:app --host 0.0.0.0 --port "$API_PORT" --reload ) &
API_PID=$!
trap 'kill $API_PID ${WEB_PID:-} 2>/dev/null; wait $API_PID ${WEB_PID:-} 2>/dev/null' EXIT INT TERM

# The API takes a few seconds to import; the web server is up in under one. Start the web
# server only once the API answers, so a page opened straight away never sees a proxy error.
for _ in $(seq 1 60); do
  curl -sf -m 1 -o /dev/null "http://127.0.0.1:$API_PORT/api/games" && break
  kill -0 "$API_PID" 2>/dev/null || { echo "api exited; see the output above" >&2; exit 1; }
  sleep 0.5
done
curl -sf -m 1 -o /dev/null "http://127.0.0.1:$API_PORT/api/games" || { echo "api did not answer on :$API_PORT within 30s" >&2; exit 1; }

( cd web && exec npm run dev -- --port "$WEB_PORT" ) &
WEB_PID=$!

echo
echo "  web  http://localhost:$WEB_PORT   (dev, proxies /api to :$API_PORT)"
echo "  api  http://localhost:$API_PORT"
echo "  Ctrl-C stops both."
echo
wait
