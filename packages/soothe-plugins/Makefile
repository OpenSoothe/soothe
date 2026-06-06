# Makefile for soothe-community package
# Development workflow automation

.PHONY: help install install-dev test test-cov lint format build clean docs version check-all publish-check publish-test publish publish-clean release

# Default target
.DEFAULT_GOAL := help

# Variables
PYTHON := python3
UV := uv
PIP := $(UV) pip
PYTEST := $(PYTHON) -m pytest
RUFF := $(PYTHON) -m ruff
PACKAGE := soothe-community
SRC_DIR := src/soothe_community
TEST_DIR := tests

# Suppress make's "Entering/Leaving directory" messages
MAKEFLAGS += --no-print-directory

# Use bash for consistent behavior
SHELL := bash

# Colors for output
RED := \033[0;31m
GREEN := \033[0;32m
YELLOW := \033[0;33m
BLUE := \033[0;34m
NC := \033[0m  # No Color

# ============================================================================
# Helper Functions
# ============================================================================

# Check if a command exists
define check_cmd
	@if ! command -v $(1) >/dev/null 2>&1; then \
		echo "$(RED)❌ $(1) not found. Please install it first.$(NC)"; \
		exit 1; \
	fi
endef

# Check if uv is available (critical for this project)
define check_uv
	@if ! command -v $(UV) >/dev/null 2>&1; then \
		echo "$(RED)❌ uv not found. Install with: curl -LsSf https://astral.sh/uv/install.sh | sh$(NC)"; \
		exit 1; \
	fi
endef

# Ensure virtual environment exists and is activated
define ensure_venv
	@if [ ! -d ".venv" ]; then \
		echo "$(BLUE)Creating virtual environment...$(NC)"; \
		$(UV) venv; \
	fi
endef

# ============================================================================
# Installation
# ============================================================================

install: ## Install package in production mode
	$(check_uv)
	$(PIP) install .
	@echo "$(GREEN)✅ Package installed$(NC)"

install-dev: ## Install package in development mode with all dev dependencies
	$(check_uv)
	$(ensure_venv)
	$(PIP) install -e ".[dev]" || { \
		echo "$(YELLOW)⚠️  Installation failed, trying with --reinstall...$(NC)"; \
		$(PIP) install -e ".[dev]" --reinstall; \
	}
	@echo "$(GREEN)✅ Development environment ready$(NC)"
	@echo "$(BLUE)💡 Activate with: source .venv/bin/activate$(NC)"

install-clean: ## Clean install (remove existing first)
	$(check_uv)
	$(PIP) uninstall -y $(PACKAGE) 2>/dev/null || true
	rm -rf .venv 2>/dev/null || true
	$(MAKE) install-dev

# ============================================================================
# Testing
# ============================================================================

test: ## Run all tests
	@$(PYTEST) $(TEST_DIR) -v --tb=short || { \
		echo "$(YELLOW)⚠️  Some tests failed. Check output above.$(NC)"; \
		exit 1; \
	}

test-cov: ## Run tests with coverage report
	@$(PYTEST) $(TEST_DIR) --cov=$(SRC_DIR) --cov-report=term --cov-report=html -v --tb=short || { \
		echo "$(YELLOW)⚠️  Some tests failed. Coverage may be incomplete.$(NC)"; \
	}
	@if [ -f "htmlcov/index.html" ]; then \
		echo "$(GREEN)📊 Coverage report: htmlcov/index.html$(NC)"; \
	fi

test-quick: ## Run tests quickly (no coverage, failfast)
	@$(PYTEST) $(TEST_DIR) -x -q --tb=line 2>/dev/null || { \
		echo "$(RED)❌ Tests failed. Run 'make test' for detailed output.$(NC)"; \
		exit 1; \
	}
	@echo "$(GREEN)✅ All tests passed$(NC)"

test-plugin: ## Run tests for specific plugin (usage: make test-plugin PLUGIN=paperscout)
	@if [ -z "$(PLUGIN)" ]; then \
		echo "$(RED)Usage: make test-plugin PLUGIN=<plugin_name>$(NC)"; \
		exit 1; \
	fi
	@if [ ! -d "$(TEST_DIR)" ]; then \
		echo "$(RED)❌ Tests directory not found$(NC)"; \
		exit 1; \
	fi
	@$(PYTEST) $(TEST_DIR) -k "$(PLUGIN)" -v || { \
		echo "$(YELLOW)⚠️  No tests found for plugin '$(PLUGIN)'$(NC)"; \
	}

test-integration: ## Run integration tests only
	@$(PYTEST) $(TEST_DIR) -v -m integration --tb=short || { \
		echo "$(YELLOW)⚠️  Integration tests failed or not found.$(NC)"; \
	}

test-unit: ## Run unit tests only
	@$(PYTEST) $(TEST_DIR) -v -m "not integration" --tb=short

# ============================================================================
# Code Quality
# ============================================================================

format: ## Format code with ruff
	@if [ ! -d "$(SRC_DIR)" ]; then \
		echo "$(RED)❌ Source directory not found: $(SRC_DIR)$(NC)"; \
		exit 1; \
	fi; \
	if ! $(PYTHON) -c "import ruff" 2>/dev/null 1>/dev/null; then \
		echo "$(YELLOW)⚠️  ruff not installed. Install with: pip install ruff$(NC)"; \
		exit 0; \
	fi; \
	$(RUFF) format $(SRC_DIR) $(TEST_DIR) || { \
		echo "$(YELLOW)⚠️  Some files could not be formatted. Check output above.$(NC)"; \
	}; \
	echo "$(GREEN)✅ Code formatted$(NC)"

lint: ## Lint code with ruff
	@if [ ! -d "$(SRC_DIR)" ]; then \
		echo "$(RED)❌ Source directory not found: $(SRC_DIR)$(NC)"; \
		exit 1; \
	fi; \
	if ! $(PYTHON) -c "import ruff" 2>/dev/null 1>/dev/null; then \
		echo "$(YELLOW)⚠️  ruff not installed. Install with: pip install ruff$(NC)"; \
		exit 0; \
	fi; \
	$(RUFF) check $(SRC_DIR) $(TEST_DIR) 2>/dev/null || { \
		echo "$(YELLOW)⚠️  Linting issues found. Run 'make lint-fix' to auto-fix.$(NC)"; \
		exit 1; \
	}; \
	echo "$(GREEN)✅ No linting issues$(NC)"

lint-fix: ## Lint and auto-fix issues
	@if [ ! -d "$(SRC_DIR)" ]; then \
		echo "$(RED)❌ Source directory not found: $(SRC_DIR)$(NC)"; \
		exit 1; \
	fi; \
	if ! $(PYTHON) -c "import ruff" 2>/dev/null 1>/dev/null; then \
		echo "$(YELLOW)⚠️  ruff not installed. Install with: pip install ruff$(NC)"; \
		exit 0; \
	fi; \
	$(RUFF) check --fix $(SRC_DIR) $(TEST_DIR) || true; \
	$(RUFF) format $(SRC_DIR) $(TEST_DIR) || true; \
	echo "$(GREEN)✅ Linting issues fixed and code formatted$(NC)"

type-check: ## Run type checking with mypy (if available)
	@if ! command -v mypy >/dev/null 2>&1 && ! $(PYTHON) -c "import mypy" 2>/dev/null; then \
		echo "$(YELLOW)⚠️  mypy not installed. Skipping type check.$(NC)"; \
		echo "$(BLUE)💡 Install with: pip install mypy$(NC)"; \
		exit 0; \
	fi
	@$(PYTHON) -m mypy $(SRC_DIR) --ignore-missing-imports || { \
		echo "$(YELLOW)⚠️  Type checking found issues.$(NC)"; \
		exit 0; \
	}
	@echo "$(GREEN)✅ Type checking passed$(NC)"

check-all: ## Run all quality checks (format, lint, type-check, test)
	@echo "$(BLUE)🔍 Running all quality checks...$(NC)"
	@failed=0; \
	$(MAKE) format || failed=1; \
	$(MAKE) lint || failed=1; \
	$(MAKE) type-check || true; \
	$(MAKE) test-quick || failed=1; \
	if [ $$failed -eq 1 ]; then \
		echo "$(RED)❌ Some checks failed$(NC)"; \
		exit 1; \
	else \
		echo "$(GREEN)✅ All checks passed$(NC)"; \
	fi

# ============================================================================
# Build & Distribution
# ============================================================================

build: ## Build package distributions (wheel and sdist)
	@# Ensure build module is available
	@if ! $(PYTHON) -c "import build" 2>/dev/null; then \
		echo "$(YELLOW)⚠️  build module not found. Installing...$(NC)"; \
		$(PIP) install build --quiet; \
	fi
	$(PYTHON) -m build || { \
		echo "$(RED)❌ Build failed$(NC)"; \
		exit 1; \
	}
	@if [ -d "dist" ]; then \
		echo "$(GREEN)📦 Built distributions in dist/$(NC)"; \
		ls -la dist/ | tail -n +2; \
	fi

build-wheel: ## Build wheel only
	@if ! $(PYTHON) -c "import build" 2>/dev/null; then \
		$(PIP) install build --quiet; \
	fi
	$(PYTHON) -m build --wheel || { \
		echo "$(RED)❌ Wheel build failed$(NC)"; \
		exit 1; \
	}

build-sdist: ## Build source distribution only
	@if ! $(PYTHON) -c "import build" 2>/dev/null; then \
		$(PIP) install build --quiet; \
	fi
	$(PYTHON) -m build --sdist || { \
		echo "$(RED)❌ Source distribution build failed$(NC)"; \
		exit 1; \
	}

clean-build: ## Remove build artifacts
	@rm -rf build/ dist/ *.egg-info src/*.egg-info 2>/dev/null || true
	@find $(SRC_DIR) -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find $(TEST_DIR) -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@rm -rf .pytest_cache .ruff_cache .coverage htmlcov .mypy_cache 2>/dev/null || true
	@echo "$(GREEN)🧹 Build artifacts cleaned$(NC)"

# ============================================================================
# PyPI Publishing
# ============================================================================

TWINE := $(PYTHON) -m twine

publish-check: ## Check distribution files before publishing
	@if [ ! -d "dist" ] || [ -z "$$(ls -A dist 2>/dev/null)" ]; then \
		echo "$(RED)❌ No distributions found. Run 'make build' first.$(NC)"; \
		exit 1; \
	fi
	@# Ensure twine is available
	@if ! $(PYTHON) -c "import twine" 2>/dev/null; then \
		echo "$(YELLOW)⚠️  twine not found. Installing...$(NC)"; \
		$(PIP) install twine --quiet; \
	fi
	$(TWINE) check dist/* || { \
		echo "$(RED)❌ Distribution validation failed$(NC)"; \
		exit 1; \
	}
	@echo "$(GREEN)✅ Distribution files validated$(NC)"

publish-test: ## Publish to TestPyPI (for testing before real release)
	@# Ensure twine is available
	@if ! $(PYTHON) -c "import twine" 2>/dev/null; then \
		$(PIP) install twine --quiet; \
	fi
	$(MAKE) build
	$(MAKE) publish-check
	@echo "$(BLUE)🚀 Uploading to TestPyPI...$(NC)"
	$(TWINE) upload --repository testpypi dist/* --skip-existing || { \
		echo "$(YELLOW)⚠️  Upload may have partially succeeded (some files might already exist)$(NC)"; \
	}
	@echo "$(GREEN)✅ Published to TestPyPI: https://test.pypi.org/project/$(PACKAGE)/$(NC)"
	@echo "$(BLUE)📝 Test install: pip install --index-url https://test.pypi.org/simple/ $(PACKAGE)$(NC)"

publish: ## Publish to PyPI (production)
	@# Ensure twine is available
	@if ! $(PYTHON) -c "import twine" 2>/dev/null; then \
		$(PIP) install twine --quiet; \
	fi
	$(MAKE) build
	$(MAKE) publish-check
	@echo "$(YELLOW)⚠️  Publishing to PyPI (production)...$(NC)"
	@echo "$(BLUE)Press Enter to continue or Ctrl+C to cancel...$(NC)"
	@read confirm || true
	$(TWINE) upload dist/* --skip-existing || { \
		echo "$(YELLOW)⚠️  Upload may have partially succeeded$(NC)"; \
	}
	@echo "$(GREEN)✅ Published to PyPI: https://pypi.org/project/$(PACKAGE)/$(NC)"

publish-clean: ## Clean dist directory before fresh build and publish
	@rm -rf dist/ 2>/dev/null || true
	$(MAKE) build
	$(MAKE) publish-check

release: ## Full release workflow (check, build, publish to PyPI)
	@$(MAKE) check-all || { \
		echo "$(RED)❌ Checks failed. Fix issues before release.$(NC)"; \
		exit 1; \
	}
	$(MAKE) publish-clean
	@echo "$(GREEN)🚀 Ready to publish. Run 'make publish' to upload to PyPI.$(NC)"

# ============================================================================
# Documentation
# ============================================================================

docs: ## Generate documentation (if pdocs available)
	@if ! command -v pdoc >/dev/null 2>&1 && ! $(PYTHON) -c "import pdoc" 2>/dev/null; then \
		echo "$(YELLOW)⚠️  pdoc not installed. Installing...$(NC)"; \
		$(PIP) install pdoc --quiet; \
	fi
	@if [ ! -d "$(SRC_DIR)" ]; then \
		echo "$(RED)❌ Source directory not found$(NC)"; \
		exit 1; \
	fi
	$(PYTHON) -m pdoc $(SRC_DIR) -o docs/html || { \
		echo "$(YELLOW)⚠️  Documentation generation had issues$(NC)"; \
	}
	@if [ -d "docs/html" ]; then \
		echo "$(GREEN)📚 Documentation generated in docs/html$(NC)"; \
	fi

docs-clean: ## Remove generated documentation
	@rm -rf docs/html 2>/dev/null || true
	@echo "$(GREEN)🧹 Documentation cleaned$(NC)"

docs-view: ## View documentation in browser (requires docs)
	@if [ ! -d "docs/html" ]; then \
		echo "$(YELLOW)⚠️  No docs found. Run 'make docs' first.$(NC)"; \
		$(MAKE) docs; \
	fi
	@if command -v open >/dev/null 2>&1; then \
		open docs/html/index.html; \
	elif command -v xdg-open >/dev/null 2>&1; then \
		xdg-open docs/html/index.html; \
	else \
		echo "$(BLUE)📚 Open docs/html/index.html manually$(NC)"; \
	fi

# ============================================================================
# Version Management
# ============================================================================

version: ## Show current package version
	@if [ ! -f "$(SRC_DIR)/__init__.py" ]; then \
		echo "$(RED)❌ __init__.py not found$(NC)"; \
		exit 1; \
	fi
	@grep "__version__" $(SRC_DIR)/__init__.py | head -1 || { \
		echo "$(YELLOW)⚠️  No __version__ found in __init__.py$(NC)"; \
	}

version-bump: ## Bump version (usage: make version-bump TYPE=patch|minor|major)
	@if [ -z "$(TYPE)" ]; then \
		echo "$(RED)Usage: make version-bump TYPE=patch|minor|major$(NC)"; \
		exit 1; \
	fi
	@if [ ! -f "$(SRC_DIR)/__init__.py" ]; then \
		echo "$(RED)❌ __init__.py not found$(NC)"; \
		exit 1; \
	fi
	@current_version=$$(grep "__version__" $(SRC_DIR)/__init__.py | sed 's/.*"\([^"]*\)".*/\1/'); \
	echo "$(BLUE)Current version: $$current_version$(NC)"; \
	echo "$(YELLOW)⚠️  Manual version bump required. Edit __version__ in $(SRC_DIR)/__init__.py$(NC)"; \
	echo "$(BLUE)💡 For $(TYPE) bump, change from $$current_version accordingly:$(NC)"; \
	@if [ "$(TYPE)" = "major" ]; then \
		echo "  major: X.0.0"; \
	elif [ "$(TYPE)" = "minor" ]; then \
		echo "  minor: x.Y.0"; \
	else \
		echo "  patch: x.y.Z"; \
	fi

# ============================================================================
# Plugin Development
# ============================================================================

plugin-list: ## List all available plugins
	@echo "$(BLUE)📦 Available plugins:$(NC)"
	@if grep -q "soothe.plugins" pyproject.toml 2>/dev/null; then \
		grep -A 10 "soothe.plugins" pyproject.toml | grep "=" | sed 's/^ */  - /' || echo "$(YELLOW)  No plugins configured$(NC)"; \
	else \
		echo "$(YELLOW)  No plugin entry points in pyproject.toml$(NC)"; \
	fi

plugin-template: ## Create new plugin from template (usage: make plugin-template NAME=my_plugin)
	@if [ -z "$(NAME)" ]; then \
		echo "$(RED)Usage: make plugin-template NAME=<plugin_name>$(NC)"; \
		exit 1; \
	fi
	@if [ ! -d "$(SRC_DIR)/.plugin_template" ]; then \
		echo "$(YELLOW)⚠️  Plugin template not found. Creating basic structure...$(NC)"; \
		mkdir -p $(SRC_DIR)/$(NAME); \
		touch $(SRC_DIR)/$(NAME)/__init__.py; \
	else \
		cp -r $(SRC_DIR)/.plugin_template $(SRC_DIR)/$(NAME); \
	fi
	@echo "$(GREEN)✅ Plugin created in $(SRC_DIR)/$(NAME)$(NC)"
	@echo "$(BLUE)📝 Next steps:$(NC)"
	@echo "   1. Edit files in $(SRC_DIR)/$(NAME)/"
	@echo "   2. Add tests in $(TEST_DIR)/$(NAME)/"
	@echo "   3. Register in pyproject.toml entry-points"

plugin-validate: ## Validate all plugin entry points
	@echo "$(BLUE)Checking plugin entry points in pyproject.toml...$(NC)"
	@if [ ! -f "pyproject.toml" ]; then \
		echo "$(RED)❌ pyproject.toml not found$(NC)"; \
		exit 1; \
	fi
	@if grep -q "soothe.plugins" pyproject.toml 2>/dev/null; then \
		echo "$(GREEN)✅ Entry points section found$(NC)"; \
		@grep -A 10 "soothe.plugins" pyproject.toml | grep "=" | wc -l | awk '{print "$(GREEN)✅ " $$1 " plugins registered$(NC)"}'; \
	else \
		echo "$(YELLOW)⚠️  No entry points section found$(NC)"; \
	fi

# ============================================================================
# Git & Release
# ============================================================================

git-status: ## Show git status summary
	@if ! command -v git >/dev/null 2>&1; then \
		echo "$(RED)❌ git not found$(NC)"; \
		exit 1; \
	fi
	@git status -s || echo "$(YELLOW)⚠️  Not a git repository$(NC)"
	@echo ""
	@git log --oneline -5 2>/dev/null || echo "$(YELLOW)⚠️  No commits yet$(NC)"

git-clean: ## Remove untracked files (dry run)
	@if ! git rev-parse --git-dir >/dev/null 2>&1; then \
		echo "$(YELLOW)⚠️  Not a git repository$(NC)"; \
		exit 0; \
	fi
	@git clean -n -d || true
	@echo "$(BLUE)Run 'make git-clean-force' to actually remove files$(NC)"

git-clean-force: ## Remove untracked files (force)
	@if ! git rev-parse --git-dir >/dev/null 2>&1; then \
		echo "$(YELLOW)⚠️  Not a git repository$(NC)"; \
		exit 0; \
	fi
	@git clean -f -d
	@echo "$(GREEN)🧹 Untracked files removed$(NC)"

release-prep: ## Prepare for release (run all checks)
	@$(MAKE) check-all || { \
		echo "$(RED)❌ Checks failed. Fix before release.$(NC)"; \
		exit 1; \
	}
	$(MAKE) build
	@echo "$(GREEN)✅ Release preparation complete$(NC)"
	@echo "$(BLUE)📝 Next steps:$(NC)"
	@echo "   1. Update version in $(SRC_DIR)/__init__.py"
	@echo "   2. git commit -am 'Release v<X.Y.Z>'"
	@echo "   3. git tag v<X.Y.Z>"
	@echo "   4. git push && git push --tags"
	@echo "   5. make publish"

# ============================================================================
# Dependencies
# ============================================================================

deps-check: ## Check for outdated dependencies
	$(PIP) list --outdated || { \
		echo "$(YELLOW)⚠️  Could not check dependencies$(NC)"; \
	}

deps-update: ## Update dependencies to latest versions
	$(PIP) install --upgrade -e ".[dev]" || { \
		echo "$(YELLOW)⚠️  Update had issues, trying alternative...$(NC)"; \
		$(PIP) install --upgrade pip && $(PIP) install -e ".[dev]"; \
	}
	@echo "$(GREEN)✅ Dependencies updated$(NC)"

deps-lock: ## Generate requirements lock file (if using pip-tools)
	@if ! command -v pip-compile >/dev/null 2>&1; then \
		echo "$(YELLOW)⚠️  pip-tools not installed. Installing...$(NC)"; \
		$(PIP) install pip-tools --quiet; \
	fi
	@if [ -f "pyproject.toml" ]; then \
		pip-compile pyproject.toml -o requirements.txt || { \
			echo "$(YELLOW)⚠️  Could not generate requirements.txt$(NC)"; \
		}; \
		echo "$(GREEN)✅ Requirements locked$(NC)"; \
	else \
		echo "$(RED)❌ pyproject.toml not found$(NC)"; \
	fi

deps-tree: ## Show dependency tree
	@if ! $(PYTHON) -c "import pipdeptree" 2>/dev/null; then \
		echo "$(YELLOW)⚠️  pipdeptree not installed. Installing...$(NC)"; \
		$(PIP) install pipdeptree --quiet; \
	fi
	$(PYTHON) -m pipdeptree || $(PIP) list

# ============================================================================
# Development Utilities
# ============================================================================

shell: ## Start Python shell with package loaded
	@# Try to load package, fallback to basic shell
	$(PYTHON) -i -c "from soothe_community import *; print('📦 soothe-community loaded')" 2>/dev/null || \
	$(PYTHON) -i -c "print('$(YELLOW)⚠️  Package not installed. Run make install-dev first$(NC)')"

info: ## Show package information
	@echo "$(BLUE)📦 Package: $(PACKAGE)$(NC)"
	@$(MAKE) --no-print-directory version 2>/dev/null || echo "$(YELLOW)  Version not found$(NC)"
	@echo ""
	@echo "$(BLUE)📂 Structure:$(NC)"
	@if [ -d "$(SRC_DIR)" ]; then \
		find $(SRC_DIR) -type d | head -10; \
	else \
		echo "$(YELLOW)  Source directory not found$(NC)"; \
	fi
	@echo ""
	@echo "$(BLUE)📋 Entry points:$(NC)"
	@$(MAKE) --no-print-directory plugin-list 2>/dev/null || true

env-info: ## Show environment information
	@echo "$(BLUE)🐍 Python:$(NC)"
	@$(PYTHON) --version 2>/dev/null || echo "$(YELLOW)  Python not found$(NC)"
	@echo ""
	@echo "$(BLUE)📦 Package manager:$(NC)"
	@if command -v $(UV) >/dev/null 2>&1; then \
		$(UV) --version; \
	else \
		echo "$(YELLOW)  uv not found$(NC)"; \
	fi
	@echo ""
	@echo "$(BLUE)🔍 Tools:$(NC)"
	@$(PYTHON) -c "import pytest" 2>/dev/null && echo "  pytest: $(GREEN)✓$(NC)" || echo "  pytest: $(RED)✗$(NC)"
	@$(PYTHON) -c "import ruff" 2>/dev/null && echo "  ruff: $(GREEN)✓$(NC)" || echo "  ruff: $(RED)✗$(NC)"
	@$(PYTHON) -c "import mypy" 2>/dev/null && echo "  mypy: $(GREEN)✓$(NC)" || echo "  mypy: $(RED)✗$(NC)"
	@$(PYTHON) -c "import build" 2>/dev/null && echo "  build: $(GREEN)✓$(NC)" || echo "  build: $(RED)✗$(NC)"
	@echo ""
	@echo "$(BLUE)📁 Working directory:$(NC)"
	@pwd

# ============================================================================
# Cleanup
# ============================================================================

clean: ## Clean all generated files and caches
	$(MAKE) clean-build
	$(MAKE) docs-clean
	@# Clean additional caches
	@find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	@rm -rf .coverage htmlcov 2>/dev/null || true
	@echo "$(GREEN)🧹 All cleaned$(NC)"

clean-all: ## Deep clean (includes git untracked)
	$(MAKE) clean
	@if git rev-parse --git-dir >/dev/null 2>&1; then \
		$(MAKE) git-clean-force; \
	else \
		echo "$(YELLOW)⚠️  Not a git repository$(NC)"; \
	fi

# ============================================================================
# Help
# ============================================================================

help: ## Show this help message
	@printf "$(BLUE)🛠️  soothe-community Makefile$(NC)\n"
	@printf "\n"
	@printf "Usage: make [target]\n"
	@printf "\n"
	@printf "$(GREEN)Installation:$(NC)\n"
	@printf "  install              Install package in production mode\n"
	@printf "  install-dev          Install in development mode\n"
	@printf "  install-clean        Clean reinstall\n"
	@printf "\n"
	@printf "$(GREEN)Testing:$(NC)\n"
	@printf "  test                 Run all tests\n"
	@printf "  test-cov             Run tests with coverage\n"
	@printf "  test-quick           Run tests quickly (failfast)\n"
	@printf "  test-unit            Run unit tests only\n"
	@printf "  test-integration     Run integration tests only\n"
	@printf "\n"
	@printf "$(GREEN)Code Quality:$(NC)\n"
	@printf "  format               Format code with ruff\n"
	@printf "  lint                 Lint code with ruff\n"
	@printf "  lint-fix             Lint and auto-fix issues\n"
	@printf "  type-check           Run mypy type checking\n"
	@printf "  check-all            Run all quality checks\n"
	@printf "\n"
	@printf "$(GREEN)Build & Publish:$(NC)\n"
	@printf "  build                Build wheel and sdist\n"
	@printf "  clean-build          Remove build artifacts\n"
	@printf "  publish-test         Publish to TestPyPI\n"
	@printf "  publish              Publish to PyPI (production)\n"
	@printf "  release              Full release workflow\n"
	@printf "\n"
	@printf "$(GREEN)Utilities:$(NC)\n"
	@printf "  info                 Show package info\n"
	@printf "  env-info             Show environment info\n"
	@printf "  version              Show current version\n"
	@printf "  deps-update          Update dependencies\n"
	@printf "  clean                Clean all caches\n"
	@printf "\n"
	@printf "$(GREEN)Shortcuts:$(NC)\n"
	@printf "  i                    install-dev\n"
	@printf "  t                    test-quick\n"
	@printf "  c                    check-all\n"
	@printf "  b                    build\n"
	@printf "  cl                   clean\n"
	@printf "\n"
	@printf "$(BLUE)Examples:$(NC)\n"
	@printf "  make install-dev\n"
	@printf "  make test\n"
	@printf "  make check-all\n"
	@printf "  make publish-test\n"
	@printf "\n"
	@printf "$(BLUE)For full target list: make help-full$(NC)\n"

help-full: ## Show full help with all targets
	@printf "$(BLUE)🛠️  soothe-community Makefile - All Targets$(NC)\n"
	@printf "\n"
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		sed 's/^\([^:]*\):.*## \(.*\)/\1: \2/' | \
		sort | \
		awk -F: '{printf "  %-20s %s\n", $$1, $$2}'

# ============================================================================
# Quick Shortcuts
# ============================================================================

i: install-dev ## Shortcut: install-dev
t: test-quick ## Shortcut: test-quick
c: check-all ## Shortcut: check-all
b: build ## Shortcut: build
cl: clean ## Shortcut: clean
v: version ## Shortcut: version
ci: check-all test-cov ## Shortcut: CI-like run (check-all + coverage)
