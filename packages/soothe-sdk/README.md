# Soothe SDK

A lightweight, decorator-based SDK for building Soothe plugins.

## Installation

```bash
pip install soothe-sdk
```

## Quick Start

```python
from soothe_sdk.plugin import plugin, tool, subagent

@plugin(
    name="my-plugin",
    version="1.0.0",
    description="My awesome plugin",
    dependencies=["langchain>=0.1.0"],
)
class MyPlugin:
    """My custom plugin with tools and subagents."""

    @tool(name="greet", description="Greet someone by name")
    def greet(self, name: str) -> str:
        """Greet a person."""
        return f"Hello, {name}!"

    @subagent(
        name="researcher",
        description="Research subagent with web search",
        model="openai:gpt-4o-mini",
    )
    async def create_researcher(self, model, config, context):
        """Create research subagent."""
        from langgraph.prebuilt import create_react_agent

        # Get tools
        tools = [self.greet]

        # Create agent
        agent = create_react_agent(model, tools)

        return {
            "name": "researcher",
            "description": "Research subagent",
            "runnable": agent,
        }
```

## Features

- **Decorator-based API**: Simple `@plugin`, `@tool`, `@subagent` decorators
- **Lightweight**: Only requires `pydantic` and `langchain-core`
- **Type-safe**: Full type hints and Pydantic validation
- **No runtime dependency**: SDK is separate from Soothe runtime

## API Reference

### @plugin

Defines a Soothe plugin with metadata.

```python
@plugin(
    name="my-plugin",           # Required: unique identifier
    version="1.0.0",           # Required: semantic version
    description="My plugin",   # Required: description
    dependencies=["arxiv>=2.0.0"],  # Optional: library dependencies
    trust_level="standard",    # Optional: built-in, trusted, standard, untrusted
)
class MyPlugin:
    pass
```

### @tool

Defines a tool that can be used by the agent.

```python
@tool(name="my-tool", description="What this tool does")
def my_tool(self, arg: str) -> str:
    return f"Result: {arg}"
```

### @tool_group

Organizes multiple related tools.

```python
@tool_group(name="research", description="Research tools")
class ResearchTools:
    @tool(name="arxiv")
    def search_arxiv(self, query: str) -> list:
        pass

    @tool(name="scholar")
    def search_scholar(self, query: str) -> list:
        pass
```

### @subagent

Defines a subagent factory.

```python
@subagent(
    name="researcher",
    description="Research subagent",
    model="openai:gpt-4o-mini",  # Optional default model
)
async def create_researcher(self, model, config, context):
    # Create and return subagent
    return {
        "name": "researcher",
        "description": "Research subagent",
        "runnable": agent,
    }
```

### PluginContext

Provides access to Soothe internals in lifecycle hooks.

```python
class MyPlugin:
    async def on_load(self, context: PluginContext):
        # Plugin-specific config
        self.api_key = context.config.get("api_key")

        # Global Soothe config
        self.model = context.soothe_config.resolve_model("default")

        # Logging
        context.logger.info("Plugin loaded")

        # Events
        context.emit_event("plugin.loaded", {"name": "my-plugin"})
```

## Plugin Lifecycle

Plugins can implement optional lifecycle hooks:

```python
class MyPlugin:
    async def on_load(self, context: PluginContext):
        """Called when plugin is loaded. Initialize resources."""
        pass

    async def on_unload(self):
        """Called when plugin is unloaded. Clean up resources."""
        pass

    async def health_check(self):
        """Return plugin health status."""
        from soothe_sdk.plugin import Health
        return Health(status="healthy")
```

## Publishing Your Plugin

1. Create a Python package with your plugin class
2. Add the entry point in `pyproject.toml`:

```toml
[project.entry-points."soothe.plugins"]
my_plugin = "my_package:MyPlugin"
```

3. Publish to PyPI:

```bash
pip install build
python -m build
twine upload dist/*
```

4. Users can install and use your plugin:

```bash
pip install my-plugin
```

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/

# Type checking
mypy src/soothe_sdk/

# Linting
ruff check src/soothe_sdk/

# Formatting
ruff format src/soothe_sdk/
```

## Architecture

The SDK provides decorator-based APIs for defining plugins (v0.4.0 structure):

```
soothe_sdk/
├── __init__.py           # Minimal (version only)
├── events.py             # Core concept at root
├── exceptions.py         # Core concept at root
├── verbosity.py          # Core concept at root
├── protocols/            # Protocol definitions (stable interfaces)
├── client/               # Client utilities (WebSocket + config)
│   ├── protocol.py       # WebSocketClientProtocol
│   ├── websocket_client.py
│   └── config.py         # Config constants + types (merged)
├── plugin/               # Plugin API (decorators + types)
│   ├── decorators.py     # @plugin, @tool, @tool_group, @subagent (merged)
│   ├── manifest.py       # PluginManifest (Manifest alias)
│   ├── context.py        # PluginContext (Context alias)
│   ├── health.py         # PluginHealth (Health alias)
│   ├── registry.py       # register_event() API
│   └── emit.py           # emit_progress(), set_stream_writer()
├── ux/                   # UX/display helpers
│   ├── classification.py # classify_event_to_tier
│   └── internal.py       # Internal content filtering
├── utils/                # Shared utilities
│   ├── logging.py
│   ├── display.py
│   ├── parsing.py
│   └── workspace.py
└── types/                # Deprecated (empty)
```

**Import Pattern** (v0.4.0):
```python
# Core concepts - import from root
from soothe_sdk import __version__
from soothe_sdk.events import SootheEvent, OutputEvent
from soothe_sdk.exceptions import SootheSDKError
from soothe_sdk.verbosity import VerbosityLevel, VerbosityTier

# Purpose packages - import from subpackage
from soothe_sdk.plugin import plugin, tool, subagent, register_event
from soothe_sdk.client import WebSocketClient, VerbosityLevel
from soothe_sdk.ux import classify_event_to_tier
from soothe_sdk.utils import format_cli_error, setup_logging
```

## Key Design Principles

1. **Lightweight**: Minimal dependencies (only `pydantic` and `langchain-core`)
2. **Type-safe**: Full type hints and Pydantic validation
3. **Decorator-based**: Simple, declarative plugin definition
4. **Runtime-agnostic**: No dependency on Soothe runtime
5. **Extensible**: Support for tools, subagents, and custom events

## License

MIT License - see [LICENSE](LICENSE) for details.

## Links

- [Soothe Documentation](https://soothe.readthedocs.io)
- [Plugin Development Guide](https://soothe.readthedocs.io/plugins/)
- [GitHub Repository](https://github.com/caesar0301/soothe)