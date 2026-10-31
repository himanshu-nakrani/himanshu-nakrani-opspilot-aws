#!/usr/bin/env bash
# OpsPilot one-shot deploy: CoreStack + SampleServiceStack + PipelineStack.
#
#   bash scripts/deploy.sh                # = up: preflight -> bootstrap -> synth -> deploy -> seed -> seed-knowledge -> secrets -> verify
#   bash scripts/deploy.sh preflight      # tools, Python deps, AWS identity, config, Bedrock access
#   bash scripts/deploy.sh synth          # build Lambda assets + CloudFormation into cdk.out (no AWS writes)
#   bash scripts/deploy.sh diff           # what would change in the account
#   bash scripts/deploy.sh seed           # push this checkout to the CodeCommit repo's main (RESEED=1 to re-push)
#   bash scripts/deploy.sh seed-knowledge # upload sample runbooks and sync the one knowledge base
#   bash scripts/deploy.sh secrets        # (re)write the optional Slack secret from env (ticketing needs none)
#   bash scripts/deploy.sh verify         # post-deploy smoke test (stacks, Lambdas, wiring, alarms, live URL)
#   bash scripts/deploy.sh outputs        # print stack outputs
#   bash scripts/deploy.sh dashboard      # build the frontend and run the OpsPilot dashboard locally
#   bash scripts/deploy.sh checkpoint1    # Checkpoint 1 UI on 0.0.0.0:8001 (EC2 demo, not the full dashboard)
#   bash scripts/deploy.sh destroy        # tear everything down (asks first unless YES=1)
#
# Config comes from the environment or a .env.deploy file at the repo root
# (see .env.deploy.example). Nothing here needs the AWS CLI or Docker.
set -euo pipefail

c_blue=$'\033[34m'; c_red=$'\033[31m'; c_yel=$'\033[33m'; c_grn=$'\033[32m'; c_off=$'\033[0m'
step() { echo; echo "${c_blue}==>${c_off} $*"; }
die()  { echo "${c_red}ERROR:${c_off} $*" >&2; exit 1; }
warn() { echo "  ${c_yel}WARN${c_off} $*"; }
pass() { echo "  ${c_grn}PASS${c_off} $*"; }

# Unset -> 0 so CoreStack keeps the repo. Never overwrite a value the operator already exported.
apply_codecommit_repo_exists_default() {
  if [[ -z "${CODECOMMIT_REPO_EXISTS+x}" ]]; then
    export CODECOMMIT_REPO_EXISTS=0
  fi
}

resolve_env() {
  # app.py falls back to a fake account (123456789012) without these, so always set them from STS.
  local who
  who="$("$PY" scripts/deploy_check.py whoami)" \
    || die "no AWS credentials. Set AWS_PROFILE (or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY) and AWS_REGION, e.g. in .env.deploy"
  export CDK_DEFAULT_ACCOUNT="${who% *}"
  export CDK_DEFAULT_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-${who#* }}}"
  export AWS_REGION="$CDK_DEFAULT_REGION" AWS_DEFAULT_REGION="$CDK_DEFAULT_REGION"
  # Do not probe CodeCommit. Importing an existing repo detaches it from CoreStack.
  apply_codecommit_repo_exists_default
}

preflight() {
  step "Preflight"
  command -v "$PY" >/dev/null || die "python3 not found"
  "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || die "Python 3.10+ required"
  pass "$("$PY" --version)"
  command -v node >/dev/null || die "Node.js 20.19+/22.12+ required (CDK CLI and the Vite 8 frontend build)"
  # Vite 8 engines: ^20.19.0 || >=22.12.0 — the dashboard build runs in preflight-adjacent paths.
  node -e 'const [M, m] = process.versions.node.split(".").map(Number); process.exit(M > 22 || (M === 22 && m >= 12) || (M === 20 && m >= 19) ? 0 : 1)' \
    || die "Node.js 20.19+/22.12+ required (found $(node --version))"
  pass "node $(node --version)"
  "$PY" -c 'import aws_cdk, constructs, boto3' 2>/dev/null \
    || die "Python deps missing. Run: $PY -m pip install -r requirements.txt  (inside a venv)"
  pass "aws-cdk-lib, constructs, boto3 importable"
  "$PY" -m pip --version >/dev/null 2>&1 || command -v uv >/dev/null \
    || die "pip or uv is needed to bundle Lambda dependencies"
  pass "Lambda bundler available (pip/uv; Docker not required)"

  resolve_env
  pass "AWS account $CDK_DEFAULT_ACCOUNT, region $CDK_DEFAULT_REGION"

  [[ "$CODECOMMIT_REPO" =~ ^[A-Za-z0-9_.-]{1,100}$ ]] || die "CODECOMMIT_REPO must be a CodeCommit repo name (got '$CODECOMMIT_REPO')"
  if [[ "${CODECOMMIT_REPO_EXISTS:-}" == 1 ]]; then
    pass "CoreStack will import CodeCommit repo $CODECOMMIT_REPO"
  else
    pass "CoreStack will own CodeCommit repo $CODECOMMIT_REPO"
  fi
  "$PY" scripts/deploy_check.py opscenter
  "$PY" scripts/deploy_check.py bedrock
}

bootstrap() {
  step "CDK bootstrap (aws://$CDK_DEFAULT_ACCOUNT/$CDK_DEFAULT_REGION)"
  if "$PY" scripts/deploy_check.py bootstrap-status; then
    pass "CDKToolkit already deployed"
  else
    $CDK bootstrap "${CDK_APP[@]}" "aws://$CDK_DEFAULT_ACCOUNT/$CDK_DEFAULT_REGION"
  fi
}

synth() {
  step "Synth (bundles every Lambda for Linux/cp312)"
  $CDK synth "${CDK_APP[@]}" --quiet
  pass "templates in cdk.out/: $(ls cdk.out/*.template.json | xargs -n1 basename | tr '\n' ' ')"
}

deploy() {
  step "Deploy OpsPilotCoreStack -> OpsPilotSampleServiceStack -> OpsPilotPipelineStack"
  $CDK deploy "${CDK_APP[@]}" --all --require-approval never --outputs-file "$OUTPUTS_FILE"
  pass "outputs written to $(basename "$OUTPUTS_FILE")"
}

seed()    { step "Seed CodeCommit repo $CODECOMMIT_REPO"; "$PY" scripts/deploy_check.py seed-repo; }
seed_knowledge() { step "Seed knowledge base"; "$PY" scripts/deploy_check.py seed-knowledge; }
secrets() { step "Third-party secrets"; "$PY" scripts/deploy_check.py secrets; }
verify()  { step "Verify";            "$PY" scripts/deploy_check.py verify; }

next_steps() {
  cat <<TXT

${c_grn}Deployed.${c_off} Next:
  python3 scripts/demo_faults.py list
  python3 scripts/demo_faults.py orders --watch     # alarm in ~1-2 min, then the OpsPilot run
  bash scripts/deploy.sh dashboard                        # local OpsPilot dashboard on :8000
Tear down after the demo: bash scripts/deploy.sh destroy
TXT
}

dashboard() {
  step "Dashboard"
  # The dashboard opens CodeCommit pull requests. boto3 raises "You must specify a region"
  # when AWS_REGION is unset, even if the CLI login config has one.
  export AWS_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-east-1}}"
  export AWS_DEFAULT_REGION="$AWS_REGION"
  # aws login stores a CLI session. boto3 only sees it after the keys are exported.
  if [[ -z "${AWS_ACCESS_KEY_ID:-}" ]] && command -v aws >/dev/null 2>&1; then
    if creds="$(aws configure export-credentials --format env 2>/dev/null)"; then
      eval "$creds"
    fi
  fi
  if [[ ! -f frontend/dist/index.html || "${REBUILD_FRONTEND:-0}" == 1 ]]; then
    (cd frontend && npm ci && npm run build)
  fi
  exec "$PY" -m uvicorn dashboard.app:dashboard_app --host 0.0.0.0 --port "${PORT:-8000}"
}

# Hackathon demo: Checkpoint 1 UI, not the repo-root dashboard.
# Delegates to checkpoint1/start.sh ec2, which listens on 0.0.0.0:8001.
checkpoint1() {
  local variant="${1:-ui}"
  step "Checkpoint 1"
  [[ -n "${ROOT:-}" && -f "$ROOT/checkpoint1/start.sh" ]] || die "missing checkpoint1/start.sh"
  exec bash "$ROOT/checkpoint1/start.sh" ec2 "$variant"
}

destroy() {
  resolve_env
  step "Destroy all OpsPilot stacks in $CDK_DEFAULT_ACCOUNT/$CDK_DEFAULT_REGION"
  if [[ "${YES:-0}" != 1 ]]; then
    read -r -p "Type 'destroy' to confirm: " ans; [[ "$ans" == destroy ]] || die "aborted"
  fi
  $CDK destroy "${CDK_APP[@]}" --all --force
  echo "Note: Secrets Manager keeps opspilot/* secrets for a 7-30 day recovery window."
  echo "Note: CodeCommit repo $CODECOMMIT_REPO is retained (fix PRs survive). A later deploy keeps it in CoreStack unless CODECOMMIT_REPO_EXISTS was already exported as 1."
}

# Sourcing this file (tests) loads functions only: no .env.deploy, no deploy command.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  return 0
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

[[ -f .env.deploy ]] && { set -a; source .env.deploy; set +a; }

PY="${PYTHON:-python3}"
CDK="npx -y aws-cdk@2"
# Run the CDK app with the same interpreter as the checks (cdk.json hardcodes python3, which may not be the venv).
CDK_APP=(--app "$PY infra/app.py")
export PYTHONPATH="src:.${PYTHONPATH:+:$PYTHONPATH}"
# jsii refuses a group-writable ~/.cache; a private cache dir avoids that.
export JSII_RUNTIME_PACKAGE_CACHE_ROOT="${JSII_RUNTIME_PACKAGE_CACHE_ROOT:-/tmp/jsii-cache-$(id -u)}"
# Source control is AWS CodeCommit (IAM auth, no tokens). CoreStack owns the repo.
# An unset CODECOMMIT_REPO_EXISTS becomes 0. Export 1 before running this script to import instead.
export CODECOMMIT_REPO="${CODECOMMIT_REPO:-opspilot-aws}"
export BEDROCK_MODEL_ID="${BEDROCK_MODEL_ID:-us.moonshotai.kimi-k3}"
OUTPUTS_FILE="$ROOT/cdk-outputs.json"

apply_codecommit_repo_exists_default

cmd="${1:-up}"
case "$cmd" in
  up)        preflight; bootstrap; synth; deploy; seed; seed_knowledge; secrets; verify; next_steps ;;
  preflight) preflight ;;
  bootstrap) resolve_env; bootstrap ;;
  synth)     if [[ "${OFFLINE:-0}" == 1 ]]; then export CDK_DEFAULT_ACCOUNT=123456789012 CDK_DEFAULT_REGION=us-east-1; else resolve_env; fi; synth ;;
  diff)      resolve_env; $CDK diff "${CDK_APP[@]}" --all ;;
  deploy)    resolve_env; deploy ;;
  seed)      resolve_env; seed ;;
  seed-knowledge) resolve_env; seed_knowledge ;;
  secrets)   resolve_env; secrets ;;
  verify)    resolve_env; verify ;;
  outputs)   resolve_env; "$PY" scripts/deploy_check.py outputs ;;
  dashboard) dashboard ;;
  checkpoint1) checkpoint1 "${2:-ui}" ;;
  destroy)   destroy ;;
  -h|--help|help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "unknown command '$cmd' (try: bash scripts/deploy.sh help)" ;;
esac
