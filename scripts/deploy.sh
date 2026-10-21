#!/usr/bin/env bash
# OpsPilot one-shot deploy: CoreStack + SampleServiceStack + PipelineStack.
#
#   bash scripts/deploy.sh                # = up: preflight -> bootstrap -> synth -> deploy -> seed -> secrets -> verify
#   bash scripts/deploy.sh preflight      # tools, Python deps, AWS identity, config, Bedrock access
#   bash scripts/deploy.sh synth          # build Lambda assets + CloudFormation into cdk.out (no AWS writes)
#   bash scripts/deploy.sh diff           # what would change in the account
#   bash scripts/deploy.sh seed           # push this checkout to the CodeCommit repo's main (RESEED=1 to re-push)
#   bash scripts/deploy.sh secrets        # (re)write the optional Slack secret from env (ticketing needs none)
#   bash scripts/deploy.sh verify         # post-deploy smoke test (stacks, Lambdas, wiring, alarms, live URL)
#   bash scripts/deploy.sh outputs        # print stack outputs
#   bash scripts/deploy.sh dashboard      # build the frontend and run the OpsPilot dashboard locally
#   bash scripts/deploy.sh destroy        # tear everything down (asks first unless YES=1)
#
# Config comes from the environment or a .env.deploy file at the repo root
# (see .env.deploy.example). Nothing here needs the AWS CLI or Docker.
set -euo pipefail

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
# Source control is AWS CodeCommit (IAM auth, no tokens). CoreStack creates the repo, or imports it if it exists.
export CODECOMMIT_REPO="${CODECOMMIT_REPO:-opspilot-aws}"
export BEDROCK_MODEL_ID="${BEDROCK_MODEL_ID:-us.anthropic.claude-haiku-5-5}"
OUTPUTS_FILE="$ROOT/cdk-outputs.json"

c_blue=$'\033[34m'; c_red=$'\033[31m'; c_yel=$'\033[33m'; c_grn=$'\033[32m'; c_off=$'\033[0m'
step() { echo; echo "${c_blue}==>${c_off} $*"; }
die()  { echo "${c_red}ERROR:${c_off} $*" >&2; exit 1; }
warn() { echo "  ${c_yel}WARN${c_off} $*"; }
pass() { echo "  ${c_grn}PASS${c_off} $*"; }

resolve_env() {
  # app.py falls back to a fake account (123456789012) without these, so always set them from STS.
  local who
  who="$("$PY" scripts/deploy_check.py whoami)" \
    || die "no AWS credentials. Set AWS_PROFILE (or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY) and AWS_REGION, e.g. in .env.deploy"
  export CDK_DEFAULT_ACCOUNT="${who% *}"
  export CDK_DEFAULT_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-${who#* }}}"
  export AWS_REGION="$CDK_DEFAULT_REGION" AWS_DEFAULT_REGION="$CDK_DEFAULT_REGION"
  # A repo kept from an earlier deploy (RETAIN) or pre-created by the event team is imported, not re-created.
  if [[ -z "${CODECOMMIT_REPO_EXISTS:-}" ]]; then
    if "$PY" scripts/deploy_check.py repo-status; then export CODECOMMIT_REPO_EXISTS=1; else export CODECOMMIT_REPO_EXISTS=0; fi
  fi
}

preflight() {
  step "Preflight"
  command -v "$PY" >/dev/null || die "python3 not found"
  "$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || die "Python 3.10+ required"
  pass "$("$PY" --version)"
  command -v node >/dev/null || die "Node.js 18+ required for the CDK CLI"
  node -e 'process.exit(+process.versions.node.split(".")[0] >= 18 ? 0 : 1)' || die "Node.js 18+ required"
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
    pass "CodeCommit repo $CODECOMMIT_REPO exists; CoreStack will import it"
  else
    pass "CodeCommit repo $CODECOMMIT_REPO will be created by CoreStack"
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
  if [[ ! -f frontend/dist/index.html || "${REBUILD_FRONTEND:-0}" == 1 ]]; then
    (cd frontend && npm ci && npm run build)
  fi
  exec "$PY" -m uvicorn dashboard.app:dashboard_app --host 0.0.0.0 --port "${PORT:-8000}"
}

destroy() {
  resolve_env
  step "Destroy all OpsPilot stacks in $CDK_DEFAULT_ACCOUNT/$CDK_DEFAULT_REGION"
  if [[ "${YES:-0}" != 1 ]]; then
    read -r -p "Type 'destroy' to confirm: " ans; [[ "$ans" == destroy ]] || die "aborted"
  fi
  $CDK destroy "${CDK_APP[@]}" --all --force
  echo "Note: Secrets Manager keeps opspilot/* secrets for a 7-30 day recovery window."
  echo "Note: CodeCommit repo $CODECOMMIT_REPO is retained (fix PRs survive); the next deploy imports it."
}

cmd="${1:-up}"
case "$cmd" in
  up)        preflight; bootstrap; synth; deploy; seed; secrets; verify; next_steps ;;
  preflight) preflight ;;
  bootstrap) resolve_env; bootstrap ;;
  synth)     if [[ "${OFFLINE:-0}" == 1 ]]; then export CDK_DEFAULT_ACCOUNT=123456789012 CDK_DEFAULT_REGION=us-east-1; else resolve_env; fi; synth ;;
  diff)      resolve_env; $CDK diff "${CDK_APP[@]}" --all ;;
  deploy)    resolve_env; deploy ;;
  seed)      resolve_env; seed ;;
  secrets)   resolve_env; secrets ;;
  verify)    resolve_env; verify ;;
  outputs)   resolve_env; "$PY" scripts/deploy_check.py outputs ;;
  dashboard) dashboard ;;
  destroy)   destroy ;;
  -h|--help|help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//' ;;
  *) die "unknown command '$cmd' (try: bash scripts/deploy.sh help)" ;;
esac
