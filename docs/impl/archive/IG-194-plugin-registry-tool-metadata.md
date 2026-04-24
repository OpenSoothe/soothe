# IG-194: `PluginRegistry` tool/subagent metadata accessors

## Problem

`ToolTriggerRegistry` and `ToolContextRegistry` call `PluginRegistry.get_tool_metadata()` and `get_subagent_metadata()`, which were never implemented, causing `AttributeError` at runtime.

## Solution

- Add `get_tool_metadata(tool_name)` — scan loaded plugin tools (decorated methods or LangChain tools), return `triggers` / `system_context` from RFC-210 attributes.
- Add `get_subagent_metadata(name)` — delegate to subagent factories via `get_subagent_factory`, read `_subagent_triggers` / `_subagent_system_context`.

## Files

- `packages/soothe/src/soothe/plugin/registry.py`
- `packages/soothe/tests/unit/plugin/test_plugin_registry_metadata.py`

## Verification

`./scripts/verify_finally.sh`
