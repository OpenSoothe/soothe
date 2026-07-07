# IG-448: MCP Management (RFC-412)

**Status:** In Progress
**RFC:** RFC-412
**Design Draft:** docs/drafts/2026-05-29-mcp-management-design.md
**Companion:** IG-447 (Progressive Skill Loading — RFC-105, implemented)

## Goal

Replace the broken/stubbed MCP loader path with a working daemon-singleton MCP subsystem per RFC-412.

## Scope

### Batch 1: Foundation (config + package skeleton) ✅ DONE
- [x] Replace `MCPServerConfig` with extended schema (name, MCPTransport enum, auth, defer, tool_filter, timeouts)
- [x] Add `ProgressiveMCPConfig` to config/models.py
- [x] Add `mcp_servers` unique-name validation + `progressive_mcp` field to SootheConfig
- [x] Create `packages/soothe/src/soothe/mcp/` package skeleton (all 11 modules)
- [x] Implement `name_utils.py` (build_mcp_tool_name, parse_mcp_tool_name)
- [x] Implement `transports.py` (make_connection_spec)
- [x] Implement `auth.py` (MCPAuthHeaders interpolation, AuthProvider stub)
- [x] Implement `budget.py` (format_mcp_tools_within_budget)
- [x] Add `builtin_servers.py` (chrome-devtools MCP)
- [x] Update config/config.template.yml and config/config.dev.yml
- [x] Unit tests for batch 1

### Batch 2: Registry + lifecycle ✅ DONE
- [x] Implement `connection.py` (MCPConnection dataclass)
- [x] Implement `registry.py` (MCPRegistry — initialize, shutdown, always_loaded_tools, deferred_tools, invoke, read_resource)
- [x] Implement `loader.py` (backward-compat adapter for manager.py)
- [x] Implement `reconnect.py` (exponential-backoff scheduler)
- [x] Implement `cleanup.py` (subprocess cleanup ladder)
- [x] Implement `events.py` (MCP event family, self-registered as SootheEvent)
- [x] Wire `SootheDaemon._mcp_registry` lifecycle (init/start/shutdown)
- [x] Fix `core/thread/manager.py` — pass secret_resolver
- [x] Fix `soothe_daemon/health/checks/mcp_check.py` — transport-aware validation

### Batch 3: Agent integration + progressive disclosure ✅ DONE
- [x] Add `mcp_registry` param to AgentBuilder.__init__ and build()
- [x] Append MCP always-loaded tools in _builder.py after resolve_tools
- [x] Add MCP fields to LoopState (sent_mcp_tool_names, invoked_mcp_tools, disabled_mcp_servers, cached_mcp_resources)
- [x] Implement `MCPToolSearchMiddleware` in middleware/mcp_tool_search.py
- [x] Insert MCPToolSearchMiddleware at position 1c in middleware/_builder.py
- [x] Pass mcp_registry through build_soothe_middleware_stack()
- [x] Add `_compose_mcp_tools_block` to SystemPromptOptimizationMiddleware
- [x] Add MCP permission action types to config_policy.py
- [x] LoopState snapshot/rehydrate in executor.py (seed + snapshot + _OptimizationState schema)
- [x] Unit tests for batch 3

### Batch 4: Prompts + resources + CLI ✅ DONE
- [x] Merge MCP prompts into wire_entries_for_agent_config (slash commands)
- [x] Implement `@server:uri` attachment extraction + `<MCP_RESOURCE>` envelope
- [x] Add synthetic `mcp_resources_list` / `mcp_resources_read` tools
- [x] Wire TUI mcp_viewer.py data source (GET /mcp/status)
- [x] Implement `--mcp-config` daemon flag in soothe_cli/cli/main.py
- [x] Integration tests

## Files Created
- packages/soothe/src/soothe/mcp/__init__.py
- packages/soothe/src/soothe/mcp/registry.py
- packages/soothe/src/soothe/mcp/connection.py
- packages/soothe/src/soothe/mcp/loader.py
- packages/soothe/src/soothe/mcp/transports.py
- packages/soothe/src/soothe/mcp/auth.py
- packages/soothe/src/soothe/mcp/name_utils.py
- packages/soothe/src/soothe/mcp/reconnect.py
- packages/soothe/src/soothe/mcp/cleanup.py
- packages/soothe/src/soothe/mcp/events.py
- packages/soothe/src/soothe/mcp/budget.py
- packages/soothe/src/soothe/mcp/builtin_servers.py
- packages/soothe/src/soothe/mcp/tools.py (synthetic resource tools)
- packages/soothe/src/soothe/middleware/mcp_tool_search.py
- packages/soothe/tests/unit/mcp/test_name_utils.py
- packages/soothe/tests/unit/mcp/test_config_validation.py
- packages/soothe/tests/unit/mcp/test_transport_factory.py
- packages/soothe/tests/unit/mcp/test_budget_formatter.py
- packages/soothe/tests/unit/mcp/test_mcp_integration.py
- packages/soothe/tests/unit/mcp/test_mcp_tools.py
- packages/soothe/tests/unit/mcp/test_user_envelope_mcp.py

## Files Modified
- packages/soothe/src/soothe/config/models.py (MCPServerConfig, ProgressiveMCPConfig)
- packages/soothe/src/soothe/config/settings.py (validation, progressive_mcp)
- packages/soothe/src/soothe/core/agent/_builder.py (mcp_registry param + tools injection + resource tools)
- packages/soothe/src/soothe/core/thread/manager.py (pass secret_resolver)
- packages/soothe/src/soothe/core/loop/state/schemas.py (MCP fields in LoopState)
- packages/soothe/src/soothe/core/loop/engine/executor.py (MCP seed/snapshot + graph input)
- packages/soothe/src/soothe/middleware/_builder.py (mcp_registry param + MCPToolSearchMiddleware)
- packages/soothe/src/soothe/middleware/__init__.py (MCPToolSearchMiddleware export)
- packages/soothe/src/soothe/middleware/system_prompt_optimization.py (_compose_mcp_tools_block + _OptimizationState MCP fields)
- packages/soothe/src/soothe/skills/catalog.py (merge MCP prompts into wire_entries)
- packages/soothe/src/soothe/core/prompts/user_envelope.py (MCP resource extraction + envelope)
- packages/soothe/src/soothe/core/governance/config_policy.py (new MCP permissions)
- packages/soothe-daemon/src/soothe_daemon/server.py (_mcp_registry lifecycle)
- packages/soothe-daemon/src/soothe_daemon/health/checks/mcp_check.py (transport-aware)
- packages/soothe-daemon/src/soothe_daemon/protocol/router.py (mcp_status handler)
- packages/soothe-cli/src/soothe_cli/tui/app/_model.py (_fetch_mcp_status + dynamic viewer data)
- packages/soothe-cli/src/soothe_cli/cli/main.py (--mcp-config flag)
- packages/soothe-cli/src/soothe_cli/cli/commands/run_cmd.py (_merge_mcp_config helper)
- packages/soothe-cli/src/soothe_cli/runtime/transport/session.py (get_mcp_status method)
- packages/soothe-sdk/src/soothe_sdk/client/websocket.py (get_mcp_status RPC method)
- config/config.template.yml
- config/config.dev.yml