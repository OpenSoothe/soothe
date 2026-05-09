#!/usr/bin/env bash
#
# Show Ray cluster status (nodes, resources).
#
# Usage:
#   ./scripts/ray/status_local_ray.sh
#

set -euo pipefail

if ! command -v ray >/dev/null 2>&1; then
  echo "error: 'ray' not on PATH. Install with: pip install 'ray[default]'" >&2
  exit 1
fi

exec ray status
