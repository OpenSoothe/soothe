---
title: "MCP Integration"
parent: Capabilities
grand_parent: Wiki
nav_order: 3
description: >-
  Model Context Protocol integration providing standardized access to external tools, prompts, and resources.
---

# MCP Integration

**MCP (Model Context Protocol)** integration provides standardized access to external tools, prompts, and resources. Soothe implements a daemon-singleton MCP subsystem (RFC-412) that wraps `langchain_mcp_adapters.MultiServerMCPClient` with progressive disclosure, policy gating, and resource management.

→ Source: `packages/soothe/src/soothe/mcp/`

## Design Philosophy: Wrap, Don't Replace

Soothe's MCP layer **wraps, not replaces** the `langchain_mcp_adapters` library. The library handles connection management; Soothe adds three capabilities the base library doesn't provide:

1. **Progressive disclosure** — MCP servers can expose hundreds of tools. Loading all into the LLM context would cause context bloat and degrade tool-selection accuracy. Soothe defers most tools and surfaces them via search, mirroring the RFC-105 skill-loading pattern.
2. **Policy gating** — every MCP operation (tool call, prompt invoke, resource read/list) passes through PolicyProtocol. This enforces per-server, per-tool, per-resource permissions.
3. **Reconnect scheduling** — remote transports (SSE, HTTP, WebSocket) auto-reconnect with exponential backoff. Stdio servers do not (they require manual `/mcp reconnect`).

## MCPRegistry: The Daemon Singleton

`MCPRegistry` is created once by `SootheDaemon` and shared across all threads. It owns: per-server connections, tools/prompts/resources indices, defer flags, and reconnect state. The singleton design means connection pooling — a server connected once serves all threads, avoiding redundant subprocess spawning or network connections.

The registry partitions tools into two tiers:
- **Always-loaded** (`defer: false`): added directly to `AgentBuilder.all_tools`, available every turn.
- **Deferred** (`defer: true`, the default): listed in a compact `<AVAILABLE_MCP_TOOLS>` block in the system prompt, surfaced via search.

## Progressive Disclosure Flow

This is the most architecturally significant MCP feature. The flow spans two turns:

**Turn 1 — Static tier**: `SystemPromptOptimizationMiddleware` composes an `<AVAILABLE_MCP_TOOLS>` block containing deferred tool names with brief descriptions (truncated to ~100 chars). Only *new* tools (delta from what's already been sent) are included. The listing is budgeted to 2000 characters via `format_mcp_tools_within_budget()`.

**Turn 2+ — Dynamic tier**: the model calls `mcp_tool_search(query="search files", limit=5)`. The middleware searches by name/description overlap, returns top-k matches with full descriptions, and **promotes** invoked tools — once the model calls an `mcp__<server>__<tool>`, that tool becomes always-available on subsequent turns.

This promotion is tracked in `LoopState.invoked_mcp_tools` and snapshot at iteration boundaries. The activation state (`sent_mcp_tool_names`, `invoked_mcp_tools`, `disabled_mcp_servers`) persists across turns.

**Rationale**: without progressive disclosure, a workspace with 5 MCP servers exposing 200 tools would consume ~20K tokens just for tool descriptions — before any user content. The search-and-promote pattern means the agent only sees detailed descriptions for tools it's actively considering.

## Prompts as Slash Commands

MCP prompts are surfaced as slash commands: `/mcp__<server>__<prompt>`. The integration merges MCP prompts with local skills in `wire_entries_for_agent_config()`, each becoming a wire entry with `source="mcp"`.

Prompt content is fetched **lazily** on invocation, not cached — because prompt output is argument-dependent (e.g., `/mcp__filesystem__review-code language=python` produces different content than `language=rust`). The `MCPRegistry.get_prompt()` method fetches the body from the MCP server at invocation time.

## Resources as Attachments

MCP resources are referenced via `@server:uri` syntax in messages (e.g., `@filesystem:/src/auth.py`). The integration flow:

1. `extract_mcp_resource_mentions()` parses the message for `@server:uri` patterns.
2. `MCPRegistry.read_resource()` fetches content from the MCP server.
3. Content is wrapped in `<MCP_RESOURCE server="..." uri="...">` tags and injected into the system prompt as an attachment block.

Two synthetic tools — `mcp_resources_list` and `mcp_resources_read` — are injected once any resource-capable server connects, enabling the agent to explore available resources.

## Policy-Gated Access

Every MCP operation has a permission string checked via PolicyProtocol:

| Operation | Permission |
|-----------|------------|
| Tool invocation | `mcp:call:<server>:<tool>` |
| Prompt invocation | `mcp:invoke:<server>:<prompt>` |
| Resource read | `mcp:read:<server>:<uri>` |
| Resource list | `mcp:list:<server>` |

This means policy can restrict individual tools within a server — e.g., allow `read_file` but deny `write_file` on a filesystem MCP server. Workspace filtering is applied on top: always-loaded tools are filtered by workspace boundary before being added to the agent's tool set.

## Server Configuration

MCP servers are configured in `config.yml`. Key concepts:

- **Transports**: `stdio` (local subprocess, most common), `sse` (HTTP Server-Sent Events), `streamable_http`, `websocket`.
- **`defer`**: defaults to `true` — most servers should be deferred to avoid context bloat. Set `false` only for servers with a small, always-needed tool set.
- **`tool_filter`**: fnmatch patterns to allowlist specific tools (e.g., `read_*`, `list_*`). Applied after connection, before registration.
- **`env`**: environment variables for stdio subprocesses.
- **`auth`**: headers for remote transports, with `${ENV_VAR}` interpolation for secrets (resolved by SootheConfig's `secret_resolver` before connection).

## Connection Management

**Batched connection**: servers connect concurrently in batches to avoid overwhelming the system. Stdio servers batch at 3 concurrent (subprocess spawning overhead); remote servers at 20 concurrent (network I/O is cheap). This mirrors Claude Code's approach.

**Reconnect for remote transports**: exponential backoff — max 5 attempts, 1s initial delay, 30s max, ±0.5s jitter. Events emitted at each stage: `disconnected` → `reconnecting` (per attempt) → `connected` (success) or `connect_failed_terminal` (exhausted).

**Stdio does not auto-reconnect** — the subprocess is gone. Users must manually run `/mcp reconnect <server>`. This is a deliberate design choice: auto-restarting dead subprocesses could mask configuration errors.

**`list_changed` notifications**: MCP servers send `tools/list_changed`, `prompts/list_changed`, `resources/list_changed` when their capabilities change. Soothe invalidates the per-server cache, re-fetches, applies a 16ms debounce to coalesce rapid updates, and emits a `soothe.mcp.list_changed` event. The next agent turn picks up the delta.

**Shutdown**: graceful with deadline enforcement. Stdio uses a cleanup ladder (SIGINT → 100ms poll → SIGTERM → 600ms failsafe → kill -9); remote uses session close then client exit.

## Extension Pattern

MCP servers are external processes — you don't write them *in* Soothe; you configure Soothe to connect to them. See the [MCP specification](https://modelcontextprotocol.io) for building servers.

To add a custom MCP server, add it to `config.yml`:

```yaml
mcp_servers:
  - name: my-custom
    transport: stdio
    command: ["python", "-m", "my_mcp_server"]
    defer: true
```

The server exposes tools via the MCP protocol; Soothe discovers them on connection and applies progressive disclosure, policy gating, and workspace filtering automatically.

## Gotchas

- **Defer by default**: setting `defer: false` on a server with many tools causes context bloat. Only use `false` for small, always-needed tool sets.
- **Secret interpolation**: always use `${ENV_VAR}` syntax for auth headers and env vars — never hardcode secrets in config files.
- **Stdio reconnect**: if a stdio server crashes, it stays down until manually reconnected. Check `soothed doctor --mcp` for health status.
- **Tool name collisions**: MCP tools are namespaced as `mcp__<server>__<tool>`, so collisions across servers are impossible. But if a built-in tool has the same name, the built-in wins.
- **Budget overflow**: if deferred tool descriptions exceed the 2000-char budget, some tools won't appear in the `<AVAILABLE_MCP_TOOLS>` listing. Use `tool_filter` to reduce the tool set, or set `defer: false` for critical tools.

## Related RFCs

| RFC | Title |
|-----|-------|
| [RFC-412](../../specs/RFC-412-mcp-management.md) | MCP Management |
| [RFC-105](../../specs/RFC-105-progressive-skill-loading.md) | Progressive Skill Loading |
| [RFC-305](../../specs/RFC-305-policy-protocol-architecture.md) | Policy Protocol |
| [RFC-600](../../specs/RFC-600-plugin-extension-system.md) | Plugin Extension System |

---

**Previous**: [Tools System](tools.md) | **Next**: [Extension Patterns](extension-patterns.md)
