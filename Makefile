# Makefile for soothe project

.PHONY: sync sync-dev format lint test build clean help

# Default target
help:
	@echo "Available commands:"
	@echo "  make sync       - Sync dependencies with uv"
	@echo "  make sync-dev   - Sync dev dependencies"
	@echo "  make format     - Format code with ruff"
	@echo "  make lint       - Lint code with ruff"
	@echo "  make test       - Run tests with pytest"
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
format:
	@echo "Formatting code..."
	uv run ruff format src/ tests/
	@echo "✓ Code formatted"

# Lint code
lint:
	@echo "Linting code..."
	uv run ruff check src/ tests/
	@echo "✓ Linting complete"

# Run tests
test:
	@echo "Running tests..."
	uv run pytest tests/ -v
	@echo "✓ Tests complete"

# Build package
build:
	@echo "Building package..."
	uv build
	@echo "✓ Package built"

# Clean build artifacts
clean:
	@echo "Cleaning build artifacts..."
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage .ruff_cache .uv
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ Build artifacts cleaned"