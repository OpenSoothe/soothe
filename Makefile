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

.PHONY: help setup sync sync-verify docker-up docker-down reset-the-world
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
	@echo "  make docker-up        - Start docker compose services"
	@echo "  make docker-down      - Stop docker compose services"
	@echo "  make reset-the-world  - Reset all state and restart"
	@echo ""
	@echo "Unified Targets:"
	@echo "  make sync             - Sync all packages + extras + dev deps"
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
	@.venv/bin/python -c "import importlib.util; pkgs=('psycopg_pool','jsonschema','langfuse'); missing=[p for p in pkgs if importlib.util.find_spec(p) is None]; assert not missing, f'Missing: {missing}'"
	@echo "Critical dependencies verified"

docker-up:
	docker compose -f docker-compose.dev.yml up -d

docker-down:
	docker compose -f docker-compose.dev.yml down

reset-the-world:
	docker compose -f docker-compose.dev.yml down -v 2>/dev/null || true
	@if [ -d ~/.soothe ]; then find ~/.soothe -mindepth 1 -maxdepth 1 ! -name config -exec rm -rf {} + 2>/dev/null || true; fi
	docker compose -f docker-compose.dev.yml up -d 2>/dev/null || true
	@echo "World reset complete"

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
		cd packages/$$pkg && uv run ruff check $$paths || failed=1 && cd ../..; \
	done; \
	echo "Linting root directories..."; \
	for dir in $(ROOT_LINT_DIRS); do \
		echo "  $$dir"; \
		uv run ruff check $$dir || failed=1; \
	done; \
	test $$failed -eq 0 && echo "Done" || exit 1

lint-src: sync
	@echo "Linting src/ only..."
	@for pkg in $(PACKAGES); do \
		echo "  $$pkg"; \
		cd packages/$$pkg && uv run ruff check src/ && cd ../..; \
	done
	@echo "Linting root directories..."
	@for dir in $(ROOT_LINT_DIRS); do \
		echo "  $$dir"; \
		uv run ruff check $$dir; \
	done
	@echo "Done"

lint-fix: sync
	@echo "Fixing linting issues..."
	@for pkg in $(PACKAGES); do \
		paths="src/"; \
		test -d "packages/$$pkg/tests" && paths="src/ tests/"; \
		echo "  $$pkg"; \
		cd packages/$$pkg && uv run ruff check --fix $$paths && cd ../..; \
	done
	@echo "Fixing root directories..."
	@for dir in $(ROOT_LINT_DIRS); do \
		echo "  $$dir"; \
		uv run ruff check --fix $$dir; \
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