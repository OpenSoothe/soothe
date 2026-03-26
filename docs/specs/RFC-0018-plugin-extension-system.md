# RFC-0018: Plugin Extension Specification

**RFC**: 0018
**Title**: Plugin Extension Specification
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-03-23
**Updated**: 2026-03-24
**Dependencies**: RFC-0001, RFC-0002, RFC-0008, RFC-0013
**Related**: RFC-0015

## Abstract

This RFC defines a standardized plugin system for Soothe that enables third-party developers to create, distribute, and integrate custom **tools** and **subagents** with clear lifecycle management, dependency declaration, and security boundaries. The specification defines a `Plugin` protocol, decorator-based API (`@plugin`, `@tool`, `@subagent`), manifest schema, discovery mechanisms, and configuration integration that preserve Soothe's protocol-first architecture while enabling a vibrant plugin ecosystem.

## Motivation

### Problem Statement

Current tool and subagent integration follows an ad-hoc pattern with several limitations:

1. **No standard entry point**: Each tool/subagent defines its own factory signature with varying parameter names and types
2. **Manual registration**: Tool factories must be added to `resolve_tools()` and subagent factories to `SUBAGENT_FACTORIES`, requiring code changes
3. **No dependency declaration**: Tools and subagents cannot declare required external libraries, leading to runtime failures
4. **No lifecycle hooks**: No standardized `on_load()`, `on_unload()`, or `health_check()` methods for resource management
5. **Limited discovery**: Only hardcoded imports and manual registration; no entry point or filesystem discovery
6. **No configuration schema**: Plugin-specific configuration is untyped `dict[str, Any]` with no validation
7. **No security model**: All plugins run with full orchestrator permissions, no trust levels

### Design Goals

1. **Decorator-based API**: Simple `@plugin`, `@tool`, `@subagent` decorators for clean, declarative code
2. **Standardized lifecycle**: `on_load()`, `on_unload()`, and `health_check()` hooks for resource management
3. **Multiple discovery mechanisms**: Python entry points, config declarations, filesystem scanning
4. **Dependency resolution**: Automatic checking of library and configuration requirements
5. **Configuration integration**: Plugin-specific config that extends `SootheConfig`
6. **Security model**: Trust levels (built-in, trusted, standard, untrusted) for access control
7. **Backward compatibility**: Existing tools and subagents work unchanged via adapters
8. **Graceful degradation**: Missing dependencies or failed initialization disables the plugin, not the orchestrator

### Non-Goals

- **Code signing and verification**: Future enhancement for cryptographically signed extensions
- **Extension marketplace**: Central registry for publishing and discovering extensions
- **Hot reloading**: Dynamic loading/unloading without orchestrator restart
- **Sandboxing**: Process isolation or WASM-based sandboxing for untrusted extensions

## Guiding Principles

### Principle 1: Decorator-Based Simplicity

Plugins use Python decorators (`@plugin`, `@tool`, `@subagent`) for clean, declarative code. No complex class hierarchies or protocol implementations required. Inspired by FastAPI and Click for developer-friendly APIs.

### Principle 2: Explicit Over Implicit

Plugins explicitly declare dependencies and configuration requirements in their manifest. No runtime introspection, magic discovery, or implicit dependencies. Everything needed to validate and load a plugin is declared upfront.

### Principle 3: Graceful Degradation

Missing dependencies, failed imports, and configuration errors result in disabled plugins, not orchestrator startup failures. The system continues with available capabilities. Required vs. optional dependencies determine whether a plugin can load.

### Principle 4: Security by Default

Third-party plugins run with restricted permissions based on trust levels. Built-in plugins are trusted by default. Explicit user approval required for elevated permissions.

### Principle 5: Deepagents Compatibility

All plugin subagents return deepagents `SubAgent` or `CompiledSubAgent` types. All plugin tools are langchain `BaseTool` instances. No new runtime types. Plugins integrate seamlessly with existing Soothe infrastructure.

## Architecture

### Component Overview

```
┌─────────────────────────────────────────────────────────┐
│                 Plugin System                            │
│                                                         │
│  ┌─────────────────┐       ┌─────────────────┐        │
│  │  Discovery      │       │   Manifest      │        │
│  │  Engine         │──────▶│   Registry      │        │
│  │                 │       │                 │        │
│  │ - Entry Points  │       │ - Validation    │        │
│  │ - Config Decl   │       │ - Storage       │        │
│  │ - Filesystem    │       │ - Lookup        │        │
│  └─────────────────┘       └─────────────────┘        │
│                                    │                   │
│                                    ▼                   │
│                          ┌─────────────────┐          │
│                          │  Dependency     │          │
│                          │  Resolver       │          │
│                          │                 │          │
│                          │ - Libraries     │          │
│                          │ - Config values │          │
│                          └─────────────────┘          │
│                                    │                   │
│                                    ▼                   │
│                          ┌─────────────────┐          │
│                          │  Plugin         │          │
│                          │  Loader         │          │
│                          │                 │          │
│                          │ - Import        │          │
│                          │ - on_load()     │          │
│                          │ - Register      │          │
│                          └─────────────────┘          │
│                                    │                   │
│                                    ▼                   │
│                          ┌─────────────────┐          │
│                          │  Plugin         │          │
│                          │  Registry       │          │
│                          │                 │          │
│                          │ Tools & Subs   │          │
│                          └─────────────────┘          │
│                                    │                   │
└────────────────────────────────────┼───────────────────┘
                                     │
                                     ▼
                          ┌─────────────────┐
                          │  resolve_tools()│
                          │  resolve_subs() │
                          └─────────────────┘
                                     │
                                     ▼
                          ┌─────────────────┐
                          │  SootheRunner   │
                          └─────────────────┘
```

### Extension Points

The plugin system supports two extension points:

1. **Tools**: Register tool groups and individual tools
2. **Subagents**: Register subagent modules

```python
from enum import Enum

class ExtensionPoint(str, Enum):
    """Supported plugin extension points."""
    TOOLS = "tools"
    SUBAGENTS = "subagents"
```

### Loading Sequence

```
┌─────────────────────────────────────────────────────────┐
│ Phase 1: Discovery                                       │
│                                                         │
│  ├─ Scan Python entry_points: "soothe.plugins"         │
│  ├─ Load config-declared: plugins list                 │
│  ├─ Scan filesystem: ~/.soothe/plugins/*/              │
│  └─ Register manifests in PluginRegistry               │
│     (Priority: built-in > entry_point > config > fs)   │
└─────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 2: Validation                                      │
│                                                         │
│  ├─ Validate manifest schema (Pydantic)                │
│  ├─ Check Python version compatibility                 │
│  ├─ Check Soothe version compatibility                 │
│  └─ Calculate trust level                              │
└─────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 3: Dependency Resolution                           │
│                                                         │
│  ├─ Check library dependencies (pip packages)          │
│  ├─ Check configuration dependencies (API keys, etc.)  │
│  └─ Determine loadability (required vs. optional)      │
└─────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 4: Initialization                                  │
│                                                         │
│  ├─ Import module (dynamic importlib)                  │
│  ├─ Call on_load(context) hook                         │
│  ├─ Register tools in tool registry                    │
│  ├─ Register subagents in subagent registry            │
│  └─ Emit soothe.plugin.loaded event                    │
└─────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 5: Runtime                                         │
│                                                         │
│  ├─ Tools available to agent via tool registry         │
│  ├─ Subagents available via task tool                  │
│  ├─ Periodic health checks (optional)                  │
│  └─ Trust level enforcement                            │
└─────────────────────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────┐
│ Phase 6: Shutdown                                        │
│                                                         │
│  ├─ Call on_unload() hook                              │
│  ├─ Clean up resources                                 │
│  └─ Emit soothe.plugin.unloaded event                  │
└─────────────────────────────────────────────────────────┘
```

## Specification

### 1. Decorator-Based Plugin API

Soothe provides a decorator-based API for defining plugins, inspired by FastAPI and Click. This allows developers to create tools and subagents with minimal boilerplate.

#### 1.1 @plugin Decorator

The `@plugin` decorator marks a class as a Soothe plugin and defines its metadata.

```python
from soothe_sdk import plugin

@plugin(
    name="my-plugin",
    version="1.0.0",
    description="My awesome plugin",
    author="Developer Name",
    dependencies=["langchain>=0.1.0"],  # Library dependencies
    trust_level="standard",  # built-in, trusted, standard, untrusted
)
class MyPlugin:
    """Plugin with lifecycle hooks."""

    async def on_load(self, context):
        """Called when plugin is loaded. Set up resources here."""
        self.api_key = context.config.get("api_key")
        self.logger = context.logger

    async def on_unload(self):
        """Called when plugin is unloaded. Clean up resources."""
        pass

    async def health_check(self):
        """Return plugin health status."""
        from soothe_sdk.types import PluginHealth
        return PluginHealth(status="healthy")
```

**Plugin Manifest Fields**:

- `name` (required): Unique plugin identifier (lowercase, hyphenated)
- `version` (required): Semantic version (e.g., "1.0.0")
- `description` (required): Human-readable description
- `author` (optional): Author name or organization
- `dependencies` (optional): List of library dependencies (PEP 440 format)
- `trust_level` (optional): One of "built-in", "trusted", "standard", "untrusted" (default: "standard")

#### 1.2 @tool Decorator

The `@tool` decorator registers a method as a langchain tool.

```python
from soothe_sdk import plugin, tool

@plugin(name="greeting-tools", version="1.0.0")
class GreetingPlugin:
    @tool(name="greet", description="Greet someone by name")
    def greet(self, name: str) -> str:
        """Greet a person."""
        return f"Hello, {name}!"

    @tool(name="farewell", description="Say goodbye")
    def farewell(self, name: str) -> str:
        """Say farewell."""
        return f"Goodbye, {name}!"
```

**Tool Decorator Fields**:

- `name` (required): Tool name
- `description` (required): Tool description for the LLM
- `group` (optional): Tool group name (default: plugin name)

#### 1.3 @tool_group Decorator

The `@tool_group` decorator defines a collection of related tools.

```python
from soothe_sdk import plugin, tool_group, tool

@plugin(name="research", version="1.0.0")
class ResearchPlugin:
    @tool_group(name="research", description="Academic research tools")
    class ResearchTools:
        @tool(name="arxiv")
        def search_arxiv(self, query: str) -> list:
            """Search ArXiv papers."""
            pass

        @tool(name="scholar")
        def search_scholar(self, query: str) -> list:
            """Search Google Scholar."""
            pass
```

#### 1.4 @subagent Decorator

The `@subagent` decorator registers a subagent factory function.

```python
from soothe_sdk import plugin, subagent

@plugin(name="research", version="1.0.0")
class ResearchPlugin:
    @subagent(
        name="researcher",
        description="Research subagent with web search",
        model="openai:gpt-4o-mini",  # Default model
    )
    async def create_researcher(self, model, config, context):
        """Create research subagent instance."""
        from langgraph.prebuilt import create_react_agent

        # Get tools from this plugin
        tools = [self.my_tool]

        # Create agent
        agent = create_react_agent(model, tools)

        return {
            "name": "researcher",
            "description": "Research subagent with web search",
            "runnable": agent,
        }
```

**Subagent Decorator Fields**:

- `name` (required): Subagent name
- `description` (required): Subagent description for the `task` tool
- `model` (optional): Default model string (e.g., "openai:gpt-4o-mini")

### 1.5 Plugin Context

The `context` parameter provides access to Soothe internals.

**PluginContext Fields**:

- `config`: Plugin-specific configuration dict
- `soothe_config`: Global `SootheConfig` instance
- `logger`: Python logger instance
- `emit_event(name, data)`: Emit a plugin event

### 2. Manifest Schema

The manifest is defined by the `@plugin` decorator and stored as a `PluginManifest` Pydantic model.

```python
from datetime import datetime
from typing import Literal, Any
from pydantic import BaseModel, Field, ConfigDict


class PluginManifest(BaseModel):
    """Complete plugin manifest.

    Attributes:
        name: Unique plugin identifier (lowercase, hyphenated).
        version: Semantic version string (e.g., "1.0.0").
        description: Human-readable description.
        author: Author name or organization.
        homepage: Project homepage URL.
        repository: Source repository URL.
        license: License identifier (SPDX format).
        dependencies: List of library dependencies (PEP 440 format).
        python_version: Python version constraint (PEP 440).
        soothe_version: Soothe version constraint (PEP 440).
        trust_level: Trust level for security.
        created_at: Manifest creation timestamp.
        updated_at: Last update timestamp.
    """

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

### 3. Discovery Mechanism

#### 3.1 Python Entry Points

Plugin packages declare themselves via Python entry points in `pyproject.toml`:

```toml
[project.entry-points."soothe.plugins"]
my_plugin = "my_package:MyPlugin"
```

#### 3.2 Config-Declared Plugins

Users can declare plugins directly in `config.yml`:

```yaml
plugins:
  - name: my-custom-plugin
    enabled: true
    module: "my_package:MyPlugin"
    config:
      api_key: "${MY_API_KEY}"
```

#### 3.3 Filesystem Discovery

Plugins can be placed in `~/.soothe/plugins/<name>/` with `plugin.py` or `__init__.py`.

#### 3.4 Priority and Conflict Resolution

Priority levels (higher = preferred):
- Built-in: 100
- Entry point: 50
- Config: 30
- Filesystem: 10

When multiple sources provide the same plugin name, the highest priority source is used.

### 4. Dependency Declaration

Plugins declare dependencies in the `@plugin` decorator using PEP 440 version specifiers.

#### 4.1 Library Dependencies

```python
@plugin(
    name="research",
    version="1.0.0",
    dependencies=["arxiv>=2.0.0", "langchain>=0.1.0"],
)
class ResearchPlugin:
    pass
```

Dependencies are checked at load time. Missing required dependencies prevent plugin loading.

#### 4.2 Configuration Dependencies

Plugins can declare required configuration values using dot-separated paths:

```python
@plugin(
    name="my-plugin",
    version="1.0.0",
    config_requirements=["providers.openai.api_key"],
)
class MyPlugin:
    pass
```

### 5. Configuration Integration

#### 5.1 Configuration Schema

Extend `SootheConfig` with plugin configuration:

```python
class PluginConfig(BaseModel):
    """Configuration for a single plugin."""
    name: str
    enabled: bool = True
    module: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
```

#### 5.2 Environment Variable Substitution

Plugin configuration supports `${VAR_NAME}` and `${VAR_NAME:-default}` syntax for environment variable substitution.

### 6. Event Integration

#### 6.1 Plugin Events

| Event Type | Description | Fields |
|------------|-------------|--------|
| `soothe.plugin.loaded` | Plugin successfully loaded | name, version, source |
| `soothe.plugin.failed` | Plugin failed to load | name, error, phase |
| `soothe.plugin.unloaded` | Plugin unloaded | name |
| `soothe.plugin.health_checked` | Health check completed | name, status, message |

#### 6.2 Event Emission

Events are emitted during plugin lifecycle phases (discovery, validation, dependency resolution, initialization, shutdown).

### 7. Security Model

#### 7.1 Trust Levels

| Trust Level | Filesystem | Network | Subprocess | Description |
|-------------|------------|---------|------------|-------------|
| built-in | Full | Full | Yes | Core Soothe plugins |
| trusted | Full | Full | Yes | Signed third-party (future) |
| standard | Read/Write | Full | No | Default for unsigned plugins |
| untrusted | None | None | No | Requires explicit approval |

#### 7.2 Permission Enforcement

Permissions are enforced at the plugin loader level based on trust level. Filesystem, network, and subprocess access can be restricted.

### 8. Loading Lifecycle

#### 8.1 Lifecycle Manager

```python
from typing import Dict
import asyncio


class PluginLifecycleManager:
    """Manage plugin lifecycle."""

    def __init__(self, registry: PluginRegistry):
        self.registry = registry
        self.loaded_plugins: dict[str, Any] = {}  # plugin_name -> plugin_instance

    async def load_all(self, config: SootheConfig) -> dict[str, Any]:
        """Load all discovered and validated plugins.

        Args:
            config: Resolved Soothe configuration.

        Returns:
            Map of name -> loaded plugin instance for successful loads.
        """
        loaded = {}

        # Phase 1: Discovery
        await self._discover_all()
        logger.info(f"Discovered {len(self.registry.list_all())} plugins")

        # Phase 2: Validation
        validated = self._validate_all()
        logger.info(f"Validated {len(validated)} plugins")

        # Phase 3: Dependency Resolution
        resolved = self._resolve_dependencies_all(validated, config)
        logger.info(f"Resolved dependencies for {len(resolved)} plugins")

        # Phase 4: Initialization
        for name, entry in resolved.items():
            try:
                plugin_instance = await self._load_plugin(entry, config)
                loaded[name] = plugin_instance
                self.loaded_plugins[name] = plugin_instance

                logger.info(f"Loaded plugin '{name}'")
            except Exception:
                logger.exception(f"Failed to initialize plugin '{name}'")

        return loaded

    async def shutdown_all(self) -> None:
        """Shutdown all loaded plugins."""
        for name, plugin in self.loaded_plugins.items():
            try:
                if hasattr(plugin, 'on_unload'):
                    await plugin.on_unload()
                logger.info(f"Shutdown plugin '{name}'")
            except Exception:
                logger.exception(f"Failed to shutdown plugin '{name}'")

    async def _discover_all(self) -> None:
        """Run all discovery mechanisms."""
        # Entry points
        for module_path in discover_entry_points():
            # Load and register
            pass

        # Config-declared
        # ...

        # Filesystem
        for module_path in discover_filesystem():
            # Load and register
            pass

    def _validate_all(self) -> dict[str, RegistryEntry]:
        """Validate all manifests.

        Returns:
            Map of name -> entry for valid manifests.
        """
        validated = {}

        for entry in self.registry.list_all():
            errors = validate_manifest(entry.manifest)
            if errors:
                logger.error(
                    f"Manifest validation failed for '{entry.manifest.name}': {errors}"
                )
                continue

            validated[entry.manifest.name] = entry

        return validated

    def _resolve_dependencies_all(
        self,
        entries: dict[str, RegistryEntry],
        config: SootheConfig,
    ) -> dict[str, RegistryEntry]:
        """Resolve dependencies for all manifests.

        Returns:
            Map of name -> entry for manifests with satisfied dependencies.
        """
        resolved = {}

        for name, entry in entries.items():
            missing = resolve_dependencies(entry.manifest, config)

            if missing:
                logger.error(
                    f"Missing dependencies for '{name}': {missing}"
                )
                continue

            resolved[name] = entry

        return resolved

    async def _load_plugin(self, entry: RegistryEntry, config: SootheConfig) -> Any:
        """Load the plugin for a registry entry.

        Args:
            entry: Registry entry with manifest.
            config: Soothe configuration.

        Returns:
            Loaded plugin instance.
        """
        # Import module
        module_path = entry.source  # e.g., "my_package:MyPlugin"
        module_name, class_name = module_path.split(":")

        module = importlib.import_module(module_name)
        plugin_class = getattr(module, class_name)

        # Instantiate
        plugin_instance = plugin_class()

        # Call on_load
        if hasattr(plugin_instance, 'on_load'):
            context = PluginContext(
                config=config.get_plugin_config(entry.manifest.name),
                soothe_config=config,
                logger=logging.getLogger(f"soothe.plugins.{entry.manifest.name}"),
            )
            await plugin_instance.on_load(context)

        return plugin_instance
```

### 9. Error Handling

#### 9.1 Error Types

```python
class PluginError(Exception):
    """Base error for plugin system."""
    pass


class DiscoveryError(PluginError):
    """Error during plugin discovery."""
    pass


class ValidationError(PluginError):
    """Error during manifest validation."""
    pass


class DependencyError(PluginError):
    """Error during dependency resolution."""
    pass


class InitializationError(PluginError):
    """Error during plugin initialization."""
    pass


class ToolCreationError(PluginError):
    """Error during tool creation."""
    pass


class SubagentCreationError(PluginError):
    """Error during subagent instance creation."""
    pass
```

#### 9.2 Error Recovery

```python
from typing import Optional


async def load_plugin_safe(
    plugin_class,
    config: SootheConfig,
) -> Any | None:
    """Load plugin with comprehensive error handling.

    Args:
        plugin_class: Plugin class to load.
        config: Soothe configuration.

    Returns:
        Loaded plugin instance or None if failed.
    """
    try:
        # Instantiate
        plugin_instance = plugin_class()

        # Get manifest
        manifest = plugin_instance.manifest
        name = manifest.name

        # Validate manifest
        errors = validate_manifest(manifest)
        if errors:
            logger.error(f"Manifest validation failed for '{name}': {errors}")
            return None

        # Resolve dependencies
        missing = resolve_dependencies(manifest, config)
        if missing:
            logger.error(f"Missing dependencies for '{name}': {missing}")
            return None

        # Initialize
        if hasattr(plugin_instance, 'on_load'):
            context = PluginContext(
                config=config.get_plugin_config(name),
                soothe_config=config,
                logger=logging.getLogger(f"soothe.plugins.{name}"),
            )
            await plugin_instance.on_load(context)

        return plugin_instance

    except InitializationError:
        logger.exception(f"Initialization failed")
        return None
    except Exception:
        logger.exception(f"Unexpected error loading plugin")
        return None
```

### 10. Migration Path

#### 10.1 Migrating Existing Subagents

**Before (browser subagent)**:

```python
# src/soothe/subagents/browser.py

def create_browser_subagent(
    model: Any = None,
    *,
    headless: bool = True,
    max_steps: int = 100,
    use_vision: bool = True,
    **kwargs: Any,
) -> CompiledSubAgent:
    """Create browser automation subagent."""
    # ... implementation ...
    return {
        "name": "browser",
        "description": "Navigate and interact with web pages",
        "runnable": runnable,
    }
```

**After (browser plugin)**:

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
        # ... same implementation as before ...
        return {
            "name": "browser",
            "description": "Navigate and interact with web pages",
            "runnable": runnable,
        }


# Backward compatibility wrapper in old location
# src/soothe/subagents/browser.py

from soothe.plugins.browser import BrowserPlugin

_plugin_instance = BrowserPlugin()

def create_browser_subagent(*args, **kwargs):
    """Backward-compatible factory function."""
    return _plugin_instance.create_browser_subagent(*args, **kwargs)

BROWSER_DESCRIPTION = "Navigate and interact with web pages"
```

#### 10.2 Migrating Existing Tools

**Before (execution tools)**:

```python
# src/soothe/tools/execution.py

def create_execution_tools(workspace_root: str | None = None) -> list[BaseTool]:
    """Create execution tool group."""
    return [
        ShellExecuteTool(workspace_root=workspace_root),
        # ... more tools ...
    ]
```

**After (execution tools plugin)**:

```python
# src/soothe/plugins/execution/__init__.py

from soothe_sdk import plugin, tool_group, tool

@plugin(
    name="execution",
    version="1.0.0",
    description="Shell execution tools",
    trust_level="built-in",
)
class ExecutionPlugin:
    """Execution tools plugin."""

    @tool_group(name="execution", description="Shell execution tools")
    class ExecutionTools:
        @tool(name="shell_execute", description="Execute shell commands")
        def shell_execute(self, command: str) -> str:
            # ... implementation ...
            pass

        @tool(name="python_execute", description="Execute Python code")
        def python_execute(self, code: str) -> str:
            # ... implementation ...
            pass


# Backward compatibility wrapper
# src/soothe/tools/execution.py

from soothe.plugins.execution import ExecutionPlugin

_plugin_instance = ExecutionPlugin()

def create_execution_tools(workspace_root: str | None = None) -> list[BaseTool]:
    """Backward-compatible factory function."""
    # Extract tools from plugin
    return [
        _plugin_instance.ExecutionTools().shell_execute,
        _plugin_instance.ExecutionTools().python_execute,
    ]
```

#### 10.3 Backward Compatibility Guarantees

1. **Existing factory functions work**: `create_<name>_subagent()` and `create_<name>_tools()` continue to work
2. **Old imports work**: `from soothe.subagents.browser import create_browser_subagent` still works
3. **Config compatibility**: Existing `subagents.browser` config format still supported
4. **No breaking changes**: All existing imports and APIs continue to work
5. **Gradual migration**: Components can be migrated one at a time

#### 10.4 Deprecation Timeline

- **v0.2.0**: Introduce plugin system, publish migration guide
- **v0.3.0**: Deprecation warnings for old-style factories
- **v0.4.0**: Remove old-style factory support, require plugin API

## Configuration Examples

### Complete YAML Configuration

```yaml
# config.yml

# Plugin system configuration
plugins:
  # Built-in plugins (auto-loaded)
  - name: browser
    enabled: true
    config:
      headless: true
      max_steps: 100
      use_vision: true

  - name: claude
    enabled: true

  - name: skillify
    enabled: true

  - name: weaver
    enabled: true

  # Third-party plugins
  - name: research-assistant
    enabled: true
    module: "my_package:ResearchPlugin"
    config:
      arxiv_api_key: "${ARXIV_API_KEY}"
      max_results: 10

  - name: custom-tools
    enabled: false
    module: "custom.plugin:CustomPlugin"
    config:
      option: value
```

### Plugin Manifest Example

**manifest.yml** (for filesystem-discovered plugins):

```yaml
name: research-assistant
version: 1.0.0
description: Research assistant with ArXiv and web search capabilities
author: Research Team
homepage: https://github.com/example/research-assistant
license: MIT

dependencies:
  - arxiv>=2.0.0
  - langchain>=0.1.0

python_version: ">=3.11"
soothe_version: ">=0.1.0"

trust_level: standard
```

### Plugin Code Example

**Complete plugin with tools and subagent**:

```python
# my_package/__init__.py
from soothe_sdk import plugin, tool, tool_group, subagent

@plugin(
    name="research-assistant",
    version="1.0.0",
    description="Research assistant with ArXiv and web search",
    dependencies=["arxiv>=2.0.0"],
)
class ResearchPlugin:
    """Research assistant plugin with tools and subagent."""

    async def on_load(self, context):
        """Initialize plugin."""
        import arxiv
        self.arxiv_client = arxiv.Client()
        self.logger = context.logger
        self.max_results = context.config.get("max_results", 10)

    async def on_unload(self):
        """Clean up."""
        pass

    # Tool group with multiple tools
    @tool_group(name="research", description="Academic research tools")
    class ResearchTools:
        @tool(name="arxiv_search", description="Search ArXiv papers")
        def search_arxiv(self, query: str) -> list:
            """Search ArXiv for papers."""
            # ... implementation ...
            pass

        @tool(name="scholar_search", description="Search Google Scholar")
        def search_scholar(self, query: str) -> list:
            """Search Google Scholar."""
            # ... implementation ...
            pass

    # Subagent
    @subagent(
        name="researcher",
        description="Research subagent with academic search tools",
        model="openai:gpt-4o-mini",
    )
    async def create_researcher(self, model, config, context):
        """Create research subagent."""
        from langgraph.prebuilt import create_react_agent

        # Get tools from this plugin
        tools = [
            self.ResearchTools().search_arxiv,
            self.ResearchTools().search_scholar,
        ]

        # Create agent
        agent = create_react_agent(model, tools)

        return {
            "name": "researcher",
            "description": "Research subagent",
            "runnable": agent,
        }

# Entry point declaration in pyproject.toml:
# [project.entry-points."soothe.plugins"]
# research = "my_package:ResearchPlugin"
```

## Implementation Checklist

### Core Implementation

- [ ] Define `PluginManifest` Pydantic model in `src/soothe/plugin/manifest.py`
- [ ] Define `PluginContext` in `src/soothe/plugin/context.py`
- [ ] Create `PluginRegistry` in `src/soothe/plugin/registry.py`
- [ ] Implement `PluginLoader` in `src/soothe/plugin/loader.py`
- [ ] Implement `PluginLifecycleManager` in `src/soothe/plugin/lifecycle.py`
- [ ] Integrate with `SootheConfig` in `src/soothe/config/settings.py`
- [ ] Add to `config/config.yml` template

### SDK Implementation

- [ ] Create `soothe_sdk` package structure
- [ ] Implement `@plugin` decorator in `src/soothe_sdk/decorators/plugin.py`
- [ ] Implement `@tool` decorator in `src/soothe_sdk/decorators/tool.py`
- [ ] Implement `@tool_group` decorator in `src/soothe_sdk/decorators/tool.py`
- [ ] Implement `@subagent` decorator in `src/soothe_sdk/decorators/subagent.py`
- [ ] Create `PluginContext` type in `src/soothe_sdk/types/context.py`
- [ ] Implement dependency helpers in `src/soothe_sdk/depends.py`

### Discovery Implementation

- [ ] Implement entry point discovery (`discover_entry_points()`)
- [ ] Implement config-declared discovery (`discover_config_declared()`)
- [ ] Implement filesystem discovery (`discover_filesystem()`)
- [ ] Add priority/conflict resolution in `PluginRegistry`

### Integration

- [ ] Modify `src/soothe/core/agent.py` to load plugins
- [ ] Modify `src/soothe/core/resolver/__init__.py` to use plugin registry
- [ ] Modify `src/soothe/core/resolver/_resolver_tools.py` to use plugin tool registry
- [ ] Add `PluginConfig` to `src/soothe/config/models.py`

### Migration

- [ ] Create browser plugin in `src/soothe/plugins/browser/`
- [ ] Create claude plugin in `src/soothe/plugins/claude/`
- [ ] Create skillify plugin in `src/soothe/plugins/skillify/`
- [ ] Create weaver plugin in `src/soothe/plugins/weaver/`
- [ ] Create core_tools plugin in `src/soothe/plugins/core_tools/`
- [ ] Add backward compatibility wrappers in old locations

### Testing

- [ ] Unit tests for manifest validation
- [ ] Unit tests for plugin decorators
- [ ] Unit tests for plugin registry
- [ ] Unit tests for lifecycle management
- [ ] Integration tests for discovery mechanisms
- [ ] Integration tests for tool registration
- [ ] Integration tests for subagent registration
- [ ] End-to-end tests for plugin loading

### Documentation

- [ ] Update CLAUDE.md with plugin system overview
- [ ] Create plugin developer guide (`docs/plugin_development.md`)
- [ ] Create migration guide (`docs/plugin_migration.md`)
- [ ] Add examples to `examples/plugins/`
- [ ] Update API reference with SDK documentation

## Security Considerations

### Threat Model

1. **Malicious plugins**: Plugins could contain malicious code
2. **Dependency confusion**: Attacker publishes malicious package with same name
3. **Resource exhaustion**: Poorly written plugins consume excessive resources
4. **Data exfiltration**: Plugins leak sensitive data through network/file access

### Mitigations

1. **Trust levels**: Built-in plugins are trusted by default, third-party run with restricted permissions
2. **Permission enforcement**: Permission boundaries based on trust level
3. **Dependency verification**: Check library versions against constraints
4. **Resource limits**: Timeout initialization, limit memory/CPU usage
5. **Audit logging**: Log all plugin actions for security review

### Best Practices

1. **Principle of least privilege**: Plugins run with minimum permissions needed
2. **Explicit user consent**: User approves elevated permissions
3. **Code review**: Review plugin code before installation
4. **Signed plugins**: Future support for cryptographic signatures
5. **Sandbox consideration**: Future support for containerized/WASM plugins

## Future Enhancements

1. **Cryptographic signing**: GPG/SSH key signing for plugins
2. **Plugin marketplace**: Central registry for third-party plugins
3. **Hot reloading**: Load/unload plugins without orchestrator restart
4. **Plugin versioning**: Support multiple versions simultaneously
5. **Sandboxing**: Use containers/WASM for untrusted plugins
6. **Protocol extensions**: Extend plugin system to support protocol implementations
7. **Middleware extensions**: Support middleware plugins
8. **Command extensions**: Support slash command plugins
9. **Plugin dependencies**: Allow plugins to depend on other plugins
10. **Performance monitoring**: Track plugin performance and resource usage

## References

- RFC-0001: System Conceptual Design
- RFC-0002: Core Modules Architecture Design
- RFC-0008: Agentic Loop Execution Architecture
- RFC-0013: Unified Daemon Communication Protocol
- RFC-0015: Authentication and Security Model
- PEP 440: Version Identification and Dependency Specification
- PEP 517: A Build System Independent Format
- Python Packaging User Guide: Entry Points

---

**Document Status**: Draft
**Last Updated**: 2026-03-24
**Review Status**: Pending Review
