# Makefile for Soothe Multi-Package Monorepo
#
# This Makefile manages four packages:
# 1. soothe-sdk        - Shared SDK (WebSocket client, protocol, types)
# 2. soothe-cli        - CLI client (Typer CLI + Textual TUI)
# 3. soothe            - In-process agent core (library)
# 4. soothe-daemon     - Daemon server (WebSocket/HTTP transports)
#
# Uses .venv managed by uv for development.

.PHONY: setup reset-the-world sync format format-check lint lint-fix test test-unit test-integration test-coverage build clean help \
        sdk-publish sdk-publish-test cli-publish cli-publish-test soothe-publish soothe-publish-test daemon-publish daemon-publish-test publish publish-test

# Default target
help:
	@echo "Soothe Multi-Package Monorepo"
	@echo ""
	@echo "Setup:"
	@echo "  make setup            - Sync workspace dependencies (creates .venv if needed)"
	@echo "  make reset-the-world  - Reset all state: docker compose down -v + clean ~/.soothe/ (keeps config) + restart"
	@echo ""
	@echo "Unified Targets (all packages):"
	@echo "  make sync             - Sync all packages with all extras"
	@echo "  make format           - Format all packages"
	@echo "  make format-check     - Check formatting (for CI)"
	@echo "  make lint             - Lint all packages"
	@echo "  make lint-fix         - Auto-fix all linting issues"
	@echo "  make test             - Test all packages"
	@echo "  make test-unit        - Run unit tests for all packages"
	@echo "  make test-integration - Run integration tests"
	@echo "  make test-coverage    - Run tests with coverage report"
	@echo "  make build            - Build all packages"
	@echo "  make clean            - Clean all packages"
	@echo ""
	@echo "Publish (per-package):"
	@echo "  make sdk-publish      - Publish soothe-sdk to PyPI"
	@echo "  make cli-publish      - Publish soothe-cli to PyPI"
	@echo "  make soothe-publish   - Publish soothe to PyPI"
	@echo "  make daemon-publish   - Publish soothe-daemon to PyPI"
	@echo "  make publish          - Publish all packages to PyPI"
	@echo ""
	@echo "Publish to TestPyPI:"
	@echo "  make sdk-publish-test - Publish soothe-sdk to TestPyPI"
	@echo "  make cli-publish-test - Publish soothe-cli to TestPyPI"
	@echo "  make soothe-publish-test - Publish soothe to TestPyPI"
	@echo "  make daemon-publish-test - Publish soothe-daemon to TestPyPI"
	@echo "  make publish-test     - Publish all packages to TestPyPI"

# ============================================================================
# Workspace Setup
# ============================================================================

setup:
	@echo "Syncing workspace dependencies..."
	uv sync --all-extras
	@echo "Workspace ready (.venv created if needed)"

# Reset all state: docker volumes + ~/.soothe/ (keeps config), then restart services
reset-the-world:
	@echo "Resetting the world..."
	@echo "Stopping docker containers and removing volumes..."
	docker compose down -v 2>/dev/null || echo "No docker compose services running"
	@echo "Cleaning ~/.soothe/ (keeping config/)..."
	@if [ -d ~/.soothe ]; then \
		find ~/.soothe -mindepth 1 -maxdepth 1 ! -name config -exec rm -rf {} + 2>/dev/null || true; \
	fi
	@echo "Starting docker containers..."
	docker compose up -d 2>/dev/null || echo "No docker compose services to start"
	@echo "World reset complete"

# ============================================================================
# Unified Targets (all packages)
# ============================================================================

sync:
	@echo "Syncing all workspace dependencies with extras..."
	uv sync --all-extras --package soothe --package soothe-sdk --package soothe-cli --package soothe-daemon
	@echo "All packages synced with all dependencies and extras"

format: sync
	@echo "Formatting all packages..."
	cd packages/soothe-sdk && uv run ruff format src/
	cd packages/soothe-cli && uv run ruff format src/
	cd packages/soothe && uv run ruff format src/
	cd packages/soothe-daemon && uv run ruff format src/
	@echo "All packages formatted"

format-check: sync
	@echo "Checking formatting for all packages..."
	cd packages/soothe-sdk && uv run ruff format --check src/
	cd packages/soothe-cli && uv run ruff format --check src/
	cd packages/soothe && uv run ruff format --check src/
	cd packages/soothe-daemon && uv run ruff format --check src/
	@echo "All packages format checked"

lint: sync
	@echo "Linting all packages..."
	cd packages/soothe-sdk && uv run ruff check src/
	cd packages/soothe-cli && uv run ruff check src/
	cd packages/soothe && uv run ruff check src/
	cd packages/soothe-daemon && uv run ruff check src/
	@echo "All packages linted"

lint-fix: sync
	@echo "Auto-fixing linting issues in all packages..."
	cd packages/soothe-sdk && uv run ruff check --fix src/
	cd packages/soothe-cli && uv run ruff check --fix src/
	cd packages/soothe && uv run ruff check --fix src/
	cd packages/soothe-daemon && uv run ruff check --fix src/
	@echo "All packages lint-fixed"

test: sync test-unit test-integration
	@echo "All packages tested"

test-unit: sync
	@echo "Running unit tests for all packages..."
	cd packages/soothe-sdk && uv run pytest tests/unit/ -v
	cd packages/soothe-cli && uv run pytest tests/unit/ -v
	cd packages/soothe && uv run pytest tests/unit/ -v
	cd packages/soothe-daemon && uv run pytest tests/unit/ -v
	@echo "All unit tests complete"

test-integration: sync
	@echo "Running integration tests..."
	@echo "Note: Integration tests require external services and real LLM API calls"
	cd packages/soothe && uv run pytest tests/integration/ --run-integration -v
	cd packages/soothe-daemon && uv run pytest tests/integration/ --run-integration -v
	@echo "Integration tests complete"

test-coverage: sync
	@echo "Running tests with coverage for all packages..."
	cd packages/soothe && uv run pytest tests/ --cov=soothe --cov-report=term-missing
	cd packages/soothe-daemon && uv run pytest tests/ --cov=soothe_daemon --cov-report=term-missing
	@echo "Coverage reports generated"

build: sync
	@echo "Building all packages..."
	cd packages/soothe-sdk && uv build --out-dir dist
	cd packages/soothe-cli && uv build --out-dir dist
	cd packages/soothe && uv build --out-dir dist
	cd packages/soothe-daemon && uv build --out-dir dist
	@echo "All packages built"

clean:
	@echo "Cleaning all package artifacts..."
	rm -rf packages/*/dist/ packages/*/*.egg-info
	find packages -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find packages -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find packages -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	@echo "All packages cleaned"

# ============================================================================
# Publish Targets (per-package)
# ============================================================================

sdk-publish:
	@echo "Publishing soothe-sdk to PyPI..."
	cd packages/soothe-sdk && uv publish dist/* --native-tls
	@echo "soothe-sdk published to PyPI"

sdk-publish-test:
	@echo "Publishing soothe-sdk to TestPyPI..."
	cd packages/soothe-sdk && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls
	@echo "soothe-sdk published to TestPyPI"

cli-publish:
	@echo "Publishing soothe-cli to PyPI..."
	cd packages/soothe-cli && uv publish dist/* --native-tls
	@echo "soothe-cli published to PyPI"

cli-publish-test:
	@echo "Publishing soothe-cli to TestPyPI..."
	cd packages/soothe-cli && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls
	@echo "soothe-cli published to TestPyPI"

soothe-publish:
	@echo "Publishing soothe to PyPI..."
	cd packages/soothe && uv publish dist/* --native-tls
	@echo "soothe published to PyPI"

soothe-publish-test:
	@echo "Publishing soothe to TestPyPI..."
	cd packages/soothe && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls
	@echo "soothe published to TestPyPI"

daemon-publish:
	@echo "Publishing soothe-daemon to PyPI..."
	cd packages/soothe-daemon && uv publish dist/* --native-tls
	@echo "soothe-daemon published to PyPI"

daemon-publish-test:
	@echo "Publishing soothe-daemon to TestPyPI..."
	cd packages/soothe-daemon && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls
	@echo "soothe-daemon published to TestPyPI"

publish: build sdk-publish cli-publish soothe-publish daemon-publish
	@echo "All packages published to PyPI"

publish-test: build sdk-publish-test cli-publish-test soothe-publish-test daemon-publish-test
	@echo "All packages published to TestPyPI"