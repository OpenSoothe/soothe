# Makefile for Soothe Multi-Package Monorepo
#
# This Makefile manages five packages:
# 1. soothe-sdk        - Shared SDK (WebSocket client, protocol, types)
# 2. soothe-cli        - CLI client (Typer CLI + Textual TUI)
# 3. soothe            - In-process agent core (library)
# 4. soothe-daemon     - Daemon server (WebSocket/HTTP transports)
# 5. soothe-plugins    - Official plugins (built-in tools/subagents)
#
# Uses .venv managed by uv for development.

.PHONY: help setup sync sync-verify
.PHONY: docker-dev-up docker-dev-down docker-dev-ps
.PHONY: docker-daemon-build docker-daemon-build-pypi
.PHONY: docker-daemon-up docker-daemon-down docker-daemon-ps

# Docker Compose env file (all commands use deploy/.env)
DOCKER_ENV_FILE := --env-file deploy/.env
.PHONY: reset-the-world
.PHONY: format format-check lint lint-src lint-fix
.PHONY: test test-unit test-integration test-coverage build clean
.PHONY: sdk-publish cli-publish soothe-publish daemon-publish publish
.PHONY: sdk-publish-test cli-publish-test soothe-publish-test daemon-publish-test publish-test

# ============================================================================
# Configuration
# ============================================================================

PACKAGES = soothe-sdk soothe-cli soothe soothe-daemon soothe-plugins

# Root-level directories to lint (outside packages)
ROOT_LINT_DIRS = examples scripts

ifdef UV_PYPI_MIRROR
UV_SYNC = uv sync --all-packages --all-extras --default-index $(UV_PYPI_MIRROR)
else
UV_SYNC = UV_INDEX_URL= UV_DEFAULT_INDEX= uv sync --all-packages --all-extras 
endif

# ============================================================================
# Help
# ============================================================================

help:
	@echo "Soothe Multi-Package Monorepo"
	@echo ""
	@echo "Setup:"
	@echo "  make setup            - Sync workspace dependencies"
	@echo "  make sync             - Sync all packages + extras + dev deps"
	@echo ""
	@echo "Docker (Dev):"
	@echo "  make docker-dev-up    - Start dev dependencies (pgvector + Langfuse)"
	@echo "  make docker-dev-down  - Stop dev dependencies"
	@echo "  make docker-dev-ps    - Show dev containers status"
	@echo ""
	@echo "Docker (Daemon - Dev):"
	@echo "  make docker-daemon-build     - Build soothed:local-slim from source (no browser)"
	@echo "  make docker-daemon-build-pypi - Build soothed from PyPI (requires SOOTHE_VERSION)"
	@echo "  make docker-daemon-up        - Full dev stack: deps + langfuse + daemon"
	@echo "  make docker-daemon-down      - Stop dev stack"
	@echo "  make docker-daemon-ps        - Show daemon stack status"
	@echo ""
	@echo "Docker (Reset):"
	@echo "  make reset-the-world   - Reset all state and restart clean"
	@echo ""
	@echo "Quality:"
	@echo "  make format           - Format all packages (src + tests)"
	@echo "  make format-check     - Check formatting (for CI)"
	@echo "  make lint             - Lint all packages (src + tests)"
	@echo "  make lint-src         - Lint only src/ (lighter check)"
	@echo "  make lint-fix         - Auto-fix linting issues"
	@echo "  make test             - Run all tests"
	@echo "  make test-unit        - Run unit tests"
	@echo "  make test-integration - Run integration tests"
	@echo "  make test-coverage    - Run tests with coverage"
	@echo "  make build            - Build all packages"
	@echo "  make clean            - Clean all artifacts"
	@echo ""
	@echo "Publish:"
	@echo "  make publish          - Publish all to PyPI"
	@echo "  make publish-test     - Publish all to TestPyPI"

# ============================================================================
# Workspace Setup
# ============================================================================

setup:
	@echo "Syncing workspace dependencies..."
	$(UV_SYNC)
	@echo "Workspace ready"

sync:
	@echo "Syncing all workspace packages..."
	$(UV_SYNC)
	@$(MAKE) sync-verify
	@echo "All packages synced"

sync-verify:
	@.venv/bin/python -c "import importlib.util; pkgs=('psycopg_pool','jsonschema','langfuse','jinja2'); missing=[p for p in pkgs if importlib.util.find_spec(p) is None]; assert not missing, f'Missing: {missing}'"
	@echo "Critical dependencies verified"

# ============================================================================
# Docker Commands
# ============================================================================
#
# Profiles in docker-compose.yml:
#   - default:    Dev dependencies (soothe-pgvector)
#   - langfuse:   Langfuse v3 observability stack
#   - daemon:     Local soothed daemon (dev image from SOOTHE_IMAGE)
#
# Config files:
#   - Dev:        config/develop/config.docker.yml (default)
#
# Quick reference:
#   Dev stack (deps + Langfuse): make docker-dev-up
#   Full dev stack:             make docker-daemon-build && make docker-daemon-up

# Version from VERSION file
SOOTHE_VERSION := $(shell cat VERSION)

# --- Dev Dependencies (pgvector + Langfuse by default) ---------------------

docker-dev-up:
	@echo "Starting dev dependencies (pgvector + Langfuse)..."
	docker compose $(DOCKER_ENV_FILE) --profile langfuse up -d
	@echo ""
	@echo "Dev database: port 6432"
	@echo "Langfuse UI: http://localhost:3300"
	@echo "Sign-in: dev@soothe.local / SootheLangfuseLocalDev1"

docker-dev-down:
	@echo "Stopping dev dependencies..."
	docker compose $(DOCKER_ENV_FILE) --profile langfuse down

docker-dev-ps:
	docker compose $(DOCKER_ENV_FILE) --profile langfuse ps

# --- Image Build -----------------------------------------------------------

docker-daemon-build:
	@echo "Building soothed:local-slim from local source (no browser)..."
	docker build -f packages/soothe-daemon/Dockerfile.local \
		--build-arg INCLUDE_BROWSER=false \
		-t soothed:local-slim .
	@echo "Build complete: soothed:local-slim"
	@echo "Run with: make docker-daemon-up"

docker-daemon-build-pypi:
	@echo "Building soothed:${SOOTHE_VERSION}-local from PyPI (full image with browser)..."
	docker build -f packages/soothe-daemon/Dockerfile \
		--build-arg SOOTHE_VERSION=$(SOOTHE_VERSION) \
		--build-arg INCLUDE_BROWSER=true \
		-t soothed:$(SOOTHE_VERSION)-local .
	@echo "Build complete: soothed:$(SOOTHE_VERSION)-local"

# --- Daemon Dev Stack (daemon profile, config/develop/config.yml) ---------------------

docker-daemon-up:
	@echo "Starting full dev stack: deps + langfuse + daemon..."
	SOOTHE_IMAGE=soothed:local-slim docker compose $(DOCKER_ENV_FILE) --profile langfuse --profile daemon up -d
	@echo ""
	@echo "Stack running. Check status: make docker-daemon-ps"
	@echo ""
	@echo "Services:"
	@echo "  Daemon API:    http://localhost:8765"
	@echo "  Langfuse UI:   http://localhost:3300"
	@echo "  PostgreSQL:    port 6432"
	@echo ""
	@echo "Langfuse sign-in: dev@soothe.local / SootheLangfuseLocalDev1"

docker-daemon-down:
	@echo "Stopping dev stack..."
	docker compose $(DOCKER_ENV_FILE) --profile langfuse --profile daemon down

docker-daemon-ps:
	docker compose $(DOCKER_ENV_FILE) --profile daemon ps

# --- Reset -----------------------------------------------------------------

reset-the-world:
	@echo "Resetting all Docker state and local data..."
	docker compose $(DOCKER_ENV_FILE) --profile daemon --profile langfuse down -v 2>/dev/null || true
	@if [ -d ~/.soothe ]; then \
		find ~/.soothe -mindepth 1 -maxdepth 1 ! -name config -exec rm -rf {} + 2>/dev/null || true; \
	fi
	docker compose $(DOCKER_ENV_FILE) --profile langfuse up -d 2>/dev/null || true
	@echo "World reset complete. Dev stack (pgvector + Langfuse) restarted."

# ============================================================================
# Format & Lint
# ============================================================================

format: sync
	@echo "Formatting all packages..."
	@for pkg in $(PACKAGES); do \
		paths="src/"; \
		test -d "packages/$$pkg/tests" && paths="src/ tests/"; \
		echo "  $$pkg"; \
		cd packages/$$pkg && uv run ruff format $$paths && cd ../..; \
	done
	@echo "Formatting root directories..."
	@for dir in $(ROOT_LINT_DIRS); do \
		echo "  $$dir"; \
		uv run ruff format $$dir; \
	done
	@echo "Done"

format-check: sync
	@echo "Checking formatting..."
	@failed=0; \
	for pkg in $(PACKAGES); do \
		paths="src/"; \
		test -d "packages/$$pkg/tests" && paths="src/ tests/"; \
		cd packages/$$pkg && uv run ruff format --check $$paths || failed=1 && cd ../..; \
	done; \
	for dir in $(ROOT_LINT_DIRS); do \
		echo "  $$dir"; \
		uv run ruff format --check $$dir || failed=1; \
	done; \
	test $$failed -eq 0 && echo "OK" || exit 1

lint: sync
	@echo "Linting all packages (src + tests)..."
	@failed=0; \
	for pkg in $(PACKAGES); do \
		paths="src/"; \
		test -d "packages/$$pkg/tests" && paths="src/ tests/"; \
		echo "  $$pkg"; \
		cd packages/$$pkg && uv run ruff format --check $$paths && uv run ruff check $$paths || failed=1 && cd ../..; \
	done; \
	echo "Linting root directories..."; \
	for dir in $(ROOT_LINT_DIRS); do \
		echo "  $$dir"; \
		uv run ruff format --check $$dir && uv run ruff check $$dir || failed=1; \
	done; \
	test $$failed -eq 0 && echo "Done" || exit 1

lint-src: sync
	@echo "Linting src/ only..."
	@for pkg in $(PACKAGES); do \
		echo "  $$pkg"; \
		cd packages/$$pkg && uv run ruff format --check src/ && uv run ruff check src/ && cd ../..; \
	done
	@echo "Linting root directories..."
	@for dir in $(ROOT_LINT_DIRS); do \
		echo "  $$dir"; \
		uv run ruff format --check $$dir && uv run ruff check $$dir; \
	done
	@echo "Done"

lint-fix: sync
	@echo "Fixing linting and formatting issues..."
	@for pkg in $(PACKAGES); do \
		paths="src/"; \
		test -d "packages/$$pkg/tests" && paths="src/ tests/"; \
		echo "  $$pkg"; \
		cd packages/$$pkg && uv run ruff format $$paths && uv run ruff check --fix $$paths && cd ../..; \
	done
	@echo "Fixing root directories..."
	@for dir in $(ROOT_LINT_DIRS); do \
		echo "  $$dir"; \
		uv run ruff format $$dir && uv run ruff check --fix $$dir; \
	done
	@echo "Done"

# ============================================================================
# Tests
# ============================================================================

test: sync test-unit test-integration
	@echo "All tests complete"

test-unit: sync
	@echo "Running unit tests..."
	@for pkg in $(PACKAGES); do \
		if test -d "packages/$$pkg/tests/unit"; then \
			echo "  $$pkg" && cd packages/$$pkg && uv run pytest tests/unit/ -v --tb=short && cd ../..; \
		fi; \
	done

test-integration: sync
	@echo "Running integration tests..."
	@cd packages/soothe && uv run pytest tests/integration/ --run-integration -v && cd ..
	@cd packages/soothe-daemon && uv run pytest tests/integration/ --run-integration -v && cd ..

test-coverage: sync
	@cd packages/soothe && uv run pytest tests/ --cov=soothe --cov-report=term-missing && cd ..
	@cd packages/soothe-daemon && uv run pytest tests/ --cov=soothe_daemon --cov-report=term-missing && cd ..

# ============================================================================
# Build & Clean
# ============================================================================

build: sync
	@echo "Building all packages..."
	@for pkg in $(PACKAGES); do \
		echo "  $$pkg"; \
		cd packages/$$pkg && uv build --out-dir dist && cd ../..; \
	done
	@echo "Done"

clean:
	rm -rf packages/*/dist/ packages/*/*.egg-info
	find packages -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find packages -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find packages -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
	@echo "Done"

# ============================================================================
# Publish
# ============================================================================

sdk-publish:
	cd packages/soothe-sdk && uv publish dist/* --native-tls

cli-publish:
	cd packages/soothe-cli && uv publish dist/* --native-tls

soothe-publish:
	cd packages/soothe && uv publish dist/* --native-tls

daemon-publish:
	cd packages/soothe-daemon && uv publish dist/* --native-tls

publish: build sdk-publish cli-publish soothe-publish daemon-publish
	@echo "Published to PyPI"

sdk-publish-test:
	cd packages/soothe-sdk && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls

cli-publish-test:
	cd packages/soothe-cli && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls

soothe-publish-test:
	cd packages/soothe && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls

daemon-publish-test:
	cd packages/soothe-daemon && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls

publish-test: build sdk-publish-test cli-publish-test soothe-publish-test daemon-publish-test
	@echo "Published to TestPyPI"
