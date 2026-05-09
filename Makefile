# Makefile for Soothe Multi-Package Monorepo
#
# This Makefile manages three packages:
# 1. soothe-sdk        - Shared SDK (WebSocket client, protocol, types)
# 2. soothe-cli        - CLI client (Typer CLI + Textual TUI)
# 3. soothe            - Daemon server (main package)
#
# Uses pyenv virtualenv "soothe-dev" for isolation (not .venv).

PYENV_VENV_NAME := soothe-dev
PYENV_VENV := $(shell pyenv prefix $(PYENV_VENV_NAME) 2>/dev/null)
PYTHON := $(PYENV_VENV)/bin/python
PIP := $(PYENV_VENV)/bin/pip

.PHONY: setup reset-the-world sync sync-dev format format-check lint lint-fix test test-unit test-integration test-coverage build publish publish-test clean help \
        sdk-sync sdk-format sdk-lint sdk-test sdk-build sdk-publish sdk-publish-test \
        cli-sync cli-format cli-lint cli-test cli-build cli-publish cli-publish-test \
        daemon-sync daemon-sync-dev daemon-format daemon-format-check daemon-lint daemon-lint-fix daemon-test daemon-test-unit daemon-test-integration daemon-test-coverage daemon-build daemon-publish daemon-publish-test daemon-clean

# Default target
help:
	@echo "Soothe Multi-Package Monorepo (pyenv: $(PYENV_VENV_NAME))"
	@echo ""
	@echo "Setup:"
	@echo "  make setup            - Create pyenv virtualenv 'soothe-dev' if missing"
	@echo "  make reset-the-world  - Reset all state: docker compose down -v + clean ~/.soothe/ (keeps config)"
	@echo ""
	@echo "Multi-Package Targets (all packages):"
	@echo "  make sync             - Sync all packages with all extras"
	@echo "  make format           - Format all packages"
	@echo "  make lint             - Lint all packages"
	@echo "  make lint-fix         - Auto-fix all linting issues"
	@echo "  make test             - Test all packages"
	@echo "  make build            - Build all packages"
	@echo "  make publish          - Publish all packages"
	@echo "  make clean            - Clean all packages"
	@echo ""
	@echo "SDK Package (soothe-sdk):"
	@echo "  make sdk-sync         - Sync SDK dependencies"
	@echo "  make sdk-format       - Format SDK code"
	@echo "  make sdk-lint         - Lint SDK code"
	@echo "  make sdk-test         - Run SDK tests"
	@echo "  make sdk-build        - Build SDK package"
	@echo "  make sdk-publish      - Publish SDK package to PyPI"
	@echo "  make sdk-publish-test - Publish SDK package to TestPyPI"
	@echo ""
	@echo "CLI Package (soothe-cli):"
	@echo "  make cli-sync         - Sync CLI dependencies"
	@echo "  make cli-format       - Format CLI code"
	@echo "  make cli-lint         - Lint CLI code"
	@echo "  make cli-test         - Run CLI tests"
	@echo "  make cli-build        - Build CLI package"
	@echo "  make cli-publish      - Publish CLI package to PyPI"
	@echo "  make cli-publish-test - Publish CLI package to TestPyPI"
	@echo ""
	@echo "Daemon Package (soothe - in packages/soothe/):"
	@echo "  make daemon-sync      - Sync daemon dependencies"
	@echo "  make daemon-sync-dev  - Sync daemon dev dependencies"
	@echo "  make daemon-format    - Format daemon code"
	@echo "  make daemon-format-check - Check daemon code formatting (for CI)"
	@echo "  make daemon-lint      - Lint daemon code"
	@echo "  make daemon-lint-fix  - Auto-fix daemon linting issues"
	@echo "  make daemon-test      - Run daemon tests (unit + integration)"
	@echo "  make daemon-test-unit - Run daemon unit tests only"
	@echo "  make daemon-test-integration - Run daemon integration tests"
	@echo "  make daemon-test-coverage - Run daemon tests with coverage"
	@echo "  make daemon-build     - Build daemon package"
	@echo "  make daemon-publish   - Publish daemon package to PyPI"
	@echo "  make daemon-publish-test - Publish daemon package to TestPyPI"
	@echo "  make daemon-clean     - Clean daemon build artifacts"

# ============================================================================
# Pyenv Virtualenv Setup
# ============================================================================

setup:
	@if pyenv prefix $(PYENV_VENV_NAME) >/dev/null 2>&1; then \
		echo "pyenv virtualenv '$(PYENV_VENV_NAME)' already exists"; \
	else \
		echo "Creating pyenv virtualenv '$(PYENV_VENV_NAME)' with Python 3.12..."; \
		pyenv virtualenv 3.12 $(PYENV_VENV_NAME); \
		echo "Setting local .python-version to $(PYENV_VENV_NAME)..."; \
		pyenv local $(PYENV_VENV_NAME); \
		echo "Virtualenv created and activated"; \
	fi

# Reset all state: docker volumes + ~/.soothe/ (keeps config)
reset-the-world:
	@echo "Resetting the world..."
	@echo "Stopping docker containers and removing volumes..."
	docker compose down -v 2>/dev/null || echo "No docker compose services running"
	@echo "Cleaning ~/.soothe/ (keeping config/)..."
	@if [ -d ~/.soothe ]; then \
		find ~/.soothe -mindepth 1 -maxdepth 1 ! -name config -exec rm -rf {} + 2>/dev/null || true; \
	fi
	@echo "World reset complete"

# ============================================================================
# Multi-Package Targets (all packages)
# ============================================================================

sync:
	@echo "Syncing all workspace dependencies with extras..."
	UV_PROJECT_ENVIRONMENT=$(PYENV_VENV) uv sync --all-extras --package soothe --package soothe-sdk --package soothe-cli
	@echo "All packages synced with all dependencies and extras"

format: daemon-format sdk-format cli-format
	@echo "All packages formatted"

lint: daemon-lint sdk-lint cli-lint
	@echo "All packages linted"

lint-fix:
	@echo "Auto-fixing linting issues in all packages..."
	cd packages/soothe && $(PYENV_VENV)/bin/ruff check --fix src/
	cd packages/soothe-sdk && $(PYENV_VENV)/bin/ruff check --fix src/
	cd packages/soothe-cli && $(PYENV_VENV)/bin/ruff check --fix src/
	@echo "All packages lint-fixed"

test: daemon-test-unit sdk-test cli-test
	@echo "All packages tested"

build: daemon-build sdk-build cli-build
	@echo "All packages built"

publish: daemon-publish sdk-publish cli-publish
	@echo "All packages published"

clean: daemon-clean
	@echo "Cleaning all package artifacts..."
	rm -rf packages/*/dist/ packages/*/*.egg-info
	find packages -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "All packages cleaned"

# ============================================================================
# Daemon Package Targets (soothe)
# ============================================================================

daemon-sync:
	@echo "Syncing daemon dependencies..."
	cd packages/soothe && UV_PROJECT_ENVIRONMENT=$(PYENV_VENV) uv sync --all-extras
	@echo "Daemon dependencies synced"

daemon-sync-dev:
	@echo "Syncing daemon dev dependencies..."
	cd packages/soothe && UV_PROJECT_ENVIRONMENT=$(PYENV_VENV) uv sync --all-extras
	@echo "Daemon dev dependencies synced"

daemon-format: daemon-sync-dev
	@echo "Formatting daemon code..."
	cd packages/soothe && $(PYENV_VENV)/bin/ruff format src/
	@echo "Daemon code formatted"

daemon-format-check: daemon-sync-dev
	@echo "Checking daemon code formatting..."
	cd packages/soothe && $(PYENV_VENV)/bin/ruff format --check src/
	@echo "Daemon format check passed"

daemon-lint: daemon-sync-dev
	@echo "Linting daemon code..."
	cd packages/soothe && $(PYENV_VENV)/bin/ruff check src/
	@echo "Daemon linting complete"

daemon-lint-fix: daemon-sync-dev
	@echo "Auto-fixing daemon linting issues..."
	cd packages/soothe && $(PYENV_VENV)/bin/ruff check --fix src/
	@echo "Daemon linting issues fixed"

daemon-test: daemon-test-unit daemon-test-integration
	@echo "All daemon tests complete"

daemon-test-unit: daemon-sync-dev
	@echo "Running daemon unit tests..."
	cd packages/soothe && $(PYENV_VENV)/bin/pytest tests/unit/ -v
	@echo "Daemon unit tests complete"

daemon-test-integration: daemon-sync-dev
	@echo "Running daemon integration tests..."
	@echo "Note: Integration tests require external services (PostgreSQL, Weaviate) and real LLM API calls"
	@echo "Use: pytest tests/integration/ --run-integration"
	cd packages/soothe && $(PYENV_VENV)/bin/pytest tests/integration/ --run-integration -v
	@echo "Daemon integration tests complete"

daemon-test-coverage: daemon-sync-dev
	@echo "Running daemon tests with coverage..."
	cd packages/soothe && $(PYENV_VENV)/bin/pytest tests/ --cov=soothe --cov-report=term-missing --cov-report=html
	@echo "Daemon coverage report generated in htmlcov/"

daemon-build:
	@echo "Building daemon package..."
	cd packages/soothe && uv build --out-dir dist
	@echo "Daemon package built"

daemon-publish:
	@echo "Publishing daemon package to PyPI..."
	cd packages/soothe && uv publish dist/* --native-tls
	@echo "Daemon package published to PyPI"

daemon-publish-test:
	@echo "Publishing daemon package to TestPyPI..."
	cd packages/soothe && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls
	@echo "Daemon package published to TestPyPI"

daemon-clean:
	@echo "Cleaning daemon build artifacts..."
	rm -rf build/ dist/ *.egg-info .pytest_cache .coverage .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@echo "Daemon build artifacts cleaned"

# ============================================================================
# SDK Package Targets (soothe-sdk)
# ============================================================================

sdk-sync:
	@echo "Syncing SDK dependencies..."
	cd packages/soothe-sdk && UV_PROJECT_ENVIRONMENT=$(PYENV_VENV) uv sync --all-extras
	@echo "SDK dependencies synced"

sdk-format: sdk-sync
	@echo "Formatting SDK code..."
	cd packages/soothe-sdk && $(PYENV_VENV)/bin/ruff format src/
	@echo "SDK code formatted"

sdk-lint: sdk-sync
	@echo "Linting SDK code..."
	cd packages/soothe-sdk && $(PYENV_VENV)/bin/ruff check src/
	@echo "SDK linting complete"

sdk-test: sdk-sync
	@echo "Running SDK tests..."
	cd packages/soothe-sdk && $(PYENV_VENV)/bin/pytest tests/ -v
	@echo "SDK tests complete"

sdk-build:
	@echo "Building SDK package..."
	cd packages/soothe-sdk && uv build --out-dir dist
	@echo "SDK package built"

sdk-publish:
	@echo "Publishing SDK package to PyPI..."
	cd packages/soothe-sdk && uv publish dist/* --native-tls
	@echo "SDK package published to PyPI"

sdk-publish-test:
	@echo "Publishing SDK package to TestPyPI..."
	cd packages/soothe-sdk && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls
	@echo "SDK package published to TestPyPI"

# ============================================================================
# CLI Package Targets (soothe-cli)
# ============================================================================

cli-sync:
	@echo "Syncing CLI dependencies..."
	cd packages/soothe-cli && UV_PROJECT_ENVIRONMENT=$(PYENV_VENV) uv sync --all-extras
	@echo "CLI dependencies synced"

cli-format: cli-sync
	@echo "Formatting CLI code..."
	cd packages/soothe-cli && $(PYENV_VENV)/bin/ruff format src/
	@echo "CLI code formatted"

cli-lint: cli-sync
	@echo "Linting CLI code..."
	cd packages/soothe-cli && $(PYENV_VENV)/bin/ruff check src/
	@echo "CLI linting complete"

cli-test: cli-sync
	@echo "Running CLI tests..."
	cd packages/soothe-cli && $(PYENV_VENV)/bin/pytest tests/ -v
	@echo "CLI tests complete"

cli-build:
	@echo "Building CLI package..."
	cd packages/soothe-cli && uv build --out-dir dist
	@echo "CLI package built"

cli-publish:
	@echo "Publishing CLI package to PyPI..."
	cd packages/soothe-cli && uv publish dist/* --native-tls
	@echo "CLI package published to PyPI"

cli-publish-test:
	@echo "Publishing CLI package to TestPyPI..."
	cd packages/soothe-cli && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls
	@echo "CLI package published to TestPyPI"