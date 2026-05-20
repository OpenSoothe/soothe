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

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Track overall status
OVERALL_STATUS=0
FAILED_CHECKS=()

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

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

# Sync a single package (idempotent, skips if already synced)
_sync_package() {
    local pkg="$1"
    cd "$PROJECT_ROOT/packages/$pkg"
    uv sync --all-extras >/dev/null 2>&1 || true
    cd "$PROJECT_ROOT"
}

# Sync all packages once
_sync_all_packages() {
    for pkg in "${ALL_PACKAGES[@]}"; do
        _sync_package "$pkg"
    done
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PACKAGE DEPENDENCY VALIDATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

validate_package_dependencies() {
    print_header "Package Dependency Validation"

    # Rule 1: soothe-cli MUST NOT import the daemon runtime
    print_info "Checking: soothe-cli must not import daemon runtime (soothe_daemon)..."

    CLI_DAEMON_IMPORTS=$(grep -rEl 'from soothe_daemon|import soothe_daemon' packages/soothe-cli/src --include='*.py' 2>/dev/null || true)

    if [ -n "$CLI_DAEMON_IMPORTS" ]; then
        print_failure "CLI package imports daemon runtime (violations found)"
        echo "Violations:"
        echo "$CLI_DAEMON_IMPORTS"
        echo ""
        echo "Forbidden patterns:"
        grep -rE 'from soothe_daemon|import soothe_daemon' packages/soothe-cli/src --include='*.py' | head -10 || true
        return 1
    else
        print_success "CLI package does not import daemon runtime"
    fi

    # Rule 2: soothe-sdk MUST NOT import any other package
    print_info "Checking: soothe-sdk must be independent (no soothe-cli/soothe/soothe_daemon imports)..."

    SDK_IMPORTS=$(grep -rEl 'from soothe_cli|from soothe_daemon|from soothe[. ]|import soothe_cli|import soothe_daemon|import soothe$|import soothe\.' packages/soothe-sdk/src --include='*.py' 2>/dev/null || true)

    if [ -n "$SDK_IMPORTS" ]; then
        print_failure "SDK package imports other packages (violations found)"
        echo "Violations:"
        echo "$SDK_IMPORTS"
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
        echo "Violations:"
        echo "$SOOTHE_TO_DAEMON_SRC"
        echo ""
        grep -rE 'from soothe_daemon|import soothe_daemon' packages/soothe/src --include='*.py' | head -10 || true
        return 1
    fi

    # Same rule, distribution-metadata edition: pyproject.toml must not pull
    # soothe-daemon into soothe's dependency tree. Only check the core
    # dependencies block (not optional-dependencies, where daemon extra is OK).
    if sed -n '/^dependencies = \[/,/\]/p' packages/soothe/pyproject.toml | grep -E '"soothe-daemon' >/dev/null 2>&1; then
        print_failure "packages/soothe/pyproject.toml core dependencies lists soothe-daemon"
        sed -n '/^dependencies = \[/,/\]/p' packages/soothe/pyproject.toml | grep -nE '"soothe-daemon' || true
        return 1
    fi
    print_success "soothe does not depend on soothe-daemon (one-way dep verified)"

    # Rule 4: soothe-daemon MUST NOT depend on soothe-cli in core dependencies
    # (dev dependency for tests is OK)
    print_info "Checking: soothe-daemon must not depend on soothe-cli in runtime deps..."
    if sed -n '/^dependencies = \[/,/\]/p' packages/soothe-daemon/pyproject.toml | grep -E '"soothe-cli' >/dev/null 2>&1; then
        print_failure "packages/soothe-daemon/pyproject.toml core dependencies lists soothe-cli"
        sed -n '/^dependencies = \[/,/\]/p' packages/soothe-daemon/pyproject.toml | grep -nE '"soothe-cli' || true
        return 1
    fi
    print_success "soothe-daemon does not depend on soothe-cli in runtime deps"

    # Rule 5: Workspace integrity - all packages must be in sync
    print_info "Checking: workspace integrity..."

    if ! command -v uv >/dev/null 2>&1; then
        print_warning "uv not found, skipping workspace sync check"
    else
        if ! uv sync --dry-run >/dev/null 2>&1; then
            print_failure "Workspace sync would fail (run 'uv sync' to resolve)"
            return 1
        else
            print_success "Workspace packages are in sync"
        fi
    fi

    # Rule 5: Check for package import boundaries using existing script
    if [ -f "scripts/check_module_import_boundaries.sh" ]; then
        print_info "Running import boundary checks..."
        if bash scripts/check_module_import_boundaries.sh >/dev/null 2>&1; then
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

    if ! command -v uv >/dev/null 2>&1; then
        print_failure "uv is not installed. Please install uv first."
        exit 1
    fi

    print_info "Syncing workspace packages with all dependencies..."
    # Run uv sync with all packages and extras - must succeed
    if ! uv sync --all-packages --all-extras 2>&1; then
        print_failure "uv sync failed - cannot continue verification"
        print_info "Try running 'make sync' or 'uv sync --all-packages --all-extras' manually"
        exit 1
    fi
    print_success "Workspace synced (all packages, all extras)"
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CODE FORMATTING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

check_formatting() {
    print_header "Code Formatting Check"

    PROJECT_ROOT="$(pwd)"

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

        for pkg in "${ALL_PACKAGES[@]}"; do
            print_info "  $pkg..."
            _sync_package "$pkg"
            cd "$PROJECT_ROOT/packages/$pkg"
            local paths="src/"
            if [ -d "tests/" ]; then
                paths="src/ tests/"
            fi
            if uv run ruff format --check $paths >/dev/null 2>&1; then
                cd "$PROJECT_ROOT"
                print_success "    $pkg formatting OK"
            else
                cd "$PROJECT_ROOT"
                print_failure "    $pkg formatting issues found"
                format_failed=true
            fi
        done

        if $format_failed; then
            print_failure "Code formatting check failed (run with --fix to auto-fix)"
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

    PROJECT_ROOT="$(pwd)"

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

        for pkg in "${ALL_PACKAGES[@]}"; do
            print_info "  $pkg..."
            _sync_package "$pkg"
            cd "$PROJECT_ROOT/packages/$pkg"
            local paths="src/"
            if [ -d "tests/" ]; then
                paths="src/ tests/"
            fi
            if uv run ruff check $paths >/dev/null 2>&1; then
                cd "$PROJECT_ROOT"
                print_success "    $pkg linting OK"
            else
                cd "$PROJECT_ROOT"
                print_failure "    $pkg linting errors found"
                lint_failed=true
            fi
        done

        if $lint_failed; then
            print_failure "Linting check failed (run with --fix to auto-fix)"
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

    PROJECT_ROOT="$(pwd)"

    local tests_failed=false

    for pkg in "${ALL_PACKAGES[@]}"; do
        if [ ! -d "$PROJECT_ROOT/packages/$pkg/tests/unit" ]; then
            continue
        fi

        print_info "Running unit tests for $pkg..."
        _sync_package "$pkg"
        cd "$PROJECT_ROOT/packages/$pkg"
        if uv run python -m pytest tests/unit/ -v --tb=short; then
            cd "$PROJECT_ROOT"
            print_success "$pkg unit tests passed"
        else
            cd "$PROJECT_ROOT"
            print_failure "$pkg unit tests failed"
            tests_failed=true
        fi
    done

    if $tests_failed; then
        return 1
    fi

    return 0
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN EXECUTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print_header "Soothe Pre-Commit Verification Suite"

# Always setup workspace first (single sync, no hanging pipe)
setup_workspace

# Dependency validation only mode
if $DEPS_ONLY; then
    validate_package_dependencies
    exit $OVERALL_STATUS
fi

# Run all checks
validate_package_dependencies
check_formatting
check_linting
run_tests

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
    print_info "Fix the issues above and run this script again."
    echo ""
    exit 1
fi
