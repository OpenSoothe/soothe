# Makefile for soothe project

.PHONY: sync sync-dev format lint lint-fix test test-unit test-integration test-coverage build clean help

# Default target
help:
	@echo "Available commands:"
	@echo "  make sync       - Sync dependencies with uv"
	@echo "  make sync-dev   - Sync dev dependencies"
	@echo "  make format     - Format code with ruff"
	@echo "  make lint       - Lint code with ruff"
	@echo "  make lint-fix   - Auto-fix linting issues with ruff"
	@echo "  make test       - Run all tests with pytest"
	@echo "  make test-unit  - Run unit tests only"
	@echo "  make test-integration - Run integration tests (requires --run-integration)"
	@echo "  make test-coverage - Run tests with coverage report"
	@echo "  make build      - Build the package"
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
test: sync-dev
	@echo "Running all tests..."
	uv run pytest tests/ -v
	@echo "✓ Tests complete"

# Run unit tests only
test-unit: sync-dev
	@echo "Running unit tests..."
	uv run pytest tests/unit_tests/ -v
	@echo "✓ Unit tests complete"

# Run integration tests (requires external services)
test-integration: sync-dev
	@echo "Running integration tests..."
	@echo "Note: Integration tests require external services (PostgreSQL, Weaviate)"
	@echo "Use: pytest tests/integration_tests/ --run-integration"
	uv run pytest tests/integration_tests/ --run-integration -v
	@echo "✓ Integration tests complete"

# Run tests with coverage
test-coverage: sync-dev
	@echo "Running tests with coverage..."
	uv run pytest tests/ --cov=soothe --cov-report=term-missing --cov-report=html
	@echo "✓ Coverage report generated in htmlcov/"

# Build package
build: sync
	@echo "Building package..."
	uv build
	@echo "✓ Package built"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage .ruff_cache .uv
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Build artifacts cleaned"
