# Makefile for soothe project

.PHONY: sync sync-dev format format-check lint lint-fix test test-unit test-integration test-coverage build publish publish-test clean help

# Default target
help:
	@echo "Available commands:"
	@echo "  make sync       - Sync dependencies with uv"
	@echo "  make sync-dev   - Sync dev dependencies"
	@echo "  make format     - Format code with ruff"
	@echo "  make format-check - Check code formatting (for CI)"
	@echo "  make lint       - Lint code with ruff"
	@echo "  make lint-fix   - Auto-fix linting issues with ruff"
	@echo "  make test       - Run unit tests (default, fast)"
	@echo "  make test-unit  - Run unit tests only"
	@echo "  make test-integration - Run integration tests (requires external services)"
	@echo "  make test-coverage - Run tests with coverage report"
	@echo "  make build      - Build the package"
	@echo "  make publish    - Publish package to PyPI"
	@echo "  make publish-test - Publish package to TestPyPI"
	@echo "  make clean      - Clean build artifacts"

# Sync dependencies
sync:
	@echo "Syncing dependencies..."
	uv sync --all-extras
	@echo "✓ Dependencies synced"

# Sync dev dependencies
sync-dev:
	@echo "Syncing dev dependencies..."
	uv sync --all-extras --group test
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

# Run all tests (unit tests only by default)
test: test-unit test-integration
	@echo "✓ All tests complete"

# Run unit tests only
test-unit: sync-dev
	@echo "Running unit tests..."
	uv run pytest tests/unit_tests/ -v
	@echo "✓ Unit tests complete"

# Run integration tests (requires external services and real LLM calls)
test-integration: sync-dev
	@echo "Running integration tests..."
	@echo "Note: Integration tests require external services (PostgreSQL, Weaviate) and real LLM API calls"
	@echo "Use: pytest tests/integration/ --run-integration"
	uv run pytest tests/integration/ --run-integration -v
	@echo "✓ Integration tests complete"

# Run tests with coverage
test-coverage: sync-dev
	@echo "Running tests with coverage..."
	uv run pytest tests/ --cov=soothe --cov-report=term-missing --cov-report=html
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
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage .ruff_cache .uv
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Build artifacts cleaned"
