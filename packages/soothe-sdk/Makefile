# Makefile for Soothe SDK Package
#
# This Makefile manages the soothe-sdk package independently

.PHONY: sync sync-dev format format-check lint lint-fix test test-unit test-coverage build publish publish-test clean help

# Default target
help:
	@echo "Soothe SDK Package"
	@echo ""
	@echo "Development:"
	@echo "  make sync       - Sync dependencies with uv"
	@echo "  make sync-dev   - Sync dev dependencies"
	@echo "  make format     - Format code with ruff"
	@echo "  make format-check - Check code formatting (for CI)"
	@echo "  make lint       - Lint code with ruff"
	@echo "  make lint-fix   - Auto-fix linting issues with ruff"
	@echo ""
	@echo "Testing:"
	@echo "  make test       - Run all tests"
	@echo "  make test-unit  - Run unit tests only"
	@echo "  make test-coverage - Run tests with coverage report"
	@echo ""
	@echo "Building & Publishing:"
	@echo "  make build      - Build the package"
	@echo "  make publish    - Publish package to PyPI"
	@echo "  make publish-test - Publish package to TestPyPI"
	@echo ""
	@echo "Cleanup:"
	@echo "  make clean      - Clean build artifacts"

# Sync dependencies
sync:
	@echo "Syncing dependencies..."
	uv sync
	@echo "✓ Dependencies synced"

# Sync dev dependencies
sync-dev:
	@echo "Syncing dev dependencies..."
	uv sync --extra dev
	@echo "✓ Dev dependencies synced"

# Format code
format: sync-dev
	@echo "Formatting code..."
	uv run ruff format src/ tests/
	@echo "✓ Code formatted"

# Check formatting (for CI)
format-check: sync-dev
	@echo "Checking code formatting..."
	uv run ruff format --check src/ tests/
	@echo "✓ Format check passed"

# Lint code
lint: sync-dev
	@echo "Linting code..."
	uv run ruff check src/ tests/
	@echo "✓ Linting complete"

# Auto-fix linting issues
lint-fix: sync-dev
	@echo "Auto-fixing linting issues..."
	uv run ruff check --fix src/ tests/
	@echo "✓ Linting issues fixed"

# Run all tests
test: test-unit
	@echo "✓ All tests complete"

# Run unit tests only
test-unit: sync-dev
	@echo "Running unit tests..."
	uv run pytest tests/ -v
	@echo "✓ Unit tests complete"

# Run tests with coverage
test-coverage: sync-dev
	@echo "Running tests with coverage..."
	uv run pytest tests/ --cov=soothe_sdk --cov-report=term-missing --cov-report=html
	@echo "✓ Coverage report generated in htmlcov/"

# Build package
build:
	@echo "Building package..."
	uv build
	@echo "✓ Package built"

# Publish package to PyPI
publish:
	@echo "Publishing package to PyPI..."
	uv publish
	@echo "✓ Package published to PyPI"

# Publish package to TestPyPI
publish-test:
	@echo "Publishing package to TestPyPI..."
	uv publish --index-url https://test.pypi.org/simple/
	@echo "✓ Package published to TestPyPI"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage .ruff_cache htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Build artifacts cleaned"