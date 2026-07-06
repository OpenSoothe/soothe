# Testing Guide

Comprehensive testing guide for Soothe monorepo.

---

## Testing Architecture

Soothe uses a **multi-package monorepo** with five packages:

```
packages/
├── soothe-sdk/        # Shared SDK (protocol types, decorators)
├── soothe-cli/        # CLI + TUI
├── soothe/            # Agent core (library)
├── soothe-daemon/     # Daemon server
└── soothe-plugins/    # Optional plugins and subagents
```

Each package has its own test suite:
- Unit tests: `packages/<name>/tests/unit/`
- Integration tests: `packages/<name>/tests/integration/`

---

## Quick Start

### Run All Tests

```bash
# Run all unit tests (900+ tests)
make test-unit

# Run all tests with coverage
make test-coverage

# Quick verification (format + lint + unit tests)
./scripts/verify_finally.sh

# Quick check without tests (format + lint only)
./scripts/verify_finally.sh --quick
```

### Run Specific Package Tests

```bash
# SDK tests
cd packages/soothe-sdk
uv run pytest tests/

# CLI tests
cd packages/soothe-cli
uv run pytest tests/

# Core tests
cd packages/soothe
uv run pytest tests/

# Daemon tests
cd packages/soothe-daemon
uv run pytest tests/
```

---

## Test Types

### Unit Tests

**Purpose**: Test individual functions, classes, and modules in isolation.

**Location**: `packages/<name>/tests/unit/<module_path>/`

**Example structure**:
```
packages/soothe/tests/unit/
├── core/
│   ├── strange_loop/
│   │   ├── test_strange_loop_graph.py
│   │   ├── test_execute_node.py
│   │   └── test_plan_node.py
│   ├── events/
│   │   ├── test_event_registration.py
│   │   └── test_event_catalog.py
│   └── agent_factory/
│   │   ├── test_create_soothe_agent.py
│   └── resolver/
│   │   ├── test_protocol_resolver.py
├── backends/
│   ├── memory/
│   │   ├── test_memu_backend.py
│   ├── durability/
│   │   ├── test_sqlite_backend.py
│   │   ├── test_postgres_backend.py
```

**Run unit tests**:
```bash
make test-unit
```

### Integration Tests

**Purpose**: Test module interactions, protocol implementations, and backend integrations.

**Location**: `packages/<name>/tests/integration/`

**Example structure**:
```
packages/soothe/tests/integration/
├── protocols/
│   ├── test_memory_protocol.py
│   ├── test_planner_protocol.py
│   ├── test_durability_protocol.py
├── backends/
│   ├── test_pgvector_backend.py  # Requires PostgreSQL + pgvector
│   ├── test_weaviate_backend.py  # Requires Weaviate server
├── agent/
│   ├── test_full_loop_execution.py
```

**Run integration tests**:
```bash
make test-integration

# Integration tests require external services
docker compose -f docker-compose.yml up -d  # Start PostgreSQL + pgvector
make test-integration
```

### End-to-End Tests

**Purpose**: Test complete workflows from CLI to daemon to agent execution.

**Location**: `scripts/` (benchmark and validation scripts)

**Examples**:
- `scripts/benchmark_e2e_concurrent_queries.py` - Concurrent query handling
- `scripts/verify_daemon_events.py` - Daemon event streaming
- `scripts/validate_streaming.py` - Output streaming validation

**Run E2E tests**:
```bash
# Requires running daemon
soothed start
python scripts/verify_daemon_events.py
python scripts/benchmark_e2e_concurrent_queries.py
```

---

## Test Organization

### Module Self-Containment Pattern (IG-047)

Tests are placed **close to the code they test**:

```
packages/soothe/src/soothe/foundation/sloop/engine/
├── __init__.py
├── strange_loop.py      # StrangeLoop engine

packages/soothe/tests/unit/core/loop/engine/
├── test_strange_loop_model_roles.py      # Tests for strange_loop.py
```

**Why**: 
- Easier to find and maintain tests
- Clear mapping between source and test files
- Supports modular development

### Test Naming Conventions

- Test files: `test_<module_name>.py`
- Test classes: `Test<FeatureName>`
- Test functions: `test_<scenario>_<expected_result>`

**Example**:
```python
# test_execute_node.py

class TestExecuteNode:
    def test_execute_with_valid_plan_returns_results(self):
        """Test Execute node with a valid plan."""
        pass
    
    def test_execute_with_empty_plan_returns_error(self):
        """Test Execute node with empty plan."""
        pass
    
    def test_execute_with_timeout_retries_correctly(self):
        """Test Execute node timeout retry behavior."""
        pass
```

---

## Test Configuration

### pytest Configuration

Each package has `pyproject.toml` with pytest settings:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
addopts = [
    "-v",
    "--tb=short",
    "--strict-markers",
    "--cov=src",
    "--cov-report=term-missing",
    "--cov-report=html",
]
markers = [
    "slow: marks tests as slow (deselect with '-m not slow')",
    "integration: marks tests as integration tests",
    "e2e: marks tests as end-to-end tests",
]
```

### Test Markers

Use markers to categorize tests:

```python
import pytest

@pytest.mark.unit
def test_unit_function():
    """Unit test."""
    pass

@pytest.mark.integration
def test_integration_backend():
    """Integration test requiring PostgreSQL."""
    pass

@pytest.mark.slow
def test_slow_benchmark():
    """Slow benchmark test."""
    pass

@pytest.mark.e2e
def test_e2e_workflow():
    """End-to-end workflow test."""
    pass
```

**Run tests by marker**:
```bash
# Run only unit tests
pytest -m unit

# Skip slow tests
pytest -m "not slow"

# Run integration tests only
pytest -m integration
```

---

## Writing Tests

### Test Structure

Follow **Google-style test structure**:

```python
def test_feature_scenario():
    """Brief description of what is being tested.
    
    Args: None (or describe test parameters)
    
    Returns: None (test functions don't return)
    
    Raises: AssertionError on failure
    """
    # Setup
    config = create_test_config()
    agent = create_test_agent(config)
    
    # Exercise
    result = agent.execute_goal("test goal")
    
    # Verify
    assert result.status == "completed"
    assert len(result.steps) == 3
    
    # Cleanup (if needed)
    cleanup_test_resources()
```

### Fixtures

Use pytest fixtures for reusable test components:

```python
# tests/conftest.py

import pytest
from soothe.config import SootheConfig

@pytest.fixture
def test_config():
    """Create a test configuration."""
    return SootheConfig(
        providers=[{
            "name": "test_provider",
            "provider_type": "openai",
            "api_key": "test-key",
            "models": ["gpt-4o-mini"]
        }],
        router={"default": "test_provider:gpt-4o-mini"}
    )

@pytest.fixture
def test_agent(test_config):
    """Create a test agent instance."""
    from soothe.foundation.core.agent import create_soothe_agent
    return create_soothe_agent(test_config)

@pytest.fixture
def mock_llm_response():
    """Mock LLM response for testing."""
    return {
        "content": "Test response",
        "tool_calls": []
    }
```

### Mocking

Use `unittest.mock` or `pytest-mock` for mocking:

```python
from unittest.mock import Mock, patch
import pytest

def test_with_mock_llm(mock_llm_response):
    """Test with mocked LLM."""
    with patch('soothe.foundation.core.agent.ChatOpenAI') as mock_chat:
        mock_chat.return_value.invoke.return_value = mock_llm_response
        
        # Test code here
        agent = create_test_agent()
        result = agent.invoke({"input": "test"})
        
        # Verify mock was called
        mock_chat.return_value.invoke.assert_called_once()

@pytest.mark.usefixtures("test_config")
def test_with_fixture():
    """Test using fixture."""
    # test_config is automatically injected
    pass
```

### Async Tests

Use `pytest-asyncio` for async tests:

```python
import pytest

@pytest.mark.asyncio
async def test_async_agent_execution():
    """Test async agent execution."""
    agent = await create_async_test_agent()
    result = await agent.execute_goal_async("async test")
    assert result.status == "completed"
```

---

## Test Coverage

### Coverage Targets

- **Unit tests**: 80%+ coverage for core modules
- **Integration tests**: 60%+ coverage for backends and protocols
- **Overall**: 75%+ coverage

### Run Coverage Report

```bash
# All packages with coverage
make test-coverage

# Single package
cd packages/soothe
uv run pytest --cov=src --cov-report=html tests/

# View HTML report
open htmlcov/index.html
```

### Coverage Configuration

Each package has `.coveragerc` or coverage settings in `pyproject.toml`:

```toml
[tool.coverage.run]
source = ["src"]
omit = [
    "tests/*",
    "*/__pycache__/*",
    "*/site-packages/*",
]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
]
```

---

## Running Tests

### Daily Development Workflow

```bash
# 1. Make code changes
vim packages/soothe/src/soothe/foundation/sloop/engine/strange_loop.py

# 2. Run relevant unit tests
cd packages/soothe
uv run pytest tests/unit/core/loop/engine/test_strange_loop_model_roles.py -v

# 3. Format and lint
make format
make lint

# 4. Run full verification before commit
./scripts/verify_finally.sh
```

### Pre-Commit Verification

**MANDATORY**: Run `./scripts/verify_finally.sh` before every commit:

```bash
./scripts/verify_finally.sh
```

This runs:
1. Workspace integrity check (`uv sync`)
2. Dependency validation
3. Code formatting check (`make format`)
4. Linting (`make lint`)
5. Unit tests (`make test-unit`)

**Options**:
```bash
# Auto-fix formatting and linting issues
./scripts/verify_finally.sh --fix

# Quick check (format + lint only, skip tests)
./scripts/verify_finally.sh --quick

# Dependency validation only
./scripts/verify_finally.sh --deps
```

### CI/CD Pipeline

Tests run in GitHub Actions:

```yaml
# .github/workflows/test.yml
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install uv
          uv sync --all-packages --all-extras
      - name: Run tests
        run: ./scripts/verify_finally.sh
```

---

## Test Best Practices

### 1. Test Isolation

Each test should be independent:

```python
# ❌ Bad: Shared state between tests
shared_state = {}

def test_1():
    shared_state['result'] = compute()

def test_2():
    # Depends on test_1 running first
    assert shared_state['result'] == expected
```

```python
# ✅ Good: Independent tests
def test_1():
    result = compute()
    assert result == expected

def test_2():
    result = compute()
    assert result == expected
```

### 2. Test Readability

Tests should be self-documenting:

```python
# ❌ Bad: Cryptic test
def test_agent():
    a = Agent()
    r = a.run("g")
    assert r.s == "c"
```

```python
# ✅ Good: Clear test
def test_agent_executes_goal_and_returns_completed_status():
    """Test that agent executes a goal and returns completed status."""
    agent = Agent()
    result = agent.execute_goal("test goal")
    assert result.status == "completed"
```

### 3. Edge Cases

Test edge cases and error conditions:

```python
def test_agent_handles_empty_goal():
    """Test agent handling of empty goal."""
    with pytest.raises(ValueError, match="Goal cannot be empty"):
        agent.execute_goal("")

def test_agent_handles_timeout():
    """Test agent timeout handling."""
    with pytest.raises(TimeoutError):
        agent.execute_goal_timeout("slow goal", timeout=1)

def test_agent_handles_invalid_config():
    """Test agent handling of invalid config."""
    with pytest.raises(ConfigError):
        create_agent(invalid_config)
```

### 4. Test Data

Use realistic test data:

```python
# ✅ Good: Realistic test data
@pytest.fixture
def realistic_goal():
    return {
        "input": "Analyze the Python files in /src and count lines of code",
        "context": {
            "workspace": "/tmp/test_workspace",
            "files": ["main.py", "utils.py"]
        }
    }

def test_with_realistic_data(realistic_goal):
    result = agent.execute_goal(realistic_goal)
    assert result.status == "completed"
```

---

## Debugging Failed Tests

### View Detailed Errors

```bash
# Verbose output
pytest -v tests/unit/core/loop/engine/test_strange_loop_model_roles.py

# Detailed traceback
pytest --tb=long tests/unit/core/loop/engine/test_strange_loop_model_roles.py

# Show local variables on failure
pytest --tb=long --showlocals tests/unit/core/loop/engine/test_strange_loop_model_roles.py
```

### Debug Mode

```python
# Add debug prints (remove before commit)
def test_debug():
    agent = create_agent()
    result = agent.execute_goal("test")
    print(f"Result: {result}")  # Debug output
    print(f"Steps: {result.steps}")  # Debug output
    assert result.status == "completed"
```

```bash
# Run with debug output visible
pytest -s tests/unit/core/test_debug.py
```

### Interactive Debugging

```bash
# Use pytest's pdb support
pytest --pdb tests/unit/core/test_failure.py

# Debug on first failure
pytest -x --pdb tests/unit/core/
```

---

## Performance Testing

### Benchmarks

Run performance benchmarks:

```bash
# Concurrent query benchmark
python scripts/benchmark_e2e_concurrent_queries.py

# TUI performance check
./scripts/tui_perf_check.sh
```

### Slow Test Management

```python
@pytest.mark.slow
def test_slow_operation():
    """Mark slow tests."""
    # Slow test code
    pass
```

```bash
# Skip slow tests during development
pytest -m "not slow"

# Run slow tests only in CI
pytest -m slow
```

---

## Testing Commands Summary

| Command | Purpose |
|---------|---------|
| `make test-unit` | Run all unit tests |
| `make test-integration` | Run integration tests |
| `make test-coverage` | Run tests with coverage report |
| `make test` | Run all tests |
| `./scripts/verify_finally.sh` | Full verification (format + lint + tests) |
| `./scripts/verify_finally.sh --fix` | Auto-fix issues |
| `./scripts/verify_finally.sh --quick` | Quick check (skip tests) |
| `pytest -v <test_file>` | Verbose test output |
| `pytest -m <marker>` | Run tests by marker |
| `pytest -k <pattern>` | Run tests matching pattern |

---

## See Also

- **[Contributing Guide](contributing-guide.md)** - Development workflow and code standards
- **[Configuration Guide](configuration-guide/index.md)** - Test configuration settings
- **[Architecture Overview](architecture/index.md)** - System architecture for test design
- **[RFC-000](../specs/RFC-000-system-conceptual-design.md)** - Conceptual design for test planning