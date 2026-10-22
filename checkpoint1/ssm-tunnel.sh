#!/usr/bin/env bash
# Forward a port from your laptop to the same port on an EC2 instance (SSM Session Manager).
# Run this on your laptop while the app listens on the instance (see checkpoint1/start.sh ec2).
#
#   bash ssm-tunnel.sh i-0123456789abcdef0           # default remote/local 8000
#   bash ssm-tunnel.sh i-0123456789abcdef0 5174      # Checkpoint 1 UI
#   bash ssm-tunnel.sh i-0123456789abcdef0 8000 18000
#
# Requires: AWS CLI v2, session-manager-plugin, and local credentials (AWS_PROFILE / SSO).
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTANCE_ID="${1:?usage: ssm-tunnel.sh <instance-id> [remote-port] [local-port]}"
REMOTE_PORT="${2:-8000}"
LOCAL_PORT="${3:-$REMOTE_PORT}"

if [[ -f "$APP_DIR/.env.deploy" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$APP_DIR/.env.deploy"
  set +a
elif [[ -f "$APP_DIR/../.env.deploy" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$APP_DIR/../.env.deploy"
  set +a
fi

command -v aws >/dev/null || { echo "AWS CLI required" >&2; exit 1; }

echo "SSM port forward: localhost:${LOCAL_PORT} → instance:${REMOTE_PORT} (${INSTANCE_ID})"
echo "Open http://127.0.0.1:${LOCAL_PORT} after the tunnel connects."
echo "(Ctrl+C to stop)"

exec aws ssm start-session \
  --target "$INSTANCE_ID" \
  --document-name AWS-StartPortForwardingSession \
  --parameters "{\"portNumber\":[\"${REMOTE_PORT}\"],\"localPortNumber\":[\"${LOCAL_PORT}\"]}"
