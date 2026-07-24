#!/usr/bin/env bash
#
# check_module_import_boundaries.sh — enforce import layering for monorepo-owned
# packages only (soothe, soothe-daemon, soothe-cli).
#
# Submodules (soothe-sdk, soothe-nano, language clients) are consumed as code;
# their internal boundaries and formatting are owned by their own repos.
#
# Rules (host packages only):
#   1. soothe must NOT import soothe_daemon or soothe_cli
#   2. soothe_daemon must NOT import soothe_cli or soothe_client
#   3. soothe / soothe-daemon must NOT import private soothe_nano.middleware._*
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
check_module_import_boundaries.sh — monorepo-owned package import boundaries.

Rules (soothe / soothe-daemon / soothe-cli only):
  1. soothe must not import soothe_daemon or soothe_cli.
  2. soothe-daemon must not import soothe_cli or soothe_client.
  3. host must not import private soothe-nano middleware modules.

Submodule packages (soothe-sdk, soothe-nano, clients) are not formatted or
boundary-scanned here — maintain them in their own repositories.

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

echo "Soothe monorepo import boundaries (owned packages)…"
echo ""

# Rule 1: soothe (in-proc core) must not import daemon or CLI.
run_check "${PKG_DIR}/soothe/src" \
  '^\s*(from|import)\s+soothe_daemon(\.|\s|$)' \
  "soothe must not import soothe_daemon"
run_check "${PKG_DIR}/soothe/src" \
  '^\s*(from|import)\s+soothe_cli(\.|\s|$)' \
  "soothe must not import soothe_cli"

# Rule 2: soothe-daemon must not import CLI or the WS client (client sits above).
run_check "${PKG_DIR}/soothe-daemon/src" \
  '^\s*(from|import)\s+soothe_cli(\.|\s|$)' \
  "soothe-daemon must not import soothe_cli"
run_check "${PKG_DIR}/soothe-daemon/src" \
  '^\s*(from|import)\s+soothe_client(\.|\s|$)' \
  "soothe-daemon must not import soothe_client"

# Rule 3: monorepo packages must not import private soothe-nano middleware.
run_check "${PKG_DIR}/soothe/src" \
  '^\s*(from|import)\s+soothe_nano\.middleware\._' \
  "soothe must not import soothe-nano private middleware modules"
run_check "${PKG_DIR}/soothe-daemon/src" \
  '^\s*(from|import)\s+soothe_nano\.middleware\._' \
  "soothe-daemon must not import soothe-nano private middleware modules"
run_check "${PKG_DIR}/soothe-cli/src" \
  '^\s*(from|import)\s+soothe_nano\.middleware\._' \
  "soothe-cli must not import soothe-nano private middleware modules"

echo ""

if [[ "$failures" -gt 0 ]]; then
  echo "ERROR: ${failures} boundary violation(s). Fix imports."
  exit 1
fi

echo "OK: all module import boundary checks passed."
