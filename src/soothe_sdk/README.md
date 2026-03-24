# Soothe SDK

A lightweight, decorator-based SDK for building Soothe plugins.

## Installation

```bash
pip install soothe-sdk
```

## Quick Start

```python
from soothe_sdk import plugin, tool, subagent

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
        from soothe_sdk.types import PluginHealth
        return PluginHealth(status="healthy")
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
pip install soothe-sdk[dev]

# Run tests
pytest tests/

# Type checking
mypy src/soothe_sdk/

# Linting
ruff check src/soothe_sdk/
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Links

- [Soothe Documentation](https://soothe.readthedocs.io)
- [Plugin Development Guide](https://soothe.readthedocs.io/plugins/)
- [GitHub Repository](https://github.com/example/soothe)