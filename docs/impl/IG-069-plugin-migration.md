# IG-069: Plugin Migration

**Implementation Guide**: 069
**Title**: Migrating Built-in Components to Plugin System
**RFC**: RFC-0018 (Plugin Extension Specification)
**Related**: IG-051 (Plugin API Implementation)
**Created**: 2026-03-27
**Status**: Draft

## Overview

This guide describes how to migrate existing subagents and tools to the new plugin system introduced in RFC-0018 and implemented in IG-051. The plugin system provides a standardized decorator-based API for tools and subagents with lifecycle management, dependency declaration, and configuration integration.

### What We're Building

Migrate all built-in subagents and tools from factory function pattern to plugin pattern:

- **Subagents**: browser, claude, skillify, weaver
- **Tools**: core tool groups (execution, file_ops, datetime, etc.)

### Migration Goals

1. **Backward Compatibility**: All existing imports and APIs continue to work
2. **Gradual Migration**: Components can be migrated one at a time
3. **No Breaking Changes**: Existing code using old imports continues to work
4. **Plugin Benefits**: Gain lifecycle hooks, dependency checking, configuration integration

## Migration Strategy

### Backward Compatibility Guarantees

1. **Existing factory functions work**: `create_<name>_subagent()` and `create_<name>_tools()` continue to work
2. **Old imports work**: `from soothe.subagents.browser import create_browser_subagent` still works
3. **Config compatibility**: Existing `subagents.browser` config format still supported
4. **No breaking changes**: All existing imports and APIs continue to work
5. **Gradual migration**: Components can be migrated one at a time

### Deprecation Timeline

- **v0.2.0**: Introduce plugin system, publish migration guide
- **v0.3.0**: Deprecation warnings for old-style factories
- **v0.4.0**: Remove old-style factory support, require plugin API

## Implementation Phases

### Phase 1: Migrate Subagents (Days 1-4)

**Goal**: Migrate all built-in subagents to plugin pattern.

#### Subagents to Migrate

1. **browser**: `src/soothe/subagents/browser/` → `src/soothe/plugins/browser/`
2. **claude**: `src/soothe/subagents/claude/` → `src/soothe/plugins/claude/`
3. **skillify**: `src/soothe/subagents/skillify/` → `src/soothe/plugins/skillify/`
4. **weaver**: `src/soothe/subagents/weaver/` → `src/soothe/plugins/weaver/`

#### Migration Pattern

For each subagent, follow these steps:

**Step 1**: Create plugin package structure

```bash
mkdir -p src/soothe/plugins/<name>/
touch src/soothe/plugins/<name>/__init__.py
```

**Step 2**: Create plugin class with `@plugin` decorator

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
        # ... same implementation as before ...
        from browser_use import Agent as BrowserAgent
        # ... build runnable ...
        return {
            "name": "browser",
            "description": "Navigate and interact with web pages",
            "runnable": runnable,
        }
```

**Step 3**: Create backward compatibility wrapper in old location

```python
# src/soothe/subagents/browser/__init__.py

from soothe.plugins.browser import BrowserPlugin

_plugin_instance = BrowserPlugin()

def create_browser_subagent(*args, **kwargs):
    """Backward-compatible factory function."""
    return _plugin_instance.create_browser_subagent(*args, **kwargs)

BROWSER_DESCRIPTION = "Navigate and interact with web pages"
```

**Step 4**: Verify old imports still work

```python
# This should still work
from soothe.subagents.browser import create_browser_subagent, BROWSER_DESCRIPTION
```

#### Detailed Example: Browser Subagent

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

### Phase 2: Migrate Tools (Days 5-8)

**Goal**: Migrate all built-in tool groups to plugin pattern.

#### Tools to Migrate

- **execution**: Shell execution tools
- **file_ops**: File operation tools
- **datetime**: Date/time tools
- **websearch**: Web search tools
- **research**: Research tools
- **...**: Other tool groups

#### Migration Pattern for Tools

For each tool group, follow these steps:

**Step 1**: Create plugin package structure

```bash
mkdir -p src/soothe/plugins/core_tools/
touch src/soothe/plugins/core_tools/__init__.py
touch src/soothe/plugins/core_tools/execution.py
```

**Step 2**: Create plugin class with `@plugin` and `@tool_group` decorators

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
```

**Step 3**: Create backward compatibility wrapper

```python
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

#### Detailed Example: Execution Tools

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

### Phase 3: Testing (Days 9-10)

**Goal**: Ensure all migrations work correctly.

#### Tests to Write

```
tests/plugin/
├── test_browser_migration.py      # Browser plugin migration tests
├── test_claude_migration.py       # Claude plugin migration tests
├── test_skillify_migration.py     # Skillify plugin migration tests
├── test_weaver_migration.py       # Weaver plugin migration tests
├── test_execution_migration.py    # Execution tools migration tests
└── test_backward_compat.py        # Backward compatibility tests
```

#### Test Cases for Each Migration

1. **Import tests**: Verify old imports still work
   ```python
   def test_browser_backward_compat():
       from soothe.subagents.browser import create_browser_subagent, BROWSER_DESCRIPTION
       assert callable(create_browser_subagent)
       assert BROWSER_DESCRIPTION == "Navigate and interact with web pages"
   ```

2. **Functional tests**: Verify functionality unchanged
   ```python
   async def test_browser_functionality():
       from soothe.plugins.browser import BrowserPlugin
       plugin = BrowserPlugin()
       await plugin.on_load(None)
       subagent = await plugin.create_browser_subagent(model, config, headless=True)
       assert subagent["name"] == "browser"
   ```

3. **Plugin loading tests**: Verify plugin discovery and loading
   ```python
   async def test_browser_plugin_loaded():
       from soothe.plugin import PluginRegistry, PluginLoader
       registry = PluginRegistry()
       loader = PluginLoader(registry)
       # ... test plugin loading ...
   ```

4. **Lifecycle tests**: Verify `on_load()` and `on_unload()` are called
   ```python
   async def test_browser_lifecycle():
       from soothe.plugins.browser import BrowserPlugin
       plugin = BrowserPlugin()
       context = PluginContext(...)
       await plugin.on_load(context)
       # ... verify initialization ...
   ```

#### Manual Testing Checklist

After migration, manually verify:

- [ ] Old imports still work
- [ ] New plugin imports work
- [ ] Tools are registered correctly
- [ ] Subagents are registered correctly
- [ ] Configuration integration works
- [ ] Lifecycle hooks are called
- [ ] Plugin discovery finds the plugin
- [ ] Backward compatibility maintained

### Phase 4: Documentation (Day 11)

**Goal**: Create migration guide for third-party developers.

#### Documentation to Create

1. **Update CLAUDE.md**: Add plugin migration section
2. **Update docs/user_guide.md**: Document plugin system
3. **Create migration examples**: Show before/after patterns

## File Structure Summary

### New Files to Create

```
src/soothe/plugins/
├── browser/
│   ├── __init__.py      # BrowserPlugin class
│   └── subagent.py      # @subagent implementation
├── claude/
│   ├── __init__.py
│   └── subagent.py
├── skillify/
│   ├── __init__.py
│   └── subagent.py
├── weaver/
│   ├── __init__.py
│   └── subagent.py
└── core_tools/
    ├── __init__.py      # CoreToolsPlugin class
    ├── execution.py     # @tool_group for execution tools
    ├── file_ops.py      # @tool_group for file operations
    └── datetime.py      # @tool_group for datetime tools
```

### Files to Modify (Add Backward Wrappers)

```
src/soothe/subagents/
├── browser/__init__.py       # Add backward wrapper
├── claude/__init__.py        # Add backward wrapper
├── skillify/__init__.py      # Add backward wrapper
└── weaver/__init__.py        # Add backward wrapper

src/soothe/tools/
├── execution.py              # Add backward wrapper
├── file_ops.py               # Add backward wrapper
└── datetime.py               # Add backward wrapper
```

## Migration Checklist

For each component to migrate:

- [ ] Create plugin package in `src/soothe/plugins/<name>/`
- [ ] Add `@plugin` decorator with metadata
- [ ] Add `@subagent` or `@tool_group` decorators
- [ ] Move implementation to plugin methods
- [ ] Add lifecycle hooks if needed (`on_load`, `on_unload`, `health_check`)
- [ ] Create backward compatibility wrapper in old location
- [ ] Verify old imports still work
- [ ] Write migration tests
- [ ] Update documentation
- [ ] Run full test suite: `./scripts/verify_finally.sh`

## Common Issues and Solutions

### Issue: Import errors after migration

**Solution**: Ensure backward compatibility wrapper is properly set up in old location.

```python
# Wrong: Missing wrapper
# src/soothe/subagents/browser.py is empty

# Right: Wrapper forwards to plugin
# src/soothe/subagents/browser.py
from soothe.plugins.browser import BrowserPlugin
_plugin_instance = BrowserPlugin()

def create_browser_subagent(*args, **kwargs):
    return _plugin_instance.create_browser_subagent(*args, **kwargs)
```

### Issue: Configuration not loaded

**Solution**: Verify plugin name matches config key and `on_load()` accesses `context.config`.

```python
# Wrong: Plugin name doesn't match config
@plugin(name="browser-automation", ...)  # Config has "browser"

# Right: Plugin name matches config
@plugin(name="browser", ...)  # Config has "browser"

async def on_load(self, context):
    config = context.config  # Access plugin-specific config
```

### Issue: Dependencies not checked

**Solution**: Add `dependencies` parameter to `@plugin` decorator.

```python
# Wrong: No dependency declaration
@plugin(name="browser", version="1.0.0", description="...")

# Right: Declare dependencies
@plugin(
    name="browser",
    version="1.0.0",
    description="...",
    dependencies=["browser-use~=0.1.0"],
)
```

### Issue: Tools not registered

**Solution**: Verify tool methods have `@tool` decorator and return langchain `BaseTool`.

```python
# Wrong: Missing @tool decorator
def shell_execute(self, command: str) -> str:
    return subprocess.run(command, shell=True).stdout

# Right: Add @tool decorator
@tool(name="shell_execute", description="Execute shell commands")
def shell_execute(self, command: str) -> str:
    return subprocess.run(command, shell=True).stdout
```

## Verification

### Unit Tests

Run all plugin migration tests:

```bash
pytest tests/plugin/test_*_migration.py -v
```

### Integration Tests

Run full test suite:

```bash
./scripts/verify_finally.sh
```

### Manual Verification

1. **Test backward compatibility**:
   ```python
   from soothe.subagents.browser import create_browser_subagent
   from soothe.tools.execution import create_execution_tools

   # Should still work
   subagent = create_browser_subagent(...)
   tools = create_execution_tools(...)
   ```

2. **Test new plugin imports**:
   ```python
   from soothe.plugins.browser import BrowserPlugin
   from soothe.plugins.execution import ExecutionPlugin

   # Should work
   browser = BrowserPlugin()
   execution = ExecutionPlugin()
   ```

3. **Test plugin loading**:
   ```bash
   soothe run "Test browser plugin"
   # Should load browser plugin successfully
   ```

## Success Criteria

- [ ] All built-in subagents migrated to plugins
- [ ] All built-in tool groups migrated to plugins
- [ ] Backward compatibility maintained (old imports work)
- [ ] Plugin lifecycle hooks work correctly
- [ ] Configuration integration works
- [ ] All tests pass
- [ ] Documentation updated
- [ ] No breaking changes for users

## Timeline

- **Days 1-4**: Migrate subagents (browser, claude, skillify, weaver)
- **Days 5-8**: Migrate tools (execution, file_ops, datetime, etc.)
- **Days 9-10**: Testing
- **Day 11**: Documentation

**Total**: 11 days

## References

- RFC-0018: Plugin Extension Specification
- IG-051: Plugin API Implementation
- soothe_sdk documentation (coming soon)
- Python entry points documentation

---

**Implementation Status**: Not Started
**Last Updated**: 2026-03-27