#!/usr/bin/env bash
#
# verify_finally.sh - Run all verification checks before committing
#
# This script runs the complete verification suite:
# 1. Code formatting check (make format-check)
# 2. Linting (make lint) - checks ALL files in src/ and tests/
# 3. Unit tests (make test-unit)
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
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --fix     Auto-fix formatting and linting issues"
            echo "  --quick   Skip tests (format + lint only)"
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
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}  $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
}

# Function to print success message
print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

# Function to print failure message
print_failure() {
    echo -e "${RED}✗ $1${NC}"
}

# Function to print warning
print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

# Function to print info
print_info() {
    echo -e "${CYAN}ℹ $1${NC}"
}

# Function to suggest fixes
suggest_fixes() {
    local check_name="$1"
    echo ""
    echo -e "${YELLOW}💡 Suggested fixes:${NC}"

    case $check_name in
        "format-check")
            echo "  1. Run: make format"
            echo "  2. Or run: $0 --fix"
            ;;
        "lint")
            echo "  1. Run: make lint-fix"
            echo "  2. Or run: $0 --fix"
            echo "  3. Check specific files with: uv run ruff check src/ tests/ --show-fixes"
            ;;
        "test-unit")
            echo "  1. Run specific failing tests: uv run pytest tests/unit/test_file.py::test_name -xvs"
            echo "  2. Check test output above for error details"
            ;;
    esac
    echo ""
}

# Get script start time
START_TIME=$(date +%s)

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           Soothe Pre-Commit Verification Suite                    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════╝${NC}"

# Show configuration
if [ "$AUTO_FIX" = true ]; then
    echo -e "${CYAN}Auto-fix mode: ENABLED${NC}"
fi
if [ "$SKIP_TESTS" = true ]; then
    echo -e "${CYAN}Quick mode: ENABLED (tests skipped)${NC}"
fi

# Count files to check
SRC_FILES=$(find src -name "*.py" 2>/dev/null | wc -l | tr -d ' ')
TEST_FILES=$(find tests -name "*.py" 2>/dev/null | wc -l | tr -d ' ')
TOTAL_FILES=$((SRC_FILES + TEST_FILES))

print_info "Checking ${TOTAL_FILES} Python files (${SRC_FILES} in src/, ${TEST_FILES} in tests/)"

# ─────────────────────────────────────────────────────────────────────────────
# Check 1: Code Formatting
# ─────────────────────────────────────────────────────────────────────────────

if [ "$SKIP_TESTS" = true ]; then
    TOTAL_CHECKS=2
else
    TOTAL_CHECKS=3
fi

print_header "Check 1/${TOTAL_CHECKS}: Code Formatting (make format-check)"

if [ "$AUTO_FIX" = true ]; then
    print_info "Auto-fixing formatting issues..."
    if make format 2>&1; then
        print_success "Code formatting fixed"
    else
        print_failure "Code formatting fix failed"
        OVERALL_STATUS=1
        FAILED_CHECKS+=("format-check")
    fi
else
    if make format-check > /dev/null 2>&1; then
        print_success "Code formatting check passed"
        echo "  All files are properly formatted"
    else
        print_failure "Code formatting check failed"
        echo ""
        echo "  Running format check with output:"
        echo ""
        if make format-check 2>&1; then
            :
        else
            OVERALL_STATUS=1
            FAILED_CHECKS+=("format-check")
            suggest_fixes "format-check"
        fi
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Check 2: Linting
# ─────────────────────────────────────────────────────────────────────────────

print_header "Check 2/${TOTAL_CHECKS}: Linting (make lint)"

if [ "$AUTO_FIX" = true ]; then
    print_info "Auto-fixing linting issues..."
    if make lint-fix 2>&1; then
        print_success "Linting issues fixed"
    else
        print_failure "Linting fix failed"
        echo ""
        echo "  Some issues cannot be auto-fixed. Running lint check..."
        if make lint 2>&1; then
            :
        else
            OVERALL_STATUS=1
            FAILED_CHECKS+=("lint")
            suggest_fixes "lint"
        fi
    fi
else
    if make lint > /dev/null 2>&1; then
        print_success "Linting check passed"
        echo "  No linting errors found"
    else
        print_failure "Linting check failed"
        echo ""
        echo "  Running lint with output:"
        echo ""
        if make lint 2>&1; then
            :
        else
            OVERALL_STATUS=1
            FAILED_CHECKS+=("lint")
            suggest_fixes "lint"
        fi
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Check 3: Unit Tests
# ─────────────────────────────────────────────────────────────────────────────

if [ "$SKIP_TESTS" = false ]; then
    print_header "Check 3/${TOTAL_CHECKS}: Unit Tests (make test-unit)"

    # Run tests and capture output
    TEST_OUTPUT_FILE=$(mktemp)
    if make test-unit 2>&1 | tee "$TEST_OUTPUT_FILE"; then
        print_success "Unit tests passed"

        # Extract test summary from output
        SUMMARY=$(grep -E "passed|failed|skipped" "$TEST_OUTPUT_FILE" | tail -1 || true)
        if [ -n "$SUMMARY" ]; then
            echo "  $SUMMARY"
        fi
    else
        EXIT_CODE=$?
        if [ $EXIT_CODE -eq 0 ]; then
            print_success "Unit tests passed"
            SUMMARY=$(grep -E "passed|failed|skipped" "$TEST_OUTPUT_FILE" | tail -1 || true)
            if [ -n "$SUMMARY" ]; then
                echo "  $SUMMARY"
            fi
        else
            print_failure "Unit tests failed"
            OVERALL_STATUS=1
            FAILED_CHECKS+=("test-unit")

            # Show failure summary
            echo ""
            echo -e "${YELLOW}Failed tests:${NC}"
            grep -E "FAILED|ERROR" "$TEST_OUTPUT_FILE" | head -10 || true
            echo ""
            suggest_fixes "test-unit"
        fi
    fi

    # Clean up temp file
    rm -f "$TEST_OUTPUT_FILE"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Final Summary
# ─────────────────────────────────────────────────────────────────────────────

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

echo ""
echo -e "${BLUE}══════════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Final Summary${NC}"
echo -e "${BLUE}══════════════════════════════════════════════════════════════════${NC}"
echo ""

if [ $OVERALL_STATUS -eq 0 ]; then
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                    ALL CHECKS PASSED! ✓                          ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    print_success "Format check: PASSED"
    print_success "Linting:       PASSED"
    if [ "$SKIP_TESTS" = false ]; then
        print_success "Unit tests:    PASSED"
    else
        print_info "Unit tests:    SKIPPED (--quick mode)"
    fi
    echo ""
    echo -e "Total duration: ${YELLOW}${DURATION}s${NC}"
    echo ""

    if [ "$AUTO_FIX" = true ]; then
        print_warning "Auto-fix was applied. Review changes before committing."
        echo ""
        echo "  To see what was changed:"
        echo "    git diff"
        echo ""
        echo "  To commit the fixes:"
        echo "    git add -A && git commit"
        echo ""
    else
        echo -e "${GREEN}✓ Ready to commit!${NC}"
        echo ""
    fi
else
    echo -e "${RED}╔══════════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${RED}║                   SOME CHECKS FAILED! ✗                          ║${NC}"
    echo -e "${RED}╚══════════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${RED}Failed checks:${NC}"
    for check in "${FAILED_CHECKS[@]}"; do
        print_failure "$check"
    done
    echo ""
    echo -e "Total duration: ${YELLOW}${DURATION}s${NC}"
    echo ""

    if [ "$AUTO_FIX" = false ]; then
        print_info "Tip: Run with --fix to auto-fix formatting and linting issues"
        echo ""
    fi

    echo -e "${RED}✗ Please fix the issues above before committing${NC}"
    echo ""
fi

exit $OVERALL_STATUS