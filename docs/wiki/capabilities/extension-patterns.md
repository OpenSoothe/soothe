---
title: "Extension Patterns"
parent: Capabilities
grand_parent: Wiki
nav_order: 4
description: >-
  Design decisions, patterns, and gotchas for building extensions that integrate cleanly with Soothe's plugin architecture.
---

# Extension Patterns

The **Plugin System** (RFC-600) provides a decorator-based API for extending Soothe with custom tools, subagents, and event types. This guide covers the design decisions, patterns, and gotchas for building extensions that integrate cleanly with Soothe's architecture.

→ SDK Source: `packages/soothe-sdk/src/soothe_sdk/plugin/`

## Design Philosophy

Soothe's extension model is built on three principles:

1. **Decorator-based, not inheritance-heavy** — plugins are plain Python classes decorated with `@plugin`, with `@tool`/`@subagent` methods. No deep class hierarchies to learn. The decorators attach a `PluginManifest` to the class and add helper methods for extracting tools/subagents.
2. **Manifest as single source of truth** — the `@plugin` decorator's arguments become a `PluginManifest` (Pydantic model with `extra="forbid"`) that carries all metadata: name, version, dependencies, trust level, config requirements. This is the contract between plugin and loader.
3. **Graceful degradation** — a failing plugin disables itself, not the orchestrator. Missing dependencies prevent loading but don't crash the daemon. This is critical for a system that loads many plugins at startup.

## Extension Points

| Extension Point | Decorator | Produces |
|----------------|-----------|----------|
| **Tools** | `@tool` | `BaseTool` or callable registered for agent use |
| **Subagents** | `@subagent` | Factory returning a `CompiledSubAgent` runnable |
| **Tool groups** | `@tool_group` | Class of related tools registered as a set |
| **Events** | `register_event()` | Wire event class registration for observability |

## Trust Levels and Security Boundaries

Plugins declare a `trust_level` that determines their permission envelope:

| Level | Use Case | Permissions |
|-------|----------|-------------|
| `built-in` | Core capabilities (planner, deep_research, academic_research, browser_use, veritas) | Full — can request any permission |
| `trusted` | Verified third-party plugins | Elevated |
| `standard` | Most third-party plugins (default) | Default permissions |
| `untrusted` | Experimental/plugins under review | Restricted |

Built-in plugins cannot be overridden by lower-trust plugins — the discovery priority system enforces this. Trust levels are not advisory; they're enforced by PolicyProtocol when the plugin requests permissions at runtime.

## Plugin Lifecycle

A plugin's lifecycle has three hooks:

- **`on_load(context)`** — called when the plugin is loaded. Use for: initializing resources, validating configuration, setting up connections. The `context` provides config, a logger, runtime services (policy, persistence, vector_store), and an `emit_event` callable.
- **`on_unload()`** — called when the plugin is unloaded. Use for: closing connections, saving state, releasing resources.
- **`health_check()`** — called periodically. Returns a `PluginHealth` with status and message. The daemon uses this to monitor plugin health.

The services dict in `context` is populated by the daemon during loading — it includes `"policy"` (PolicyProtocol), `"persistence"`, `"emit_progress"`, and `"vector_store"`. Plugins access these via `context.services["policy"]` rather than importing daemon internals directly.

## Discovery Mechanisms and Priority

Soothe discovers plugins through three mechanisms, resolved in priority order:

| Priority | Mechanism | Best For |
|----------|-----------|----------|
| 100 | **Built-in** (always wins, cannot be overridden) | Core capabilities |
| 50 | **Entry points** (`[project.entry-points."soothe.plugins"]` in pyproject.toml) | Distributable packages |
| 30 | **Config-declared** (`plugins:` in nano.yml with `module: "path:Class"`) | Runtime/environment-specific plugins |
| 10 | **Filesystem** (`~/.soothe/plugins/<name>/plugin.py`) | User-specific, quick experimentation |

Entry points are recommended for distributable plugins — they use standard Python packaging and are discovered via `importlib.metadata`. Config-declared plugins need no installation, making them ideal for environment-specific or development setups. Filesystem plugins are lowest priority but require zero setup.

When the same plugin name is found by multiple mechanisms, the highest priority wins. Built-in plugins are untouchable.

## Dependency Management

Plugins declare two types of dependencies in the manifest:

- **Library dependencies** (`dependencies`): PEP 440 version specifiers (e.g., `"arxiv>=2.0.0"`). Missing dependencies prevent plugin loading — the orchestrator logs the error and continues with other plugins.
- **Configuration dependencies** (`config_requirements`): dotted paths to required config values (e.g., `"providers.openai.api_key"`). These are validated at load time.

For **optional dependencies** (features that work with or without a library), use try/except ImportError in `on_load()` and degrade gracefully — log a warning and set a flag. The plugin loads either way, and tools can check the flag at call time.

## Minimal Plugin Example

```python
from soothe_sdk.plugin import plugin, tool

@plugin(name="my-tools", version="1.0.0", trust_level="standard")
class MyToolsPlugin:
    async def on_load(self, context):
        self.api_key = context.config.get("api_key")
        context.logger.info("Loaded my-tools v1.0.0")

    @tool(name="greet", description="Greet someone by name")
    def greet(self, name: str) -> str:
        return f"Hello, {name}!"
```

For subagents, the `@subagent` method is a **factory** — it receives `(model, config, context)` and returns a compiled LangGraph runnable. See [Subagents Architecture](subagents.md) for the full subagent pattern.

## Module Self-Containment (IG-047)

Plugins should follow the self-containment pattern: each subagent or tool group is a complete module with its own `__init__.py` (plugin definition + public API), `events.py` (wire events + `register_event()` calls), `implementation.py` (factory functions), `schemas.py` (state/output schemas), and `engine.py` (LangGraph engine, if complex).

The critical detail: **events are registered via side-effect imports**. The `events.py` module calls `register_event()` at module load. The `__init__.py` imports `events` (with `# noqa: F401`) to trigger registration. Forgetting this import means events silently don't fire — a common and hard-to-debug issue.

## Configuration Validation

Plugins validate their config in `on_load()`. The recommended pattern is to define a Pydantic model for the plugin's config schema and instantiate it from `context.config`:

```python
from pydantic import BaseModel

class MyPluginConfig(BaseModel):
    api_key: str
    timeout: int = 30

class MyPlugin:
    async def on_load(self, context):
        self.config = MyPluginConfig(**context.config)
```

Environment variable interpolation (`${ENV_VAR}`) is handled by SootheConfig before the config reaches the plugin, so plugins receive resolved values.

## Event Registration Pattern

Events follow RFC-403 namespacing: `soothe.plugin.<name>.*` for plugin lifecycle, `soothe.tool.<component>.*` for tool operations, `soothe.subagent.<name>.*` for subagent lifecycle. Register at module load:

```python
from soothe.events import register_event

class MyToolEvent(SootheEvent):
    type: str = "soothe.tool.my_plugin.operation"
    target: str

register_event(MyToolEvent, summary_template="Operation on {target}")
```

The `summary_template` provides human-readable event summaries for the daemon's event stream.

## Testing Extensions

- **Unit tests**: test tool methods directly (call them as functions), test subagent factories with mock models, verify output schemas.
- **Integration tests**: test the full plugin lifecycle — load via `PluginLifecycleManager`, verify tools/subagents appear in the registry, check event registration.
- **Security tests**: verify workspace boundaries are enforced for any tool that touches the filesystem.

Run `./scripts/verify_finally.sh` after changes — this is Soothe's standard verification script.

## Gotchas

- **Built-in plugins are immutable**: you cannot override `planner`, `deep_research`, `academic_research`, `browser_use`, `veritas`, etc. with a lower-priority plugin of the same name. Use a different name.
- **`extra="forbid"` on manifests**: the `PluginManifest` Pydantic model forbids extra fields. Passing an unrecognized argument to `@plugin()` raises a validation error.
- **Event registration is import-dependent**: if `events.py` isn't imported, events don't register. Always include the side-effect import in `__init__.py`.
- **Graceful degradation is mandatory**: a plugin that raises in `on_load()` is disabled, but a plugin that crashes during tool execution can disrupt the agent loop. Wrap risky operations in try/except and return error messages rather than raising.
- **Optional dependencies**: use try/except ImportError, not `dependencies` in the manifest. Manifest dependencies are *required* — if listed, the plugin won't load without them.
- **Config requirements are validated**: `config_requirements` entries are checked at load. A missing required config value prevents loading — make requirements optional by not listing them and checking in `on_load()` instead.

## Related RFCs

| RFC | Title |
|-----|-------|
| [RFC-600](../../specs/RFC-600-plugin-extension-system.md) | Plugin Extension System |
| [RFC-601](../../specs/RFC-601-built-in-agents.md) | Built-in Plugin Agents |
| [RFC-101](../../specs/RFC-101-tool-interface.md) | Tool Interface (single-purpose design) |
| [IG-047](../../impl/IG-047-module-self-containment.md) | Module Self-Containment |

---

**Previous**: [MCP Integration](mcp.md) | **Back to**: [Capabilities Index](index.md)
