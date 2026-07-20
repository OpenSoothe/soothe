# Makefile for Soothe Multi-Package Monorepo
#
# This Makefile manages packages:
# 1. soothe-sdk        - Shared SDK (events/display/wire/protocols)
# 2. soothe-nano       - Batteries-included Coding CoreAgent
# 3. soothe-cli        - CLI client (Typer CLI + Textual TUI)
# 4. soothe            - StrangeLoop / Autopilot / host composition
# 5. soothe-daemon     - Daemon server (WebSocket/HTTP transports)
# 6. soothe-plugins    - Official plugins (depends on soothe-nano)
#
# Uses .venv managed by uv for development.

.PHONY: help setup sync sync-verify
.PHONY: docker-dev-up docker-dev-down docker-dev-ps
.PHONY: docker-prod-pull docker-prod-up docker-prod-down docker-prod-ps

# Docker Compose env file (all commands use deploy/.env)
DOCKER_ENV_FILE := --env-file deploy/.env
# Production stack (deploy/docker-compose.yml)
DOCKER_PROD_COMPOSE := docker compose -f deploy/docker-compose.yml $(DOCKER_ENV_FILE)
.PHONY: reset-the-world
.PHONY: format format-check lint lint-src lint-fix autofix vulture vulture-whitelist
.PHONY: test test-unit test-integration test-coverage build clean
.PHONY: sdk-publish nano-publish cli-publish soothe-publish daemon-publish publish
.PHONY: sdk-publish-test nano-publish-test cli-publish-test soothe-publish-test daemon-publish-test publish-test

# ============================================================================
# Configuration
# ============================================================================

PACKAGES = soothe-sdk soothe-nano soothe-cli soothe soothe-daemon soothe-plugins

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
	@echo "Docker (Production):"
	@echo "  make docker-prod-pull  - Pull production images (pgvector + soothed)"
	@echo "  make docker-prod-up    - Start production stack (deploy/)"
	@echo "  make docker-prod-down  - Stop production stack"
	@echo "  make docker-prod-ps    - Show production stack status"
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
	@echo "  make autofix          - Run all auto-fixes (format + lint-fix)"
	@echo "  make vulture          - Dead-code analysis (vulture, min 90% confidence)"
	@echo "  make vulture-whitelist - Regenerate scripts/vulture_whitelist.py"
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
#   Production stack:           cp deploy/env-example deploy/.env && make docker-prod-up

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

# --- Production Stack (deploy/docker-compose.yml) --------------------------

docker-prod-pull:
	@echo "Pulling production images..."
	$(DOCKER_PROD_COMPOSE) pull
	@echo "Pull complete"

docker-prod-up:
	@echo "Starting production stack (PostgreSQL + pgvector + soothed)..."
	$(DOCKER_PROD_COMPOSE) up -d
	@echo ""
	@echo "Stack running. Check status: make docker-prod-ps"
	@echo ""
	@echo "Services:"
	@echo "  Daemon API:  http://localhost:8765"
	@echo "  PostgreSQL:  internal (soothe-pgvector)"
	@echo ""
	@echo "Config: deploy/.env (copy from deploy/env-example if missing)"

docker-prod-down:
	@echo "Stopping production stack..."
	$(DOCKER_PROD_COMPOSE) down

docker-prod-ps:
	$(DOCKER_PROD_COMPOSE) ps

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

autofix: format lint-fix
	@echo "All auto-fixes applied"

vulture: sync
	@echo "Running vulture dead-code analysis..."
	@.venv/bin/vulture
	@echo "OK — no new high-confidence dead code"

vulture-whitelist: sync
	@echo "Regenerating scripts/vulture_whitelist.py (review diff before commit)..."
	@{ \
		echo '"""Vulture whitelist — known false positives and tracked dead-code debt.'; \
		echo ''; \
		echo 'Regenerate (then review diff) with::'; \
		echo ''; \
		echo '    make vulture-whitelist'; \
		echo ''; \
		echo 'Each entry suppresses a specific high-confidence finding until the code is'; \
		echo 'fixed or removed.'; \
		echo '"""'; \
		echo ''; \
		.venv/bin/vulture --make-whitelist; \
	} > scripts/vulture_whitelist.py
	@echo "Wrote scripts/vulture_whitelist.py"

# ============================================================================
# Tests
# ============================================================================

test: sync test-unit test-integration
	@echo "All tests complete"

test-unit: sync
	@echo "Running unit tests..."
	@set -e; for pkg in $(PACKAGES); do \
		if test -d "packages/$$pkg/tests/unit"; then \
			echo "  $$pkg" && (cd packages/$$pkg && uv run pytest tests/unit/ -v --tb=short); \
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

nano-publish:
	cd packages/soothe-nano && uv publish dist/* --native-tls

cli-publish:
	cd packages/soothe-cli && uv publish dist/* --native-tls

soothe-publish:
	cd packages/soothe && uv publish dist/* --native-tls

daemon-publish:
	cd packages/soothe-daemon && uv publish dist/* --native-tls

publish: build sdk-publish nano-publish cli-publish soothe-publish daemon-publish
	@echo "Published to PyPI"

sdk-publish-test:
	cd packages/soothe-sdk && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls

nano-publish-test:
	cd packages/soothe-nano && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls

cli-publish-test:
	cd packages/soothe-cli && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls

soothe-publish-test:
	cd packages/soothe && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls

daemon-publish-test:
	cd packages/soothe-daemon && uv publish dist/* --index-url https://test.pypi.org/simple/ --native-tls

publish-test: build sdk-publish-test cli-publish-test soothe-publish-test daemon-publish-test
	@echo "Published to TestPyPI"
