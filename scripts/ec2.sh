#!/usr/bin/env bash
# EC2 demo control for the already-deployed OpsPilot stacks.
#
#   bash scripts/ec2.sh startup [dashboard|checkpoint1|all]
#   bash scripts/ec2.sh kill [dashboard|checkpoint1|all]
#   bash scripts/ec2.sh restart [dashboard|checkpoint1|all]
#   bash scripts/ec2.sh redeploy          # git pull, then update the three CloudFormation stacks
#   bash scripts/ec2.sh fix               # git pull, restart the main dashboard (Raise PR region fix)
#   bash scripts/ec2.sh status
#   bash scripts/ec2.sh logs [dashboard|checkpoint1]
#   bash scripts/ec2.sh login             # aws login (remote code when run on the instance)
#   bash scripts/ec2.sh verify
#   bash scripts/ec2.sh open-ports        # inbound TCP 8000 and 8001, idempotent
#   bash scripts/ec2.sh help
#
# Run from anywhere. The script cds to the repo root.
# Dashboard:  http://<public-ip>:8000   log /tmp/dashboard.log
# Checkpoint 1 UI: http://<public-ip>:8001   log /tmp/checkpoint1.log
# redeploy updates the existing stacks. It does not create a second copy and it does not destroy.
set -euo pipefail

c_blue=$'\033[34m'; c_red=$'\033[31m'; c_yel=$'\033[33m'; c_grn=$'\033[32m'; c_off=$'\033[0m'
step() { echo; echo "${c_blue}==>${c_off} $*"; }
die()  { echo "${c_red}ERROR:${c_off} $*" >&2; exit 1; }
warn() { echo "  ${c_yel}WARN${c_off} $*"; }
pass() { echo "  ${c_grn}PASS${c_off} $*"; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

DASH_PORT="${PORT:-8000}"
CP1_PORT="${CP1_PORT:-8001}"
DASH_LOG=/tmp/dashboard.log
CP1_LOG=/tmp/checkpoint1.log
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"

usage() {
  cat <<EOF
EC2 demo control. Run on the instance, from the repo:

  bash scripts/ec2.sh startup [dashboard|checkpoint1|all]   # default all
  bash scripts/ec2.sh kill [dashboard|checkpoint1|all]      # default all
  bash scripts/ec2.sh restart [dashboard|checkpoint1|all]   # kill, then startup
  bash scripts/ec2.sh redeploy                              # git pull --ff-only, then bash scripts/deploy.sh
  bash scripts/ec2.sh fix                                   # git pull, restart dashboard only (Raise PR)
  bash scripts/ec2.sh status
  bash scripts/ec2.sh logs [dashboard|checkpoint1]          # last 80 lines, default dashboard
  bash scripts/ec2.sh login                                 # aws login; on EC2 prints a URL and code
  bash scripts/ec2.sh verify                                # bash scripts/deploy.sh verify
  bash scripts/ec2.sh open-ports                            # TCP ${DASH_PORT} and ${CP1_PORT} on this instance
  bash scripts/ec2.sh help

Dashboard is http://<public-ip>:${DASH_PORT} (log ${DASH_LOG}).
Checkpoint 1 UI is http://<public-ip>:${CP1_PORT} (log ${CP1_LOG}).
redeploy updates the existing CloudFormation stacks in ${REGION}. It does not destroy them.
EOF
}

ensure_venv() {
  [[ -x "$ROOT/.venv/bin/python" ]] || die "missing .venv. From the repo root, without sudo:
  python3.11 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt 'botocore[crt]'"
  # shellcheck disable=SC1091
  source "$ROOT/.venv/bin/activate"
  export PYTHON="$ROOT/.venv/bin/python"
  export AWS_REGION="$REGION"
  export AWS_DEFAULT_REGION="$REGION"
}

public_ip() {
  local token ip=""
  token="$(curl -fsS -m 2 -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null || true)"
  token="${token//$'\r'/}"
  token="${token//$'\n'/}"
  if [[ -n "$token" ]]; then
    ip="$(curl -fsS -m 2 -H "X-aws-ec2-metadata-token: $token" \
      "http://169.254.169.254/latest/meta-data/public-ipv4" 2>/dev/null || true)"
  fi
  ip="${ip//$'\r'/}"
  ip="${ip//$'\n'/}"
  if [[ "$ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    printf '%s\n' "$ip"
  fi
}

imds_token() {
  curl -fsS -m 2 -X PUT "http://169.254.169.254/latest/api/token" \
    -H "X-aws-ec2-metadata-token-ttl-seconds: 21600"
}

port_listening() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn | grep -qE ":${port}[[:space:]]"
  else
    (echo >/dev/tcp/127.0.0.1/"$port") >/dev/null 2>&1
  fi
}

listener_pids() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -H -ltnp "sport = :${port}" 2>/dev/null | sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' | sort -u
  fi
}

stop_matching() {
  local pattern="$1"
  if pgrep -f "$pattern" >/dev/null 2>&1; then
    pkill -f "$pattern" || true
    pass "stopped processes matching: $pattern"
  fi
}

kill_dashboard() {
  stop_matching "uvicorn dashboard.app:dashboard_app"
  stop_matching "bash scripts/deploy.sh dashboard"
  local pid
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    kill "$pid" 2>/dev/null || true
    pass "stopped pid $pid on port ${DASH_PORT}"
  done < <(listener_pids "$DASH_PORT")
}

kill_checkpoint1() {
  stop_matching "checkpoint1/start.sh ec2"
  stop_matching "bash scripts/deploy.sh checkpoint1"
  stop_matching "vite preview --host"
  stop_matching "npm run preview -- --host"
  local pid
  while read -r pid; do
    [[ -n "$pid" ]] || continue
    kill "$pid" 2>/dev/null || true
    pass "stopped pid $pid on port ${CP1_PORT}"
  done < <(listener_pids "$CP1_PORT")
}

wait_until_free() {
  local port="$1"
  local i
  for i in 1 2 3 4 5; do
    port_listening "$port" || return 0
    sleep 1
  done
  warn "port ${port} is still in use"
}

print_url() {
  local port="$1" label="$2" ip
  ip="$(public_ip || true)"
  if [[ -n "$ip" ]]; then
    echo "  ${label}: http://${ip}:${port}"
  else
    echo "  ${label}: listening on 0.0.0.0:${port} (public IPv4 lookup failed)"
  fi
}

start_dashboard() {
  if port_listening "$DASH_PORT"; then
    pass "dashboard already listening on ${DASH_PORT}"
    print_url "$DASH_PORT" "Dashboard"
    return 0
  fi
  step "Starting dashboard on 0.0.0.0:${DASH_PORT}"
  nohup bash "$ROOT/scripts/deploy.sh" dashboard >"$DASH_LOG" 2>&1 &
  pass "pid $! log ${DASH_LOG}"
  print_url "$DASH_PORT" "Dashboard"
  echo "  First start builds the frontend. Wait, then: bash scripts/ec2.sh status"
}

start_checkpoint1() {
  if port_listening "$CP1_PORT"; then
    pass "Checkpoint 1 already listening on ${CP1_PORT}"
    print_url "$CP1_PORT" "Checkpoint 1"
    return 0
  fi
  step "Starting Checkpoint 1 UI on 0.0.0.0:${CP1_PORT}"
  nohup bash "$ROOT/scripts/deploy.sh" checkpoint1 >"$CP1_LOG" 2>&1 &
  pass "pid $! log ${CP1_LOG}"
  print_url "$CP1_PORT" "Checkpoint 1"
  echo "  First start builds the UI. Wait, then: bash scripts/ec2.sh status"
}

normalize_target() {
  case "${1:-all}" in
    dashboard|checkpoint1|all) printf '%s\n' "$1" ;;
    "") printf 'all\n' ;;
    *) die "unknown target '$1' (use dashboard, checkpoint1, or all)" ;;
  esac
}

cmd_startup() {
  local target
  target="$(normalize_target "${1:-all}")"
  ensure_venv
  case "$target" in
    dashboard) start_dashboard ;;
    checkpoint1) start_checkpoint1 ;;
    all) start_dashboard; start_checkpoint1 ;;
  esac
}

cmd_kill() {
  local target
  target="$(normalize_target "${1:-all}")"
  step "Stopping ${target}"
  case "$target" in
    dashboard) kill_dashboard; wait_until_free "$DASH_PORT" ;;
    checkpoint1) kill_checkpoint1; wait_until_free "$CP1_PORT" ;;
    all) kill_dashboard; kill_checkpoint1; wait_until_free "$DASH_PORT"; wait_until_free "$CP1_PORT" ;;
  esac
  pass "kill ${target} done"
}

cmd_restart() {
  local target
  target="$(normalize_target "${1:-all}")"
  cmd_kill "$target"
  cmd_startup "$target"
}

cmd_redeploy() {
  ensure_venv
  step "git pull --ff-only"
  git pull --ff-only
  step "Updating existing stacks (bash scripts/deploy.sh)"
  echo "  This updates OpsPilotCoreStack, OpsPilotSampleServiceStack, and OpsPilotPipelineStack."
  echo "  It does not create a second copy and it does not destroy."
  bash "$ROOT/scripts/deploy.sh"
}

cmd_fix() {
  ensure_venv
  step "git pull --ff-only"
  git pull --ff-only
  cmd_kill dashboard
  cmd_startup dashboard
  echo
  echo "  Raise PR again on the dashboard. CodeCommit now gets region ${REGION}."
}

cmd_status() {
  local ip
  ip="$(public_ip || true)"
  step "Status"
  if [[ -n "$ip" ]]; then
    echo "  public ip ${ip}"
  else
    warn "public IPv4 lookup failed (not on EC2, or IMDS is blocked)"
  fi
  if port_listening "$DASH_PORT"; then
    pass "dashboard listening on ${DASH_PORT} $(listener_pids "$DASH_PORT" | tr '\n' ' ')"
    [[ -n "$ip" ]] && echo "  http://${ip}:${DASH_PORT}"
  else
    warn "dashboard is not listening on ${DASH_PORT}"
  fi
  if port_listening "$CP1_PORT"; then
    pass "checkpoint1 listening on ${CP1_PORT} $(listener_pids "$CP1_PORT" | tr '\n' ' ')"
    [[ -n "$ip" ]] && echo "  http://${ip}:${CP1_PORT}"
  else
    warn "checkpoint1 is not listening on ${CP1_PORT}"
  fi
  echo
  echo "  ${DASH_LOG}:"
  tail -n 5 "$DASH_LOG" 2>/dev/null || echo "  (no dashboard log yet)"
  echo "  ${CP1_LOG}:"
  tail -n 5 "$CP1_LOG" 2>/dev/null || echo "  (no checkpoint1 log yet)"
}

cmd_logs() {
  local which="${1:-dashboard}" log
  case "$which" in
    dashboard) log="$DASH_LOG" ;;
    checkpoint1) log="$CP1_LOG" ;;
    *) die "unknown log '$which' (use dashboard or checkpoint1)" ;;
  esac
  [[ -f "$log" ]] || die "no log at $log"
  tail -n 80 "$log"
}

cmd_login() {
  command -v aws >/dev/null 2>&1 || die "aws CLI is not installed. Install 2.32.0 or later: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
  export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
  if ! aws login help >/dev/null 2>&1; then
    die "aws login needs AWS CLI 2.32.0 or later. Update: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
  fi
  step "AWS login (${REGION})"
  if imds_token >/dev/null 2>&1; then
    aws login --remote --region "$REGION"
  else
    aws login --region "$REGION"
  fi
}

cmd_verify() {
  ensure_venv
  bash "$ROOT/scripts/deploy.sh" verify
}

cmd_open_ports() {
  local token mac sgs sg port err
  command -v aws >/dev/null 2>&1 || die "aws CLI is not installed"
  export AWS_REGION="$REGION" AWS_DEFAULT_REGION="$REGION"
  token="$(imds_token)" || die "IMDS token failed. Run this on the EC2 instance."
  mac="$(curl -fsS -m 2 -H "X-aws-ec2-metadata-token: $token" \
    "http://169.254.169.254/latest/meta-data/mac")"
  sgs="$(curl -fsS -m 2 -H "X-aws-ec2-metadata-token: $token" \
    "http://169.254.169.254/latest/meta-data/network/interfaces/macs/${mac}/security-group-ids")"
  [[ -n "$sgs" ]] || die "no security group ids from IMDS"
  step "Opening TCP ${DASH_PORT} and ${CP1_PORT} in ${REGION}"
  while read -r sg; do
    [[ -n "$sg" ]] || continue
    for port in "$DASH_PORT" "$CP1_PORT"; do
      err="$(mktemp)"
      if aws ec2 authorize-security-group-ingress \
        --region "$REGION" \
        --group-id "$sg" \
        --protocol tcp \
        --port "$port" \
        --cidr 0.0.0.0/0 2>"$err"; then
        pass "${sg} tcp/${port} opened"
      elif grep -q "InvalidPermission.Duplicate" "$err"; then
        pass "${sg} tcp/${port} already open"
      else
        cat "$err" >&2
        rm -f "$err"
        die "could not open ${sg} tcp/${port}"
      fi
      rm -f "$err"
    done
  done <<<"$sgs"
}

cmd="${1:-help}"
shift || true
case "$cmd" in
  startup) cmd_startup "${1:-all}" ;;
  kill|stop) cmd_kill "${1:-all}" ;;
  restart) cmd_restart "${1:-all}" ;;
  redeploy) cmd_redeploy ;;
  fix) cmd_fix ;;
  status) cmd_status ;;
  logs) cmd_logs "${1:-dashboard}" ;;
  login) cmd_login ;;
  verify) cmd_verify ;;
  open-ports) cmd_open_ports ;;
  help|-h|--help) usage ;;
  *) die "unknown command '$cmd'. Run: bash scripts/ec2.sh help" ;;
esac
