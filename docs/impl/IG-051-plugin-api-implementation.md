# IG-047: Plugin API Implementation

**Implementation Guide**: 047
**Title**: Plugin API Implementation
**RFC**: RFC-0018 (Plugin Extension Specification)
**Created**: 2026-03-24
**Status**: Draft

## Overview

This guide implements a simplified plugin system for Soothe that enables third-party developers to create custom **tools** and **subagents** using a decorator-based API.

### What We're Building

- **Core plugin system**: Manifest, registry, loader, lifecycle manager
- **SDK package**: `soothe_sdk` with `@plugin`, `@tool`, `@tool_group`, `@subagent` decorators
- **Discovery mechanisms**: Python entry points, config declarations, filesystem scanning
- **Integration**: Connect plugin system to Soothe's tool and subagent resolution
- **Migration**: Convert built-in tools and subagents to plugins with backward compatibility

### Scope

**Included**:
- Tool plugins (tool groups and individual tools)
- Subagent plugins (subagent modules)

**Excluded** (not in this implementation):
- Protocol implementations
- Middleware
- Slash commands
- Vector stores
- Model providers

## Architecture

### Component Diagram

```
┌─────────────────────────────────────────────────────────┐
│                 Plugin System                            │
│                                                         │
│  soothe_sdk (Developer API)                            │
│  ├─ @plugin, @tool, @tool_group, @subagent            │
│  └─ PluginContext, PluginManifest                      │
│                                                         │
│  soothe.plugin (Core System)                           │
│  ├─ PluginRegistry (name -> plugin)                    │
│  ├─ PluginLoader (discovery + loading)                 │
│  ├─ PluginLifecycleManager (init/shutdown/health)     │
│  └─ PluginManifest (metadata)                          │
│                                                         │
└─────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────┐
│  Integration with Soothe                                │
│                                                         │
│  core/agent.py                                          │
│  └─ Load plugins during agent creation                 │
│                                                         │
│  core/resolver/                                         │
│  ├─ resolve_tools() uses plugin tool registry          │
│  └─ resolve_subagents() uses plugin subagent registry  │
│                                                         │
│  config/settings.py                                     │
│  └─ PluginConfig added to SootheConfig                 │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

```
1. Discovery
   Entry Points / Config / Filesystem
            ↓
   PluginLoader.discover_all()
            ↓
   [PluginManifest, PluginManifest, ...]

2. Validation & Dependency Resolution
   PluginLoader.validate_manifests()
   PluginLoader.resolve_dependencies()
            ↓
   [ValidPluginManifest, ...]

3. Loading
   PluginLoader.load_plugin(manifest)
            ↓
   @plugin decorator creates plugin class
            ↓
   PluginLifecycleManager.initialize_plugin()
            ↓
   plugin.on_load(context)

4. Registration
   PluginRegistry.register_tools(plugin)
   PluginRegistry.register_subagents(plugin)
            ↓
   Tools available in tool registry
   Subagents available in subagent registry

5. Runtime
   resolve_tools() → get tools from plugin registry
   resolve_subagents() → get subagents from plugin registry
```

## Implementation Phases

### Phase 1: Core Plugin System (Days 1-3)

**Goal**: Create the foundational plugin infrastructure.

#### Files to Create

```
src/soothe/plugin/
├── __init__.py          # Public API
├── manifest.py          # PluginManifest Pydantic model
├── context.py           # PluginContext class
├── registry.py          # PluginRegistry
├── loader.py            # PluginLoader (discovery + loading)
├── lifecycle.py         # PluginLifecycleManager
├── events.py            # Plugin events (loaded, failed, unloaded)
└── exceptions.py        # PluginError, etc.
```

#### Implementation Steps

1. **Create `manifest.py`**:

```python
from datetime import datetime
from typing import Literal, Any
from pydantic import BaseModel, Field, ConfigDict

class PluginManifest(BaseModel):
    """Plugin manifest with metadata."""

    model_config = ConfigDict(extra="forbid")

    # Core metadata
    name: str
    version: str
    description: str
    author: str = ""
    homepage: str = ""
    repository: str = ""
    license: str = "MIT"

    # Dependencies
    dependencies: list[str] = Field(default_factory=list)  # PEP 440 specifiers
    python_version: str = ">=3.11"
    soothe_version: str = ">=0.1.0"

    # Security
    trust_level: Literal["built-in", "trusted", "standard", "untrusted"] = "standard"

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

2. **Create `context.py`**:

```python
from typing import Any, Callable
import logging

class PluginContext:
    """Context provided to plugin lifecycle hooks."""

    def __init__(
        self,
        config: dict[str, Any],
        soothe_config: "SootheConfig",
        logger: logging.Logger,
        emit_event: Callable[[str, dict], None],
    ):
        self.config = config
        self.soothe_config = soothe_config
        self.logger = logger
        self._emit_event = emit_event

    def emit_event(self, name: str, data: dict[str, Any]) -> None:
        """Emit a plugin event."""
        self._emit_event(name, data)
```

3. **Create `registry.py`**:

```python
from typing import Any, Literal
from dataclasses import dataclass

@dataclass
class RegistryEntry:
    """Entry in the plugin registry."""
    manifest: "PluginManifest"
    source: Literal["built-in", "entry_point", "config", "filesystem"]
    priority: int
    plugin_instance: Any | None = None
    tools: list[Any] | None = None  # langchain BaseTool instances
    subagents: list[Any] | None = None  # SubAgent/CompiledSubAgent dicts

class PluginRegistry:
    """Registry for discovered plugins."""

    PRIORITY_BUILTIN = 100
    PRIORITY_ENTRY_POINT = 50
    PRIORITY_CONFIG = 30
    PRIORITY_FILESYSTEM = 10

    def __init__(self):
        self._plugins: dict[str, RegistryEntry] = {}

    def register(
        self,
        manifest: "PluginManifest",
        source: Literal["built-in", "entry_point", "config", "filesystem"],
        priority: int | None = None,
    ) -> None:
        """Register a plugin manifest."""
        # Implementation from RFC-0018
        pass

    def get(self, name: str) -> RegistryEntry | None:
        """Get registry entry by name."""
        return self._plugins.get(name)

    def list_all(self) -> list[RegistryEntry]:
        """List all registered entries."""
        return list(self._plugins.values())

    def get_all_tools(self) -> list[Any]:
        """Get all registered tools from all plugins."""
        tools = []
        for entry in self._plugins.values():
            if entry.tools:
                tools.extend(entry.tools)
        return tools

    def get_all_subagents(self) -> list[Any]:
        """Get all registered subagents from all plugins."""
        subagents = []
        for entry in self._plugins.values():
            if entry.subagents:
                subagents.extend(entry.subagents)
        return subagents
```

4. **Create `loader.py`**:

```python
import importlib
import importlib.metadata
from pathlib import Path
from typing import Any

class PluginLoader:
    """Plugin discovery and loading."""

    def __init__(self, registry: "PluginRegistry"):
        self.registry = registry
        self.logger = logging.getLogger("soothe.plugin.loader")

    def discover_all(self, config: "SootheConfig") -> list[str]:
        """Run all discovery mechanisms."""
        module_paths = []

        # Entry points
        module_paths.extend(self._discover_entry_points())

        # Config-declared
        module_paths.extend(self._discover_config_declared(config))

        # Filesystem
        module_paths.extend(self._discover_filesystem())

        return module_paths

    def _discover_entry_points(self) -> list[str]:
        """Discover plugins from Python entry points."""
        # Implementation from RFC-0018
        pass

    def _discover_config_declared(self, config: "SootheConfig") -> list[str]:
        """Discover plugins declared in configuration."""
        # Implementation from RFC-0018
        pass

    def _discover_filesystem(self) -> list[str]:
        """Discover plugins from filesystem."""
        # Implementation from RFC-0018
        pass

    def load_plugin(
        self,
        module_path: str,
        config: "SootheConfig",
    ) -> Any:
        """Load a plugin from module path.

        Args:
            module_path: Python import path (e.g., "my_package:MyPlugin")
            config: Soothe configuration.

        Returns:
            Loaded plugin instance.
        """
        # Import module
        module_name, class_name = module_path.split(":")
        module = importlib.import_module(module_name)
        plugin_class = getattr(module, class_name)

        # Instantiate
        plugin_instance = plugin_class()

        return plugin_instance
```

5. **Create `lifecycle.py`**:

```python
import asyncio
from typing import Any

class PluginLifecycleManager:
    """Manage plugin lifecycle."""

    def __init__(self, registry: "PluginRegistry"):
        self.registry = registry
        self.loaded_plugins: dict[str, Any] = {}
        self.logger = logging.getLogger("soothe.plugin.lifecycle")

    async def load_all(self, config: "SootheConfig") -> dict[str, Any]:
        """Load all discovered and validated plugins."""
        # Implementation from RFC-0018
        pass

    async def shutdown_all(self) -> None:
        """Shutdown all loaded plugins."""
        # Implementation from RFC-0018
        pass
```

### Phase 2: SDK Package (Days 4-6)

**Goal**: Create the decorator-based SDK for plugin developers.

#### Files to Create

```
src/soothe_sdk/
├── __init__.py          # Public API: @plugin, @tool, @tool_group, @subagent
├── decorators/
│   ├── __init__.py
│   ├── plugin.py        # @plugin decorator
│   ├── tool.py          # @tool, @tool_group decorators
│   └── subagent.py      # @subagent decorator
├── types/
│   ├── __init__.py
│   ├── manifest.py      # PluginManifest type hints
│   └── context.py       # PluginContext type hints
├── depends.py           # Dependency helpers (future)
└── exceptions.py        # PluginError, etc.
```

#### Implementation Steps

1. **Create `decorators/plugin.py`**:

```python
from functools import wraps
from typing import Any, Callable
from soothe.plugin.manifest import PluginManifest

def plugin(
    name: str,
    version: str,
    description: str,
    author: str = "",
    dependencies: list[str] | None = None,
    trust_level: str = "standard",
    **kwargs,
) -> Callable:
    """Plugin decorator that marks a class as a Soothe plugin."""

    def decorator(cls: type) -> type:
        # Store manifest on class
        cls._plugin_manifest = PluginManifest(
            name=name,
            version=version,
            description=description,
            author=author,
            dependencies=dependencies or [],
            trust_level=trust_level,
            **kwargs,
        )

        # Add manifest property
        @property
        def manifest(self) -> PluginManifest:
            return self._plugin_manifest

        cls.manifest = manifest

        # Add get_tools() method to extract @tool decorated methods
        def get_tools(self) -> list[Any]:
            """Extract all tools from this plugin."""
            tools = []
            for attr_name in dir(self):
                attr = getattr(self, attr_name)
                if hasattr(attr, '_is_tool'):
                    tools.append(attr)
            return tools

        cls.get_tools = get_tools

        # Add get_subagents() method
        def get_subagents(self) -> list[Any]:
            """Extract all subagents from this plugin."""
            subagents = []
            for attr_name in dir(self):
                attr = getattr(self, attr_name)
                if hasattr(attr, '_is_subagent'):
                    subagents.append(attr)
            return subagents

        cls.get_subagents = get_subagents

        return cls

    return decorator
```

2. **Create `decorators/tool.py`**:

```python
from functools import wraps
from typing import Any, Callable
from langchain.tools import Tool

def tool(
    name: str,
    description: str = "",
    group: str | None = None,
) -> Callable:
    """Tool decorator that registers a method as a langchain tool."""

    def decorator(func: Callable) -> Callable:
        # Mark as tool
        func._is_tool = True
        func._tool_name = name
        func._tool_description = description
        func._tool_group = group

        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            return await func(self, *args, **kwargs)

        # Copy metadata
        wrapper._is_tool = True
        wrapper._tool_name = name
        wrapper._tool_description = description
        wrapper._tool_group = group

        return wrapper

    return decorator


def tool_group(
    name: str,
    description: str = "",
) -> Callable:
    """Tool group decorator for organizing related tools."""

    def decorator(cls: type) -> type:
        cls._is_tool_group = True
        cls._tool_group_name = name
        cls._tool_group_description = description
        return cls

    return decorator
```

3. **Create `decorators/subagent.py`**:

```python
from functools import wraps
from typing import Any, Callable

def subagent(
    name: str,
    description: str,
    model: str | None = None,
) -> Callable:
    """Subagent decorator that registers a factory function."""

    def decorator(func: Callable) -> Callable:
        # Mark as subagent factory
        func._is_subagent = True
        func._subagent_name = name
        func._subagent_description = description
        func._subagent_model = model

        @wraps(func)
        async def wrapper(self, model, config, context, **kwargs):
            return await func(self, model, config, context, **kwargs)

        # Copy metadata
        wrapper._is_subagent = True
        wrapper._subagent_name = name
        wrapper._subagent_description = description
        wrapper._subagent_model = model

        return wrapper

    return decorator
```

### Phase 3: Integration with Soothe (Days 7-8)

**Goal**: Connect plugin system to Soothe's core.

#### Files to Modify

1. `src/soothe/config/models.py` - Add PluginConfig
2. `src/soothe/config/settings.py` - Add plugins field
3. `src/soothe/core/agent.py` - Load plugins
4. `src/soothe/core/resolver/__init__.py` - Use plugin registry
5. `src/soothe/core/resolver/_resolver_tools.py` - Use plugin tools

#### Implementation Steps

1. **Add PluginConfig to `config/models.py`**:

```python
from pydantic import BaseModel, Field
from typing import Any

class PluginConfig(BaseModel):
    """Configuration for a single plugin."""

    name: str
    enabled: bool = True
    module: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
```

2. **Add plugins to `config/settings.py`**:

```python
class SootheConfig(BaseSettings):
    # ... existing fields ...

    # Plugin system
    plugins: list[PluginConfig] = Field(default_factory=list)

    def get_plugin_config(self, name: str) -> dict[str, Any]:
        """Get plugin-specific configuration."""
        for plugin in self.plugins:
            if plugin.name == name:
                return plugin.config
        return {}
```

3. **Load plugins in `core/agent.py`**:

```python
from soothe.plugin import PluginRegistry, PluginLifecycleManager

def create_soothe_agent(config: SootheConfig | None = None, ...) -> CompiledStateGraph:
    # ... existing code ...

    # Create plugin registry
    plugin_registry = PluginRegistry()

    # Load plugins
    lifecycle_manager = PluginLifecycleManager(plugin_registry)
    loaded_plugins = asyncio.run(lifecycle_manager.load_all(config))

    # Get tools and subagents from plugins
    plugin_tools = plugin_registry.get_all_tools()
    plugin_subagents = plugin_registry.get_all_subagents()

    # Merge with existing tools/subagents
    all_tools = [*config_tools, *plugin_tools, *(tools or [])]
    all_subagents = [*config_subagents, *plugin_subagents, *(subagents or [])]

    # ... rest of agent creation ...
```

### Phase 4: Migrate Built-in Components (Days 9-12)

**Goal**: Convert existing tools and subagents to plugins.

#### Files to Create

```
src/soothe/plugins/
├── browser/
│   ├── __init__.py      # BrowserPlugin class
│   └── subagent.py      # @subagent create_browser_subagent
├── claude/
│   ├── __init__.py      # ClaudePlugin class
│   └── subagent.py
├── skillify/
│   ├── __init__.py      # SkillifyPlugin class
│   └── subagent.py
├── weaver/
│   ├── __init__.py      # WeaverPlugin class
│   └── subagent.py
└── core_tools/
    ├── __init__.py      # CoreToolsPlugin class
    ├── execution.py     # @tool_group for execution tools
    ├── file_ops.py      # @tool_group for file operations
    └── datetime.py      # @tool_group for datetime tools
```

#### Migration Pattern

For each built-in component:

1. Create plugin class with `@plugin` decorator
2. Add `@subagent` or `@tool_group` decorators
3. Move implementation code to plugin methods
4. Create backward compatibility wrapper in old location
5. Test that both old and new imports work

**Example (browser subagent)**:

```python
# src/soothe/plugins/browser/__init__.py

from soothe_sdk import plugin, subagent

@plugin(
    name="browser",
    version="1.0.0",
    description="Navigate and interact with web pages using browser-use",
    dependencies=["browser-use~=0.1.0"],
    trust_level="built-in",
)
class BrowserPlugin:
    """Browser automation plugin."""

    async def on_load(self, context):
        """Check browser-use availability."""
        try:
            import browser_use
        except ImportError:
            from soothe.plugin.exceptions import PluginError
            raise PluginError("browser-use library not installed")

    @subagent(
        name="browser",
        description="Navigate and interact with web pages",
        model="openai:gpt-4o-mini",
    )
    async def create_browser_subagent(
        self,
        model,
        config,
        headless: bool = True,
        max_steps: int = 100,
        use_vision: bool = True,
        **kwargs,
    ):
        """Create browser automation subagent."""
        # ... existing implementation from subagents/browser.py ...
        from browser_use import Agent as BrowserAgent
        # ... build runnable ...
        return {
            "name": "browser",
            "description": "Navigate and interact with web pages",
            "runnable": runnable,
        }


# src/soothe/subagents/browser.py (backward compatibility)

from soothe.plugins.browser import BrowserPlugin

_plugin_instance = BrowserPlugin()

def create_browser_subagent(*args, **kwargs):
    """Backward-compatible factory function."""
    return _plugin_instance.create_browser_subagent(*args, **kwargs)

BROWSER_DESCRIPTION = "Navigate and interact with web pages"
```

### Phase 5: Testing and Documentation (Days 13-14)

**Goal**: Ensure quality and create developer guides.

#### Tests to Write

```
tests/plugin/
├── test_manifest.py          # Manifest validation
├── test_decorators.py        # Decorator tests
├── test_registry.py          # Registry tests
├── test_loader.py            # Discovery and loading tests
├── test_lifecycle.py         # Lifecycle tests
└── test_integration.py       # End-to-end tests

tests/integration/
└── test_plugin_loading.py    # Full plugin loading workflow
```

#### Documentation to Create

```
docs/
├── plugin_development.md     # Developer guide
├── plugin_migration.md       # Migration guide
└── examples/plugins/
    ├── simple_tool.py        # Minimal tool plugin
    ├── tool_group.py         # Tool group plugin
    ├── subagent.py           # Subagent plugin
    └── combined.py           # Tools + subagent plugin
```

## File Structure Summary

### New Files to Create

```
src/soothe/
├── plugin/
│   ├── __init__.py
│   ├── manifest.py
│   ├── context.py
│   ├── registry.py
│   ├── loader.py
│   ├── lifecycle.py
│   ├── events.py
│   └── exceptions.py
├── plugins/
│   ├── browser/
│   │   ├── __init__.py
│   │   └── subagent.py
│   ├── claude/
│   │   ├── __init__.py
│   │   └── subagent.py
│   ├── skillify/
│   │   ├── __init__.py
│   │   └── subagent.py
│   ├── weaver/
│   │   ├── __init__.py
│   │   └── subagent.py
│   └── core_tools/
│       ├── __init__.py
│       ├── execution.py
│       ├── file_ops.py
│       └── datetime.py

src/soothe_sdk/
├── __init__.py
├── decorators/
│   ├── __init__.py
│   ├── plugin.py
│   ├── tool.py
│   └── subagent.py
├── types/
│   ├── __init__.py
│   ├── manifest.py
│   └── context.py
└── exceptions.py
```

### Files to Modify

```
src/soothe/
├── config/
│   ├── models.py            # Add PluginConfig
│   ├── settings.py          # Add plugins field
│   └── config.yml           # Add plugins section
├── core/
│   ├── agent.py             # Load plugins
│   └── resolver/
│       ├── __init__.py      # Use plugin registry
│       └── _resolver_tools.py # Use plugin tools
```

## Verification

### Unit Tests

Run: `pytest tests/plugin/ -v`

### Integration Tests

Run: `pytest tests/integration/test_plugin_loading.py -v`

### Manual Testing

1. Create a test plugin:

```python
# test_plugin.py
from soothe_sdk import plugin, tool

@plugin(name="test", version="1.0.0", description="Test plugin")
class TestPlugin:
    @tool(name="test_tool", description="Test tool")
    def test_tool(self, query: str) -> str:
        return f"Test: {query}"
```

2. Add to config.yml:

```yaml
plugins:
  - name: test
    enabled: true
    module: "test_plugin:TestPlugin"
```

3. Run Soothe and verify tool is available:

```bash
soothe run "Use test_tool with query='hello'"
```

### Expected Results

- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] Built-in plugins load successfully
- [ ] Tools from plugins are available
- [ ] Subagents from plugins are available
- [ ] Backward compatibility maintained
- [ ] Documentation is complete

## Success Criteria

1. Plugin system loads tools and subagents from plugins
2. Decorator API is simple and intuitive
3. Discovery mechanisms work (entry points, config, filesystem)
4. Built-in components migrated to plugins
5. Backward compatibility maintained
6. Tests provide good coverage
7. Documentation enables developers to create plugins

## Timeline

- **Days 1-3**: Core plugin system
- **Days 4-6**: SDK package
- **Days 7-8**: Integration
- **Days 9-12**: Migrate built-ins
- **Days 13-14**: Testing and documentation

**Total**: 14 days

## References

- RFC-0018: Plugin Extension Specification
- RFC-0001: System Conceptual Design
- RFC-0002: Core Modules Architecture Design
- FastAPI decorator patterns
- Click decorator patterns
- Python entry points documentation

---

**Implementation Status**: Not Started
**Last Updated**: 2026-03-24