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
# 3. Code formatting check (make format)
# 4. Linting (make lint) - checks ALL packages
# 5. Unit tests (all packages)
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
pkgs = ("psycopg_pool", "jsonschema", "langfuse")
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

# Background: alert when pytest produces no output for SLOW_TEST_THRESHOLD_SEC.
_hang_watcher() {
    local activity_file="$1"
    local context_file="$2"
    local pkg="$3"
    local slow_file="$4"
    local last_alert_ts=""

    while [ -f "${activity_file}.running" ]; do
        sleep 10
        [ ! -f "$activity_file" ] && continue

        local last_ts now elapsed ctx
        last_ts=$(cat "$activity_file")
        now=$(_now_seconds)
        elapsed=$((now - last_ts))
        ctx=$(cat "$context_file" 2>/dev/null || echo "unknown")

        if [ "$elapsed" -lt "$SLOW_TEST_THRESHOLD_SEC" ]; then
            continue
        fi
        if [ "$last_alert_ts" = "$last_ts" ]; then
            continue
        fi

        last_alert_ts="$last_ts"
        local ctx_short="${ctx#tests/unit/}"
        echo -e "  ${YELLOW}⏱${NC} no output for $(_format_duration "$elapsed") — possible hang after: ${ctx_short}" >&2
        printf '%s|%s|%s|hang\n' "$pkg" "$ctx" "$elapsed" >>"$slow_file"
    done
}

# Stream pytest output: print fail/error/skip/slow immediately.
# $2 failures file (pkg|test_id|reason), $3 slow file (pkg|test_id|sec|kind),
# $4 activity timestamp file, $5 context file (last completed test id).
_parse_pytest_lines() {
    local pkg="$1"
    local failures_file="$2"
    local slow_file="$3"
    local activity_file="$4"
    local context_file="$5"
    local summary_line=""
    local last_ts
    local collecting=true

    last_ts=$(_now_seconds)
    echo "$last_ts" >"$activity_file"
    echo "collecting" >"$context_file"

    while IFS= read -r line; do
        echo "$(_now_seconds)" >"$activity_file"

        if [[ "$line" =~ collected[[:space:]]+[0-9]+[[:space:]]+items ]]; then
            collecting=false
            last_ts=$(_now_seconds)
            echo "after collection" >"$context_file"
            continue
        fi

        if [[ "$line" =~ ^tests/([^[:space:]]+)[[:space:]]+(PASSED|FAILED|ERROR|SKIPPED) ]]; then
            local test_id="tests/${BASH_REMATCH[1]}"
            local status="${BASH_REMATCH[2]}"
            local short_id="${test_id#tests/unit/}"
            local now elapsed

            now=$(_now_seconds)
            elapsed=$((now - last_ts))
            if [ "$collecting" = false ] && [ "$elapsed" -ge "$SLOW_TEST_THRESHOLD_SEC" ]; then
                if ! grep -Fq "${pkg}|${test_id}|" "$slow_file" 2>/dev/null; then
                    echo -e "  ${YELLOW}⏱${NC} ${short_id} ($(_format_duration "$elapsed"))"
                    printf '%s|%s|%s|slow\n' "$pkg" "$test_id" "$elapsed" >>"$slow_file"
                fi
            fi
            last_ts="$now"
            echo "$test_id" >"$context_file"

            case "$status" in
                PASSED) ;;
                FAILED)
                    echo -e "  ${RED}✗${NC} ${short_id}"
                    printf '%s|%s|\n' "$pkg" "$test_id" >>"$failures_file"
                    ;;
                ERROR)
                    echo -e "  ${RED}!${NC} ${short_id} (error)"
                    printf '%s|%s|\n' "$pkg" "$test_id" >>"$failures_file"
                    ;;
                SKIPPED)
                    echo -e "  ${YELLOW}○${NC} ${short_id} (skipped)"
                    ;;
            esac
        elif [[ "$line" =~ ^FAILED[[:space:]]+(tests/[^[:space:]]+)[[:space:]]-[[:space:]]*(.+)$ ]]; then
            local test_id="${BASH_REMATCH[1]}"
            local reason="${BASH_REMATCH[2]}"
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
        elif [[ "$line" =~ ^=+[[:space:]]+([0-9]+[[:space:]].*)[[:space:]]=+$ ]]; then
            summary_line="${BASH_REMATCH[1]}"
        fi
    done

    if [ -n "$summary_line" ]; then
        echo -e "  ${DIM}${summary_line}${NC}"
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
    CLI_DAEMON_IMPORTS=$(grep -rEl 'from soothe_daemon|import soothe_daemon' packages/soothe-cli/src --include='*.py' 2>/dev/null || true)

    if [ -n "$CLI_DAEMON_IMPORTS" ]; then
        print_fail "cli must not import soothe_daemon"
        local violations
        violations=$(grep -rE 'from soothe_daemon|import soothe_daemon' packages/soothe-cli/src --include='*.py' | head -10)
        record_failure_log "Dependency: CLI -> daemon" "$violations"
        return 1
    else
        print_ok "cli → daemon boundary"
    fi

    # Rule 2: soothe-sdk MUST NOT import any other package
    SDK_IMPORTS=$(grep -rEl 'from soothe_cli|from soothe_daemon|from soothe[. ]|import soothe_cli|import soothe_daemon|import soothe$|import soothe\.' packages/soothe-sdk/src --include='*.py' 2>/dev/null || true)

    if [ -n "$SDK_IMPORTS" ]; then
        print_fail "sdk must be independent"
        local violations
        violations=$(grep -rE 'from soothe_cli|from soothe_daemon|from soothe[. ]|import soothe_cli|import soothe_daemon|import soothe$|import soothe\.' packages/soothe-sdk/src --include='*.py' | head -10)
        record_failure_log "Dependency: SDK independence" "$violations"
        return 1
    else
        print_ok "sdk independence"
    fi

    # Rule 3: soothe (in-proc agent core) MUST NOT depend on soothe-daemon
    SOOTHE_TO_DAEMON_SRC=$(grep -rEl 'from soothe_daemon|import soothe_daemon' packages/soothe/src --include='*.py' 2>/dev/null || true)
    if [ -n "$SOOTHE_TO_DAEMON_SRC" ]; then
        print_fail "soothe must not import soothe_daemon"
        local violations
        violations=$(grep -rE 'from soothe_daemon|import soothe_daemon' packages/soothe/src --include='*.py' | head -10)
        record_failure_log "Dependency: soothe -> daemon" "$violations"
        return 1
    fi

    if sed -n '/^dependencies = \[/,/\]/p' packages/soothe/pyproject.toml | grep -E '"soothe-daemon' >/dev/null 2>&1; then
        print_fail "soothe pyproject.toml lists soothe-daemon in core deps"
        local violations
        violations=$(sed -n '/^dependencies = \[/,/\]/p' packages/soothe/pyproject.toml | grep -nE '"soothe-daemon')
        record_failure_log "Dependency: soothe pyproject.toml" "$violations"
        return 1
    fi
    print_ok "soothe ↛ soothe-daemon"

    # Rule 4: soothe-daemon MUST NOT depend on soothe-cli in core dependencies
    if sed -n '/^dependencies = \[/,/\]/p' packages/soothe-daemon/pyproject.toml | grep -E '"soothe-cli' >/dev/null 2>&1; then
        print_fail "soothe-daemon pyproject.toml lists soothe-cli in core deps"
        local violations
        violations=$(sed -n '/^dependencies = \[/,/\]/p' packages/soothe-daemon/pyproject.toml | grep -nE '"soothe-cli')
        record_failure_log "Dependency: daemon pyproject.toml" "$violations"
        return 1
    fi
    print_ok "daemon ↛ soothe-cli (runtime)"

    # Rule 5: Workspace integrity - all packages must be in sync
    if ! command -v uv >/dev/null 2>&1; then
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

    for pkg in "${ALL_PACKAGES[@]}"; do
        cd "$WORKSPACE_ROOT/packages/$pkg"
        local paths="src/"
        if [ -d "tests/" ]; then
            paths="src/ tests/"
        fi
        local output
        local exit_code
        output=$(uv run ruff format --check $paths 2>&1) && exit_code=0 || exit_code=$?
        cd "$WORKSPACE_ROOT"
        if [ $exit_code -eq 0 ]; then
            print_ok "$pkg"
        else
            print_fail "$pkg"
            format_failed=true
            format_details+="\n[$pkg]\n${output}\n"
        fi
    done

    if $format_failed; then
        record_failure_log "Formatting" "$format_details"
        print_note "run with --fix to auto-fix"
        return 1
    fi

    return 0
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
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

    for pkg in "${ALL_PACKAGES[@]}"; do
        cd "$WORKSPACE_ROOT/packages/$pkg"
        local paths="src/"
        if [ -d "tests/" ]; then
            paths="src/ tests/"
        fi
        local output
        local exit_code
        output=$(uv run ruff check $paths 2>&1) && exit_code=0 || exit_code=$?
        cd "$WORKSPACE_ROOT"
        if [ $exit_code -eq 0 ]; then
            print_ok "$pkg"
        else
            print_fail "$pkg"
            lint_failed=true
            lint_details+="\n[$pkg]\n${output}\n"
        fi
    done

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
    output=$(uv run python scripts/check_asyncapi_drift.py --strict 2>&1) && exit_code=0 || exit_code=$?
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
    local test_details=""

    for pkg in "${ALL_PACKAGES[@]}"; do
        if [ ! -d "$WORKSPACE_ROOT/packages/$pkg/tests/unit" ]; then
            continue
        fi

        echo -e "  ${CYAN}${pkg}${NC}"
        cd "$WORKSPACE_ROOT/packages/$pkg"

        local failures_file output_file slow_file activity_file context_file
        failures_file=$(mktemp)
        output_file=$(mktemp)
        slow_file=$(mktemp)
        activity_file=$(mktemp)
        context_file=$(mktemp)
        touch "${activity_file}.running"
        local exit_code=0
        local watcher_pid=""

        _hang_watcher "$activity_file" "$context_file" "$pkg" "$slow_file" &
        watcher_pid=$!

        set +e
        uv run python -m pytest tests/unit/ \
            -v --tb=line --no-header --disable-warnings \
            2>&1 | tee "$output_file" | _parse_pytest_lines "$pkg" "$failures_file" "$slow_file" "$activity_file" "$context_file"
        exit_code=${PIPESTATUS[0]}
        set -e

        rm -f "${activity_file}.running"
        wait "$watcher_pid" 2>/dev/null || true

        cd "$WORKSPACE_ROOT"

        if [ -s "$failures_file" ]; then
            _collect_failures_file "$failures_file"
        fi
        if [ -s "$slow_file" ]; then
            _collect_slow_file "$slow_file"
        fi

        if [ $exit_code -eq 0 ]; then
            print_ok "${pkg}"
        else
            print_fail "${pkg}"
            tests_failed=true
            test_details+="\n[$pkg]\n"
            test_details+=$(grep -E "^FAILED|^ERROR" "$output_file" || true)
            test_details+="\n"
        fi

        rm -f "$failures_file" "$output_file" "$slow_file" "$activity_file" "$context_file"
    done

    if $tests_failed; then
        record_failure_log "Tests" "$test_details"
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

    echo -e "${BOLD}Slow / hanging tests (≥$(_format_duration "$SLOW_TEST_THRESHOLD_SEC"), ${#SLOW_TEST_ENTRIES[@]}):${NC}"
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

    echo -e "${BOLD}Failed tests (${#FAILED_TEST_ENTRIES[@]}):${NC}"
    local current_pkg=""
    for entry in "${FAILED_TEST_ENTRIES[@]}"; do
        IFS='|' read -r pkg test_id reason <<<"$entry"
        if [ "$pkg" != "$current_pkg" ]; then
            echo -e "  ${BOLD}${pkg}${NC}"
            current_pkg="$pkg"
        fi
        local short_id="${test_id#tests/unit/}"
        echo -e "    ${RED}✗${NC} ${short_id}"
        if [ -n "$reason" ]; then
            echo -e "      ${DIM}${reason}${NC}"
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
check_formatting || true
check_linting || true
check_asyncapi_drift || true
run_tests || true

print_final_summary
exit $OVERALL_STATUS
