# Contributing to Soothe Community Plugins

Thank you for your interest in contributing to soothe-community! This guide will help you add new plugins, tools, and subagents.

## Table of Contents

- [Adding a New Plugin](#adding-a-new-plugin)
- [Plugin Structure](#plugin-structure)
- [Development Workflow](#development-workflow)
- [Testing Guidelines](#testing-guidelines)
- [Code Standards](#code-standards)

## Adding a New Plugin

### 1. Create Plugin Package

Create a new package in `src/soothe_community/your_plugin/`:

```
src/soothe_community/
├── __init__.py
├── paperscout/
│   └── ...
└── your_plugin/
    ├── __init__.py          # Plugin class with @plugin decorator
    ├── events.py            # Custom events (optional)
    ├── models.py            # Data models
    ├── state.py             # State definitions (if subagent)
    ├── implementation.py    # Core logic
    └── README.md            # Plugin documentation
```

### 2. Define Plugin Class

Create your plugin class in `__init__.py`:

```python
from soothe_sdk import plugin, subagent, tool

@plugin(
    name="your_plugin",
    version="1.0.0",
    description="Brief description of your plugin",
    dependencies=[
        "required-package>=1.0.0",
    ],
    trust_level="standard",  # or "trusted" for privileged plugins
)
class YourPlugin:
    """Your plugin implementation."""

    async def on_load(self, context):
        """Called when plugin is loaded.

        Args:
            context: Plugin context with config, logger, and utilities.
        """
        # Validate dependencies
        # Initialize resources
        context.logger.info("Your plugin loaded")

    @subagent(
        name="your_agent",
        description="What your agent does",
        model="openai:gpt-4o-mini",
    )
    async def create_subagent(self, model, config, context, **kwargs):
        """Create your subagent.

        Returns:
            Subagent dict with name, description, and runnable.
        """
        from .implementation import create_your_subagent

        return create_your_subagent(config=config, **kwargs)

    @tool(
        name="your_tool",
        description="What your tool does",
    )
    def your_tool(self, arg: str) -> str:
        """Your tool implementation."""
        return f"Result: {arg}"
```

### 3. Register Plugin

Add entry point to `pyproject.toml`:

```toml
[project.entry-points."soothe.plugins"]
your_plugin = "soothe_community.your_plugin:YourPlugin"
```

### 4. Add Dependencies

Add required packages to `dependencies` in `pyproject.toml`:

```toml
dependencies = [
    # ... existing dependencies ...
    "your-required-package>=1.0.0",
]
```

### 5. Create Tests

Create test suite in `tests/test_your_plugin/`:

```
tests/
├── conftest.py
├── test_paperscout/
│   └── ...
└── test_your_plugin/
    ├── conftest.py        # Plugin-specific fixtures
    ├── test_events.py     # Event tests
    ├── test_models.py     # Model tests
    ├── test_plugin.py     # Plugin lifecycle tests
    └── test_implementation.py  # Core logic tests
```

## Plugin Structure

### Subagent Plugins

For agent-based plugins:

```python
from langgraph.graph import StateGraph
from deepagents import CompiledSubAgent

def create_your_subagent(config, **kwargs) -> dict:
    """Create and return a compiled subagent.

    Returns:
        Dict with 'name', 'description', and 'runnable' (CompiledSubAgent).
    """
    # Define state
    # Create graph
    # Add nodes and edges
    # Compile subagent
    return {
        "name": "your_agent",
        "description": "What it does",
        "runnable": compiled_graph,
    }
```

### Tool Plugins

For simple tool-based plugins:

```python
from langchain_core.tools import tool

@tool
def your_tool(arg: str) -> str:
    """Tool description.

    Args:
        arg: Argument description.

    Returns:
        Result description.
    """
    # Tool implementation
    return result
```

## Development Workflow

### 1. Setup Development Environment

```bash
# Clone repository
git clone <soothe-community-repo>
cd soothe-community

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # or `source .venv/bin/activate.fish`

# Install in development mode
pip install -e ".[dev]"
```

### 2. Develop Your Plugin

```bash
# Create plugin package
mkdir -p src/soothe_community/your_plugin

# Implement plugin
# Add tests

# Run tests
pytest tests/test_your_plugin/

# Format code
ruff format src/soothe_community/your_plugin/

# Lint code
ruff check --fix src/soothe_community/your_plugin/
```

### 3. Test Integration

```bash
# Test with Soothe
pip install -e /path/to/soothe
soothe checkhealth

# Run your plugin
soothe run "test query" --subagent your_agent
```

## Testing Guidelines

### Test Structure

```python
# tests/test_your_plugin/test_plugin.py

import pytest
from soothe_community.your_plugin import YourPlugin

@pytest.fixture
def plugin():
    """Create plugin instance."""
    return YourPlugin()

@pytest.mark.asyncio
async def test_plugin_load(plugin, mock_soothe_config):
    """Test plugin can load."""
    context = MagicMock()
    context.logger = MagicMock()

    await plugin.on_load(context)

    # Verify initialization

def test_plugin_metadata(plugin):
    """Test plugin metadata."""
    assert plugin.name == "your_plugin"
    assert plugin.version == "1.0.0"
```

### Test Coverage

- **Unit tests**: Test individual functions and classes
- **Integration tests**: Test plugin with Soothe framework
- **Event tests**: Test custom event emission
- **Error handling**: Test error cases

## Code Standards

### Python Style

- **Python >=3.11**
- **Type hints** on all public functions
- **Google-style docstrings**
- **Ruff** for formatting and linting
- **Line length**: 120 characters

### Docstring Format

```python
def your_function(arg: str, optional: int = 0) -> dict:
    """Brief description.

    Args:
        arg: Description of arg.
        optional: Description of optional parameter.

    Returns:
        Description of return value.

    Raises:
        ValueError: When arg is invalid.
    """
    pass
```

### Event Registration

Register custom events in `events.py`:

```python
from soothe.core.event_catalog import register_event
from soothe.core.base_events import SootheEvent

class YourCustomEvent(SootheEvent):
    type: str = "soothe.community.your_plugin.custom"
    data: str

# Register at module load time
register_event(
    YourCustomEvent,
    summary_template="Custom event: {data}",
)
```

## Submitting Changes

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/your-plugin`)
3. **Commit** changes (`git commit -m "Add your_plugin"`)
4. **Push** to branch (`git push origin feature/your-plugin`)
5. **Open** a Pull Request

### PR Checklist

- [ ] Code follows style guidelines
- [ ] Tests added and passing
- [ ] Documentation updated
- [ ] Entry points registered
- [ ] Dependencies added to `pyproject.toml`

## Getting Help

- **Issues**: Open an issue on GitHub
- **Documentation**: See Soothe RFCs and implementation guides
- **Examples**: Check `paperscout/` for reference implementation

## License

By contributing, you agree that your contributions will be licensed under the MIT License.