#!/usr/bin/env bash
#
# tui_perf_check.sh - TUI performance checklist helper
#
# This script provides a small workflow for local TUI performance analysis:
# 1) Verify required dev tools are available.
# 2) Start Textual console in verbose mode.
# 3) Run the TUI app in Textual dev mode.
# 4) Run a pyinstrument profile session and save HTML output.
#
# Usage:
#   ./scripts/tui_perf_check.sh check
#   ./scripts/tui_perf_check.sh console
#   ./scripts/tui_perf_check.sh run
#   ./scripts/tui_perf_check.sh profile [seconds]
#   ./scripts/tui_perf_check.sh all [seconds]
#

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE_DIR="${ROOT_DIR}/tmp/tui-perf"
DEFAULT_PROFILE_SECONDS=20

print_usage() {
  cat <<'EOF'
Usage:
  ./scripts/tui_perf_check.sh check
  ./scripts/tui_perf_check.sh console
  ./scripts/tui_perf_check.sh run
  ./scripts/tui_perf_check.sh profile [seconds]
  ./scripts/tui_perf_check.sh all [seconds]

Commands:
  check            Verify textual-dev and pyinstrument availability
  console          Start Textual console with verbose logs
  run              Run Soothe TUI in Textual dev mode
  profile [sec]    Record a pyinstrument profile (default: 20s)
  all [sec]        Print the recommended full workflow
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Missing command: ${cmd}"
    return 1
  fi
}

check_dependencies() {
  require_cmd uv
  if ! uv run textual --version >/dev/null 2>&1; then
    echo "Missing textual devtools in environment."
    echo "Install with: uv add --dev textual-dev"
    return 1
  fi
  if ! uv run python -c "import pyinstrument" >/dev/null 2>&1; then
    echo "Missing pyinstrument in environment."
    echo "Install with: uv add --dev pyinstrument"
    return 1
  fi
  echo "Dependency check passed."
}

run_console() {
  echo "Starting Textual console (-v). Keep this terminal open."
  cd "${ROOT_DIR}"
  uv run textual console -v
}

run_app() {
  echo "Starting Soothe TUI in Textual dev mode."
  cd "${ROOT_DIR}"
  uv run textual run --dev "python -m soothe_cli.cli.main"
}

run_profile() {
  local seconds="${1:-${DEFAULT_PROFILE_SECONDS}}"
  mkdir -p "${PROFILE_DIR}"
  local timestamp
  timestamp="$(date +%Y%m%d-%H%M%S)"
  local out_html="${PROFILE_DIR}/tui-profile-${timestamp}.html"

  cd "${ROOT_DIR}"
  echo "Profiling for ${seconds}s. Interact with TUI (scroll 10-20s)."
  uv run pyinstrument -d "${seconds}" -r html -o "${out_html}" -m soothe_cli.cli.main
  echo "Profile report saved to: ${out_html}"
}

print_all_workflow() {
  local seconds="${1:-${DEFAULT_PROFILE_SECONDS}}"
  cat <<EOF
Recommended workflow:
1) Terminal A:
   ./scripts/tui_perf_check.sh console
2) Terminal B:
   ./scripts/tui_perf_check.sh run
3) Terminal C:
   ./scripts/tui_perf_check.sh profile ${seconds}

Notes:
- During profiling, reproduce scroll jank for 10-20 seconds.
- Inspect hot paths in ${PROFILE_DIR}.
EOF
}

main() {
  local cmd="${1:-}"
  case "${cmd}" in
    check)
      check_dependencies
      ;;
    console)
      check_dependencies
      run_console
      ;;
    run)
      check_dependencies
      run_app
      ;;
    profile)
      check_dependencies
      run_profile "${2:-${DEFAULT_PROFILE_SECONDS}}"
      ;;
    all)
      check_dependencies
      print_all_workflow "${2:-${DEFAULT_PROFILE_SECONDS}}"
      ;;
    ""|-h|--help|help)
      print_usage
      ;;
    *)
      echo "Unknown command: ${cmd}"
      echo ""
      print_usage
      exit 1
      ;;
  esac
}

main "$@"
