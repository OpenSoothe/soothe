# Soothe Test Suite

This directory contains workspace-level integration tests for the Soothe project.

## Test Structure

```text
tests/integration/                          # Workspace integration tests (daemon + tools + transports)
packages/soothe/tests/unit/                 # Daemon package unit tests (fast, isolated)
packages/soothe/tests/unit/plugin/          # Plugin system unit tests
packages/soothe/tests/unit/core/runner/     # Runner bridge tests (GoalEngine → AgentLoop)
packages/soothe-cli/tests/unit/             # CLI package unit tests
packages/soothe-sdk/tests/                  # SDK package tests (unit + integration)
packages/soothe-community/tests/integration/ # Community plugin integration tests
```

Unit-level tests have been moved into their respective packages. Integration tests remain here because they test workspace-level functionality requiring a running daemon and external services.

## Running Tests

### Unit Tests (daemon package)

Run all unit tests:

```bash
cd packages/soothe
uv run pytest tests/unit/
```

Run a specific test file:

```bash
cd packages/soothe
uv run pytest tests/unit/backends/persistence/test_persistence.py
```

Run with coverage:

```bash
cd packages/soothe
uv run pytest tests/unit/ --cov=soothe --cov-report=html
```

### Integration Tests

Integration tests require external services (PostgreSQL, Weaviate, etc.) and are skipped by default.

Run integration tests:

```bash
# Run all integration tests
pytest tests/integration/ --run-integration

# Run specific integration test file
pytest tests/integration/test_daemon_multi_client.py --run-integration

# Run RFC-400 E2E tests
pytest tests/integration/test_rfc0013_e2e.py --run-integration

# Run slow tests (stress tests)
pytest tests/integration/test_rfc0013_e2e.py --run-integration -m slow
```

## Test Coverage

The test suite covers the following modules:

### Unit Tests (61 files, ~900 tests)

**Core Framework:**
- Configuration (`test_config.py`)
- Context Protocol (`test_context.py`)
- Memory Protocol (`test_memory_memu.py`)
- Durability Protocol (`test_durability.py`)
- Persistence Layer (`test_persistence.py`)
- Planning Protocol (`test_planning.py`, `test_auto_planner.py`, `test_shared_planning.py`)
- Policy Protocol (`test_policy.py`)
- Vector Stores (`test_vector_store.py`)

**Daemon & Protocol:**
- Event Bus (`test_event_bus.py`)
- Client Session Management (`test_client_session.py`)
- Protocol v2 (`test_protocol_v2.py`)
- Transport Abstraction (`test_transport_abstraction.py`)
- Daemon CLI (`test_cli_daemon.py`)

**Agent Runtime:**
- Subagents (`test_subagents.py`)
- Tools (`test_tools.py`, `test_consolidated_tools.py`)
- Goal Engine (`test_goal_engine.py`, `test_goal_tools.py`, `test_dynamic_goals.py`)
- Concurrency (`test_concurrency_controller.py`)
- Step Scheduler (`test_step_scheduler.py`)
- Thread Management (`test_thread_manager.py`, `test_thread_deletion.py`)

**CLI & TUI:**
- CLI Commands (`test_cli_commands_autonomous.py`, `test_init_command.py`)
- TUI App (`test_cli_tui_app.py`)
- Health State (`test_cli_health_state.py`)
- Session Management (`test_cli_session.py`)

**Tools:**
- Code Edit (`test_tools_code_edit.py`)
- File Edit (`test_tools_file_edit.py`)
- Document Tools (`test_tools_document.py`)
- Audio Tools (`test_tools_audio.py`)
- Video Tools (`test_tools_video.py`)
- CLI Tools (`test_tools_cli.py`)

**Middleware:**
- System Prompt Optimization (`middleware/test_system_prompt_optimization.py`)

**SDK:**
- Plugin System (`test_sdk_basic.py`, `test_sdk_comprehensive.py`)
- Tool Error Handler (`test_tool_error_handler.py`)

**Other:**
- Artifact Store (`test_artifact_store.py`)
- Browser Runtime (`test_browser_runtime.py`, `test_browser_subagent_integration.py`)
- Inquiry Engine (`test_inquiry.py`)
- Logging (`test_logging_setup.py`)
- Progress Rendering (`test_progress_rendering.py`, `test_progress_verbosity.py`)
- Token Counting (`test_token_counting.py`)
- URL Validation (`test_url_validation.py`)

### Integration Tests (24 files, ~210 tests)

**Daemon Protocol (RFC-400):**
- Multi-Client Isolation (`test_daemon_multi_client.py`)
- Event Protocol (`test_daemon_event_protocol.py`)
- Multi-Transport (`test_daemon_multi_transport.py`)
- Unix Socket (`test_daemon_domainsocket_protocol.py`)
- WebSocket (`test_daemon_websocket_protocol.py`)
- HTTP REST (`test_daemon_http_protocol.py`)
- Thread Recovery (`test_daemon_thread_recovery.py`)
- Security (`test_daemon_security.py`)
- Error Handling (`test_daemon_error_handling.py`)
- **Comprehensive E2E** (`test_rfc0013_e2e.py` - 18 tests)

**Tool Integration:**
- Code Edit Tools (`test_code_edit_tools.py`)
- Data Tools (`test_data_tools.py`)
- Execution Tools (`test_execution_tools.py`)
- File Operations (`test_file_ops_tools.py`)
- HTTP REST Transport (`test_http_rest_transport.py`)
- Multi-Transport (`test_multi_transport.py`)
- Multimedia Tools (`test_multimedia_tools.py`)
- Performance (`test_performance.py`)
- Python Session (`test_python_session_integration.py`)
- System Prompt Optimization (`test_system_prompt_optimization.py`)
- Vector Store (`test_vector_store_integration.py`)
- Web Tools (`test_web_tools.py`)

## Test Dependencies

Test dependencies are defined in `pyproject.toml`:

```toml
[dependency-groups.test]
dependencies = [
    "pytest>=8.0.0",
    "pytest-asyncio>=1.3.0",
    "pytest-cov",
    "ruff>=0.12.0",
]
```

Install test dependencies:

```bash
pip install -e ".[test]"
```

Or using uv:

```bash
uv sync --group test
```

## Optional Dependencies

Some tests require optional dependencies:

- **pgvector**: `pip install soothe[pgvector]`
- **weaviate**: `pip install soothe[weaviate]`
- **rocksdb**: `pip install soothe[rocksdb]`
- **research**: `pip install soothe[research]`
- **websearch**: `pip install soothe[websearch]`

Tests will be skipped automatically if dependencies are not installed.

## Integration Test Setup

### PostgreSQL/pgvector

1. Install PostgreSQL with pgvector extension
2. Create a test database:
   ```sql
   CREATE DATABASE soothe_test;
   CREATE EXTENSION vector;
   ```
3. Set up connection string in test fixtures

### Weaviate

1. Run Weaviate locally:
   ```bash
   docker run -d \
     -p 8080:8080 \
     -p 50051:50051 \
     semitechnologies/weaviate:latest
   ```

## Test Patterns

### Async Tests

All async tests use `pytest.mark.asyncio`:

```python
@pytest.mark.asyncio
async def test_async_operation():
    result = await some_async_function()
    assert result is not None
```

### Fixtures

Common fixtures are defined in test files:

```python
@pytest.fixture
def mock_vector_store():
    store = AsyncMock()
    store.search = AsyncMock(return_value=[])
    return store
```

### Integration Test Markers

Integration tests are marked with `@pytest.mark.integration`:

```python
@pytest.mark.integration
class TestPGVectorStoreIntegration:
    async def test_create_collection(self):
        # ...
```

### Slow Test Markers

Slow-running tests (stress tests, performance benchmarks) are marked with `@pytest.mark.slow`:

```python
@pytest.mark.integration
@pytest.mark.slow
async def test_event_throughput_stress():
    # ...
```

## Test Documentation

- **RFC-400 Test Coverage**: `docs/testing/rfc0013_test_coverage.md`
  - Complete mapping of RFC-400 requirements to tests
  - 88 total tests for daemon protocol
  - Breaking changes validation matrix

## Continuous Integration

Tests are designed to run in CI/CD pipelines:

- **Unit tests**: Run on every push
- **Integration tests**: Run on schedule or manual trigger
- **Coverage reports**: Generated automatically

## Best Practices

1. **Unit Tests**: Test isolated units with mocked dependencies
2. **Integration Tests**: Test real interactions with external services
3. **Fixtures**: Use fixtures for common setup
4. **Async**: Use pytest-asyncio for async tests
5. **Cleanup**: Ensure proper cleanup in integration tests
6. **Markers**: Use appropriate markers (`@pytest.mark.integration`, `@pytest.mark.slow`)
7. **Naming**: Follow `test_<module>_<scenario>_<expected_result>` pattern

## Test Statistics

| Category | Files | Tests | Purpose |
|----------|-------|-------|---------|
| Unit Tests | 61 | ~900 | Fast, isolated component tests |
| Integration Tests | 24 | ~210 | End-to-end daemon and tool tests |
| **Total** | **85** | **~1110** | **Comprehensive coverage** |

## References

- RFC-400: Unified Daemon Communication Protocol
- RFC-401: Event Protocol Specification
- Test patterns inspired by the noesium project's test suite