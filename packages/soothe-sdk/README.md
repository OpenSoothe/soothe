# Soothe SDK

![PyPI - Version](https://img.shields.io/pypi/v/soothe-sdk?label=latest&logo=pypi&logoColor=white)

A lightweight, decorator-based SDK for building Soothe plugins and shared
contracts (events, wire codec, display/UX helpers, protocols).

The WebSocket transport client lives in
[`soothe-client-python`](https://github.com/mirasoth/soothe-client-python)
(`soothe_client`), not in this package.

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

        tools = [self.greet]
        agent = create_react_agent(model, tools)

        return {
            "name": "researcher",
            "description": "Research subagent",
            "runnable": agent,
        }
```

## Features

- **Decorator-based API**: `@plugin`, `@tool`, `@subagent` under `soothe_sdk.plugin`
- **Lightweight**: Only requires `pydantic` and `langchain-core`
- **Type-safe**: Full type hints and Pydantic validation
- **No runtime dependency**: SDK is separate from Soothe runtime
- **Contracts, not transport**: Wire codec under `soothe_sdk.wire`; paths under `soothe_sdk.paths`

## Canonical imports (1.0.0+)

Root package exports **version metadata only**. Import from subpackages:

```python
from soothe_sdk import __version__

from soothe_sdk.plugin import (
    plugin,
    tool,
    subagent,
    PluginManifest,
    PluginContext,
    PluginHealth,
    register_event,
    emit_progress,
)
from soothe_sdk.core.events import SootheEvent, OutputEvent
from soothe_sdk.core.exceptions import PluginError
from soothe_sdk.core.types import VerbosityLevel
from soothe_sdk.core.verbosity import VerbosityTier, should_show
from soothe_sdk.wire import messages_from_wire_dicts, ProtocolError
from soothe_sdk.paths import SOOTHE_HOME, SOOTHE_DATA_DIR
from soothe_sdk.ux.loop_stream import assistant_output_phase, LOOP_ASSISTANT_OUTPUT_PHASES
from soothe_sdk.tools.metadata import get_tool_meta, get_tool_display_name
from soothe_sdk.utils.formatting import format_cli_error, log_preview
from soothe_sdk.protocols import AsyncPersistStore, PolicyProtocol
```

### Removed in 1.0.0

| Removed | Use instead |
|---------|-------------|
| `soothe_sdk.client.*` | `soothe_sdk.wire` / `soothe_sdk.paths` (transport: `soothe_client`) |
| `soothe_sdk.langchain_wire` | `soothe_sdk.wire.codec` |
| Root re-exports (`plugin`, `SOOTHE_HOME`, …) | Subpackage imports above |
| `Manifest` / `Context` / `Health` / `Depends` | `PluginManifest` / `PluginContext` / `PluginHealth` / `library` |

## API Reference

### @plugin

```python
from soothe_sdk.plugin import plugin

@plugin(
    name="my-plugin",
    version="1.0.0",
    description="My plugin",
    dependencies=["arxiv>=2.0.0"],
    trust_level="standard",
)
class MyPlugin:
    pass
```

### @tool / @tool_group / @subagent

```python
from soothe_sdk.plugin import plugin, tool, tool_group, subagent

@plugin(name="research", version="1.0.0", description="Research tools")
class ResearchPlugin:
    @tool(name="my-tool", description="What this tool does")
    def my_tool(self, arg: str) -> str:
        return f"Result: {arg}"

    @tool_group(name="search", description="Search tools")
    class SearchTools:
        @tool(name="arxiv")
        def search_arxiv(self, query: str) -> list:
            pass

    @subagent(name="researcher", description="Research subagent", model="openai:gpt-4o-mini")
    async def create_researcher(self, model, config, context):
        return {"name": "researcher", "description": "…", "runnable": agent}
```

### PluginContext / PluginHealth

```python
from soothe_sdk.plugin import PluginContext, PluginHealth

class MyPlugin:
    async def on_load(self, context: PluginContext):
        self.api_key = context.config.get("api_key")
        context.logger.info("Plugin loaded")

    async def health_check(self) -> PluginHealth:
        return PluginHealth(status="healthy")
```

## Publishing Your Plugin

1. Create a Python package with your plugin class
2. Add the entry point in `pyproject.toml`:

```toml
[project.entry-points."soothe.plugins"]
my_plugin = "my_package:MyPlugin"
```

3. Publish to PyPI and install with `pip install my-plugin`

## Architecture

```
soothe_sdk/
├── __init__.py              # __version__ only
├── core/                    # Events, exceptions, verbosity
├── plugin/                  # Decorators + PluginManifest/Context/Health
├── wire/                    # Protocol-1 codec + encode/decode
├── paths.py                 # SOOTHE_HOME / SOOTHE_DATA_DIR
├── ux/                      # Loop stream, classification, subagent progress
├── display/                 # Card binder, transcript helpers
├── tools/                   # Tool display metadata
├── protocols/               # PersistStore, VectorStore, Policy
└── utils/                   # Formatting, logging, parsing, serde
```

## Development

```bash
pip install -e ".[dev]"
pytest tests/
ruff check src/soothe_sdk/
ruff format src/soothe_sdk/
```

## License

MIT License — see [LICENSE](LICENSE) for details.

## Links

- [Soothe Documentation](https://soothe.readthedocs.io)
- [GitHub Repository](https://github.com/mirasoth/soothe)
