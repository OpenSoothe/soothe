#!/usr/bin/env bash
#
# Stop Ray processes started with ray start on this machine.
#
# Usage:
#   ./scripts/ray/stop_local_ray.sh
#
# Run this on each host where you ran start_local_head.sh / start_local_workers.sh,
# or once per terminal session if Ray bound workers to that shell context.
#

set -euo pipefail

if ! command -v ray >/dev/null 2>&1; then
  echo "error: 'ray' not on PATH. Install with: pip install 'ray[default]'" >&2
  exit 1
fi

echo "Stopping local Ray processes started via ray start ..."
ray stop
