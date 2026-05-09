#!/usr/bin/env bash
#
# Start one or more local Ray worker processes attached to an existing head.
# Run each logical worker in sequence (matches separate-terminal workflows).
#
# Usage:
#   RAY_ADDRESS=127.0.0.1:6379 ./scripts/ray/start_local_workers.sh
#
# Environment:
#   RAY_ADDRESS    Address printed by the head (required unless default suffices)
#                  Default: 127.0.0.1:6379
#   RAY_WORKER_CPUS   --num-cpus per worker process (default: 2)
#   RAY_NUM_WORKERS   How many worker ray start invocations (default: 2)
#

set -euo pipefail

RAY_ADDRESS="${RAY_ADDRESS:-127.0.0.1:6379}"
RAY_WORKER_CPUS="${RAY_WORKER_CPUS:-2}"
RAY_NUM_WORKERS="${RAY_NUM_WORKERS:-2}"

if ! command -v ray >/dev/null 2>&1; then
  echo "error: 'ray' not on PATH. Install with: pip install 'ray[default]'" >&2
  exit 1
fi

if [[ "${RAY_NUM_WORKERS}" -lt 1 ]]; then
  echo "error: RAY_NUM_WORKERS must be >= 1" >&2
  exit 1
fi

echo "Starting ${RAY_NUM_WORKERS} worker process(es) against ${RAY_ADDRESS} (${RAY_WORKER_CPUS} CPUs each) ..."
for ((i = 1; i <= RAY_NUM_WORKERS; i++)); do
  echo "--- worker ${i}/${RAY_NUM_WORKERS} ---"
  ray start --address="${RAY_ADDRESS}" --num-cpus="${RAY_WORKER_CPUS}"
done

echo ""
echo "Workers registered. Check cluster with: ./scripts/ray/status_local_ray.sh"
