# IG-576: MCP Progressive Loading (Tools Parity)

**Status**: Complete  
**RFC**: RFC-412 (revision 2026-07-11)  
**Design**: [2026-07-11-mcp-progressive-loading-design.md](../drafts/2026-07-11-mcp-progressive-loading-design.md)

## Goal

Close the MCP progressive disclosure runtime gap: deferred tools must be discoverable via `search_mcp_tools`, promotable on invoke, and bound per model hop via `MCPActivationMiddleware` (tools-parity with `ProgressiveToolMiddleware`).

## Checklist

- [x] `ProgressiveMCPRegistry` + `merge_mcp_activation`
- [x] `MCPActivationMiddleware` (replaces `MCPToolSearchMiddleware`)
- [x] `MCPRegistry.all_tools()` + `search_mcp_tools` stub
- [x] Agent build: full MCP catalog + discovery tool registration
- [x] `SystemPromptMiddleware._compose_mcp_tools_block` → `mcp_activation`
- [x] LoopState + executor snapshot/rehydrate migration
- [x] `search_mcp_tools` stub (always registered when deferred MCP tools exist)
- [x] Unit tests
- [x] Legacy cleanup (flat MCP state, dead middleware APIs)
- [x] Integration test: progressive MCP surfacing
- [x] Builtin deferred MCP catalog (`mcp_builtins` opt-in)
- [x] `./scripts/verify_finally.sh`

## Files

| Action | Path |
|--------|------|
| New | `packages/soothe/src/soothe/mcp/progressive_registry.py` |
| New | `packages/soothe/src/soothe/mcp/discovery_tools.py` |
| New | `packages/soothe/src/soothe/middleware/mcp_activation.py` |
| New | `packages/soothe/tests/unit/mcp/test_progressive_registry.py` |
| New | `packages/soothe/tests/unit/middleware/test_mcp_activation.py` |
| New | `packages/soothe/tests/unit/mcp/test_progressive_mcp_tool_surfacing.py` |
| New | `packages/soothe/tests/unit/mcp/test_builtin_servers.py` |
| Delete | `packages/soothe/src/soothe/middleware/mcp_tool_search.py` |
| Delete | `packages/soothe/tests/unit/mcp/test_mcp_integration.py` (superseded) |
| Modify | `builtin_servers.py`, `registry.py`, `_builder.py`, `agent/_builder.py`, `system_prompt.py`, `executor.py`, `schemas.py`, `models.py`, `settings.py`, `toolkits/progressive/registry.py`, config yml |
