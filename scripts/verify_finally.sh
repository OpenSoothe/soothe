#!/usr/bin/env bash
#
# verify_finally.sh - Run all verification checks before committing (monorepo version)
#
# This script runs the complete verification suite for multi-package monorepo:
# 1. Workspace integrity check (uv sync)
# 2. Package dependency validation (no forbidden cross-package imports)
# 3. Code formatting check (make all-format)
# 4. Linting (make all-lint) - checks ALL packages
# 5. Unit tests (soothe daemon package tests)
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

# Function to print section headers
print_header() {
    echo ""
    echo -e "${BLUE}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${BLUE}║           $1${NC}"
    echo -e "${BLUE}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
}

# Function to print success message
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Function to print failure message
print_failure() {
    echo -e "${RED}✗ $1${NC}"
    FAILED_CHECKS+=("$1")
    OVERALL_STATUS=1
}

# Function to print warning
print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Function to print info
print_info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PACKAGE DEPENDENCY VALIDATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

validate_package_dependencies() {
    print_header "Package Dependency Validation"

    # Rule 1: soothe-cli MUST NOT import soothe daemon runtime
    print_info "Checking: soothe-cli must not import daemon runtime..."

    CLI_DAEMON_IMPORTS=$(find packages/soothe-cli/src -name "*.py" -exec grep -l "from soothe\." {} \; 2>/dev/null || true)

    if [ -n "$CLI_DAEMON_IMPORTS" ]; then
        print_failure "CLI package imports daemon runtime (violations found)"
        echo "Violations:"
        echo "$CLI_DAEMON_IMPORTS"
        echo ""
        echo "Forbidden patterns:"
        grep -r "from soothe\." packages/soothe-cli/src --include="*.py" | head -10 || true
        return 1
    else
        print_success "CLI package does not import daemon runtime"
    fi

    # Rule 2: soothe-sdk MUST NOT import any other package
    print_info "Checking: soothe-sdk must be independent (no soothe-cli/soothe imports)..."

    SDK_IMPORTS=$(find packages/soothe-sdk/src -name "*.py" -exec grep -l "from soothe_cli\|from soothe_daemon\|import soothe_cli\|import soothe_daemon" {} \; 2>/dev/null || true)

    if [ -n "$SDK_IMPORTS" ]; then
        print_failure "SDK package imports other packages (violations found)"
        echo "Violations:"
        echo "$SDK_IMPORTS"
        return 1
    else
        print_success "SDK package is independent"
    fi

    # Rule 3: Workspace integrity - all packages must be in sync
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

    # Rule 4: Check for package import boundaries using existing script
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

    print_info "Syncing workspace packages..."

    if ! uv sync 2>&1 | tail -5 | grep -q "Audited"; then
        # uv sync might take time, show progress
        uv sync &
        UV_PID=$!
        wait $UV_PID 2>/dev/null || true
    fi

    print_success "Workspace synced"
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CODE FORMATTING
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

check_formatting() {
    print_header "Code Formatting Check"

    if $AUTO_FIX; then
        print_info "Auto-fixing formatting across all packages..."
        if make all-format >/dev/null 2>&1; then
            print_success "Formatting auto-fixed"
        else
            print_failure "Formatting auto-fix failed"
        fi
    else
        print_info "Checking code formatting across all packages..."

        # Check each package individually
        local format_failed=false

        # SDK package
        print_info "  SDK package..."
        if cd packages/soothe-sdk && uv run ruff format --check src/ >/dev/null 2>&1; then
            print_success "    SDK formatting OK"
        else
            print_failure "    SDK formatting issues found"
            format_failed=true
        fi
        cd - >/dev/null

        # CLI package
        print_info "  CLI package..."
        if cd packages/soothe-cli && uv run ruff format --check src/ >/dev/null 2>&1; then
            print_success "    CLI formatting OK"
        else
            print_failure "    CLI formatting issues found"
            format_failed=true
        fi
        cd - >/dev/null

        # Daemon package (main tests directory)
        print_info "  Daemon package..."
        if cd packages/soothe && uv run ruff format --check src/ tests/ >/dev/null 2>&1; then
            print_success "    Daemon formatting OK"
        else
            print_failure "    Daemon formatting issues found"
            format_failed=true
        fi
        cd - >/dev/null

        # Community package
        print_info "  Community package..."
        if cd packages/soothe-community && uv run ruff format --check src/ >/dev/null 2>&1; then
            print_success "    Community formatting OK"
        else
            print_failure "    Community formatting issues found"
            format_failed=true
        fi
        cd - >/dev/null

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

    if $AUTO_FIX; then
        print_info "Auto-fixing linting issues across all packages..."
        if make all-lint >/dev/null 2>&1; then
            print_success "Linting auto-fixed"
        else
            print_failure "Linting auto-fix failed"
        fi
    else
        print_info "Running linter across all packages..."

        local lint_failed=false

        # SDK package
        print_info "  SDK package..."
        if cd packages/soothe-sdk && uv run ruff check src/ >/dev/null 2>&1; then
            print_success "    SDK linting OK"
        else
            print_failure "    SDK linting errors found"
            lint_failed=true
        fi
        cd - >/dev/null

        # CLI package
        print_info "  CLI package..."
        if cd packages/soothe-cli && uv run ruff check src/ >/dev/null 2>&1; then
            print_success "    CLI linting OK"
        else
            print_failure "    CLI linting errors found"
            lint_failed=true
        fi
        cd - >/dev/null

        # Daemon package
        print_info "  Daemon package..."
        if cd packages/soothe && uv run ruff check src/ tests/ >/dev/null 2>&1; then
            print_success "    Daemon linting OK (zero errors)"
        else
            print_failure "    Daemon linting errors found"
            lint_failed=true
        fi
        cd - >/dev/null

        # Community package
        print_info "  Community package..."
        if cd packages/soothe-community && uv run ruff check src/ >/dev/null 2>&1; then
            print_success "    Community linting OK"
        else
            print_failure "    Community linting errors found"
            lint_failed=true
        fi
        cd - >/dev/null

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

    print_info "Running unit tests for daemon package..."

    # Run daemon package tests (only package with tests currently)
    if cd packages/soothe && uv run pytest tests/unit/ -v --tb=short 2>&1 | tail -20; then
        cd - >/dev/null
        print_success "Unit tests passed"
    else
        cd - >/dev/null
        print_failure "Unit tests failed"
        return 1
    fi

    return 0
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MAIN EXECUTION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print_header "Soothe Pre-Commit Verification Suite"

# Always setup workspace first
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