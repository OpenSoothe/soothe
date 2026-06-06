# Create SubAgent Skill

Create new subagent plugins for the Soothe community ecosystem.

## Overview

This skill guides you through creating a new subagent plugin that integrates with Soothe's orchestration framework. It covers the agent paradigm, interface standards, and best practices.

## Agent Paradigm Summary

Soothe subagents follow a **LangGraph-based CompiledSubAgent** pattern:

```
┌─────────────────────────────────────────────────────────┐
│  Plugin Layer (@plugin)                                 │
│  - Metadata: name, version, description, dependencies   │
│  - Lifecycle: on_load() → verify deps, register events  │
│  - Factory: @subagent → create CompiledSubAgent         │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Subagent Factory (async)                               │
│  - Receives: model, config, context                     │
│  - Returns: CompiledSubAgent dict                       │
│    {                                                    │
│      "name": "subagent_name",                           │
│      "description": "Agent description...",             │
│      "runnable": CompiledStateGraph  # MUST have .with_config() │
│    }                                                    │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Implementation Layer (LangGraph)                       │
│  - StateGraph with TypedDict state schema               │
│  - Nodes: async/sync functions that update state        │
│  - Edges: START → node → ... → END                      │
│  - Compile: graph.compile() → Runnable                  │
└─────────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────┐
│  Events Layer (optional)                                │
│  - SootheEvent subclasses for progress/status           │
│  - Registered via register_event()                      │
│  - Wire events: soothe.subagent.<name>.*                │
└─────────────────────────────────────────────────────────┘
```

## Interface Standards (CRITICAL)

### 1. CompiledSubAgent Return Format

**The factory MUST return a dict with exactly these keys:**

```python
return {
    "name": "your_subagent_name",           # str: matches @subagent name
    "description": "Agent description...",  # str: shown in task tool UI
    "runnable": compiled_graph,             # CompiledStateGraph (NOT a dict!)
}
```

**CRITICAL: `runnable` must be a Runnable object, NOT a nested dict!**

The `runnable` field must have `.with_config()` method. If you wrap an existing
factory that already returns CompiledSubAgent, **return it directly**, don't wrap:

```python
# WRONG - causes AttributeError: 'dict' object has no attribute 'with_config'
runnable = _create_subagent(...)  # Already returns CompiledSubAgent dict
return {"name": "x", "description": "...", "runnable": runnable}  # runnable is a dict!

# CORRECT - return factory result directly
return _create_subagent(...)  # Already has correct format
```

### 2. Plugin Decorator Requirements

```python
@plugin(
    name="your_plugin",          # Unique identifier
    version="1.0.0",             # Semver
    description="What it does",
    dependencies=["langgraph>=0.2.0"],  # Required packages
    trust_level="standard",      # built-in | trusted | standard | untrusted
)
class YourPlugin:
    async def on_load(self, context: Any) -> None:
        # Verify dependencies, register events
        context.logger.info("Plugin loaded")
```

### 3. Subagent Decorator Requirements

```python
@subagent(
    name="your_subagent",               # Unique identifier (matches factory return)
    description="Detailed description for task tool selection",
    model="openai:gpt-4o-mini",         # Default model role or provider:model
    system_context="<RULES>...</RULES>", # Optional system context injection
    triggers=["RULES", "context"],      # Optional trigger keywords
)
async def create_subagent(
    self,
    model: Any,      # Resolved BaseChatModel or str
    config: Any,     # SootheConfig instance
    context: Any,    # PluginContext with work_dir, logger, soothe_config
    **kwargs: Any,   # Additional config from YAML
) -> CompiledSubAgent:
    ...
```

### 4. LangGraph Implementation Pattern

```python
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing import Annotated, TypedDict

class YourState(TypedDict):
    """State schema for the subagent graph."""
    messages: Annotated[list[Any], add_messages]
    # Add other state fields...

def _build_your_graph(model: BaseChatModel, config: Any) -> Any:
    """Build and compile the LangGraph."""

    async def your_node(state: dict[str, Any]) -> dict[str, Any]:
        # Process state, invoke model, return updates
        return {"messages": [AIMessage(content="Result")]}

    graph = StateGraph(YourState)
    graph.add_node("your_node", your_node)
    graph.add_edge(START, "your_node")
    graph.add_edge("your_node", END)
    return graph.compile()  # Returns CompiledStateGraph with .with_config()
```

### 5. Event Registration (Optional)

```python
from soothe_sdk.plugin.registry import register_event  # SDK only, no soothe dependency
from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.verbosity import VerbosityTier
from typing import Literal

SUBAGENT_YOUR_STARTED = "soothe.subagent.your.started"

class YourStartedEvent(SootheEvent):
    type: Literal["soothe.subagent.your.started"] = SUBAGENT_YOUR_STARTED
    task_preview: str = ""

register_event(
    YourStartedEvent,
    verbosity=VerbosityTier.NORMAL,
    summary_template="Your subagent started: {task_preview}",
)
```

### 6. Wire Event Emission (Progress Updates)

```python
from soothe_sdk.core.subagent_wire import emit_subagent_wire_event

emit_subagent_wire_event(
    YourStartedEvent(task_preview=str(task)[:200]).to_dict(),
    logger,
)
```

## Package Structure

```
src/soothe_plugins/your_subagent/
├── __init__.py            # Plugin class with @plugin and @subagent
├── implementation.py      # Factory + LangGraph builder
├── events.py              # SootheEvent subclasses (optional)
├── state.py               # TypedDict state schema (optional)
├── config_model.py        # Configuration model (optional)
├── nodes.py               # Node implementations (optional)
└── display_summary.py     # One-line summary formatter (optional)
```

## Dependency Requirements (CRITICAL)

**Community plugins MUST only depend on `soothe-sdk`, NOT `soothe`.**

### Required Dependencies

```toml
dependencies = [
    "soothe-sdk>=0.5.10,<1.0.0",  # Plugin decorators, events, protocols
    "langgraph>=0.2.0",           # LangGraph for subagent graphs
    # ... other package-specific deps
]
```

### Optional soothe Imports

If your plugin needs utilities from `soothe` daemon (runtime directories, workspace, etc),
use **lazy imports with try-except** so the plugin works without soothe daemon:

```python
# WRONG - breaks standalone usage
from soothe.utils.runtime import get_browser_runtime_dir

# CORRECT - optional with fallback
try:
    from soothe.utils.runtime import get_browser_runtime_dir
except ImportError:
    # Use local fallback
    def get_browser_runtime_dir():
        return Path.home() / ".soothe" / "agents" / "browser"
```

### SDK-only Imports (Always Available)

These imports work without soothe daemon:
- `soothe_sdk.plugin`: `@plugin`, `@subagent`, `@tool`
- `soothe_sdk.core.events`: `SootheEvent`
- `soothe_sdk.core.subagent_wire`: `emit_subagent_wire_event`
- `soothe_sdk.core.verbosity`: `VerbosityTier`
- `soothe_sdk.protocols`: `ActionRequest`, `PermissionSet`, etc.
- `soothe_sdk.utils.formatting`: `format_cli_error`

## Entry Point Registration

Add to `pyproject.toml`:

```toml
[project.entry-points."soothe.plugins"]
your_subagent = "soothe_plugins.your_subagent:YourPlugin"
```

## Testing Checklist

1. Factory returns `CompiledSubAgent` dict (not nested)
2. `runnable` has `.with_config()` method (is CompiledStateGraph)
3. `name` matches `@subagent(name=...)`
4. Plugin loads via `load_plugins(config)`
5. Subagent resolves in `resolve_subagents(config)`
6. Events emit correctly (if defined)

## Example: Minimal Echo Subagent

```python
# __init__.py
from soothe_sdk.plugin import plugin, subagent
from typing import Any
from .implementation import create_echo_subagent

@plugin(name="echo", version="1.0.0", description="Echo subagent")
class EchoPlugin:
    async def on_load(self, context: Any) -> None:
        context.logger.info("Echo plugin loaded")

    @subagent(name="echo", description="Echoes user messages")
    async def create_echo(self, model: Any, config: Any, context: Any) -> dict:
        return create_echo_subagent()

# implementation.py
from langgraph.graph import END, START, StateGraph
from langchain_core.messages import AIMessage
from typing import Annotated, Any, TypedDict
from langgraph.graph.message import add_messages

class EchoState(TypedDict):
    messages: Annotated[list[Any], add_messages]

def create_echo_subagent() -> dict[str, Any]:
    def echo_node(state: dict[str, Any]) -> dict[str, Any]:
        messages = state.get("messages", [])
        last = messages[-1].content if messages else ""
        return {"messages": [AIMessage(content=f"Echo: {last}")]}

    graph = StateGraph(EchoState)
    graph.add_node("echo", echo_node)
    graph.add_edge(START, "echo")
    graph.add_edge("echo", END)

    return {
        "name": "echo",
        "description": "Echoes user messages",
        "runnable": graph.compile(),  # CompiledStateGraph, NOT a dict!
    }
```

## Common Pitfalls

1. **Nested dicts**: Don't wrap factory results in another dict
2. **Missing .with_config()**: Ensure `runnable` is a compiled graph
3. **Name mismatch**: Factory `name` must match `@subagent(name=...)`
4. **Async handling**: Plugin factories are async; built-ins are sync
5. **Event wire format**: Use `emit_subagent_wire_event()` for daemon visibility

## Usage

Invoke this skill when:
- Creating a new community subagent
- Understanding subagent interface requirements
- Debugging `AttributeError: 'dict' object has no attribute 'with_config'`
- Reviewing existing subagent implementations