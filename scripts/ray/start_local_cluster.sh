#!/usr/bin/env bash
#
# One-shot: start head, wait for readiness, start workers, print ray status.
# For interactive debugging you may prefer separate terminals using
# start_local_head.sh and start_local_workers.sh manually.
#
# Usage:
#   ./scripts/ray/start_local_cluster.sh
#
# Environment:
#   RAY_HEAD_PORT, RAY_HEAD_CPUS, RAY_DASHBOARD_HOST, RAY_DASHBOARD_PORT
#   RAY_WORKER_CPUS, RAY_NUM_WORKERS
#   RAY_JOIN_SLEEP   Seconds to wait after head before workers join (default: 3)
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RAY_HEAD_PORT="${RAY_HEAD_PORT:-6379}"
RAY_JOIN_SLEEP="${RAY_JOIN_SLEEP:-3}"
export RAY_ADDRESS="${RAY_ADDRESS:-127.0.0.1:${RAY_HEAD_PORT}}"

"${SCRIPT_DIR}/start_local_head.sh"
echo ""
echo "Waiting ${RAY_JOIN_SLEEP}s for head to accept workers ..."
sleep "${RAY_JOIN_SLEEP}"
"${SCRIPT_DIR}/start_local_workers.sh"
echo ""
"${SCRIPT_DIR}/status_local_ray.sh"
