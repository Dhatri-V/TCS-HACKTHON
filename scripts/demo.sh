#!/usr/bin/env bash
set -euo pipefail

# Local hackathon demo supervisor. Secrets are read from ignored .env files or
# the caller's environment and are never printed.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$ROOT/demo-infrastructure/compose.yaml"
BACKEND_DIR="$ROOT/incident-platform/backend"
FRONTEND_DIR="$ROOT/incident-platform/frontend"
REASONER_DIR="$ROOT/llm-reasoner"
STATE_DIR="${TMPDIR:-/tmp}/tcs-hackathon-demo-${UID}"
API_BASE="http://127.0.0.1:3000"
DASHBOARD_URL="http://localhost:5173"
ORDERS_HEALTH="http://127.0.0.1:18080/health"
mkdir -p "$STATE_DIR"

say() { printf '[demo] %s\n' "$*"; }
die() { printf '[demo] ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }
pid_file() { printf '%s/%s.pid' "$STATE_DIR" "$1"; }
log_file() { printf '%s/%s.log' "$STATE_DIR" "$1"; }

load_config() {
  set +u
  set -a
  [ -f "$REASONER_DIR/.env" ] && . "$REASONER_DIR/.env"
  set +a
  set -u
}

validate_backend_config() {
  (cd "$BACKEND_DIR" && node --input-type=module -e '
    import "dotenv/config";
    if (!process.env.MONGODB_URI || (process.env.REMEDIATION_OPERATOR_TOKEN || "").length < 32)
      process.exit(1);
  ') || die 'Set MONGODB_URI and a 32+ character REMEDIATION_OPERATOR_TOKEN in the environment or backend .env.'
}

preflight() {
  need docker; need curl; need node; need npm; need python3; need lsof; need ps; need pgrep
  docker info >/dev/null 2>&1 || die 'Docker is not running.'
  [ -x "$REASONER_DIR/.venv/bin/python" ] || die 'Create llm-reasoner/.venv with Python 3.11 and install the project first.'
  [ -d "$BACKEND_DIR/node_modules" ] || die 'Run npm ci in incident-platform/backend first.'
  [ -d "$FRONTEND_DIR/node_modules" ] || die 'Run npm ci in incident-platform/frontend first.'
  load_config
  validate_backend_config
  case "${LLM_PRIMARY_MODEL:-ollama_chat/qwen2.5:3b}" in
    ollama_chat/*)
      local ollama_base="${OLLAMA_API_BASE:-http://localhost:11434}"
      curl -fsS --max-time 5 "${ollama_base%/}/api/tags" >/dev/null || die 'Ollama is unavailable; start it and ensure the configured Qwen model is installed.'
      ;;
  esac
}

reset_preflight() {
  need docker; need curl; need node; need python3; need lsof; need ps; need pgrep
  docker info >/dev/null 2>&1 || die 'Docker is not running.'
  [ -d "$BACKEND_DIR/node_modules" ] || die 'Run npm ci in incident-platform/backend first.'
  validate_backend_config
}

matches_process() {
  local name="$1" pid="$2" command
  command="$(ps -p "$pid" -o command= 2>/dev/null || true)"
  case "$name" in
    backend) [[ "$command" == *"npm start"* ]] ;;
    frontend) [[ "$command" == *"npm run dev"* ]] ;;
    watcher) [[ "$command" == *"llm_reasoner.log_watcher"* ]] ;;
    *) return 1 ;;
  esac
}

is_running() {
  local name="$1" file pid
  file="$(pid_file "$name")"
  [ -s "$file" ] || return 1
  pid="$(cat "$file")"
  kill -0 "$pid" 2>/dev/null && matches_process "$name" "$pid"
}

terminate_tree() {
  local pid="$1" child
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    terminate_tree "$child"
  done
  kill -TERM "$pid" 2>/dev/null || true
}

start_process() {
  local name="$1" cwd="$2"; shift 2
  is_running "$name" && die "$name is already running under this demo supervisor."
  (
    cd "$cwd"
    nohup "$@" >"$(log_file "$name")" 2>&1 < /dev/null &
    printf '%s\n' "$!" >"$(pid_file "$name")"
  )
}

stop_process() {
  local name="$1" file pid
  file="$(pid_file "$name")"
  [ -s "$file" ] || return 0
  pid="$(cat "$file")"
  if is_running "$name"; then
    terminate_tree "$pid"
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "$pid" 2>/dev/null || return 0
      sleep 0.2
    done
    kill -KILL "$pid" 2>/dev/null || true
  fi
}

wait_http() {
  local url="$1" expected="$2" seconds="$3" code
  for ((i=0; i<seconds; i++)); do
    code="$(curl -sS --max-time 3 -o /dev/null -w '%{http_code}' "$url" 2>/dev/null || true)"
    [ "$code" = "$expected" ] && return 0
    sleep 1
  done
  return 1
}

assert_orders_health() {
  local expected_code="$1" expected_status="$2" expected_database="$3"
  python3 - "$ORDERS_HEALTH" "$expected_code" "$expected_status" "$expected_database" <<'PY'
import json, sys, urllib.error, urllib.request
url, expected_code, expected_status, expected_database = sys.argv[1:]
try:
    response = urllib.request.urlopen(url, timeout=4)
except urllib.error.HTTPError as error:
    response = error
with response:
    code = response.status
    payload = json.load(response)
if (code, payload.get('service'), payload.get('status'), payload.get('database')) != (
        int(expected_code), 'orders-api', expected_status, expected_database):
    raise SystemExit(1)
PY
}

wait_orders_health() {
  local code="$1" status="$2" database="$3" seconds="$4"
  for ((i=0; i<seconds; i++)); do
    assert_orders_health "$code" "$status" "$database" 2>/dev/null && return 0
    sleep 1
  done
  return 1
}

ensure_demo_incident_absent() {
  local code
  code="$(curl -sS --max-time 5 -o /dev/null -w '%{http_code}' "$API_BASE/api/incidents/INC-DEMO-001" 2>/dev/null || true)"
  [ "$code" = '404' ] || die 'INC-DEMO-001 already exists. Stop the demo and run: scripts/demo.sh reset'
}

start_demo() {
  preflight
  if lsof -tiTCP:3000 -sTCP:LISTEN >/dev/null 2>&1; then
    die 'Port 3000 is already in use. Stop the existing backend before using this supervisor.'
  fi
  if lsof -tiTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then
    die 'Port 5173 is already in use. Stop the existing frontend before using this supervisor.'
  fi

  say 'Starting Docker infrastructure and waiting for PostgreSQL/orders-api health...'
  docker compose -f "$COMPOSE_FILE" up -d --build
  wait_orders_health 200 healthy healthy 90 || die 'orders-api did not reach the healthy baseline.'

  say 'Starting backend...'
  start_process backend "$BACKEND_DIR" npm start
  wait_http "$API_BASE/health" 200 45 || {
    tail -n 20 "$(log_file backend)" >&2 || true
    die 'Backend did not become healthy.'
  }
  ensure_demo_incident_absent

  say 'Starting frontend...'
  start_process frontend "$FRONTEND_DIR" npm run dev -- --port 5173 --strictPort
  wait_http "$DASHBOARD_URL" 200 45 || {
    tail -n 20 "$(log_file frontend)" >&2 || true
    die 'Frontend did not become ready.'
  }

  say 'Starting automatic Docker log watcher and LangGraph/Qwen investigation...'
  start_process watcher "$REASONER_DIR" .venv/bin/python -m llm_reasoner.log_watcher \
    --compose-file "$COMPOSE_FILE" --service orders-api --api-base "$API_BASE" --demo
  for _ in {1..30}; do
    grep -q '"watcher": "ready"' "$(log_file watcher)" 2>/dev/null && break
    is_running watcher || {
      tail -n 20 "$(log_file watcher)" >&2 || true
      die 'Log watcher exited during startup.'
    }
    sleep 1
  done
  grep -q '"watcher": "ready"' "$(log_file watcher)" 2>/dev/null || die 'Log watcher did not report ready.'

  say 'Ready. Dashboard: http://localhost:5173'
  say 'Trigger the outage with: scripts/demo.sh fail'
  say "Process logs: $STATE_DIR"
}

fail_demo() {
  preflight
  is_running backend || die 'Backend is not running under this demo supervisor.'
  is_running watcher || die 'Watcher is not running under this demo supervisor.'
  ensure_demo_incident_absent
  assert_orders_health 200 healthy healthy || die 'Refusing outage: orders-api is not at the healthy baseline.'
  say 'Stopping only the existing demo PostgreSQL service...'
  docker compose -f "$COMPOSE_FILE" stop postgres
  wait_orders_health 503 unhealthy unavailable 45 || die 'orders-api did not report the expected PostgreSQL outage.'
  say 'Outage verified. Waiting for automatic incident creation and investigation...'
  for ((i=0; i<180; i++)); do
    local state
    state="$(python3 - "$API_BASE/api/incidents/INC-DEMO-001" <<'PY' 2>/dev/null || true
import json, sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=3) as response:
    print(json.load(response).get('status', ''))
PY
)"
    if [ "$state" = 'DIAGNOSED' ]; then
      say 'Incident is DIAGNOSED and ready on the dashboard for human proposal review and approval.'
      say 'Open http://localhost:5173 and click Refresh.'
      return 0
    fi
    sleep 1
  done
  tail -n 30 "$(log_file watcher)" >&2 || true
  die 'Incident did not reach DIAGNOSED within 180 seconds.'
}

reset_demo() {
  reset_preflight
  stop_process watcher; stop_process frontend; stop_process backend
  if lsof -tiTCP:3000 -sTCP:LISTEN >/dev/null 2>&1; then
    die 'Port 3000 is still in use. Stop the backend before resetting demo data.'
  fi
  say 'Restoring the retained Docker infrastructure to a healthy baseline...'
  docker compose -f "$COMPOSE_FILE" up -d --build
  wait_orders_health 200 healthy healthy 90 || die 'Could not restore the healthy infrastructure baseline.'
  say 'Resetting only the terminal/non-executing INC-DEMO-001 record...'
  (cd "$BACKEND_DIR" && DEMO_RESET_CONFIRM=INC-DEMO-001 node scripts/reset-demo.mjs)
  docker compose -f "$COMPOSE_FILE" stop
  say 'Reset complete. Docker volumes were retained. Run: scripts/demo.sh start'
}

stop_demo() {
  stop_process watcher; stop_process frontend; stop_process backend
  docker compose -f "$COMPOSE_FILE" stop
  say 'Demo processes and Compose services stopped; MongoDB data and Docker volumes were retained.'
}

status_demo() {
  printf '%-10s %s\n' backend "$(is_running backend && echo running || echo stopped)"
  printf '%-10s %s\n' frontend "$(is_running frontend && echo running || echo stopped)"
  printf '%-10s %s\n' watcher "$(is_running watcher && echo running || echo stopped)"
  docker compose -f "$COMPOSE_FILE" ps -a
  python3 - "$API_BASE/api/incidents/INC-DEMO-001" <<'PY' 2>/dev/null || true
import json, sys, urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=3) as response:
    value=json.load(response)
print('incident   ' + value.get('status', 'unknown'))
print('workflow   ' + (value.get('remediation') or {}).get('state', 'none'))
PY
}

case "${1:-}" in
  start) start_demo ;;
  fail) fail_demo ;;
  reset) reset_demo ;;
  stop) stop_demo ;;
  status) status_demo ;;
  *) printf 'Usage: %s {reset|start|fail|status|stop}\n' "$0" >&2; exit 2 ;;
esac
