#!/usr/bin/env bash
#
# check_module_import_boundaries.sh — enforce package import layering for the
# Soothe monorepo (RFC-414 Soothe-Daemon split).
#
# Rules:
#   1. soothe (in-proc agent core) must NOT import soothe_daemon or soothe_cli
#      (one-way dep: soothe-daemon -> soothe; soothe-cli -> soothe-client-python -> soothe-sdk).
#   2. soothe_daemon must NOT import soothe_cli (CLI sits above the daemon).
#   3. soothe_sdk must NOT import any other workspace package.
#   4. soothe_client must NOT import soothe / soothe_cli / soothe_daemon.
#
# Usage:
#   ./scripts/check_module_import_boundaries.sh
#   ./scripts/check_module_import_boundaries.sh --help
#
# Requires: ripgrep (rg)
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PKG_DIR="${ROOT}/packages"

usage() {
  cat <<'EOF'
check_module_import_boundaries.sh — Soothe monorepo import boundaries.

Rules:
  1. soothe must not import soothe_daemon or soothe_cli.
  2. soothe-daemon must not import soothe_cli.
  3. soothe-sdk must not import other workspace packages.
  4. soothe-client-python must not import soothe/cli/daemon.

Usage: ./scripts/check_module_import_boundaries.sh [--help]
Requires: ripgrep (rg)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if ! command -v rg >/dev/null 2>&1; then
  echo "ERROR: ripgrep (rg) is required but not on PATH." >&2
  exit 2
fi

failures=0

run_check() {
  local path="$1"
  local pattern="$2"
  local title="$3"

  if [[ ! -d "$path" ]]; then
    echo "WARN: skip missing path: $path" >&2
    return 0
  fi

  local matches
  matches=$(rg --line-number --glob '*.py' "$pattern" "$path" 2>/dev/null || true)
  if [[ -n "$matches" ]]; then
    echo ""
    echo "FAILED: $title"
    echo "  Path: $path"
    echo "  Pattern: $pattern"
    echo "$matches" | sed 's/^/  /'
    failures=$((failures + 1))
  fi
}

echo "Soothe monorepo import boundaries…"
echo ""

# Rule 1: soothe (in-proc core) must not import daemon or CLI.
run_check "${PKG_DIR}/soothe/src" \
  '^\s*(from|import)\s+soothe_daemon(\.|\s|$)' \
  "soothe must not import soothe_daemon"
run_check "${PKG_DIR}/soothe/src" \
  '^\s*(from|import)\s+soothe_cli(\.|\s|$)' \
  "soothe must not import soothe_cli"

# Rule 2: soothe-daemon must not import CLI.
run_check "${PKG_DIR}/soothe-daemon/src" \
  '^\s*(from|import)\s+soothe_cli(\.|\s|$)' \
  "soothe-daemon must not import soothe_cli"

# Rule 3: soothe-sdk must be standalone.
run_check "${PKG_DIR}/soothe-sdk/src" \
  '^\s*(from|import)\s+(soothe|soothe_nano|soothe_daemon|soothe_cli|soothe_client)(\.|\s|$)' \
  "soothe-sdk must not import other workspace packages"

# Rule 3b: soothe-nano must not import soothe / cli / daemon.
run_check "${PKG_DIR}/soothe-nano/src" \
  '^\s*(from|import)\s+(soothe|soothe_daemon|soothe_cli)(\.|\s|$)' \
  "soothe-nano must not import soothe/cli/daemon"

# Rule 4: soothe-client-python depends only on soothe-sdk (among workspace pkgs).
run_check "${ROOT}/client/python/src" \
  '^\s*(from|import)\s+(soothe|soothe_daemon|soothe_cli)(\.|\s|$)' \
  "soothe-client-python must not import soothe/cli/daemon"

echo ""

if [[ "$failures" -gt 0 ]]; then
  echo "ERROR: ${failures} boundary violation(s). Fix imports."
  exit 1
fi

echo "OK: all module import boundary checks passed."
