#!/usr/bin/env bash
#
# verify_finally.sh - Run all verification checks before committing
#
# This script runs the complete verification suite:
# 1. Code formatting check (make format-check)
# 2. Linting (make lint)
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
#   ./scripts/verify_finally.sh
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
NC='\033[0m' # No Color

# Track overall status
OVERALL_STATUS=0
FAILED_CHECKS=()

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

# Get script start time
START_TIME=$(date +%s)

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           Soothe Pre-Commit Verification Suite                    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════════════╝${NC}"

# ─────────────────────────────────────────────────────────────────────────────
# Check 1: Code Formatting
# ─────────────────────────────────────────────────────────────────────────────

print_header "Check 1/3: Code Formatting (make format-check)"

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
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Check 2: Linting
# ─────────────────────────────────────────────────────────────────────────────

print_header "Check 2/3: Linting (make lint)"

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
    fi
fi

# ─────────────────────────────────────────────────────────────────────────────
# Check 3: Unit Tests
# ─────────────────────────────────────────────────────────────────────────────

print_header "Check 3/3: Unit Tests (make test-unit)"

# Run tests and capture output
if make test-unit 2>&1 | tee /tmp/test_output.txt; then
    print_success "Unit tests passed"

    # Extract test summary from output
    SUMMARY=$(grep -E "passed|failed" /tmp/test_output.txt | tail -1)
    if [ -n "$SUMMARY" ]; then
        echo "  $SUMMARY"
    fi
else
    EXIT_CODE=$?
    if [ $EXIT_CODE -eq 0 ]; then
        print_success "Unit tests passed"
        SUMMARY=$(grep -E "passed|failed" /tmp/test_output.txt | tail -1)
        if [ -n "$SUMMARY" ]; then
            echo "  $SUMMARY"
        fi
    else
        print_failure "Unit tests failed"
        OVERALL_STATUS=1
        FAILED_CHECKS+=("test-unit")

        # Show failure summary
        echo ""
        grep -E "FAILED|ERROR" /tmp/test_output.txt | head -10 || true
    fi
fi

# Clean up temp file
rm -f /tmp/test_output.txt

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
    print_success "Unit tests:    PASSED"
    echo ""
    echo -e "Total duration: ${YELLOW}${DURATION}s${NC}"
    echo ""
    echo -e "${GREEN}✓ Ready to commit!${NC}"
    echo ""
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
    echo -e "${RED}✗ Please fix the issues above before committing${NC}"
    echo ""
fi

exit $OVERALL_STATUS