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
NC='\033[0m' # No Color

# Track overall status
OVERALL_STATUS=0
FAILED_CHECKS=()
FAILED_LOGS=()

# Log file for capturing output (cleaned up on exit)
LOG_FILE=$(mktemp)
trap 'rm -f "$LOG_FILE"' EXIT

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

print_header() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║           $1${NC}"
    echo -e "${BLUE}╚══════════════━━══════════════════════════════════════════════════╝${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_failure() {
    echo -e "${RED}✗ $1${NC}"
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

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${CYAN}ℹ $1${NC}"
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

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PACKAGE DEPENDENCY VALIDATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

validate_package_dependencies() {
    print_header "Package Dependency Validation"

    cd "$WORKSPACE_ROOT"

    local dep_details=""

    # Rule 1: soothe-cli MUST NOT import the daemon runtime
    print_info "Checking: soothe-cli must not import daemon runtime (soothe_daemon)..."

    CLI_DAEMON_IMPORTS=$(grep -rEl 'from soothe_daemon|import soothe_daemon' packages/soothe-cli/src --include='*.py' 2>/dev/null || true)

    if [ -n "$CLI_DAEMON_IMPORTS" ]; then
        print_failure "CLI package imports daemon runtime (violations found)"
        local violations
        violations=$(grep -rE 'from soothe_daemon|import soothe_daemon' packages/soothe-cli/src --include='*.py' | head -10)
        dep_details+="[CLI -> daemon]\n${violations}\n"
        record_failure_log "Dependency: CLI -> daemon" "$violations"
        return 1
    else
        print_success "CLI package does not import daemon runtime"
    fi

    # Rule 2: soothe-sdk MUST NOT import any other package
    print_info "Checking: soothe-sdk must be independent (no soothe-cli/soothe/soothe_daemon imports)..."

    SDK_IMPORTS=$(grep -rEl 'from soothe_cli|from soothe_daemon|from soothe[. ]|import soothe_cli|import soothe_daemon|import soothe$|import soothe\.' packages/soothe-sdk/src --include='*.py' 2>/dev/null || true)

    if [ -n "$SDK_IMPORTS" ]; then
        print_failure "SDK package imports other packages (violations found)"
        local violations
        violations=$(grep -rE 'from soothe_cli|from soothe_daemon|from soothe[. ]|import soothe_cli|import soothe_daemon|import soothe$|import soothe\.' packages/soothe-sdk/src --include='*.py' | head -10)
        record_failure_log "Dependency: SDK independence" "$violations"
        return 1
    else
        print_success "SDK package is independent"
    fi

    # Rule 3: soothe (in-proc agent core) MUST NOT depend on soothe-daemon
    # The dependency arrow is one-way: soothe-daemon -> soothe, never the reverse.
    print_info "Checking: soothe must not depend on soothe-daemon..."

    SOOTHE_TO_DAEMON_SRC=$(grep -rEl 'from soothe_daemon|import soothe_daemon' packages/soothe/src --include='*.py' 2>/dev/null || true)
    if [ -n "$SOOTHE_TO_DAEMON_SRC" ]; then
        print_failure "soothe (in-proc core) imports soothe-daemon (violations found)"
        local violations
        violations=$(grep -rE 'from soothe_daemon|import soothe_daemon' packages/soothe/src --include='*.py' | head -10)
        record_failure_log "Dependency: soothe -> daemon" "$violations"
        return 1
    fi

    # Same rule, distribution-metadata edition: pyproject.toml must not pull
    # soothe-daemon into soothe's dependency tree. Only check the core
    # dependencies block (not optional-dependencies, where daemon extra is OK).
    if sed -n '/^dependencies = \[/,/\]/p' packages/soothe/pyproject.toml | grep -E '"soothe-daemon' >/dev/null 2>&1; then
        print_failure "packages/soothe/pyproject.toml core dependencies lists soothe-daemon"
        local violations
        violations=$(sed -n '/^dependencies = \[/,/\]/p' packages/soothe/pyproject.toml | grep -nE '"soothe-daemon')
        record_failure_log "Dependency: soothe pyproject.toml" "$violations"
        return 1
    fi
    print_success "soothe does not depend on soothe-daemon (one-way dep verified)"

    # Rule 4: soothe-daemon MUST NOT depend on soothe-cli in core dependencies
    # (dev dependency for tests is OK)
    print_info "Checking: soothe-daemon must not depend on soothe-cli in runtime deps..."
    if sed -n '/^dependencies = \[/,/\]/p' packages/soothe-daemon/pyproject.toml | grep -E '"soothe-cli' >/dev/null 2>&1; then
        print_failure "packages/soothe-daemon/pyproject.toml core dependencies lists soothe-cli"
        local violations
        violations=$(sed -n '/^dependencies = \[/,/\]/p' packages/soothe-daemon/pyproject.toml | grep -nE '"soothe-cli')
        record_failure_log "Dependency: daemon pyproject.toml" "$violations"
        return 1
    fi
    print_success "soothe-daemon does not depend on soothe-cli in runtime deps"

    # Rule 5: Workspace integrity - all packages must be in sync
    print_info "Checking: workspace integrity..."

    if ! command -v uv >/dev/null 2>&1; then
        print_warning "uv not found, skipping workspace sync check"
    else
        # Match the real sync invocation so the dry-run cannot quietly disagree.
        local sync_output
        sync_output=$(uv sync --all-packages --all-extras --dry-run 2>&1) || true
        if echo "$sync_output" | grep -qE "error|would update|would install"; then
            print_failure "Workspace sync would fail (run 'make sync' to resolve)"
            record_failure_log "Workspace sync" "$(echo "$sync_output" | head -20)"
            return 1
        else
            print_success "Workspace packages are in sync"
        fi
    fi

    # Rule 5: Check for package import boundaries using existing script
    if [ -f "$WORKSPACE_ROOT/scripts/check_module_import_boundaries.sh" ]; then
        print_info "Running import boundary checks..."
        if bash "$WORKSPACE_ROOT/scripts/check_module_import_boundaries.sh" >/dev/null 2>&1; then
            print_success "Import boundary checks passed"
        else
            print_warning "Import boundary checks failed (see script output for details)"
        fi
    fi

    return 0
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# WORKSPACE SETUP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

setup_workspace() {
    print_header "Workspace Setup"

    cd "$WORKSPACE_ROOT"

    if ! command -v uv >/dev/null 2>&1; then
        print_failure "uv is not installed. Please install uv first."
        exit 1
    fi

    print_info "Syncing workspace packages with all dependencies (equivalent to 'make sync')..."
    # Equivalent to `make sync`: --all-packages + --all-extras with index env
    # vars cleared so a misconfigured mirror cannot leave the venv with
    # dist-info but no wheels (psycopg_pool/jsonschema/langfuse drop-outs).
    if ! "${UV_SYNC_CMD[@]}" 2>&1; then
        print_failure "uv sync failed - cannot continue verification"
        print_info "Try running 'make sync' or 'uv sync --all-packages --all-extras' manually"
        exit 1
    fi
    print_success "Workspace synced (all packages, all extras)"

    print_info "Verifying critical daemon dependencies (psycopg_pool, jsonschema, langfuse)..."
    if ! _verify_critical_deps; then
        print_failure "Critical dependencies missing after sync (broken mirror?)"
        print_info "Try: 'make sync' to re-sync with PyPI"
        exit 1
    fi
    print_success "Critical daemon dependencies present"
}

# Re-verify the venv still has everything installed before the most
# dependency-heavy phase (tests). Cheap import-only check; on failure we
# re-run the workspace sync rather than failing the run.
ensure_deps_installed() {
    cd "$WORKSPACE_ROOT"
    if _verify_critical_deps >/dev/null 2>&1; then
        return 0
    fi
    print_warning "Critical deps missing mid-run; re-syncing workspace..."
    if ! "${UV_SYNC_CMD[@]}" >/dev/null 2>&1; then
        print_failure "Re-sync failed"
        return 1
    fi
    _verify_critical_deps
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CODE FORMATTING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

check_formatting() {
    print_header "Code Formatting Check"

    cd "$WORKSPACE_ROOT"

    if $AUTO_FIX; then
        print_info "Auto-fixing formatting across all packages..."
        if make format >/dev/null 2>&1; then
            print_success "Formatting auto-fixed"
        else
            print_failure "Formatting auto-fix failed"
        fi
    else
        print_info "Checking code formatting across all packages..."

        local format_failed=false
        local format_details=""

        for pkg in "${ALL_PACKAGES[@]}"; do
            print_info "  $pkg..."
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
                print_success "    $pkg formatting OK"
            else
                print_failure "    $pkg formatting issues found"
                format_failed=true
                format_details+="\n[$pkg]\n${output}\n"
            fi
        done

        if $format_failed; then
            print_failure "Code formatting check failed (run with --fix to auto-fix)"
            record_failure_log "Formatting" "$format_details"
            return 1
        fi
    fi

    return 0
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# LINTING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

check_linting() {
    print_header "Linting Check"

    cd "$WORKSPACE_ROOT"

    if $AUTO_FIX; then
        print_info "Auto-fixing linting issues across all packages..."
        if make lint-fix >/dev/null 2>&1; then
            print_success "Linting auto-fixed"
        else
            print_failure "Linting auto-fix failed"
        fi
    else
        print_info "Running linter across all packages..."

        local lint_failed=false
        local lint_details=""

        for pkg in "${ALL_PACKAGES[@]}"; do
            print_info "  $pkg..."
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
                print_success "    $pkg linting OK"
            else
                print_failure "    $pkg linting errors found"
                lint_failed=true
                lint_details+="\n[$pkg]\n${output}\n"
            fi
        done

        if $lint_failed; then
            print_failure "Linting check failed (run with --fix to auto-fix)"
            record_failure_log "Linting" "$lint_details"
            return 1
        fi
    fi

    return 0
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# UNIT TESTS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

run_tests() {
    if $SKIP_TESTS; then
        print_info "Skipping tests (--quick mode)"
        return 0
    fi

    print_header "Unit Tests"

    cd "$WORKSPACE_ROOT"

    # Safety net before the dependency-heaviest phase: confirm the venv still
    # has the critical packages installed; if anything has been stripped
    # (e.g. by a stray per-package `uv sync` in another shell), re-sync.
    if ! ensure_deps_installed; then
        print_failure "Cannot run tests: dependency state could not be restored"
        return 1
    fi

    local tests_failed=false
    local test_details=""
    local failed_test_files=""

    for pkg in "${ALL_PACKAGES[@]}"; do
        if [ ! -d "$WORKSPACE_ROOT/packages/$pkg/tests/unit" ]; then
            continue
        fi

        print_info "Running unit tests for $pkg..."
        cd "$WORKSPACE_ROOT/packages/$pkg"
        local output
        local exit_code
        output=$(uv run python -m pytest tests/unit/ -v --tb=short 2>&1) && exit_code=0 || exit_code=$?
        cd "$WORKSPACE_ROOT"
        if [ $exit_code -eq 0 ]; then
            print_success "$pkg unit tests passed"
        else
            print_failure "$pkg unit tests failed"
            tests_failed=true
            test_details+="\n[$pkg]\n"
            # Extract just the failed test names and summary
            test_details+=$(echo "$output" | grep -E "^FAILED|short test summary|failed [0-9]+," | head -30)
            test_details+="\n"
            # Collect failed test file paths for quick reference
            failed_test_files+=$(echo "$output" | grep -oE "tests/unit/[^:]+\.py" | sort -u | tr '\n' ' ')
        fi
    done

    if $tests_failed; then
        record_failure_log "Tests" "$test_details"
        if [ -n "$failed_test_files" ]; then
            record_failure_log "Failed test files" "$failed_test_files"
        fi
        return 1
    fi

    return 0
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN EXECUTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Ensure we start in workspace root
cd "$WORKSPACE_ROOT"

print_header "Soothe Pre-Commit Verification Suite"

# Always setup workspace first (single sync, no hanging pipe)
setup_workspace

# Dependency validation only mode
if $DEPS_ONLY; then
    validate_package_dependencies
    exit $OVERALL_STATUS
fi

# Run all checks (use || true to continue on failure and accumulate results)
validate_package_dependencies || true
check_formatting || true
check_linting || true
run_tests || true

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# FINAL SUMMARY
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print_header "Verification Summary"

if [ $OVERALL_STATUS -eq 0 ]; then
    print_success "All checks passed! Ready to commit."
    echo ""
    exit 0
else
    print_failure "Some checks failed:"
    for check in "${FAILED_CHECKS[@]}"; do
        echo "  - $check"
    done
    echo ""

    # Print detailed failure logs if available
    if [ ${#FAILED_LOGS[@]} -gt 0 ]; then
        echo -e "${BOLD}━━━━━━━━━━━━ Failure Details ━━━━━━━━━━━━${NC}"
        echo ""
        for log in "${FAILED_LOGS[@]}"; do
            echo -e "$log"
            echo ""
        done
    fi

    print_info "Fix the issues above and run this script again."
    echo ""
    exit 1
fi
