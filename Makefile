# Makefile for Soothe Multi-Package Monorepo
#
# This Makefile manages three packages:
# 1. soothe          - Main orchestration framework
# 2. soothe-sdk      - Plugin SDK for third-party developers
# 3. soothe-community - Community plugins package

.PHONY: sync sync-dev format format-check lint lint-fix test test-unit test-integration test-coverage build publish publish-test clean help \
        sdk-sync sdk-format sdk-lint sdk-test sdk-build sdk-publish sdk-publish-test \
        community-sync community-format community-lint community-test community-build community-publish community-publish-test \
        all-sync all-format all-lint all-test all-build all-publish all-clean

# Default target
help:
	@echo "Soothe Multi-Package Monorepo"
	@echo ""
	@echo "Main Package (soothe):"
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
	@echo ""
	@echo "SDK Package (soothe-sdk):"
	@echo "  make sdk-sync    - Sync SDK dependencies"
	@echo "  make sdk-format  - Format SDK code"
	@echo "  make sdk-lint    - Lint SDK code"
	@echo "  make sdk-test    - Run SDK tests"
	@echo "  make sdk-build   - Build SDK package"
	@echo "  make sdk-publish - Publish SDK package to PyPI"
	@echo "  make sdk-publish-test - Publish SDK package to TestPyPI"
	@echo ""
	@echo "Community Package (soothe-community):"
	@echo "  make community-sync    - Sync community package dependencies"
	@echo "  make community-format  - Format community package code"
	@echo "  make community-lint    - Lint community package code"
	@echo "  make community-test    - Run community package tests"
	@echo "  make community-build   - Build community package"
	@echo "  make community-publish - Publish community package to PyPI"
	@echo "  make community-publish-test - Publish community package to TestPyPI"
	@echo ""
	@echo "Multi-Package Targets:"
	@echo "  make all-sync    - Sync all packages"
	@echo "  make all-format  - Format all packages"
	@echo "  make all-lint    - Lint all packages"
	@echo "  make all-test    - Test all packages"
	@echo "  make all-build   - Build all packages"
	@echo "  make all-publish - Publish all packages"
	@echo "  make all-clean   - Clean all packages"

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
	uv run pytest tests/unit/ -v
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

# ============================================================================
# SDK Package Targets (soothe-sdk)
# ============================================================================

sdk-sync:
	@echo "Syncing SDK dependencies..."
	cd soothe-sdk-pkg && uv sync --all-extras
	@echo "✓ SDK dependencies synced"

sdk-format:
	@echo "Formatting SDK code..."
	cd soothe-sdk-pkg && uv run ruff format src/ tests/
	@echo "✓ SDK code formatted"

sdk-lint:
	@echo "Linting SDK code..."
	cd soothe-sdk-pkg && uv run ruff check src/ tests/
	@echo "✓ SDK linting complete"

sdk-test:
	@echo "Running SDK tests..."
	cd soothe-sdk-pkg && uv run pytest tests/ -v
	@echo "✓ SDK tests complete"

sdk-build:
	@echo "Building SDK package..."
	cd soothe-sdk-pkg && uv build
	@echo "✓ SDK package built"

sdk-publish:
	@echo "Publishing SDK package to PyPI..."
	cd soothe-sdk-pkg && uv publish
	@echo "✓ SDK package published to PyPI"

sdk-publish-test:
	@echo "Publishing SDK package to TestPyPI..."
	cd soothe-sdk-pkg && uv publish --index-url https://test.pypi.org/simple/
	@echo "✓ SDK package published to TestPyPI"

# ============================================================================
# Community Package Targets (soothe-community)
# ============================================================================

community-sync:
	@echo "Syncing community package dependencies..."
	cd soothe-community-pkg && uv sync --all-extras
	@echo "✓ Community dependencies synced"

community-format:
	@echo "Formatting community package code..."
	cd soothe-community-pkg && uv run ruff format src/ tests/
	@echo "✓ Community code formatted"

community-lint:
	@echo "Linting community package code..."
	cd soothe-community-pkg && uv run ruff check src/ tests/
	@echo "✓ Community linting complete"

community-test:
	@echo "Running community package tests..."
	cd soothe-community-pkg && uv run pytest tests/ -v
	@echo "✓ Community tests complete"

community-build:
	@echo "Building community package..."
	cd soothe-community-pkg && uv build
	@echo "✓ Community package built"

community-publish:
	@echo "Publishing community package to PyPI..."
	cd soothe-community-pkg && uv publish
	@echo "✓ Community package published to PyPI"

community-publish-test:
	@echo "Publishing community package to TestPyPI..."
	cd soothe-community-pkg && uv publish --index-url https://test.pypi.org/simple/
	@echo "✓ Community package published to TestPyPI"

# ============================================================================
# Multi-Package Targets (all packages)
# ============================================================================

all-sync: sync sdk-sync community-sync
	@echo "✓ All packages synced"

all-format: format sdk-format community-format
	@echo "✓ All packages formatted"

all-lint: lint sdk-lint community-lint
	@echo "✓ All packages linted"

all-test: test-unit sdk-test community-test
	@echo "✓ All packages tested"

all-build: build sdk-build community-build
	@echo "✓ All packages built"

all-publish: publish sdk-publish community-publish
	@echo "✓ All packages published"

all-clean: clean
	@echo "Cleaning all package artifacts..."
	rm -rf soothe-sdk-pkg/dist/ soothe-sdk-pkg/*.egg-info
	rm -rf soothe-community-pkg/dist/ soothe-community-pkg/*.egg-info
	find soothe-sdk-pkg -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find soothe-community-pkg -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "✓ All packages cleaned"
