#!/bin/bash
# The demo's local servers: see what is up, start what is down, stop what this script started.
#
#   scripts/demo.sh status     what is running and whether it answers
#   scripts/demo.sh start      start the servers that are not running (never a second copy)
#   scripts/demo.sh stop       stop only the servers this script started
#   scripts/demo.sh check      status, then ask every outside service (prints names and results, never a key)
#
#   8130  reports backend   (Python, FastAPI)
#   3015  markets desk      (Next.js; the production build when one exists, otherwise the dev server)
#   3000  the app           (Vite)
set -u
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUN="$ROOT/output/run"
mkdir -p "$RUN"
PY="${PYTHON:-python3}"

listening() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

code() { curl -s -m "${2:-5}" -o /dev/null -w "%{http_code}" "$1" 2>/dev/null; }

status_one() {  # name port url
  local name="$1" port="$2" url="$3"
  if ! listening "$port"; then
    printf "  %-16s :%s  DOWN\n" "$name" "$port"
    return 1
  fi
  local answer
  answer="$(code "$url" 12)"
  if [ "$answer" = "200" ]; then
    printf "  %-16s :%s  up, answers\n" "$name" "$port"
  else
    printf "  %-16s :%s  up, but %s answered %s\n" "$name" "$port" "$url" "${answer:-nothing}"
    return 1
  fi
}

status() {
  local bad=0
  status_one "reports backend" 8130 "http://127.0.0.1:8130/health" || bad=1
  status_one "markets desk" 3015 "http://127.0.0.1:3015/api/market?section=chart&ticker=SPY&range=1M" || bad=1
  status_one "the app" 3000 "http://127.0.0.1:3000/" || bad=1
  if [ "$bad" = "0" ]; then
    echo "  all three are up: open http://127.0.0.1:3000"
  else
    echo "  something is down: run  scripts/demo.sh start"
  fi
  return "$bad"
}

start_one() {  # name port dir command...
  local name="$1" port="$2" dir="$3"
  shift 3
  if listening "$port"; then
    echo "  $name: already running on :$port"
    return 0
  fi
  ( cd "$dir" && nohup "$@" > "$RUN/$name.log" 2>&1 & echo $! > "$RUN/$name.pid" )
  local i
  for i in $(seq 1 80); do
    listening "$port" && break
    sleep 0.5
  done
  if listening "$port"; then
    echo "  $name: started on :$port (log: output/run/$name.log)"
  else
    echo "  $name: DID NOT START, read output/run/$name.log"
    return 1
  fi
}

start() {
  start_one backend 8130 "$ROOT" "$PY" -m uvicorn backend.main:app --host 127.0.0.1 --port 8130
  if [ -f "$ROOT/markets/.next/BUILD_ID" ]; then
    start_one markets 3015 "$ROOT/markets" npx next start -p 3015 -H 127.0.0.1
  else
    start_one markets 3015 "$ROOT/markets" npx next dev -p 3015 -H 127.0.0.1
  fi
  start_one app 3000 "$ROOT/LECTIO/kabu" npm run dev
  echo
  status
}

stop() {
  local name pid
  for name in app markets backend; do
    if [ -f "$RUN/$name.pid" ]; then
      pid="$(cat "$RUN/$name.pid")"
      if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        kill "$pid" 2>/dev/null && echo "  $name: stopped (pid $pid)"
      else
        echo "  $name: was not running"
      fi
      rm -f "$RUN/$name.pid"
    else
      echo "  $name: not started by this script, left alone"
    fi
  done
}

case "${1:-status}" in
  status) status ;;
  start) start ;;
  stop) stop ;;
  check) status; echo; ( cd "$ROOT" && "$PY" scripts/check_keys.py ) ;;
  *) echo "usage: scripts/demo.sh status|start|stop|check"; exit 2 ;;
esac
