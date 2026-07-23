# IG-627 MCP Flat Module Restructure

## Goal

Restructure `packages/soothe-nano/src/soothe_nano/mcp` into a flat module layout with semantic file names, no backward-compat shims, and balanced file sizes.

## Scope

- Replace legacy MCP modules with:
  - `mcp_config.py`
  - `mcp_utils.py`
  - `mcp_progressive.py`
  - `mcp_resource_tools.py`
  - `mcp_events.py`
  - `mcp_registry.py`
  - `mcp_registry_support.py`
- Update all in-repo imports to new module paths.
- Remove all legacy MCP files (no compatibility aliases).
- Keep `cleanup.py`, `reconnect.py`, and `__init__.py` in place with updated imports.

## Design Notes

- `mcp_config.py` consolidates auth helpers, built-in server catalog, and transport spec creation.
- `mcp_utils.py` consolidates naming utilities, tool budget formatting, and connection state dataclass.
- `mcp_progressive.py` consolidates progressive activation reducer/state logic and discovery tool definition.
- `mcp_registry.py` remains the public MCP entrypoint and delegates focused helpers to `mcp_registry_support.py`.
- `mcp_events.py` remains a self-registering event module for MCP event schemas and emitters.

## Validation Plan

1. Run MCP unit tests and middleware tests touching MCP imports and behaviors.
2. Run full repository verification script.
3. Fix any import/type/lint regressions introduced by the refactor.
