#!/usr/bin/env bash
#
# check_module_import_boundaries.sh — enforce high-level import layering for Soothe.
#
# Rules (see also RFC-000 / CLAUDE.md architecture):
#   1. No package under src/soothe/ except "ux" may import soothe.ux (CLI/TUI stay
#      above the runtime stack: core, daemon, foundation, backends, etc.).
#   2. soothe.foundation must not import soothe.daemon (shared primitives must not
#      depend on the server process / transports).
#
# Usage:
#   ./scripts/check_module_import_boundaries.sh
#   ./scripts/check_module_import_boundaries.sh --help
#
# Requires: ripgrep (rg)
#
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SOOTHE_PKG="${ROOT}/src/soothe"

# Import statements only (avoids matching prose in comments that mentions soothe.ux).
RE_NO_UX='^\s*(from|import)\s+soothe\.ux(\.|\s|$)'
RE_FOUNDATION_NO_DAEMON='^\s*(from|import)\s+soothe\.daemon(\.|\s|$)'

usage() {
  cat <<'EOF'
check_module_import_boundaries.sh — enforce high-level import layering for Soothe.

Rules:
  1. No top-level package under src/soothe/ except «ux» may use import lines
     referring to soothe.ux (CLI/TUI sit above core, daemon, foundation, backends, …).
  2. soothe.foundation must not import soothe.daemon (shared primitives independent
     of the server / transports).

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

echo "Soothe module import boundaries (src/soothe)…"
echo ""

checked_ux_rule=0
shopt -s nullglob
for pkg_dir in "${SOOTHE_PKG}"/*/; do
  name="$(basename "$pkg_dir")"
  case "$name" in
    ux | __pycache__)
      continue
      ;;
  esac
  run_check "$pkg_dir" "$RE_NO_UX" "Package «${name}» must not import soothe.ux"
  checked_ux_rule=$((checked_ux_rule + 1))
done
shopt -u nullglob

echo "  Rule 1: checked ${checked_ux_rule} top-level packages for forbidden soothe.ux imports."

run_check "${SOOTHE_PKG}/foundation" "$RE_FOUNDATION_NO_DAEMON" \
  "soothe.foundation must not import soothe.daemon"

echo "  Rule 2: checked soothe/foundation for forbidden soothe.daemon imports."

echo ""

if [[ "$failures" -gt 0 ]]; then
  echo "ERROR: ${failures} boundary violation(s). Fix imports or adjust this script with team agreement."
  exit 1
fi

echo "OK: all module import boundary checks passed."
