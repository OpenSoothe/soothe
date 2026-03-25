# Soothe SDK Package Structure

This document describes the final polished structure of the soothe-sdk package.

## Package Layout

```
soothe-sdk-pkg/
├── .gitignore                    # Git ignore patterns
├── MIGRATION.md                  # Migration guide for standalone repo
├── README.md                     # Package overview and API reference
├── pyproject.toml                # Package configuration
├── src/
│   └── soothe_sdk/
│       ├── __init__.py          # Package initialization and public API
│       ├── decorators/          # Decorator implementations
│       │   ├── __init__.py
│       │   ├── plugin.py        # @plugin decorator
│       │   ├── subagent.py      # @subagent decorator
│       │   └── tool.py          # @tool and @tool_group decorators
│       ├── types/               # Type definitions
│       │   ├── __init__.py
│       │   ├── context.py       # PluginContext for lifecycle hooks
│       │   ├── health.py        # PluginHealth status
│       │   └── manifest.py      # PluginManifest metadata
│       ├── exceptions.py        # SDK-specific exceptions
│       └── depends.py           # Dependency utilities
└── tests/
    ├── conftest.py              # Shared test fixtures
    ├── test_decorators.py       # Decorator functionality tests
    ├── test_types.py            # Type definition tests
    └── test_integration.py      # Plugin lifecycle integration tests
```

## Key Features

### 1. Clean Package Structure
- No nested directories
- Proper `src/` layout following Python packaging best practices
- Tests colocated with package

### 2. Minimal Dependencies
- Only `pydantic>=2.0.0` for data validation
- Only `langchain-core>=1.2.0` for base types
- No runtime dependency on Soothe itself

### 3. Decorator-Based API
- Simple, declarative plugin definition
- Type-safe with Pydantic validation
- Clear separation of concerns

### 4. Comprehensive Testing
- Unit tests for all decorators
- Type validation tests
- Integration tests for plugin lifecycle

### 5. Documentation
- **README.md**: Quick start and full API reference
- **MIGRATION.md**: Standalone repository migration guide
- Inline docstrings with Google-style formatting

### 6. Build Configuration
- Proper `pyproject.toml` with all metadata
- Python 3.10-3.14 support
- Development dependencies
- Ruff configuration for code quality
- MyPy configuration for type checking

## Usage

### Installation

```bash
pip install soothe-sdk
```

### Development Installation

```bash
pip install -e ".[dev]"
```

### Running Tests

```bash
pytest tests/
```

### Type Checking

```bash
mypy src/soothe_sdk/
```

### Code Quality

```bash
ruff format src/ tests/
ruff check --fix src/ tests/
```

## API Components

### Decorators

1. **@plugin**: Define plugin metadata and class
   - Required: name, version, description
   - Optional: dependencies, trust_level

2. **@tool**: Define a tool function
   - Required: name, description
   - Automatically wrapped as langchain tool

3. **@tool_group**: Define a group of related tools
   - Required: name, description
   - Contains multiple @tool methods

4. **@subagent**: Define a subagent factory
   - Required: name, description
   - Optional: default model
   - Returns dict with name, description, runnable

### Types

1. **PluginManifest**: Plugin metadata
   - name, version, description
   - dependencies, trust_level
   - Semantic version validation

2. **PluginContext**: Lifecycle hook context
   - config: Plugin-specific configuration
   - soothe_config: Global Soothe configuration
   - logger: Plugin logger
   - emit_event: Event emission function

3. **PluginHealth**: Health check status
   - status: healthy, degraded, unhealthy
   - details: Optional error information

### Exceptions

1. **PluginError**: Base exception for all SDK errors
2. **DiscoveryError**: Plugin discovery failures
3. **ValidationError**: Metadata validation failures
4. **DependencyError**: Dependency resolution failures
5. **InitializationError**: Plugin initialization failures
6. **ToolCreationError**: Tool creation failures
7. **SubagentCreationError**: Subagent creation failures

## Extensibility Points

The SDK is designed to support:

1. **Plugin Discovery**: Entry points for automatic plugin loading
2. **Type Safety**: Full type hints for IDE support
3. **Validation**: Pydantic models for configuration validation
4. **Lifecycle Management**: Optional hooks for initialization and cleanup
5. **Health Monitoring**: Standardized health check interface

## Design Principles

1. **Lightweight**: Minimal dependencies for fast installation
2. **Type-safe**: Full type hints and Pydantic validation
3. **Decorator-based**: Simple, declarative plugin definition
4. **Runtime-agnostic**: No dependency on Soothe runtime
5. **Extensible**: Support for tools, subagents, and custom events

## Next Steps

This package is ready for:

1. **Testing**: Verify all tests pass
2. **Distribution**: Publish to PyPI
3. **Migration**: Move to standalone repository if desired
4. **Integration**: Use in Soothe plugin development

## Verification Checklist

- [x] Clean directory structure
- [x] Source files in `src/soothe_sdk/`
- [x] Comprehensive test suite
- [x] Python 3.10-3.14 support
- [x] Updated README with full API reference
- [x] Proper pyproject.toml configuration
- [x] MIGRATION.md for standalone repository
- [ ] Tests passing (requires pytest installation)
- [ ] Package installable with `pip install -e .`

## Success Metrics

The package structure is complete and ready for:

1. Independent development and testing
2. Publication to PyPI
3. Use as dependency for Soothe plugins
4. Migration to separate repository if desired