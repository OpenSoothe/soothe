#!/usr/bin/env bash
#
# verify_finally.sh - Run all verification checks before committing (monorepo version)
#
# This script runs the complete verification suite for multi-package monorepo:
# 1. Workspace integrity check (uv sync)
# 2. Package dependency validation:
#    - CLI must NOT import daemon runtime (soothe_daemon)
#    - SDK must be independent (no CLI/daemon imports)
#    - soothe (in-proc core) must NOT depend on soothe-daemon (one-way dep)
# 3. Code formatting check (ruff format, parallel per package)
# 4. Linting (ruff check, parallel per package)
# 5. Dead-code analysis (vulture, min 90% confidence)
# 6. Unit tests (all packages, parallel execution)
#
# Exit codes:
#   0 - All checks passed
#   1 - One or more checks failed
#
# ⚠️  MUST APPLY: Run this script before every commit!
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# After making any code changes, you MUST run this verification script
# to ensure all checks pass before committing. This is MANDATORY for
# maintaining code quality and preventing regressions.
#
# Usage:
#   ./scripts/verify_finally.sh              # Run all checks
#   ./scripts/verify_finally.sh --fix        # Auto-fix formatting and linting issues
#   ./scripts/verify_finally.sh --quick      # Skip tests (format + lint only)
#   ./scripts/verify_finally.sh --deps       # Dependency validation only
#
# Integration with git hooks (optional):
#   You can add this to your pre-commit hook to run automatically:
#   echo './scripts/verify_finally.sh' > .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#

set -euo pipefail

# Determine workspace root (script location's parent directory)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m' # No Color

# Track overall status
OVERALL_STATUS=0
FAILED_CHECKS=()
FAILED_LOGS=()
FAILED_TEST_ENTRIES=()
SLOW_TEST_ENTRIES=()

# Set true after setup_workspace() syncs; skips redundant dry-run in dependency checks.
WORKSPACE_SYNCED=false

# Workspace venv binaries (avoid per-package `uv run` startup overhead).
VENV_PYTHON="${WORKSPACE_ROOT}/.venv/bin/python"
VENV_RUFF="${WORKSPACE_ROOT}/.venv/bin/ruff"
VENV_VULTURE="${WORKSPACE_ROOT}/.venv/bin/vulture"

# Report tests taking longer than this (seconds), or with no pytest output (hang).
SLOW_TEST_THRESHOLD_SEC=60

# Parse command line arguments
AUTO_FIX=false
SKIP_TESTS=false
DEPS_ONLY=false

for arg in "$@"; do
  case $arg in
  --fix)
    AUTO_FIX=true
    shift
    ;;
  --quick)
    SKIP_TESTS=true
    shift
    ;;
  --deps)
    DEPS_ONLY=true
    shift
    ;;
  --help)
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --fix     Auto-fix formatting and linting issues"
    echo "  --quick   Skip tests (format + lint only)"
    echo "  --deps    Dependency validation only (skip format/lint/tests)"
    echo "  --help    Show this help message"
    exit 0
    ;;
  *)
    echo "Unknown option: $arg"
    echo "Use --help for usage information"
    exit 1
    ;;
  esac
done

# All packages in dependency order
ALL_PACKAGES=(soothe-sdk soothe-cli soothe soothe-daemon)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# HELPER FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print_section() {
  echo ""
  echo -e "${BLUE}── $1 ──${NC}"
}

print_ok() {
  echo -e "  ${GREEN}✓${NC} $1"
}

print_fail() {
  echo -e "  ${RED}✗${NC} $1"
  FAILED_CHECKS+=("$1")
  OVERALL_STATUS=1
}

# Record detailed failure output for end-of-run summary
# Usage: record_failure_log "category" "details"
record_failure_log() {
  local category="$1"
  local details="$2"
  FAILED_LOGS+=("${BOLD}${category}:${NC}\n${details}")
}

print_warn() {
  echo -e "  ${YELLOW}!${NC} $1"
}

print_note() {
  echo -e "  ${DIM}$1${NC}"
}

# Sync command kept in lockstep with `make sync` (UV_SYNC in Makefile).
# Broken/partial mirrors (e.g. tsinghua) leave dist-info without wheels for
# packages like psycopg_pool and jsonschema.
# Use UV_PYPI_MIRROR to override the default PyPI (for networks with connectivity issues).
# Usage: UV_PYPI_MIRROR=https://mirrors.aliyun.com/pypi/simple ./scripts/verify_finally.sh
# Export UV_DEFAULT_INDEX so all uv sync/run commands use the mirror.
if [[ -n "${UV_PYPI_MIRROR:-}" ]]; then
  export UV_DEFAULT_INDEX="$UV_PYPI_MIRROR"
else
  # Force PyPI by clearing any mirror environment variables
  unset UV_INDEX_URL UV_DEFAULT_INDEX UV_EXTRA_INDEX_URL UV_INDEX UV_FIND_LINKS 2>/dev/null || true
fi
UV_SYNC_CMD=(uv sync --all-packages --all-extras)

# Verify critical daemon dependencies are importable after sync.
# Mirrors the `sync-verify` Makefile target so the script catches the same
# broken-mirror failures `make sync` does.
_verify_critical_deps() {
  .venv/bin/python - <<'PY'
import importlib.util
pkgs = ("psycopg_pool", "jsonschema", "langfuse", "jinja2")
missing = [p for p in pkgs if importlib.util.find_spec(p) is None]
assert not missing, f"Missing packages after sync (broken mirror?): {missing}"
PY
}

_now_seconds() {
  date +%s
}

_format_duration() {
  local sec="$1"
  if [ "$sec" -ge 3600 ]; then
    printf '%dh %02dm %02ds' $((sec / 3600)) $(((sec % 3600) / 60)) $((sec % 60))
  elif [ "$sec" -ge 60 ]; then
    printf '%dm %02ds' $((sec / 60)) $((sec % 60))
  else
    printf '%ss' "$sec"
  fi
}

_collect_slow_file() {
  local slow_file="$1"
  if [ ! -s "$slow_file" ]; then
    return 0
  fi
  while IFS='|' read -r entry_pkg entry_test entry_sec entry_kind; do
    SLOW_TEST_ENTRIES+=("${entry_pkg}|${entry_test}|${entry_sec}|${entry_kind}")
  done <"$slow_file"
}

_collect_failures_file() {
  local failures_file="$1"
  if [ ! -s "$failures_file" ]; then
    return 0
  fi
  while IFS='|' read -r entry_pkg entry_test entry_reason; do
    FAILED_TEST_ENTRIES+=("${entry_pkg}|${entry_test}|${entry_reason}")
  done <"$failures_file"
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PACKAGE DEPENDENCY VALIDATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

validate_package_dependencies() {
  print_section "dependencies"

  cd "$WORKSPACE_ROOT"

  # Rule 1: soothe-cli MUST NOT import the daemon runtime
  # Optimized: single grep pass instead of two (check + detail)
  local violations
  violations=$(grep -rE 'from soothe_daemon|import soothe_daemon' packages/soothe-cli/src --include='*.py' 2>/dev/null | head -10 || true)
  if [ -n "$violations" ]; then
    print_fail "cli must not import soothe_daemon"
    record_failure_log "Dependency: CLI -> daemon" "$violations"
    return 1
  else
    print_ok "cli → daemon boundary"
  fi

  # Rule 2: soothe-sdk MUST NOT import any other package
  # Optimized: single grep pass instead of two
  violations=$(grep -rE 'from soothe_cli|from soothe_daemon|from soothe[. ]|import soothe_cli|import soothe_daemon|import soothe$|import soothe\.' packages/soothe-sdk/src --include='*.py' 2>/dev/null | head -10 || true)
  if [ -n "$violations" ]; then
    print_fail "sdk must be independent"
    record_failure_log "Dependency: SDK independence" "$violations"
    return 1
  else
    print_ok "sdk independence"
  fi

  # Rule 3: soothe (in-proc agent core) MUST NOT depend on soothe-daemon
  # Optimized: single grep pass instead of two
  violations=$(grep -rE 'from soothe_daemon|import soothe_daemon' packages/soothe/src --include='*.py' 2>/dev/null | head -10 || true)
  if [ -n "$violations" ]; then
    print_fail "soothe must not import soothe_daemon"
    record_failure_log "Dependency: soothe -> daemon" "$violations"
    return 1
  fi

  # Rule 3b: Check pyproject.toml dependencies
  # Optimized: read file once, grep from variable
  local soothe_deps daemon_deps
  soothe_deps=$(sed -n '/^dependencies = \[/,/\]/p' packages/soothe/pyproject.toml 2>/dev/null || true)
  if echo "$soothe_deps" | grep -qE '"soothe-daemon'; then
    print_fail "soothe pyproject.toml lists soothe-daemon in core deps"
    record_failure_log "Dependency: soothe pyproject.toml" "$(echo "$soothe_deps" | grep -nE '"soothe-daemon')"
    return 1
  fi
  print_ok "soothe ↛ soothe-daemon"

  # Rule 4: soothe-daemon MUST NOT depend on soothe-cli in core dependencies
  # Optimized: read file once, grep from variable
  daemon_deps=$(sed -n '/^dependencies = \[/,/\]/p' packages/soothe-daemon/pyproject.toml 2>/dev/null || true)
  if echo "$daemon_deps" | grep -qE '"soothe-cli'; then
    print_fail "soothe-daemon pyproject.toml lists soothe-cli in core deps"
    record_failure_log "Dependency: daemon pyproject.toml" "$(echo "$daemon_deps" | grep -nE '"soothe-cli')"
    return 1
  fi
  print_ok "daemon ↛ soothe-cli (runtime)"

  # Rule 5: Workspace integrity - all packages must be in sync
  if $WORKSPACE_SYNCED; then
    print_ok "workspace in sync"
  elif ! command -v uv >/dev/null 2>&1; then
    print_warn "uv not found, skipping workspace sync check"
  else
    local sync_output
    sync_output=$(uv sync --all-packages --all-extras --dry-run 2>&1) || true
    if echo "$sync_output" | grep -qE "error|would update|would install"; then
      print_fail "workspace out of sync (run 'make sync')"
      record_failure_log "Workspace sync" "$(echo "$sync_output" | head -20)"
      return 1
    else
      print_ok "workspace in sync"
    fi
  fi

  if [ -f "$WORKSPACE_ROOT/scripts/check_module_import_boundaries.sh" ]; then
    if bash "$WORKSPACE_ROOT/scripts/check_module_import_boundaries.sh" >/dev/null 2>&1; then
      print_ok "import boundaries"
    else
      print_warn "import boundary checks failed (see script output)"
    fi
  fi

  return 0
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WORKSPACE SETUP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

setup_workspace() {
  print_section "workspace"

  cd "$WORKSPACE_ROOT"

  if ! command -v uv >/dev/null 2>&1; then
    print_fail "uv is not installed"
    exit 1
  fi

  print_note "syncing packages..."
  if ! "${UV_SYNC_CMD[@]}" >/dev/null 2>&1; then
    print_fail "uv sync failed"
    print_note "try: make sync"
    exit 1
  fi
  print_ok "uv sync"

  if ! _verify_critical_deps >/dev/null 2>&1; then
    print_fail "critical deps missing after sync (broken mirror?)"
    print_note "try: make sync"
    exit 1
  fi
  print_ok "critical deps (psycopg_pool, jsonschema, langfuse)"
  WORKSPACE_SYNCED=true
}

ensure_deps_installed() {
  cd "$WORKSPACE_ROOT"
  if _verify_critical_deps >/dev/null 2>&1; then
    return 0
  fi
  print_warn "critical deps missing mid-run; re-syncing..."
  if ! "${UV_SYNC_CMD[@]}" >/dev/null 2>&1; then
    print_fail "re-sync failed"
    return 1
  fi
  _verify_critical_deps
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CODE FORMATTING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Run ruff format --check for one package. Args: pkg exit_file details_file
_format_check_pkg() {
  local pkg="$1"
  local exit_file="$2"
  local details_file="$3"
  local paths="src/"
  if [ -d "$WORKSPACE_ROOT/packages/$pkg/tests/" ]; then
    paths="src/ tests/"
  fi
  local output
  local exit_code=0
  output=$(cd "$WORKSPACE_ROOT/packages/$pkg" && "$VENV_RUFF" format --check $paths 2>&1) || exit_code=$?
  echo "$exit_code" >"$exit_file"
  if [ "$exit_code" -ne 0 ]; then
    printf '\n[%s]\n%s\n' "$pkg" "$output" >"${details_file}.${pkg}"
  fi
}

# Run ruff check for one package. Args: pkg exit_file details_file
_lint_check_pkg() {
  local pkg="$1"
  local exit_file="$2"
  local details_file="$3"
  local paths="src/"
  if [ -d "$WORKSPACE_ROOT/packages/$pkg/tests/" ]; then
    paths="src/ tests/"
  fi
  local output
  local exit_code=0
  output=$(cd "$WORKSPACE_ROOT/packages/$pkg" && "$VENV_RUFF" check $paths 2>&1) || exit_code=$?
  echo "$exit_code" >"$exit_file"
  if [ "$exit_code" -ne 0 ]; then
    printf '\n[%s]\n%s\n' "$pkg" "$output" >"${details_file}.${pkg}"
  fi
}

# Run pytest for one package with real-time output streaming.
# Args: pkg failures_file slow_file
_run_pkg_tests_streaming() {
  local pkg="$1"
  local failures_file="$2"
  local slow_file="$3"
  cd "$WORKSPACE_ROOT/packages/$pkg"

  # Use pytest-xdist for packages with mostly sync tests (sdk, cli).
  # soothe and soothe-daemon have many async fixtures that don't work well with xdist.
  local xdist_opts=""
  if "$VENV_PYTHON" -c "import xdist" 2>/dev/null; then
    case "$pkg" in
    soothe-sdk | soothe-cli)
      xdist_opts="-n4 --dist=loadgroup"
      ;;
    *)
      # soothe and soothe-daemon: async fixtures incompatible with xdist workers
      xdist_opts=""
      ;;
    esac
  fi

  local passed_count=0
  local failed_count=0
  local error_count=0
  local skipped_count=0
  local last_ts
  last_ts=$(_now_seconds)
  local collecting=true
  local pkg_exit_code=0

  # Run pytest and stream output line-by-line
  while IFS= read -r line; do
    # Show progress during collection phase
    if $collecting; then
      if [[ "$line" =~ ^(scheduling|created:|collecting) ]]; then
        echo -e "    ${DIM}...${NC} ${line}"
      fi
    fi

    if [[ "$line" =~ collected[[:space:]]+[0-9]+[[:space:]]+items ]]; then
      collecting=false
      last_ts=$(_now_seconds)
      continue
    fi

    # Handle both sequential and xdist output formats:
    # Sequential (from package dir): "tests/unit/test_file.py::test_func PASSED"
    # xdist (from package dir): "[gw0] [  5%] PASSED tests/unit/test_file.py::test_func"
    # Note: pytest outputs "tests/unit/" paths when run from package directory
    local test_id="" status="" short_id=""

    if [[ "$line" =~ ^(tests/[^[:space:]]+)[[:space:]]+(PASSED|FAILED|ERROR|SKIPPED) ]]; then
      # Sequential format: tests/unit/test_file.py::test_func PASSED [100%]
      test_id="${BASH_REMATCH[1]}"
      status="${BASH_REMATCH[2]}"
      short_id="${test_id#tests/unit/}"
    elif [[ "$line" =~ ^\[gw[0-9]+\]\ \[[[:space:]]*[0-9]+%\]\ (PASSED|FAILED|ERROR|SKIPPED)\ (tests/[^[:space:]]+) ]]; then
      # xdist format from package dir: [gw0] [  5%] PASSED tests/unit/test_file.py::test_func
      status="${BASH_REMATCH[1]}"
      test_id="${BASH_REMATCH[2]}"
      short_id="${test_id#tests/unit/}"
    fi

    if [ -n "$test_id" ] && [ -n "$status" ]; then
      local now elapsed
      now=$(_now_seconds)
      elapsed=$((now - last_ts))
      if [ "$collecting" = false ] && [ "$elapsed" -ge "$SLOW_TEST_THRESHOLD_SEC" ]; then
        if ! grep -Fq "${pkg}|${test_id}|" "$slow_file" 2>/dev/null; then
          echo -e "    ${YELLOW}⏱${NC} ${short_id} ($(_format_duration "$elapsed"))"
          printf '%s|%s|%s|slow\n' "$pkg" "$test_id" "$elapsed" >>"$slow_file"
        fi
      fi
      last_ts="$now"

      case "$status" in
      PASSED)
        passed_count=$((passed_count + 1))
        echo -e "    ${DIM}✓${NC} ${short_id}"
        ;;
      FAILED)
        failed_count=$((failed_count + 1))
        echo -e "    ${RED}✗${NC} ${short_id}"
        printf '%s|%s|\n' "$pkg" "$test_id" >>"$failures_file"
        ;;
      ERROR)
        error_count=$((error_count + 1))
        echo -e "    ${RED}!${NC} ${short_id} (error)"
        printf '%s|%s|\n' "$pkg" "$test_id" >>"$failures_file"
        ;;
      SKIPPED)
        skipped_count=$((skipped_count + 1))
        echo -e "    ${YELLOW}○${NC} ${short_id} (skipped)"
        ;;
      esac
    elif [[ "$line" =~ ^FAILED[[:space:]]+(tests/[^[:space:]]+)[[:space:]]-[[:space:]]*(.+)$ ]]; then
      local test_id="${BASH_REMATCH[1]}"
      local reason="${BASH_REMATCH[2]}"
      # Update the failures file with the reason
      if [ -f "$failures_file" ]; then
        local tmp
        tmp=$(mktemp)
        while IFS='|' read -r row_pkg row_test row_reason; do
          if [ "$row_pkg" = "$pkg" ] && [ "$row_test" = "$test_id" ] && [ -z "$row_reason" ]; then
            printf '%s|%s|%s\n' "$row_pkg" "$row_test" "$reason"
          else
            printf '%s|%s|%s\n' "$row_pkg" "$row_test" "$row_reason"
          fi
        done <"$failures_file" >"$tmp"
        mv "$tmp" "$failures_file"
      fi
    fi
  done < <(PYTHONUNBUFFERED=1 "$VENV_PYTHON" -u -m pytest tests/unit/ \
    $xdist_opts \
    -v --tb=line --no-header --disable-warnings --durations=15 2>&1)
  pkg_exit_code=$?

  # Print per-package summary line
  if [ "$passed_count" -gt 0 ] || [ "$failed_count" -gt 0 ] || [ "$error_count" -gt 0 ] || [ "$skipped_count" -gt 0 ]; then
    local summary_parts=""
    if [ "$passed_count" -gt 0 ]; then
      summary_parts+="${GREEN}${passed_count} passed${NC}"
    fi
    if [ "$failed_count" -gt 0 ]; then
      if [ -n "$summary_parts" ]; then summary_parts+=", "; fi
      summary_parts+="${RED}${failed_count} failed${NC}"
    fi
    if [ "$error_count" -gt 0 ]; then
      if [ -n "$summary_parts" ]; then summary_parts+=", "; fi
      summary_parts+="${RED}${error_count} errors${NC}"
    fi
    if [ "$skipped_count" -gt 0 ]; then
      if [ -n "$summary_parts" ]; then summary_parts+=", "; fi
      summary_parts+="${YELLOW}${skipped_count} skipped${NC}"
    fi
    echo -e "  ${DIM}── ${summary_parts}${NC}"
  fi

  # Package result indicator
  if [ "$pkg_exit_code" -eq 0 ]; then
    echo -e "  ${GREEN}✓${NC} ${pkg} — all tests passed"
  else
    echo -e "  ${RED}✗${NC} ${pkg} — tests failed"
  fi

  cd "$WORKSPACE_ROOT"
  return $pkg_exit_code
}

check_formatting() {
  print_section "format"

  cd "$WORKSPACE_ROOT"

  if $AUTO_FIX; then
    print_note "auto-fixing..."
    if make format >/dev/null 2>&1; then
      print_ok "format fixed"
    else
      print_fail "format auto-fix failed"
    fi
    return 0
  fi

  local format_failed=false
  local format_details=""
  local tmpdir
  tmpdir=$(mktemp -d)
  local pids=()

  for pkg in "${ALL_PACKAGES[@]}"; do
    _format_check_pkg "$pkg" "$tmpdir/${pkg}.exit" "$tmpdir/details" &
    pids+=($!)
  done

  for pid in "${pids[@]}"; do
    wait "$pid" || true
  done

  for pid in "${pids[@]}"; do
    wait "$pid" || true
  done

  # Combined loop: collect exit codes and details in one pass
  for pkg in "${ALL_PACKAGES[@]}"; do
    local exit_code
    exit_code=$(cat "$tmpdir/${pkg}.exit")
    if [ "$exit_code" -eq 0 ]; then
      print_ok "$pkg"
    else
      print_fail "$pkg"
      format_failed=true
      if [ -f "$tmpdir/details.${pkg}" ]; then
        format_details+=$(cat "$tmpdir/details.${pkg}")
      fi
    fi
  done
  rm -rf "$tmpdir"

  if $format_failed; then
    record_failure_log "Formatting" "$format_details"
    print_note "run with --fix to auto-fix"
    return 1
  fi

  return 0
}
# LINTING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

check_linting() {
  print_section "lint"

  cd "$WORKSPACE_ROOT"

  if $AUTO_FIX; then
    print_note "auto-fixing..."
    if make lint-fix >/dev/null 2>&1; then
      print_ok "lint fixed"
    else
      print_fail "lint auto-fix failed"
    fi
    return 0
  fi

  local lint_failed=false
  local lint_details=""
  local tmpdir
  tmpdir=$(mktemp -d)
  local pids=()

  for pkg in "${ALL_PACKAGES[@]}"; do
    _lint_check_pkg "$pkg" "$tmpdir/${pkg}.exit" "$tmpdir/details" &
    pids+=($!)
  done

  for pid in "${pids[@]}"; do
    wait "$pid" || true
  done

  # Combined loop: collect exit codes and details in one pass
  for pkg in "${ALL_PACKAGES[@]}"; do
    local exit_code
    exit_code=$(cat "$tmpdir/${pkg}.exit")
    if [ "$exit_code" -eq 0 ]; then
      print_ok "$pkg"
    else
      print_fail "$pkg"
      lint_failed=true
      if [ -f "$tmpdir/details.${pkg}" ]; then
        lint_details+=$(cat "$tmpdir/details.${pkg}")
      fi
    fi
  done
  rm -rf "$tmpdir"

  if $lint_failed; then
    record_failure_log "Linting" "$lint_details"
    print_note "run with --fix to auto-fix"
    return 1
  fi

  return 0
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ASYNCAPI SPEC DRIFT CHECK (RFC-450 §11.3)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

check_asyncapi_drift() {
  print_section "asyncapi"

  cd "$WORKSPACE_ROOT"

  if [ ! -f "scripts/check_asyncapi_drift.py" ]; then
    print_warn "drift checker not found, skipping"
    return 0
  fi

  local output
  local exit_code
  output=$("$VENV_PYTHON" scripts/check_asyncapi_drift.py --strict 2>&1) && exit_code=0 || exit_code=$?
  if [ $exit_code -eq 0 ]; then
    print_ok "spec ↔ pydantic in sync"
  else
    print_fail "spec drift detected"
    record_failure_log "AsyncAPI drift" "$output"
    return 1
  fi

  return 0
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DEAD-CODE ANALYSIS (VULTURE)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

check_vulture() {
  print_section "vulture"

  cd "$WORKSPACE_ROOT"

  if [ ! -x "$VENV_VULTURE" ]; then
    print_fail "vulture not installed (run 'make sync')"
    return 1
  fi

  local output
  local exit_code
  output=$("$VENV_VULTURE" 2>&1) && exit_code=0 || exit_code=$?
  if [ $exit_code -eq 0 ]; then
    print_ok "no high-confidence dead code (≥90%)"
  else
    print_fail "dead code detected"
    record_failure_log "Vulture" "$output"
    print_note "fix findings or whitelist with 'make vulture-whitelist' (review diff)"
    return 1
  fi

  return 0
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UNIT TESTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

run_tests() {
  if $SKIP_TESTS; then
    print_section "tests"
    print_note "skipped (--quick)"
    return 0
  fi

  print_section "tests"

  cd "$WORKSPACE_ROOT"

  if ! ensure_deps_installed; then
    print_fail "dependency state could not be restored"
    return 1
  fi

  local tests_failed=false
  local failures_file slow_file

  # Create shared files for tracking failures and slow tests
  failures_file=$(mktemp)
  slow_file=$(mktemp)

  # Run tests sequentially package-by-package with real-time output
  for pkg in "${ALL_PACKAGES[@]}"; do
    if [ ! -d "$WORKSPACE_ROOT/packages/$pkg/tests/unit" ]; then
      continue
    fi

    # Display package header
    echo -e ""
    echo -e "  ${BOLD}${CYAN}${pkg}${NC}"
    echo -e "  ${DIM}running tests...${NC}"

    # Run tests for this package with streaming output
    local pkg_exit_code=0
    _run_pkg_tests_streaming "$pkg" "$failures_file" "$slow_file" || pkg_exit_code=$?

    if [ "$pkg_exit_code" -ne 0 ]; then
      tests_failed=true
      OVERALL_STATUS=1
      FAILED_CHECKS+=("${pkg} tests")
    fi

    echo ""
  done

  # Collect all failures and slow tests for final summary
  if [ -s "$failures_file" ]; then
    _collect_failures_file "$failures_file"
  fi
  if [ -s "$slow_file" ]; then
    _collect_slow_file "$slow_file"
  fi

  rm -f "$failures_file" "$slow_file"

  if $tests_failed; then
    return 1
  fi

  return 0
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FINAL SUMMARY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print_slow_tests_summary() {
  if [ ${#SLOW_TEST_ENTRIES[@]} -eq 0 ]; then
    return 0
  fi

  echo -e "${BOLD}${YELLOW}Slow tests (≥$(_format_duration "$SLOW_TEST_THRESHOLD_SEC"), ${#SLOW_TEST_ENTRIES[@]}):${NC}"
  local current_pkg=""
  for entry in "${SLOW_TEST_ENTRIES[@]}"; do
    IFS='|' read -r pkg test_id elapsed kind <<<"$entry"
    if [ "$pkg" != "$current_pkg" ]; then
      echo -e "  ${BOLD}${pkg}${NC}"
      current_pkg="$pkg"
    fi
    local short_id="${test_id#tests/unit/}"
    case "$kind" in
    hang)
      echo -e "    ${YELLOW}⏱${NC} ${short_id} — no output for $(_format_duration "$elapsed") (possible hang)"
      ;;
    slow)
      echo -e "    ${YELLOW}⏱${NC} ${short_id} — $(_format_duration "$elapsed")"
      ;;
    *)
      echo -e "    ${YELLOW}⏱${NC} ${short_id} — $(_format_duration "$elapsed")"
      ;;
    esac
  done
  echo ""
}

print_failed_tests_summary() {
  if [ ${#FAILED_TEST_ENTRIES[@]} -eq 0 ]; then
    return 0
  fi

  echo -e "${BOLD}${RED}Failed tests (${#FAILED_TEST_ENTRIES[@]}):${NC}"
  local current_pkg=""
  for entry in "${FAILED_TEST_ENTRIES[@]}"; do
    IFS='|' read -r pkg test_id reason <<<"$entry"
    if [ "$pkg" != "$current_pkg" ]; then
      echo -e "  ${BOLD}${pkg}${NC}"
      current_pkg="$pkg"
    fi
    local short_id="${test_id#tests/unit/}"
    if [ -n "$reason" ]; then
      echo -e "    ${RED}✗${NC} ${short_id}"
      echo -e "      ${DIM}${reason}${NC}"
    else
      echo -e "    ${RED}✗${NC} ${short_id}"
    fi
  done
  echo ""
}

print_final_summary() {
  echo ""
  echo -e "${BOLD}══════════════════════════════════════════════════════${NC}"

  if [ $OVERALL_STATUS -eq 0 ]; then
    echo -e "${GREEN}${BOLD}All checks passed${NC} — ready to commit."
    print_slow_tests_summary
    echo ""
    return 0
  fi

  echo -e "${RED}${BOLD}Verification failed${NC}"
  echo ""

  if [ ${#FAILED_CHECKS[@]} -gt 0 ]; then
    echo -e "${BOLD}Failed checks (${#FAILED_CHECKS[@]}):${NC}"
    for check in "${FAILED_CHECKS[@]}"; do
      echo -e "  ${RED}✗${NC} $check"
    done
    echo ""
  fi

  print_failed_tests_summary
  print_slow_tests_summary

  if [ ${#FAILED_LOGS[@]} -gt 0 ]; then
    echo -e "${BOLD}Details:${NC}"
    for log in "${FAILED_LOGS[@]}"; do
      echo -e "$log"
      echo ""
    done
  fi

  print_note "Fix the issues above and re-run ./scripts/verify_finally.sh"
  echo ""
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PARALLEL CHECK WRAPPERS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Run a check function and capture its exit status to a file.
# Args: $1 = check name, $2 = output file, rest = function + args
_run_check_to_file() {
  local check_name="$1"
  local output_file="$2"
  shift 2
  "$@" >/dev/null 2>&1
  echo $? >"$output_file"
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN EXECUTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

cd "$WORKSPACE_ROOT"

echo -e "${BOLD}verify_finally${NC} — pre-commit checks"

setup_workspace

if $DEPS_ONLY; then
  validate_package_dependencies
  print_final_summary
  exit $OVERALL_STATUS
fi

validate_package_dependencies || true

# Run format, lint, and asyncapi checks in parallel for performance.
# Each writes its own output, then we collect results.
if $SKIP_TESTS; then
  # Quick mode: run checks sequentially (simpler output)
  check_formatting || true
  check_linting || true
  check_vulture || true
  check_asyncapi_drift || true
else
  # Full mode: parallelize independent checks
  # Run each check in a subshell that writes exit status to a file.
  # Parent shell collects statuses after wait to update OVERALL_STATUS.
  tmpdir=$(mktemp -d)
  pids=()

  # Launch parallel checks with exit-status capture
  (
    check_formatting
    echo $? >"$tmpdir/format.exit"
  ) >"$tmpdir/format.out" 2>&1 &
  pids+=($!)
  (
    check_linting
    echo $? >"$tmpdir/lint.exit"
  ) >"$tmpdir/lint.out" 2>&1 &
  pids+=($!)
  (
    check_vulture
    echo $? >"$tmpdir/vulture.exit"
  ) >"$tmpdir/vulture.out" 2>&1 &
  pids+=($!)
  (
    check_asyncapi_drift
    echo $? >"$tmpdir/asyncapi.exit"
  ) >"$tmpdir/asyncapi.out" 2>&1 &
  pids+=($!)

  # Wait for all checks
  for pid in "${pids[@]}"; do
    wait "$pid" || true
  done

  # Replay outputs in order
  cat "$tmpdir/format.out" 2>/dev/null || true
  cat "$tmpdir/lint.out" 2>/dev/null || true
  cat "$tmpdir/vulture.out" 2>/dev/null || true
  cat "$tmpdir/asyncapi.out" 2>/dev/null || true

  # Propagate failures to OVERALL_STATUS (subshell modifications don't reach parent)
  for check in format lint vulture asyncapi; do
    if [ -f "$tmpdir/${check}.exit" ]; then
      exit_code=$(cat "$tmpdir/${check}.exit")
      if [ "$exit_code" -ne 0 ]; then
        OVERALL_STATUS=1
      fi
    fi
  done

  rm -rf "$tmpdir"
fi

run_tests || true

print_final_summary
exit $OVERALL_STATUS
