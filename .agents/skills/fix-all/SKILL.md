---
name: fix
description: Run code quality checks and fixes - executes make test-unit, make lint, and make format in sequence. Use when validating code changes, fixing linting issues, or ensuring code quality before commits.
metadata:
  author: soothe
  version: "1.0"
compatibility: Requires Soothe development environment with uv package manager and Makefile
---

# Soothe Code Quality Fix Skill

## Overview

This skill runs essential code quality checks and automatic fixes for Soothe:

1. **Unit Tests** (`make test-unit`): Run all unit tests to ensure code correctness
2. **Linting** (`make lint`): Check code style and potential issues with ruff
3. **Formatting** (`make format`): Auto-format code to match project standards

## Prerequisites

- Soothe development environment set up
- `uv` package manager installed
- Dependencies installed (run `make sync-dev` if needed)

## Quick Start

Simply run:

```bash
make test-unit && make lint && make format
```

This will:
1. Run all unit tests to verify functionality
2. Check for linting issues
3. Auto-format code to match project standards

## What Each Command Does

### 1. Unit Tests (`make test-unit`)

Runs all unit tests in `tests/unit_tests/`:

- Validates code correctness
- Catches regressions early
- Ensures all tests pass before committing

**Output**: Test results with pass/fail status for each test

### 2. Linting (`make lint`)

Checks code quality using ruff:

- Identifies code style issues
- Detects potential bugs
- Enforces consistent coding patterns

**Output**: List of linting issues (if any) with file locations and descriptions

### 3. Formatting (`make format`)

Auto-formats code using ruff:

- Fixes code style automatically
- Ensures consistent formatting across codebase
- Aligns with project standards

**Output**: List of reformatted files (if any)

## Common Use Cases

### Before Committing Changes

Run all quality checks before committing:

```bash
make test-unit && make lint && make format
```

### Quick Fix After Changes

If you've made code changes and want to ensure they meet quality standards:

```bash
make test-unit && make lint && make format
```

### Iterative Development

Run tests frequently during development:

```bash
# Just run tests
make test-unit

# Check linting without auto-fixing
make lint

# Fix linting issues automatically
make lint-fix

# Format code
make format
```

## Exit Codes

Each command follows these exit codes:

- **0**: Success (tests pass, no linting issues, formatting complete)
- **Non-zero**: Failure (test failures, linting errors, or other issues)

When running in sequence (`&&`), execution stops at the first failure.

## Troubleshooting

### Tests Failing

1. Read the test output to identify which tests failed
2. Check the error messages and stack traces
3. Fix the failing code or tests
4. Re-run `make test-unit`

### Linting Issues

1. Review the linting errors reported by ruff
2. Option A: Run `make lint-fix` to auto-fix what's possible
3. Option B: Manually fix the issues in the code
4. Re-run `make lint`

### Formatting Issues

1. Run `make format` to auto-format code
2. Review the changes made by the formatter
3. Commit the formatted code

## Integration with Development Workflow

This skill is designed to be run:

- **Before commits**: Ensure code quality before pushing
- **After refactoring**: Validate that changes don't break tests
- **During code review**: Catch issues before they're reviewed
- **In CI/CD**: Automated quality gates

## Makefile Targets Reference

All available quality-related targets from the Makefile:

```bash
make test-unit        # Run unit tests only
make test             # Run all tests (unit + integration)
make test-coverage    # Run tests with coverage report
make lint             # Check code quality
make lint-fix         # Auto-fix linting issues
make format           # Format code
make format-check     # Check formatting without fixing (for CI)
```

## Best Practices

1. **Run tests first**: Always run `make test-unit` before linting and formatting
2. **Fix linting before formatting**: Address linting issues, then format
3. **Commit formatted code**: After formatting, review and commit the changes
4. **Use lint-fix wisely**: `make lint-fix` is powerful but review the changes
5. **Keep tests passing**: Never commit code that fails tests

## Notes

- Unit tests are fast (< 1 minute typically)
- Linting is very fast (< 10 seconds)
- Formatting is instant
- Integration tests require external services (use `make test-integration` when needed)
