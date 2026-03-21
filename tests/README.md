# Soothe Test Suite

This directory contains comprehensive unit tests and integration tests for the Soothe multi-agent framework.

## Test Structure

```
tests/
├── unit_tests/           # Unit tests (fast, no external dependencies)
│   ├── test_config.py
│   ├── test_context.py
│   ├── test_durability.py
│   ├── test_memory_store.py
│   ├── test_persistence.py
│   ├── test_planning.py
│   ├── test_policy.py
│   ├── test_subagents.py
│   ├── test_tools.py
│   └── test_vector_store.py
└── integration_tests/    # Integration tests (require external services)
    ├── conftest.py
    ├── test_tool_integration_real_llm.py
    ├── test_vector_store_integration.py
    ├── test_performance.py
    ├── test_tools_integration.py
    ├── test_system_prompt_optimization_integration.py
    └── test_python_session_integration.py
```

## Running Tests

### Unit Tests

Run all unit tests:

```bash
pytest tests/unit_tests/
```

Run a specific test file:

```bash
pytest tests/unit_tests/test_persistence.py
```

Run with coverage:

```bash
pytest tests/unit_tests/ --cov=soothe --cov-report=html
```

### Integration Tests

Integration tests require external services (PostgreSQL, Weaviate, etc.) and are skipped by default.

Run integration tests:

```bash
pytest tests/integration_tests/ --run-integration
```

## Test Coverage

The test suite covers the following modules:

### Unit Tests

1. **Persistence Layer** (`test_persistence.py`)
   - JsonPersistStore: save/load/delete operations, error handling
   - RocksDBPersistStore: database operations (when rocksdict is installed)
   - create_persist_store factory function

2. **Context Implementations** (`test_context.py`)
   - KeywordContext: ingest, project, summarize, persist/restore
   - VectorContext: embedding-based operations (with mocked dependencies)

3. **Vector Stores** (`test_vector_store.py`)
   - PGVectorStore: interface compliance, initialization, method signatures
   - WeaviateVectorStore: interface compliance, UUID generation
   - create_vector_store factory function

4. **Memory Stores** (`test_memory_memu.py`)
   - MemUMemory: remember, recall, recall_by_tags, forget, update operations
   - Integration with MemU MemoryService (with mocked dependencies)
   - Importance score computation from reinforcement tracking

5. **Durability** (`test_durability.py`)
   - InMemoryDurability: thread lifecycle, state persistence

6. **Planning** (`test_planning.py`)
   - SimplePlanner: plan creation, revision, reflection

7. **Policy** (`test_policy.py`)
   - ConfigDrivenPolicy: permission checking, profile management
   - Permission and PermissionSet classes
   - Standard, readonly, and privileged profiles

8. **Existing Tests**
   - Configuration (`test_config.py`)
   - Subagents (`test_subagents.py`)
   - Tools (`test_tools.py`)

### Integration Tests

1. **Vector Store Integration** (`test_vector_store_integration.py`)
   - PGVectorStore: CRUD operations with real PostgreSQL database
   - WeaviateVectorStore: CRUD operations with real Weaviate instance
   - Search functionality, filtering, batch operations

2. **Tool Integration with Real LLM** (`test_tool_integration_real_llm.py`)
   - Tool execution with real language model API calls
   - End-to-end tool usage workflows

3. **Performance Tests** (`test_performance.py`)
   - Query latency benchmarks with real LLM API calls
   - Complexity classification performance
   - Template planning and conditional execution

4. **Tools Integration** (`test_tools_integration.py`)
   - Real shell command execution (requires pexpect)
   - Real Python execution with IPython
   - Audio/video tool integration (requires API keys)

5. **System Prompt Optimization Integration** (`test_system_prompt_optimization_integration.py`)
   - End-to-end prompt optimization with real LLM instances
   - Middleware registration and configuration

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

## Continuous Integration

Tests are designed to run in CI/CD pipelines:

- Unit tests run on every push
- Integration tests run on schedule or manual trigger
- Coverage reports are generated automatically

## Best Practices

1. **Unit Tests**: Test isolated units with mocked dependencies
2. **Integration Tests**: Test real interactions with external services
3. **Fixtures**: Use fixtures for common setup
4. **Async**: Use pytest-asyncio for async tests
5. **Cleanup**: Ensure proper cleanup in integration tests

## References

Test patterns are inspired by the noesium project's test suite:
- `thirdparty/noesium/noesium/tests/vector_store/test_pgvector_store.py`