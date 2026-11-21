#!/bin/zsh
# Start the Europa chatbot for the PRISM BEFORE/AFTER runs, plus a public https link (Cloudflare quick tunnel).
#   scripts/serve_demo.sh on     -> number checker ON  (AFTER run, the real product)
#   scripts/serve_demo.sh off    -> number checker OFF (BEFORE run only)
#   scripts/serve_demo.sh stop   -> stop both
# Port 8010 (8000 is the dev server). Logs + the public URL go to demo-logs/ (gitignored).
# The quick-tunnel URL is temporary and changes on every start. No account needed. Keys stay in .env.
set -u
cd "$(dirname "$0")/.."
MODE="${1:-on}"
PORT=8010
LOGS=demo-logs
mkdir -p "$LOGS"

stop() {
  [ -f "$LOGS/server.pid" ] && kill "$(cat "$LOGS/server.pid")" 2>/dev/null
  [ -f "$LOGS/tunnel.pid" ] && kill "$(cat "$LOGS/tunnel.pid")" 2>/dev/null
  rm -f "$LOGS/server.pid" "$LOGS/tunnel.pid"
}

if [ "$MODE" = "stop" ]; then stop; echo "stopped"; exit 0; fi
if [ "$MODE" != "on" ] && [ "$MODE" != "off" ]; then echo "usage: $0 on|off|stop"; exit 1; fi

stop
EUROPA_CHECKER="$MODE" nohup .venv/bin/uvicorn backend.app:app --port "$PORT" > "$LOGS/server-$MODE.log" 2>&1 &
echo $! > "$LOGS/server.pid"

for i in {1..30}; do curl -s "http://localhost:$PORT/api/health" > /dev/null && break; sleep 1; done
curl -s "http://localhost:$PORT/api/health" > /dev/null || { echo "server did not start: see $LOGS/server-$MODE.log"; exit 1; }

nohup cloudflared tunnel --url "http://localhost:$PORT" --no-autoupdate > "$LOGS/tunnel.log" 2>&1 &
echo $! > "$LOGS/tunnel.pid"

URL=""
for i in {1..40}; do
  URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$LOGS/tunnel.log" | head -1)
  [ -n "$URL" ] && break; sleep 1
done
[ -z "$URL" ] && { echo "tunnel gave no URL: see $LOGS/tunnel.log"; exit 1; }
echo "$URL" > "$LOGS/public-url.txt"
echo "checker: $MODE"
echo "chat page:      $URL/"
echo "PRISM endpoint: $URL/api/ask   (POST {\"ticker\":\"AAPL\",\"question\":\"...\"})"
