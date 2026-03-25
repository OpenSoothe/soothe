# Module Self-Containment and Plugin Performance Optimization

> Implementation guide for refactoring subagents, tools, and plugins to achieve module self-containment and performance optimization.
>
> **Module**: `src/soothe/subagents/`, `src/soothe/tools/`, `src/soothe/plugin/`
> **Source**: Architecture refactoring initiative
> **Related**: RFC-0001 (System Conceptual Design), RFC-0013 (Daemon Communication Protocol)

---

## 1. Overview

This implementation guide defines the concrete architecture for refactoring Soothe's subagent, tool, and plugin modules to achieve:

1. **Module Self-Containment**: Each module contains its own events, plugin shim, and implementation
2. **Performance Optimization**: Parallel plugin loading, caching, and lazy loading support
3. **Simplified Architecture**: Elimination of redundant plugin directory and centralized event catalog

### Problem Statement

**Current Issues**:
- Events centralized in `core/event_catalog.py` (1087 lines) violate module self-containment
- Plugin shims in `src/soothe/plugins/` are thin wrappers that add no value
- Sequential plugin loading (line 73 in `lifecycle.py`) creates startup bottleneck
- No caching or lazy loading wastes resources on repeated agent creation

**Impact**:
- Hard to maintain: changes require touching multiple directories
- Slow startup: ~500ms for plugin loading, ~2-3s for agent creation
- Poor developer experience: understanding a module requires looking in 3+ locations

### Solution Overview

**Four-Phase Refactoring**:
1. **Event Migration**: Move events from central catalog into respective modules
2. **Plugin Consolidation**: Integrate plugin shims into modules, delete `plugins/` directory
3. **Performance Optimization**: Implement parallel loading, caching, lazy loading
4. **Module Structure**: Convert single-file modules to packages for consistency

---

## 2. Architectural Position

### Current Architecture

```
src/soothe/
├── core/
│   ├── event_catalog.py          # Central event definitions (ALL events)
│   └── events.py                  # Event type constants
├── subagents/
│   ├── browser.py                 # Implementation only
│   ├── claude.py                  # Implementation only
│   └── skillify/                  # Module with implementation only
├── tools/
│   ├── execution.py               # Implementation only
│   └── ...                        # Other tool implementations
├── plugin/
│   ├── lifecycle.py               # Sequential plugin loading
│   └── ...
└── plugins/                       # Redundant plugin shims
    ├── browser/
    ├── execution/
    └── ...
```

### Target Architecture

```
src/soothe/
├── core/
│   └── events.py                  # Event type constants only (reference)
├── subagents/
│   ├── browser/
│   │   ├── __init__.py          # BrowserPlugin + create_browser_subagent
│   │   ├── events.py             # BrowserStepEvent, BrowserCdpEvent
│   │   └── implementation.py     # Core browser logic
│   └── ... (all subagents as packages)
├── tools/
│   ├── execution/
│   │   ├── __init__.py          # ExecutionPlugin + create_execution_tools
│   │   ├── events.py             # Execution events (if any)
│   │   └── implementation.py     # Tool implementations
│   └── ... (all tools as packages)
└── plugin/
    ├── lifecycle.py              # Parallel loading with dependency ordering
    ├── cache.py                  # NEW: Plugin instance caching
    ├── lazy.py                   # NEW: Lazy loading support
    └── ...
```

**Key Changes**:
- ❌ Delete `core/event_catalog.py`
- ❌ Delete entire `plugins/` directory
- ✅ Each module contains: `__init__.py` (plugin + factory), `events.py`, `implementation.py`
- ✅ Plugin system optimized with parallel loading, caching, lazy loading

---

## 3. Module Structure

### 3.1 Standard Module Package Structure

Every subagent and tool module follows this canonical structure:

```
module_name/
├── __init__.py          # Plugin class + public factory function(s)
├── events.py             # Event model classes (inheriting from SootheEvent)
├── implementation.py     # Core implementation (renamed from module_name.py)
├── models.py             # Data models (if needed)
└── _internal/            # Internal helpers (optional)
```

**File Responsibilities**:

| File | Purpose | Exports |
|------|---------|---------|
| `__init__.py` | Plugin definition + public API | `PluginClass`, `create_*()` functions |
| `events.py` | Event model classes | Event classes (`*Event`) |
| `implementation.py` | Core logic | Internal functions/classes |
| `models.py` | Data models | Pydantic models for module |

### 3.2 Example: Browser Subagent

**Before** (single file):
```
subagents/
└── browser.py           # 300+ lines with implementation only
```

**After** (package):
```
subagents/browser/
├── __init__.py          # BrowserPlugin + create_browser_subagent()
├── events.py             # BrowserStepEvent, BrowserCdpEvent
└── implementation.py     # _build_browser_graph(), detect_existing_browser_intent()
```

**`__init__.py`**:
```python
"""Browser automation subagent."""

from soothe_sdk import plugin, subagent

from .implementation import create_browser_subagent as _create_browser_subagent

__all__ = ['BrowserPlugin', 'create_browser_subagent']


@plugin(
    name="browser",
    version="1.0.0",
    description="Browser automation using browser-use",
    dependencies=["browser-use~=0.1.0"],
    trust_level="built-in",
)
class BrowserPlugin:
    """Browser automation plugin."""

    async def on_load(self, context) -> None:
        """Verify browser-use is available."""
        try:
            import browser_use  # noqa: F401
        except ImportError as e:
            from soothe.plugin.exceptions import PluginError
            raise PluginError(
                "browser-use library not installed. Install with: pip install soothe[browser]",
                plugin_name="browser",
            ) from e
        context.logger.info("Browser plugin loaded")

    @subagent(
        name="browser",
        description="Browser automation specialist for web tasks...",
        model="openai:gpt-4o-mini",
    )
    async def create_browser(self, model, config, context, **kwargs):
        """Create browser automation subagent."""
        from soothe.config import BrowserSubagentConfig

        browser_config = None
        if hasattr(config, "subagents") and "browser" in config.subagents:
            subagent_config = config.subagents["browser"]
            if subagent_config.enabled and subagent_config.config:
                browser_config = BrowserSubagentConfig(**subagent_config.config)

        runnable = _create_browser_subagent(
            model=model,
            headless=kwargs.get("headless", True),
            max_steps=kwargs.get("max_steps", 100),
            use_vision=kwargs.get("use_vision", True),
            config=browser_config,
        )

        return {
            "name": "browser",
            "description": "Browser automation specialist...",
            "runnable": runnable,
        }

    def get_subagents(self):
        """Get subagent factory functions."""
        return [self.create_browser]


def create_browser_subagent(
    model,
    headless: bool = True,
    max_steps: int = 100,
    use_vision: bool = True,
    config=None,
):
    """Public factory function for browser subagent."""
    return _create_browser_subagent(
        model=model,
        headless=headless,
        max_steps=max_steps,
        use_vision=use_vision,
        config=config,
    )
```

**`events.py`**:
```python
"""Browser subagent events."""

from soothe.core.event_catalog import BrowserStepEvent, BrowserCdpEvent

__all__ = ['BrowserStepEvent', 'BrowserCdpEvent']
```

**`implementation.py`**:
```python
"""Browser subagent implementation."""

import logging
from typing import TYPE_CHECKING, Annotated, Any

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from soothe.config import BrowserSubagentConfig
from soothe.subagents.browser.events import BrowserCdpEvent, BrowserStepEvent

if TYPE_CHECKING:
    from deepagents.middleware.subagents import CompiledSubAgent

logger = logging.getLogger(__name__)

BROWSER_DESCRIPTION = "Browser automation specialist..."


class _BrowserState(dict):
    """State schema for the browser subagent graph."""
    messages: Annotated[list, add_messages]


def _suppress_external_browser_loggers() -> None:
    """Mute noisy third-party browser-use loggers."""
    # ... existing implementation ...


def _build_browser_graph(...):
    """Build browser automation graph."""
    # ... existing implementation ...


def create_browser_subagent(
    model,
    headless: bool = True,
    max_steps: int = 100,
    use_vision: bool = True,
    config=None,
) -> "CompiledSubAgent":
    """Create browser subagent (internal implementation)."""
    # ... existing implementation from browser.py ...
```

### 3.3 Example: Execution Tools

**Before** (single file):
```
tools/
└── execution.py          # 500+ lines with tool classes
```

**After** (package):
```
tools/execution/
├── __init__.py          # ExecutionPlugin + create_execution_tools()
└── implementation.py     # RunCommandTool, RunPythonTool, etc.
```

**`__init__.py`**:
```python
"""Execution tools plugin."""

from soothe_sdk import plugin

from .implementation import create_execution_tools

__all__ = ['ExecutionPlugin', 'create_execution_tools']


@plugin(
    name="execution",
    version="1.0.0",
    description="Shell and Python execution tools",
    trust_level="built-in",
)
class ExecutionPlugin:
    """Execution tools plugin."""

    def __init__(self):
        self._tools = []

    async def on_load(self, context):
        """Initialize tools with workspace from config."""
        workspace_root = context.config.get("workspace_root")
        timeout = context.config.get("timeout", 120)

        self._tools = create_execution_tools(
            workspace_root=workspace_root,
            timeout=timeout,
        )

        context.logger.info(
            "Loaded %d execution tools (workspace=%s, timeout=%ds)",
            len(self._tools), workspace_root, timeout
        )

    def get_tools(self):
        """Get list of langchain tools."""
        return self._tools
```

---

## 4. Core Types

### 4.1 Event Model Classes

**Location**: Each module's `events.py`

**Base Classes** (from `soothe.core.event_catalog`):
- `SootheEvent` - Base class for all events
- `LifecycleEvent` - Thread/session lifecycle
- `ProtocolEvent` - Core protocol activity
- `ToolEvent` - Tool execution events
- `SubagentEvent` - Subagent activity events
- `OutputEvent` - User display content
- `ErrorEvent` - Error events

**Pattern**:
```python
# subagents/browser/events.py
from soothe.core.event_catalog import SubagentEvent
from pydantic import Field

class BrowserStepEvent(SubagentEvent):
    """Browser automation step event."""

    type: str = "soothe.subagent.browser.step"
    url: str = Field(..., description="Current page URL")
    action: str = Field(..., description="Action being performed")


class BrowserCdpEvent(SubagentEvent):
    """Browser CDP connection event."""

    type: str = "soothe.subagent.browser.cdp"
    endpoint: str = Field(..., description="CDP WebSocket endpoint")
```

### 4.2 Plugin Classes

**Location**: Each module's `__init__.py`

**Base Pattern**:
```python
from soothe_sdk import plugin, subagent, tool_group

@plugin(
    name="module_name",
    version="1.0.0",
    description="Module description",
    dependencies=["optional-dep~=1.0"],
    trust_level="built-in",
)
class ModulePlugin:
    """Module plugin providing tools/subagents."""

    async def on_load(self, context):
        """Initialize plugin with context."""
        # Optional: dependency checking, resource initialization
        pass

    @subagent(name="...", description="...", model="...")
    async def create_subagent(self, model, config, context, **kwargs):
        """Subagent factory method."""
        # Create and return subagent spec
        pass

    @tool_group(name="...")
    def get_tools_method(self):
        """Tool factory method."""
        # Return list of tools
        pass

    def get_subagents(self):
        """Return list of subagent factory methods."""
        return [self.create_subagent]

    def get_tools(self):
        """Return list of tools."""
        return self._tools
```

### 4.3 Plugin Cache

**Location**: `src/soothe/plugin/cache.py`

```python
from typing import Any
import logging

logger = logging.getLogger(__name__)

_plugin_cache: dict[str, Any] = {}

def get_cached_plugin(name: str) -> Any | None:
    """Get cached plugin instance.

    Args:
        name: Plugin name.

    Returns:
        Cached plugin instance or None if not cached.
    """
    return _plugin_cache.get(name)

def cache_plugin(name: str, instance: Any) -> None:
    """Cache a plugin instance.

    Args:
        name: Plugin name.
        instance: Plugin instance to cache.
    """
    _plugin_cache[name] = instance
    logger.debug("Cached plugin '%s'", name)

def clear_plugin_cache() -> None:
    """Clear all cached plugins."""
    global _plugin_cache
    _plugin_cache = {}
    logger.debug("Cleared plugin cache")
```

### 4.4 Lazy Plugin Proxy

**Location**: `src/soothe/plugin/lazy.py`

```python
from typing import Any, Callable
import logging

logger = logging.getLogger(__name__)

class LazyPlugin:
    """Lazy-loading plugin proxy.

    Defers plugin instantiation until first attribute access.
    """

    def __init__(self, name: str, loader: Callable[[], Any]):
        """Initialize lazy plugin.

        Args:
            name: Plugin name for logging.
            loader: Callable that creates plugin instance.
        """
        self._name = name
        self._loader = loader
        self._instance: Any | None = None

    def __getattr__(self, attr: str) -> Any:
        """Load plugin on first attribute access.

        Args:
            attr: Attribute name.

        Returns:
            Attribute from loaded plugin instance.
        """
        if self._instance is None:
            logger.info("Lazy-loading plugin '%s'", self._name)
            self._instance = self._loader()
        return getattr(self._instance, attr)
```

---

## 5. Key Interfaces

### 5.1 Plugin Discovery Interface

**Location**: `src/soothe/plugin/discovery.py`

**Function to Update**: `discover_all_plugins()`

**Change**: Remove old `plugins/` directory from discovery paths, add new module locations.

```python
def discover_all_plugins(config: "SootheConfig") -> dict[str, tuple[str, dict]]:
    """Discover all plugins from configured sources.

    Returns:
        Dict mapping plugin name to (module_path, plugin_config).

    Updated discovery order:
    1. Built-in plugins in subagents/<name>/__init__.py
    2. Built-in plugins in tools/<name>/__init__.py
    3. Entry points (soothe.plugins group)
    4. Config-declared plugins
    5. Filesystem plugins (~/.soothe/plugins/)
    """
    discovered = {}

    # Discover built-in subagent plugins
    for subagent_name in ["browser", "claude", "skillify", "weaver"]:
        module_path = f"soothe.subagents.{subagent_name}"
        discovered[subagent_name] = (module_path, {})

    # Discover built-in tool plugins
    for tool_name in ["execution", "file_ops", "code_edit", "data", ...]:
        module_path = f"soothe.tools.{tool_name}"
        discovered[tool_name] = (module_path, {})

    # Continue with entry points, config, filesystem discovery...
    # ... existing logic ...
```

### 5.2 Plugin Lifecycle Interface

**Location**: `src/soothe/plugin/lifecycle.py`

**Class**: `PluginLifecycleManager`

**Method to Update**: `load_all()`

**New Signature**:
```python
async def load_all(
    self,
    config: "SootheConfig",
    lazy_plugins: list[str] | None = None,
) -> dict[str, Any]:
    """Load all discovered plugins with parallel loading and caching.

    Args:
        config: Soothe configuration.
        lazy_plugins: Optional list of plugin names to load lazily.

    Returns:
        Dict mapping plugin names to loaded instances.
    """
```

**New Methods**:
```python
def _build_dependency_graph(
    self,
    discovered: dict[str, tuple[str, dict]],
) -> dict[str, set[str]]:
    """Build plugin dependency graph.

    Args:
        discovered: Discovered plugins dict.

    Returns:
        Dict mapping plugin name to set of dependency names.
    """

async def _load_plugins_parallel(
    self,
    graph: dict[str, set[str]],
    discovered: dict[str, tuple[str, dict]],
    config: "SootheConfig",
    lazy_plugins: list[str] | None = None,
) -> None:
    """Load plugins in parallel respecting dependencies.

    Args:
        graph: Dependency graph.
        discovered: Discovered plugins.
        config: Soothe configuration.
        lazy_plugins: Plugins to load lazily.
    """
```

---

## 6. Implementation Details

### 6.1 Event Migration Process

**Step 1: Create events.py in each module**

For each subagent/tool module:
1. Create `events.py` file
2. Identify events in `core/event_catalog.py` that belong to this module
3. Copy event class definitions to `events.py`
4. Update imports to use `from soothe.core.event_catalog import <BaseClass>`

**Step 2: Update imports in implementation files**

For each file that imports events:
1. Find: `from soothe.core.event_catalog import BrowserStepEvent`
2. Replace: `from soothe.subagents.browser.events import BrowserStepEvent`

**Step 3: Delete core/event_catalog.py**

After all imports updated:
1. Verify no imports from `event_catalog.py`
2. Delete the file

### 6.2 Plugin Shim Consolidation Process

**Step 1: Convert modules to packages**

For each single-file module:
1. Create directory: `mkdir -p src/soothe/subagents/browser`
2. Move file: `mv src/soothe/subagents/browser.py src/soothe/subagents/browser/implementation.py`
3. Create `__init__.py` with plugin class
4. Create `events.py` with event classes

**Step 2: Move plugin classes**

For each plugin in `plugins/<name>/__init__.py`:
1. Copy plugin class to module's `__init__.py`
2. Update imports to use relative imports
3. Add factory function exports

**Step 3: Update discovery**

In `plugin/discovery.py`:
1. Update discovery to find plugins in new locations
2. Remove old `plugins/` directory from paths

**Step 4: Delete plugins/ directory**

After verification:
1. `rm -rf src/soothe/plugins/`

### 6.3 Parallel Loading Implementation

**Algorithm**: Topological sort with parallel execution

```python
async def _load_plugins_parallel(
    self,
    graph: dict[str, set[str]],
    discovered: dict[str, tuple[str, dict]],
    config: "SootheConfig",
    lazy_plugins: list[str] | None = None,
) -> None:
    """Load plugins in parallel respecting dependencies."""
    import asyncio

    loaded = set()
    lazy_plugins = set(lazy_plugins or [])

    while len(loaded) < len(graph):
        # Find plugins with all dependencies satisfied
        ready = [
            name for name, deps in graph.items()
            if name not in loaded and deps.issubset(loaded)
        ]

        if not ready:
            # Circular dependency or missing dependency
            remaining = set(graph.keys()) - loaded
            logger.error(
                "Cannot resolve dependencies for plugins: %s",
                remaining
            )
            break

        # Separate eager and lazy plugins
        eager = [name for name in ready if name not in lazy_plugins]
        lazy = [name for name in ready if name in lazy_plugins]

        # Load eager plugins in parallel
        if eager:
            tasks = [
                self._load_single_plugin(
                    discovered[name][0],
                    config,
                    discovered[name][1]
                )
                for name in eager
            ]
            await asyncio.gather(*tasks, return_exceptions=True)
            loaded.update(eager)

        # Create lazy proxies for lazy plugins
        for name in lazy:
            from soothe.plugin.lazy import LazyPlugin
            from soothe.plugin.cache import cache_plugin

            def loader(n=name):
                # Sync loader for lazy plugin
                return self.loader.load_plugin(
                    discovered[n][0],
                    config,
                    discovered[n][1]
                )

            lazy_proxy = LazyPlugin(name, loader)
            cache_plugin(name, lazy_proxy)
            loaded.add(name)
```

### 6.4 Caching Integration

**In lifecycle.py `_load_single_plugin()`**:

```python
async def _load_single_plugin(
    self,
    module_path: str,
    config: "SootheConfig",
    plugin_config: dict[str, Any],
) -> None:
    """Load a single plugin from module path."""
    from soothe.plugin.cache import get_cached_plugin, cache_plugin

    # Check cache first
    plugin_name = module_path.split(".")[-1]
    cached = get_cached_plugin(plugin_name)
    if cached:
        logger.debug("Using cached plugin '%s'", plugin_name)
        self.loaded_plugins[plugin_name] = cached
        return

    try:
        # Load plugin instance
        plugin_instance = self.loader.load_plugin(module_path, config, plugin_config)

        # ... existing loading logic ...

        # Cache the loaded plugin
        cache_plugin(plugin_name, plugin_instance)

    except Exception as e:
        # ... error handling ...
```

---

## 7. Error Handling

### 7.1 Dependency Resolution Errors

**Error**: Circular dependency detected

**Handling**:
```python
if not ready and len(loaded) < len(graph):
    remaining = set(graph.keys()) - loaded
    raise CircularDependencyError(
        f"Circular dependency detected among plugins: {remaining}"
    )
```

**Error**: Missing dependency

**Handling**:
```python
for name, deps in graph.items():
    missing = deps - set(graph.keys())
    if missing:
        raise MissingDependencyError(
            f"Plugin '{name}' depends on missing plugins: {missing}"
        )
```

### 7.2 Import Errors During Migration

**Error**: Module imports from old location

**Detection**: grep for `from soothe.core.event_catalog import`

**Fix**: Update all imports before deleting files

### 7.3 Plugin Loading Failures

**Error**: Plugin fails to load

**Handling** (existing):
```python
except Exception as e:
    emit_progress(
        PluginFailedEvent(
            name=plugin_name,
            error=str(e),
            phase="loading",
        ).model_dump(),
        logger,
    )
    logger.exception("Failed to load plugin from %s", module_path)
```

---

## 8. Configuration

### 8.1 Plugin Loading Configuration

**Location**: `config/config.yml`

**New Configuration Options**:
```yaml
plugins:
  # Parallel loading
  parallel_loading:
    enabled: true  # Enable parallel plugin loading
    max_workers: 4  # Max concurrent plugin loads

  # Lazy loading
  lazy_loading:
    enabled: false  # Enable lazy loading (opt-in)
    lazy_plugins:   # Plugins to load on first use
      - "weaver"
      - "skillify"
    eager_plugins:  # Plugins to load at startup
      - "browser"
      - "execution"
      - "file_ops"

  # Caching
  caching:
    enabled: true  # Cache plugin instances
```

### 8.2 Config Schema Updates

**Location**: `src/soothe/config/settings.py`

**New Settings**:
```python
class PluginLoadingConfig(BaseModel):
    """Plugin loading configuration."""

    parallel_loading: bool = True
    max_workers: int = 4
    lazy_loading_enabled: bool = False
    lazy_plugins: list[str] = Field(default_factory=list)
    eager_plugins: list[str] = Field(default_factory=list)
    caching_enabled: bool = True


class SootheConfig(BaseSettings):
    # ... existing fields ...

    plugin_loading: PluginLoadingConfig = Field(
        default_factory=PluginLoadingConfig
    )
```

---

## 9. Testing Strategy

### 9.1 Unit Tests

**Test Event Imports**:
```python
# tests/unit/subagents/test_browser_events.py
def test_browser_events_importable():
    """Test that browser events can be imported from module."""
    from soothe.subagents.browser.events import (
        BrowserStepEvent,
        BrowserCdpEvent,
    )

    event = BrowserStepEvent(url="https://example.com", action="click")
    assert event.type == "soothe.subagent.browser.step"
```

**Test Plugin Discovery**:
```python
# tests/unit/plugin/test_discovery.py
def test_discover_builtin_plugins():
    """Test that built-in plugins are discovered in new locations."""
    from soothe.plugin.discovery import discover_all_plugins
    from soothe.config import SootheConfig

    config = SootheConfig()
    discovered = discover_all_plugins(config)

    assert "browser" in discovered
    assert discovered["browser"][0] == "soothe.subagents.browser"

    assert "execution" in discovered
    assert discovered["execution"][0] == "soothe.tools.execution"
```

**Test Parallel Loading**:
```python
# tests/unit/plugin/test_lifecycle.py
@pytest.mark.asyncio
async def test_parallel_plugin_loading():
    """Test that plugins load in parallel with dependency ordering."""
    from soothe.plugin.lifecycle import PluginLifecycleManager
    from soothe.plugin.registry import PluginRegistry
    from soothe.config import SootheConfig

    registry = PluginRegistry()
    manager = PluginLifecycleManager(registry)

    config = SootheConfig()

    # Mock plugins with dependencies
    # ... setup ...

    loaded = await manager.load_all(config)

    # Verify parallel execution
    # ... assertions ...
```

**Test Caching**:
```python
# tests/unit/plugin/test_cache.py
def test_plugin_caching():
    """Test that plugin instances are cached."""
    from soothe.plugin.cache import cache_plugin, get_cached_plugin, clear_plugin_cache

    clear_plugin_cache()

    # Cache a mock plugin
    mock_plugin = object()
    cache_plugin("test", mock_plugin)

    # Retrieve from cache
    cached = get_cached_plugin("test")
    assert cached is mock_plugin

    # Clear cache
    clear_plugin_cache()
    assert get_cached_plugin("test") is None
```

**Test Lazy Loading**:
```python
# tests/unit/plugin/test_lazy.py
def test_lazy_plugin_loading():
    """Test that lazy plugins load on first access."""
    from soothe.plugin.lazy import LazyPlugin

    load_count = 0

    def loader():
        nonlocal load_count
        load_count += 1
        return object()

    lazy = LazyPlugin("test", loader)

    # Not loaded yet
    assert load_count == 0

    # Access attribute triggers load
    _ = lazy.some_attr
    assert load_count == 1

    # Second access uses cached instance
    _ = lazy.another_attr
    assert load_count == 1
```

### 9.2 Integration Tests

**Test Full Agent Creation**:
```python
# tests/integration/test_agent_creation.py
@pytest.mark.asyncio
async def test_agent_creation_with_new_modules():
    """Test that agent creation works with refactored modules."""
    from soothe.core.agent import create_soothe_agent
    from soothe.config import SootheConfig

    config = SootheConfig()
    agent = create_soothe_agent(config)

    # Verify agent created successfully
    assert agent is not None

    # Verify plugins loaded
    from soothe.plugin.global_registry import get_plugin_registry
    registry = get_plugin_registry()

    assert "browser" in registry._plugins
    assert "execution" in registry._plugins
```

**Test Event Emission**:
```python
# tests/integration/test_events.py
@pytest.mark.asyncio
async def test_events_emitted_from_modules():
    """Test that events are emitted correctly from refactored modules."""
    from soothe.core.agent import create_soothe_agent
    from soothe.config import SootheConfig

    config = SootheConfig()
    agent = create_soothe_agent(config)

    # Run agent and capture events
    events = []
    async for event in agent.astream({"messages": [...]}):
        if event.get("type", "").startswith("soothe."):
            events.append(event)

    # Verify event types
    assert any(e["type"] == "soothe.subagent.browser.step" for e in events)
```

### 9.3 Performance Tests

**Benchmark Plugin Loading**:
```python
# tests/performance/test_plugin_loading.py
import time

def test_plugin_loading_performance():
    """Benchmark plugin loading time before and after optimization."""
    from soothe.plugin.lifecycle import PluginLifecycleManager
    from soothe.plugin.registry import PluginRegistry
    from soothe.config import SootheConfig

    config = SootheConfig()

    # Measure loading time
    start = time.time()

    registry = PluginRegistry()
    manager = PluginLifecycleManager(registry)
    loaded = asyncio.run(manager.load_all(config))

    elapsed = time.time() - start

    # Should be < 300ms with parallel loading
    assert elapsed < 0.3, f"Plugin loading took {elapsed}s (expected < 0.3s)"

    # Compare with sequential (baseline ~500ms)
    # ... comparison logic ...
```

---

## 10. Migration Guide

### 10.1 Migration Phases

**Phase 1: Event Migration (Week 1)**

1. Create `events.py` in each module
2. Move event classes from `core/event_catalog.py`
3. Update all imports across codebase
4. Run tests, fix failures
5. Delete `core/event_catalog.py`

**Phase 2: Plugin Consolidation (Week 2)**

1. Convert single-file modules to packages
2. Move plugin classes from `plugins/` to modules
3. Update plugin discovery
4. Run tests, fix failures
5. Delete `plugins/` directory

**Phase 3: Performance Optimization (Week 3)**

1. Implement parallel plugin loading
2. Implement plugin caching
3. Implement lazy loading
4. Add configuration options
5. Performance testing and benchmarks

**Phase 4: Documentation and Cleanup (Week 4)**

1. Update CLAUDE.md
2. Update user documentation
3. Add migration guide for external plugins
4. Run `make lint`, fix issues
5. Final testing

### 10.2 Migration Commands

**Phase 1: Event Migration**

```bash
# Create events.py files
mkdir -p src/soothe/subagents/browser
touch src/soothe/subagents/browser/events.py

# Find imports to update
grep -r "from soothe.core.event_catalog import" src/

# After updating imports, delete catalog
rm src/soothe/core/event_catalog.py
```

**Phase 2: Plugin Consolidation**

```bash
# Convert browser module
mkdir -p src/soothe/subagents/browser
mv src/soothe/subagents/browser.py src/soothe/subagents/browser/implementation.py

# After migrating all plugins, delete plugins directory
rm -rf src/soothe/plugins/
```

**Phase 3: Run Tests**

```bash
# Run all tests
pytest tests/

# Run linting
make lint

# Fix any issues
ruff check --fix src/
```

### 10.3 Validation Checklist

After each phase:

- [ ] All tests pass (`pytest tests/`)
- [ ] No linting errors (`make lint`)
- [ ] Imports updated (check with grep)
- [ ] No broken imports (run agent creation)
- [ ] Performance improved (run benchmarks)

---

## 11. Success Criteria

### 11.1 Functionality

✅ All events moved to module `events.py` files
✅ `core/event_catalog.py` deleted
✅ All plugin shims consolidated into modules
✅ `plugins/` directory deleted
✅ All subagents/tools converted to packages
✅ All tests pass
✅ Agent creation works correctly

### 11.2 Performance

✅ Plugin loading time < 300ms (was ~500ms)
✅ Agent creation time < 2s (was ~2-3s)
✅ Plugin cache hit rate > 90% on repeated creation
✅ Parallel loading working (verify with logs)

### 11.3 Code Quality

✅ `make lint` passes with no errors
✅ All modules follow canonical structure
✅ No backward compatibility code
✅ Documentation updated

### 11.4 Developer Experience

✅ Each module self-contained
✅ Clear module structure
✅ Easy to add new subagents/tools
✅ Plugin development guide updated

---

## 12. Post-Migration Tasks

### 12.1 Documentation Updates

**Update CLAUDE.md**:
- Remove `plugins/` directory references
- Update module map table
- Add module self-containment principle

**Update User Guide**:
- Document new module structure
- Update examples for plugin development

**Create Migration Guide**:
- Guide for external plugin developers
- Breaking changes list
- How to update third-party plugins

### 12.2 Performance Monitoring

**Add Metrics**:
- Plugin loading time
- Cache hit rate
- Agent creation time

**Add Logging**:
- Parallel loading progress
- Cache hits/misses
- Lazy loading events

---

## 13. References

- RFC-0001: System Conceptual Design
- RFC-0013: Unified Daemon Communication Protocol
- Implementation Guide Template: `docs/impl/README.md`
- Plugin System RFC-0018 (if exists)