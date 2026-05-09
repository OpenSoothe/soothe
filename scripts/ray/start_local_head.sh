#!/usr/bin/env bash
#
# Start a local Ray head node for debugging distributed / RFC-221 Ray runners.
#
# Usage:
#   ./scripts/ray/start_local_head.sh
#
# Environment (optional overrides):
#   RAY_HEAD_PORT       GCS / Redis port (default: 6379)
#   RAY_HEAD_CPUS       --num-cpus for head (default: 4)
#   RAY_DASHBOARD_HOST  (default: 127.0.0.1)
#   RAY_DASHBOARD_PORT  (default: 8265)
#
# Workers should connect with:
#   RAY_ADDRESS=127.0.0.1:${RAY_HEAD_PORT:-6379} ./scripts/ray/start_local_workers.sh
#

set -euo pipefail

RAY_HEAD_PORT="${RAY_HEAD_PORT:-6379}"
RAY_HEAD_CPUS="${RAY_HEAD_CPUS:-4}"
RAY_DASHBOARD_HOST="${RAY_DASHBOARD_HOST:-127.0.0.1}"
RAY_DASHBOARD_PORT="${RAY_DASHBOARD_PORT:-8265}"

if ! command -v ray >/dev/null 2>&1; then
  echo "error: 'ray' not on PATH. Install with: pip install 'ray[default]'" >&2
  exit 1
fi

echo "Starting Ray head on port ${RAY_HEAD_PORT} (dashboard ${RAY_DASHBOARD_HOST}:${RAY_DASHBOARD_PORT}) ..."
ray start --head \
  --port="${RAY_HEAD_PORT}" \
  --dashboard-host="${RAY_DASHBOARD_HOST}" \
  --dashboard-port="${RAY_DASHBOARD_PORT}" \
  --num-cpus="${RAY_HEAD_CPUS}"

echo ""
echo "Head is up. Join workers with:"
echo "  RAY_ADDRESS=127.0.0.1:${RAY_HEAD_PORT} ./scripts/ray/start_local_workers.sh"
