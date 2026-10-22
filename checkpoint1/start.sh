#!/usr/bin/env bash
# Start the Checkpoint 1 app. Everything it needs lives in this folder
# (frontend, dashboard, src, sample_service, evals).
#
#   bash start.sh local [ui|app]     # laptop: AWS CLI profile / SSO, UI on 127.0.0.1:5174
#   bash start.sh ec2 [ui|app]       # EC2: UI on 0.0.0.0:8001 (open the public IP in Safari)
#
# From the repo root on EC2:
#   bash scripts/deploy.sh checkpoint1
#
# Variants:
#   ui    Vite Checkpoint 1 dashboard (demo incidents). Default.
#   app   FastAPI in this folder, serving frontend/dist plus /api
#
# Environment (optional):
#   PORT          app listen port (default 8000)
#   CP1_PORT      ui listen port (default 5174 local, 8001 on ec2)
#   BIND_HOST     ec2 listen address (default 0.0.0.0)
set -euo pipefail

c_blue=$'\033[34m'; c_red=$'\033[31m'; c_grn=$'\033[32m'; c_off=$'\033[0m'
step() { echo; echo "${c_blue}==>${c_off} $*"; }
die()  { echo "${c_red}ERROR:${c_off} $*" >&2; exit 1; }
pass() { echo "  ${c_grn}PASS${c_off} $*"; }

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"

MODE="${1:-}"
VARIANT="${2:-ui}"
# Earlier docs used "full" for the API process. Same thing, now inside this folder.
if [[ "$VARIANT" == "full" || "$VARIANT" == "cp1" ]]; then
  [[ "$VARIANT" == "full" ]] && VARIANT="app"
  [[ "$VARIANT" == "cp1" ]] && VARIANT="ui"
fi
# EC2 demo is the Checkpoint 1 UI on 8001. Laptop dev stays on 5174.
if [[ "$MODE" == "ec2" ]]; then
  CP1_PORT="${CP1_PORT:-8001}"
else
  CP1_PORT="${CP1_PORT:-5174}"
fi
APP_PORT="${PORT:-8000}"

usage() {
  cat <<'EOF'
Start the Checkpoint 1 app from this folder.

  bash start.sh local [ui|app]     # laptop: AWS CLI profile / SSO (.env.deploy)
  bash start.sh ec2 [ui|app]       # EC2: UI on 0.0.0.0:8001

  bash scripts/deploy.sh checkpoint1   # same EC2 UI, from the repo root

Variants:
  ui    Vite dashboard with demo incidents (default)
  app   FastAPI + built frontend from this folder (port 8000)

Environment:
  PORT, CP1_PORT, BIND_HOST
  CP1_PORT defaults to 5174 on local and 8001 on ec2.
  BIND_HOST defaults to 0.0.0.0 on ec2.
EOF
}

ensure_node() {
  command -v node >/dev/null || die "Node.js 18+ required"
  node -e 'process.exit(+process.versions.node.split(".")[0] >= 18 ? 0 : 1)' || die "Node.js 18+ required"
  pass "node $(node --version)"
}

ensure_aws_cli() {
  command -v aws >/dev/null || die "AWS CLI required for credential check (install awscli v2)"
  pass "aws $(aws --version 2>&1 | head -1)"
}

aws_identity() {
  local out account region
  out="$(aws sts get-caller-identity --output json 2>&1)" || die "AWS credentials not available: $out"
  account="$(echo "$out" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["Account"])')"
  region="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
  if [[ -z "$region" ]]; then
    region="$(aws configure get region 2>/dev/null || true)"
  fi
  region="${region:-us-east-1}"
  export AWS_REGION="$region" AWS_DEFAULT_REGION="$region"
  pass "AWS account $account, region $region"
}

load_env_file() {
  local file="$1"
  set -a
  # shellcheck disable=SC1090
  source "$file"
  set +a
  pass "Loaded $file"
}

load_env_local() {
  if [[ -f "$APP_DIR/.env.deploy" ]]; then
    load_env_file "$APP_DIR/.env.deploy"
  elif [[ -f "$APP_DIR/../.env.deploy" ]]; then
    load_env_file "$APP_DIR/../.env.deploy"
    echo "  Tip: copy that file to $APP_DIR/.env.deploy so this folder stays self-contained."
  else
    echo "  (no .env.deploy — using the AWS CLI default credential chain)"
    echo "  Copy .env.deploy.example to .env.deploy in this folder to pin a profile."
  fi
  if [[ -n "${AWS_PROFILE:-}" ]]; then
    export AWS_PROFILE
    pass "AWS_PROFILE=$AWS_PROFILE"
  fi
}

load_env_ec2() {
  # Drop env keys and AWS_PROFILE so boto3/CLI use aws login, or an instance
  # role when one is attached. App mode installs botocore[crt] for aws login.
  unset AWS_PROFILE AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  if [[ -f "$APP_DIR/.env.deploy" ]]; then
    local line
    while IFS= read -r line || [[ -n "$line" ]]; do
      [[ "$line" =~ ^AWS_REGION= ]] && export "${line%%#*}"
      [[ "$line" =~ ^AWS_DEFAULT_REGION= ]] && export "${line%%#*}"
    done < "$APP_DIR/.env.deploy"
  fi
  export AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
  export AWS_DEFAULT_REGION="$AWS_REGION"
  pass "AWS credential chain: aws login or instance role (profile unset)"
}

ensure_python_app() {
  command -v "$PY" >/dev/null || die "python3 not found"
  export PYTHONPATH="${APP_DIR}/src:${APP_DIR}${PYTHONPATH:+:$PYTHONPATH}"
  if [[ -x "$APP_DIR/.venv/bin/python" ]]; then
    PY="$APP_DIR/.venv/bin/python"
  fi
  if ! "$PY" -c 'import fastapi, uvicorn, boto3, strands' >/dev/null 2>&1; then
    step "Python deps missing — creating ${APP_DIR}/.venv"
    command -v "$PY" >/dev/null || die "python3 not found"
    local base="${PYTHON:-python3}"
    "$base" -m venv "$APP_DIR/.venv"
    "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" 'botocore[crt]'
    PY="$APP_DIR/.venv/bin/python"
  fi
  # aws login credentials are invisible to boto3 until the crt extra is installed.
  # UI mode never calls this function.
  if ! "$PY" -c 'import awscrt' >/dev/null 2>&1; then
    step "Installing botocore[crt] so aws login credentials work with boto3"
    "$PY" -m pip install 'botocore[crt]'
  fi
  "$PY" -c 'import awscrt' >/dev/null 2>&1 \
    || die "botocore[crt] is required so boto3 can use aws login credentials"
  pass "$("$PY" --version) (PYTHONPATH includes this folder)"
}

# Print the URL to open just before the process is replaced by the server.
announce_ec2_url() {
  local host="$1"
  local port="$2"
  local public_ip="" token=""
  if command -v curl >/dev/null 2>&1; then
    token="$(curl -fsS -m 2 -X PUT "http://169.254.169.254/latest/api/token" \
      -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null || true)"
    token="${token//$'\r'/}"
    token="${token//$'\n'/}"
    if [[ -n "$token" ]]; then
      public_ip="$(curl -fsS -m 2 \
        -H "X-aws-ec2-metadata-token: $token" \
        "http://169.254.169.254/latest/meta-data/public-ipv4" 2>/dev/null || true)"
    fi
  fi
  public_ip="${public_ip//$'\r'/}"
  public_ip="${public_ip//$'\n'/}"
  echo
  if [[ "$public_ip" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}$ ]]; then
    echo "  ${c_grn}Open in Safari:${c_off} http://${public_ip}:${port}"
  else
    echo "  Public IPv4 lookup failed. Listening on ${host}:${port}"
  fi
  echo "  Allow inbound TCP ${port} from your IP in the instance security group."
}

start_ui_dev() {
  local host="$1"
  step "Checkpoint 1 UI (dev) on http://${host}:${CP1_PORT}"
  ensure_node
  cd "$APP_DIR/frontend"
  if [[ ! -d node_modules ]]; then npm install; fi
  exec npm run dev -- --host "$host" --port "$CP1_PORT"
}

start_ui_preview() {
  local host="$1"
  step "Checkpoint 1 UI (preview) on http://${host}:${CP1_PORT}"
  ensure_node
  cd "$APP_DIR/frontend"
  npm install
  npm run build
  if [[ "$MODE" == "ec2" ]]; then
    announce_ec2_url "$host" "$CP1_PORT"
  fi
  exec npm run preview -- --host "$host" --port "$CP1_PORT" --strictPort
}

start_app() {
  local host="$1"
  step "Checkpoint 1 API + UI on http://${host}:${APP_PORT}"
  ensure_python_app
  ensure_node
  if [[ ! -f "$APP_DIR/frontend/dist/index.html" ]]; then
    (cd "$APP_DIR/frontend" && npm install && npm run build)
  fi
  cd "$APP_DIR"
  if [[ "$MODE" == "ec2" ]]; then
    announce_ec2_url "$host" "$APP_PORT"
  fi
  exec "$PY" -m uvicorn dashboard.app:dashboard_app --host "$host" --port "$APP_PORT"
}

case "$MODE" in
  local)
    step "Local startup (AWS CLI credential chain)"
    load_env_local
    ensure_aws_cli
    aws_identity
    case "$VARIANT" in
      ui)  start_ui_dev "127.0.0.1" ;;
      app) start_app "127.0.0.1" ;;
      *)   die "unknown variant '$VARIANT' (use ui or app)" ;;
    esac
    ;;
  ec2)
    EC2_HOST="${BIND_HOST:-0.0.0.0}"
    step "EC2 startup (Checkpoint 1, bind ${EC2_HOST})"
    case "$VARIANT" in
      ui)
        echo "  Checkpoint 1 UI does not need AWS credentials."
        start_ui_preview "$EC2_HOST"
        ;;
      app)
        load_env_ec2
        ensure_aws_cli
        aws_identity
        start_app "$EC2_HOST"
        ;;
      *) die "unknown variant '$VARIANT' (use ui or app)" ;;
    esac
    ;;
  -h|--help|help|"")
    usage
    exit 0
    ;;
  *)
    die "unknown mode '$MODE' (use local or ec2). Run: bash start.sh help"
    ;;
esac
