# RFC-600: Plugin Extension Specification

**RFC**: 600
**Title**: Plugin Extension Specification
**Status**: Implemented
**Kind**: Architecture Design
**Created**: 2026-03-23
**Updated**: 2026-03-27
**Dependencies**: RFC-000, RFC-001, RFC-200, RFC-400
**Related**: RFC-400

## Abstract

This RFC defines a standardized plugin system for Soothe enabling third-party developers to create, distribute, and integrate custom tools and subagents with clear lifecycle management, dependency declaration, and security boundaries. The specification provides a `Plugin` protocol, decorator-based API (`@plugin`, `@tool`, `@subagent`), manifest schema, discovery mechanisms, and configuration integration that preserve Soothe's protocol-first architecture.

## Problem Statement

Current tool and subagent integration has several limitations:

1. **No standard entry point** - Varying factory signatures
2. **Manual registration** - Requires code changes
3. **No dependency declaration** - Runtime failures from missing libraries
4. **No lifecycle hooks** - No standardized `on_load()`, `on_unload()`, `health_check()` methods
5. **Limited discovery** - Only hardcoded imports
6. **No configuration schema** - Untyped configuration
7. **No security model** - All plugins run with full permissions

## Design Goals

1. **Decorator-based API** - Clean, declarative code
2. **Standardized lifecycle** - Resource management hooks
3. **Multiple discovery mechanisms** - Entry points, config, filesystem
4. **Dependency resolution** - Automatic requirement checking
5. **Configuration integration** - Plugin-specific config extending `SootheConfig`
6. **Security model** - Trust levels for access control
7. **Backward compatibility** - Existing tools/subagents work via adapters
8. **Graceful degradation** - Missing dependencies disable plugin, not orchestrator

## Guiding Principles

1. **Decorator-Based Simplicity** - Use `@plugin`, `@tool`, `@subagent` for clean code (inspired by FastAPI/Click)
2. **Explicit Over Implicit** - Declare all dependencies upfront in manifest
3. **Graceful Degradation** - Failures result in disabled plugins, not orchestrator crashes
4. **Security by Default** - Third-party plugins run with restricted permissions
5. **Deepagents Compatibility** - Return `SubAgent`/`CompiledSubAgent` and `BaseTool` types

## Architecture

### Component Flow

```
Discovery Engine → Manifest Registry → Dependency Resolver → Plugin Loader → Tool/Subagent Registry
```

**Components**:
- **Discovery Engine**: Entry points, config declarations, filesystem scanning
- **Manifest Registry**: Validation, storage, lookup of plugin metadata
- **Dependency Resolver**: Library and configuration dependency checking
- **Plugin Loader**: Import, `on_load()` hook, tool/subagent registration
- **Plugin Registry**: Runtime tool and subagent lookup for `resolve_tools()`, `resolve_subs()`

### Extension Points

- **Tools**: Register tool groups and individual tools (`ExtensionPoint.TOOLS`)
- **Subagents**: Register subagent modules (`ExtensionPoint.SUBAGENTS`)

### Loading Phases

1. **Discovery** - Scan entry points, config, filesystem
2. **Validation** - Validate manifest schema, version compatibility
3. **Dependency Resolution** - Check libraries and config requirements
4. **Initialization** - Import module, call `on_load()`, register tools/subagents
5. **Runtime** - Tools/subagents available to agent, health checks
6. **Shutdown** - Call `on_unload()`, cleanup resources

**Priority**: built-in (100) > entry_point (50) > config (30) > filesystem (10)

## Specification

### 1. Plugin API

#### @plugin Decorator

```python
@plugin(
    name="my-plugin",
    version="1.0.0",
    description="My awesome plugin",
    dependencies=["langchain>=0.1.0"],
    trust_level="standard",
)
class MyPlugin:
    async def on_load(self, context):
        """Initialize resources."""
        self.api_key = context.config.get("api_key")

    async def on_unload(self):
        """Cleanup resources."""

    async def health_check(self):
        """Return health status."""
        return PluginHealth(status="healthy")
```

**Manifest Fields**:
- `name` (required): Unique identifier (lowercase, hyphenated)
- `version` (required): Semantic version
- `description` (required): Human-readable description
- `dependencies` (optional): Library dependencies (PEP 440)
- `trust_level` (optional): "built-in", "trusted", "standard", "untrusted" (default: "standard")

#### @tool Decorator

```python
@tool(name="greet", description="Greet someone")
def greet(self, name: str) -> str:
    return f"Hello, {name}!"
```

**Fields**: `name` (required), `description` (required), `group` (optional)

#### @subagent Decorator

```python
@subagent(name="researcher", description="Research agent", model="openai:gpt-4o-mini")
async def create_researcher(self, model, config, context):
    agent = create_react_agent(model, tools)
    return {"name": "researcher", "description": "...", "runnable": agent}
```

**Fields**: `name` (required), `description` (required), `model` (optional)

#### PluginContext

- `config`: Plugin-specific configuration dict
- `soothe_config`: Global `SootheConfig` instance
- `logger`: Python logger instance
- `emit_event(name, data)`: Emit plugin event

### 2. Manifest Schema

```python
class PluginManifest(BaseModel):
    name: str
    version: str
    description: str
    author: str = ""
    dependencies: list[str] = Field(default_factory=list)
    python_version: str = ">=3.11"
    soothe_version: str = ">=0.1.0"
    trust_level: Literal["built-in", "trusted", "standard", "untrusted"] = "standard"
    created_at: datetime = Field(default_factory=datetime.utcnow)
```

### 3. Discovery Mechanisms

#### Entry Points (pyproject.toml)

```toml
[project.entry-points."soothe.plugins"]
my_plugin = "my_package:MyPlugin"
```

#### Config-Declared (config.yml)

```yaml
plugins:
  - name: my-custom-plugin
    enabled: true
    module: "my_package:MyPlugin"
    config:
      api_key: "${MY_API_KEY}"
```

#### Filesystem

Plugins in `~/.soothe/plugins/<name>/` with `plugin.py` or `__init__.py`.

### 4. Dependencies

#### Library Dependencies

```python
@plugin(name="research", dependencies=["arxiv>=2.0.0", "langchain>=0.1.0"])
class ResearchPlugin:
    pass
```

Missing dependencies prevent plugin loading.

#### Configuration Dependencies

```python
@plugin(name="my-plugin", config_requirements=["providers.openai.api_key"])
class MyPlugin:
    pass
```

### 5. Configuration Integration

```python
class PluginConfig(BaseModel):
    name: str
    enabled: bool = True
    module: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
```

Supports `${VAR_NAME}` and `${VAR_NAME:-default}` substitution.

### 6. Events

| Event | Description |
|-------|-------------|
| `soothe.plugin.loaded` | Plugin loaded successfully |
| `soothe.plugin.failed` | Plugin failed to load |
| `soothe.plugin.unloaded` | Plugin unloaded |
| `soothe.plugin.health_checked` | Health check completed |

### 7. Security Model

| Trust Level | Filesystem | Network | Subprocess |
|-------------|------------|---------|------------|
| built-in | Full | Full | Yes |
| trusted | Full | Full | Yes |
| standard | Read/Write | Full | No |
| untrusted | None | None | No |

Permissions enforced at plugin loader level based on trust level.

### 8. Error Handling

**Error Types**:
- `DiscoveryError` - Plugin discovery failure
- `ValidationError` - Manifest validation failure
- `DependencyError` - Dependency resolution failure
- `InitializationError` - Plugin initialization failure
- `ToolCreationError` - Tool creation failure
- `SubagentCreationError` - Subagent creation failure

**Error Recovery**: Missing dependencies, failed imports, and config errors disable the plugin, not the orchestrator.

### 9. Migration Path

**Before** (old-style factory):
```python
def create_browser_subagent(model=None, **kwargs) -> CompiledSubAgent:
    return {"name": "browser", "runnable": runnable}
```

**After** (plugin-based):
```python
@plugin(name="browser", version="1.0.0", dependencies=["browser-use~=0.1.0"])
class BrowserPlugin:
    @subagent(name="browser", description="Web navigation")
    async def create_browser_subagent(self, model, config, **kwargs):
        return {"name": "browser", "runnable": runnable}
```

**Backward Compatibility**:
- Old factory functions still work via wrappers
- Old imports still valid
- Config format unchanged
- Gradual migration possible

**Deprecation Timeline**:
- v0.2.0: Introduce plugin system
- v0.3.0: Deprecation warnings for old factories
- v0.4.0: Require plugin API

## Implementation Checklist

### Core
- [ ] `PluginManifest` model (`src/soothe/plugin/manifest.py`)
- [ ] `PluginContext` (`src/soothe/plugin/context.py`)
- [ ] `PluginRegistry` (`src/soothe/plugin/registry.py`)
- [ ] `PluginLoader` (`src/soothe/plugin/loader.py`)
- [ ] `PluginLifecycleManager` (`src/soothe/plugin/lifecycle.py`)
- [ ] Integrate with `SootheConfig`

### SDK
- [ ] `@plugin`, `@tool`, `@tool_group`, `@subagent` decorators
- [ ] `PluginContext` type
- [ ] Dependency helpers

### Discovery
- [ ] Entry point, config, filesystem discovery
- [ ] Priority/conflict resolution

### Integration
- [ ] Modify `core/agent.py`, `core/resolver/` to use plugin registry

### Migration
- [ ] Migrate browser, claude, skillify, weaver plugins
- [ ] Add backward compatibility wrappers

### Testing
- [ ] Unit tests for manifest, decorators, registry, lifecycle
- [ ] Integration tests for discovery, registration

### Documentation
- [ ] Plugin developer guide
- [ ] Migration guide
- [ ] Examples

## Security Considerations

**Threats**: Malicious plugins, dependency confusion, resource exhaustion, data exfiltration

**Mitigations**:
- Trust levels and permission enforcement
- Dependency verification
- Resource limits (timeout, memory/CPU)
- Audit logging

**Best Practices**:
- Principle of least privilege
- Explicit user consent for elevated permissions
- Code review before installation
- Future: cryptographic signatures, sandboxing

## Future Enhancements

- Cryptographic signing
- Plugin marketplace
- Hot reloading
- Versioning support
- Container/WASM sandboxing
- Protocol extensions
- Middleware/command extensions
- Plugin dependencies
- Performance monitoring

## References

- RFC-000: System Conceptual Design
- RFC-001: Core Modules Architecture
- RFC-200: Agentic Loop Execution
- RFC-400: Daemon Communication Protocol
- RFC-400: Event Processing & Filtering
- PEP 440: Version Specification
- PEP 517: Build System Format

---

**Status**: Implemented
**Last Updated**: 2026-03-27