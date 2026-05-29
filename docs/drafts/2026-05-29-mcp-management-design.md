# MCP Management

**Date:** 2026-05-29
**Status:** Draft
**Builds on:** RFC-100 (CoreAgent Runtime), RFC-101 (Tool Interface), RFC-406 (Policy Protocol Architecture), RFC-600 (Plugin Extension System)
**Companion:** [Progressive Skill Loading](2026-05-29-progressive-skill-loading-design.md) — both drafts share the "defer-by-default + budgeted listing" pattern.
**Scope:** Replace the broken/stubbed MCP loader path with a working daemon-singleton MCP subsystem: per-server connection sharing across threads, progressive MCP tool surfacing via a `ToolSearchMiddleware`, MCP prompts as slash commands, MCP resources as `@server:uri` attachments, bearer-token/headers auth (OAuth deferred to a follow-on RFC).

---

## 1. Motivation

MCP support in soothe today is effectively zero functional surface:

- `MCPServerConfig` schema exists (`config/models.py:165`) but is missing `name`, transport enum, `headers`, `env` interpolation, per-server tool filters, and timeouts; daemon health check (`soothe-daemon/.../mcp_check.py:28`) already calls `server.name` which doesn't exist on the model
- `soothe.mcp` package **does not exist** — `core/thread/manager.py:24,553` does `from soothe.mcp.loader import …` which raises `ImportError` on every thread create/resume; the exception is silently swallowed
- `langchain-mcp-adapters>=0.2.0` is declared in `pyproject.toml:37` and installed in `.venv` but **never imported** in any `packages/` source
- Data path is severed in three places: `_resolver_tools.py:resolve_tools` ignores `config.mcp_servers`; `_builder.py:create_deep_agent` never receives MCP tools; the `_ensure_mcp_session` return value is discarded (`_, manager = await load_mcp_tools(...)`)
- TUI `/mcp` viewer always renders `"No MCP servers configured"` because `mcp_server_info` is never wired into `run_textual_tui`
- `--mcp-config` CLI flag is referenced in user-facing hint text but **not implemented** anywhere in `soothe-cli`
- `docs/user_guide.md:67` links to `docs/wiki/mcp-servers.md` which **does not exist**

Meanwhile Claude Code has a mature MCP stack (`src/services/mcp/` ~5K LOC across `config.ts`, `client.ts`, `auth.ts`, `useManageMCPConnections.ts`) with patterns directly applicable to soothe:

- **Single connection per `(server_name, config)`** memoized across the process (`client.ts:595`), with concurrent batch-spawn at startup (3 stdio / 20 remote)
- **Six transports**: stdio, SSE, HTTP (streamable), WebSocket, plus internal SDK and in-process pairs
- **Two-phase discovery**: `Promise.all([fetchTools, fetchPrompts, fetchSkills, fetchResources])` per server, LRU-cached per server name
- **`list_changed` notifications** invalidate the LRU and push fresh entries into AppState
- **16ms batched AppState writes** coalesce server-state churn
- **Progressive disclosure for MCP tools**: `isDeferredTool` (`tools/ToolSearchTool/prompt.ts:62`) keeps MCP tools out of the default tool array; model uses `ToolSearchTool` to surface them on demand; servers opt out via `_meta['anthropic/alwaysLoad']`
- **MCP prompts → slash commands** named `mcp__<server>__<prompt>`; **MCP skills → Skill tool** (feature-gated)
- **MCP resources → `@server:uri` attachments** + two synthetic `ListMcpResourcesTool`/`ReadMcpResourceTool` once a resource-capable server connects
- **Per-server reconnect with exponential backoff** (max 5 attempts, 30s cap) for remote transports only — stdio never auto-reconnects
- **OAuth with PKCE + dynamic client registration + step-up + XAA** (~2.4K LOC in `auth.ts`) — out of scope for v1

This draft specifies the soothe-side replacement: a clean, working baseline with the connection sharing and progressive-disclosure patterns adopted now, and an explicit carve-out for OAuth in a follow-on RFC.

---

## 2. Design decisions

Three choices were settled before drafting:

| Decision | Resolution | Reason |
|---|---|---|
| Connection scope | **Daemon singleton** — one connection per `(name, config)` shared across all threads; per-thread views are filters over the shared registry | Matches Claude Code's memoized `connectToServer`; aligns with `langchain_mcp_adapters.MultiServerMCPClient`'s shape; fixes the current N×M subprocess explosion; per-thread auth scoping can land later as a refinement without re-architecting |
| Tool surfacing | **Progressive (defer-by-default)** — MCP tools not in `tools=` by default; surface via a new `ToolSearchMiddleware` analogous to the progressive-skill-loading registry | Same context-budget rationale as the companion draft; mirrors `isDeferredTool` (Claude Code `src/tools/ToolSearchTool/prompt.ts:62`); per-server `defer: bool` field provides escape hatch for must-always-load cases |
| Auth in v1 | **Bearer tokens + headers + env interpolation** | Covers ~80% of remote MCP servers (API-key-style auth); OAuth is the largest single piece of Claude Code's MCP stack and warrants its own RFC; this draft carves out token-storage and refresh hooks to keep v2 additive |

---

## 3. Reference: how Claude Code manages MCP

Distilled map, with anchors for the soothe-side adaptation.

### Config & precedence

`getClaudeCodeMcpConfigs()` (`src/services/mcp/config.ts:1071`) merges scopes:
```
plugin < user < project (.mcp.json, walked up from cwd) < local (per-project private)
```
Enterprise scope (`<managed-dir>/managed-mcp.json`), when present, **exclusively replaces all other scopes** (`config.ts:1082-1096`). `--mcp-config` CLI flag adds a `dynamic` scope; `--strict-mcp-config` skips file-based scopes entirely. Project `.mcp.json` servers require first-use trust approval (`mcpServerApproval.tsx`), persisted to `enabledMcpjsonServers` / `disabledMcpjsonServers`.

### Transports

Single if/else chain in `connectToServer()` (`client.ts:619-961`) dispatches to:
- `stdio` → `StdioClientTransport` (subprocess; default for `command` configs)
- `sse`, `sse-ide` → `SSEClientTransport`
- `http` → `StreamableHTTPClientTransport`
- `ws`, `ws-ide` → `WebSocketTransport`
- `sdk` → in-process `SdkControlClientTransport`
- Chrome MCP / Computer Use → `createLinkedTransportPair()` for in-process

### Connection lifecycle

`connectToServer` is `memoize`d on `${name}-${jsonStringify(config)}` (`client.ts:595`). Two-phase init in `useManageMCPConnections.loadAndConnectMcpConfigs` (`useManageMCPConnections.ts:858`):
1. Local + project configs spawn concurrently, batched (`batchSize` default 3 stdio / 20 remote)
2. claude.ai connectors fetched asynchronously, deduped, merged

`onclose` (`client.ts:1374`) clears all four memoize caches (`connectToServer`, `fetchToolsForClient`, `fetchPromptsForClient`, `fetchResourcesForClient`). Remote transports auto-reconnect with exponential backoff (`MAX_RECONNECT_ATTEMPTS=5`, `INITIAL_BACKOFF_MS=1000`, capped 30s). Stdio servers do **not** auto-reconnect — user must invoke `/mcp reconnect <name>`.

### Discovery & registration

After `client.connect()`, `getMcpToolsCommandsAndResources()` (`client.ts:2226`) fans out:
```ts
Promise.all([fetchToolsForClient, fetchPromptsForClient,
             feature('MCP_SKILLS') ? fetchMcpSkillsForClient : [],
             fetchResourcesForClient])
```
Each is `memoizeWithLRU(20)` keyed by `client.name`, invalidated on `list_changed` and `onclose`. Results pushed via `onConnectionAttempt` → `updateServer` (`useManageMCPConnections.ts:297`), batched with `setTimeout(16ms)` to coalesce churn.

Name mangling: `buildMcpToolName()` (`mcpStringUtils.ts:50`) → `mcp__<sanitizedServer>__<sanitizedTool>`. `normalizeNameForMCP()` (`normalization.ts:17`) strips non-`[a-zA-Z0-9_-]` chars.

### Surfacing to the model

- **Tools**: merged into the tool pool by `assembleToolPool()` (`tools.ts:345`) — built-ins sorted first, then MCP sorted, contiguous partitions to preserve cache breakpoints. **Default: deferred** via `isDeferredTool` (`tools/ToolSearchTool/prompt.ts:62`) — model uses `ToolSearchTool` to discover them. Servers opt out per-tool via `_meta['anthropic/alwaysLoad']` (read at `client.ts:1785`).
- **Prompts**: become slash commands `/mcp__<server>__<prompt>` (`client.ts:2054-2096`)
- **Skills** (feature-gated `MCP_SKILLS`): become Skill-tool-invocable commands with `loadedFrom='mcp'`; never get inline shell execution (`loadSkillsDir.ts:374`)
- **Resources**: via `@server:uri` extractor (`attachments.ts:2792`), resolved by `processMcpResourceAttachments` (`attachments.ts:1995`); two synthetic tools `ListMcpResourcesTool` + `ReadMcpResourceTool` injected once any resource-capable server connects

### Permissions

`MCPTool.checkPermissions()` returns `passthrough` (MCPTool.ts:56). Rule engine supports:
- Direct match `mcp__server__tool`
- Server-wide `mcp__server`
- Wildcard `mcp__server__*`

Enterprise `allowedMcpServers` / `deniedMcpServers` filter at load time (`config.ts:417, 364`).

### Subprocess cleanup ladder

For stdio (`client.ts:1404-1500`): detach stderr handler → `SIGINT` → poll every 50ms for 100ms → `SIGTERM` → 600ms failsafe. Layered on top of SDK's `transport.close()` because Docker-wrapped servers ignore default abort signals.

---

## 4. Architecture (soothe-side)

```
Daemon startup
  SootheDaemon.__init__:
    self._mcp_registry = MCPRegistry(config.mcp_servers)
    await self._mcp_registry.initialize()         # phase 1: connect all enabled servers concurrently
                                                  #   uses langchain_mcp_adapters.MultiServerMCPClient
                                                  #   batched: 3 stdio / 20 remote
    self._mcp_registry.subscribe_list_changed()   # arms list_changed handlers

MCPRegistry (process singleton, daemon-owned)
  connections : dict[str, MCPConnection]           # keyed by server name
  tools       : dict[str, list[BaseTool]]          # per server, langchain BaseTool instances
  prompts     : dict[str, list[PromptCommand]]     # per server, soothe Command objects
  resources   : dict[str, list[ResourceDescriptor]] # per server
  defer       : dict[str, bool]                    # per server, from config.defer

  on list_changed(server, kind):
    invalidate cache, re-fetch, update dict, emit MCPListChangedEvent

  on disconnect(server):
    clear cache, emit MCPDisconnectedEvent
    if transport is remote: schedule reconnect (exp backoff, max 5)
    if transport is stdio:  mark needs-user-reconnect

Per-thread view (no per-thread connections — just filtered views)
  ThreadContextManager.get_mcp_tools(thread_id) -> list[BaseTool]:
    returns tools across all enabled servers, applying:
      - workspace policy (PolicyProtocol denies for current workspace)
      - per-server enabled flag (LoopState.disabled_mcp_servers override)
      - defer filter (only include tools where defer=False; deferred tools
        are reachable only via ToolSearchMiddleware)

Tool assembly at agent build time (core/agent/_builder.py)
  always_tools = resolve_tools(config.tools, workspace)        # existing
  mcp_always   = mcp_registry.always_loaded_tools(workspace)   # defer=False set
  graph = create_deep_agent(tools = always_tools + mcp_always, ...)

Progressive surfacing during a turn (middleware stack)
  ToolSearchMiddleware.modify_request (new, mirrors progressive-skill registry):
    - On every turn, emit a budgeted <AVAILABLE_MCP_TOOLS> block (static tier)
      with name + description for deferred MCP tools the model hasn't been told
      about yet (delta-tracked on LoopState.sent_mcp_tool_names)
    - Token budget: 1% of context_window_limit (same constant as skills)
    - When model invokes `mcp_tool_search(query="...")` (new tool), search by
      name/description across all deferred tools, return top-k matches

Tool call dispatch
  When model calls mcp__server__tool:
    MCPTool.call delegates to MCPRegistry.invoke(server, tool, args)
      → langchain_mcp_adapters BaseTool.ainvoke(args)
      → callback enforces PolicyProtocol.check("mcp_call", server, tool, args)
      → metric: soothe.mcp.tool_call.latency

Slash commands & resources
  catalog.wire_entries_for_agent_config: extend to include mcp_registry.prompts
    → entries with name="mcp__<server>__<prompt>", source="mcp"
    → existing /mcp__server__prompt slash path works without code change
  AttachmentProcessor: new extract_mcp_resource_mentions handler
    → @server:uri → MCPRegistry.read_resource(server, uri) → <MCP_RESOURCE> envelope
```

The static/semi-static prompt tiering follows RFC-214: deferred-tool listing is static-tier (cache-stable), per-resource attachments are semi-static (per-turn).

---

## 5. Config schema (extended `MCPServerConfig`)

```python
class MCPTransport(StrEnum):
    STDIO = "stdio"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"
    WEBSOCKET = "websocket"

class MCPAuthHeaders(BaseModel):
    """Bearer tokens / API keys via headers. Supports ${ENV_VAR} interpolation."""
    headers: dict[str, str] = Field(default_factory=dict)

class MCPServerConfig(BaseModel):
    name: str                                                          # NEW — required
    transport: MCPTransport = MCPTransport.STDIO                       # was unconstrained str
    # stdio
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)                  # ${ENV_VAR} interpolated
    # remote (sse / streamable_http / websocket)
    url: str | None = None
    auth: MCPAuthHeaders | None = None                                 # NEW — v1 auth
    # behavior
    enabled: bool = True                                               # NEW — per-server toggle
    defer: bool = True                                                 # NEW — progressive default
    tool_filter: list[str] | None = None                               # NEW — allowlist, supports globs
    timeout_seconds: float = 30.0                                      # NEW — connect timeout
    request_timeout_seconds: float = 60.0                              # NEW — per-RPC timeout
    tool_timeout_seconds: float = 600.0                                # NEW — tool-call hard cap
```

Validation:
- `command` XOR `url` (raise `ValueError` if both or neither, dependent on `transport`)
- `transport == STDIO` requires `command`; remote transports require `url`
- `${ENV_VAR}` interpolation happens in `MCPRegistry.initialize` via existing `config.secret_resolver` (same path used by `SootheConfig.propagate_env`); missing env → connect-time error
- `tool_filter` patterns matched against the bare tool name (pre-mangling) via `fnmatch`

The `defer` default of **`True`** mirrors Claude Code's behavior; users who want a server always-loaded set `defer: false`.

Config layering follows soothe's existing pattern: a single `mcp_servers: list[MCPServerConfig]` on `SootheConfig`. No multi-scope merging in v1 (Claude Code's enterprise/local/project/user model is overkill for daemon-owned soothe). Future: a `policy_settings.mcp_overrides` hook for daemon-admin-managed servers — out of scope here.

---

## 6. Module layout

### New package: `packages/soothe/src/soothe/mcp/`

| File | Role |
|---|---|
| `__init__.py` | Public re-exports |
| `registry.py` | `MCPRegistry` — daemon-singleton; owns connections, tool/prompt/resource indices, list_changed handlers, reconnect logic |
| `connection.py` | `MCPConnection` dataclass — per-server state (client, transport, status, last_error, reconnect_attempt) |
| `loader.py` | **Replaces the missing module referenced by `core/thread/manager.py:24`.** Adapter over `langchain_mcp_adapters.MultiServerMCPClient` |
| `transports.py` | Transport factory: maps `MCPTransport` enum to the langchain-mcp-adapters connection-spec dict |
| `auth.py` | v1: header interpolation + bearer/API-key formatting. Hooks reserved for OAuth (`AuthProvider` protocol stub) |
| `name_utils.py` | `build_mcp_tool_name(server, tool)` / `parse_mcp_tool_name(name)` — port of `mcpStringUtils.ts` |
| `reconnect.py` | Exponential-backoff reconnect scheduler for remote transports |
| `cleanup.py` | Subprocess cleanup ladder for stdio (`SIGINT` → poll → `SIGTERM` → failsafe), mirroring `client.ts:1404-1500` |

### New middleware: `packages/soothe/src/soothe/middleware/mcp_tool_search.py`

`ToolSearchMiddleware(AgentMiddleware)`:
- `modify_request`: injects budgeted `<AVAILABLE_MCP_TOOLS>` block (delta-only, per-thread, mirrors progressive-skill registry pattern)
- Registers a built-in tool `mcp_tool_search(query: str, limit: int = 10)` that returns the top-k matching deferred tools
- On match-and-invoke, the matched tool gets promoted into the thread's "always available" set for the rest of the loop (LoopState.invoked_mcp_tools), so the model can call it without searching again
- Token budget: same `context_window_limit * 0.01` constant the skill registry uses; defined in `config/models.py:ProgressiveSkillsConfig` (rename to `ProgressiveLoadingConfig` to cover both)

### Modified files

| File | Change |
|---|---|
| `packages/soothe/src/soothe/config/models.py:165` | Replace `MCPServerConfig` with the extended schema above |
| `packages/soothe/src/soothe/config/settings.py:265` | No structural change; updated docstring referencing new fields |
| `packages/soothe/src/soothe/core/thread/manager.py:24,547-573` | Drop the broken `from soothe.mcp.loader import …`; replace `_ensure_mcp_session` with `_register_thread_with_mcp(thread_id)` which calls `mcp_registry.register_thread(thread_id, workspace)` (no-op connection; just registers for cleanup tracking) |
| `packages/soothe/src/soothe/core/resolver/_resolver_tools.py:134` | After `resolve_tools` returns, append `mcp_registry.always_loaded_tools(workspace)` |
| `packages/soothe/src/soothe/core/agent/_builder.py` | Inject `MCPRegistry` instance from `RunnerState` into the middleware stack so `ToolSearchMiddleware` can read deferred tools |
| `packages/soothe/src/soothe/middleware/_builder.py:59` | Insert `ToolSearchMiddleware` after `SkillActivationMiddleware` (from companion draft) |
| `packages/soothe/src/soothe/skills/catalog.py:127` (`wire_entries_for_agent_config`) | Merge `mcp_registry.prompts` into the wire entries with `source="mcp"` so MCP prompts surface as `/mcp__server__prompt` slash commands |
| `packages/soothe-daemon/src/soothe_daemon/server.py` | Daemon owns the `MCPRegistry` singleton (parallel to `_skill_index`); calls `await mcp_registry.initialize()` during startup, `await mcp_registry.shutdown()` on signal |
| `packages/soothe-daemon/src/soothe_daemon/health/checks/mcp_check.py` | Rewrite: use `server.name` (now a real field), validate command existence for stdio, ping URL for remote (HEAD with timeout); aggregate `MCPRegistry.connection_status()` |
| `packages/soothe-cli/src/soothe_cli/tui/widgets/mcp_viewer.py` | Wire `mcp_server_info` end-to-end: daemon exposes `GET /mcp/status` via `protocol/router.py`; CLI calls it before mounting viewer |
| `packages/soothe-cli/src/soothe_cli/main.py` | Implement the long-promised `--mcp-config <path>` flag: loads an extra `mcp_servers:` YAML/JSON, merged at config-resolution time |
| `packages/soothe/src/soothe/core/events/catalog.py:567` | Register `soothe.mcp.*` event family (see §10) |
| `config/config.template.yml`, `config/config.dev.yml` | Mirror the extended `mcp_servers:` schema (CLAUDE.md Rule #2) |

### Removed / fixed

- The broken `from soothe.mcp.loader import load_mcp_tools` lines disappear once the real module lands
- The buggy `server.name` reference in `mcp_check.py:28` becomes correct (the field now exists)
- TUI viewer's perpetual `"No MCP servers configured"` empty state goes away
- Empty-state hint text referencing `--mcp-config` becomes truthful once the flag is implemented

---

## 7. Reused primitives

| Need | API | Source |
|---|---|---|
| stdio / SSE / streamable-HTTP transport plumbing | `MultiServerMCPClient`, `get_tools()` | `langchain_mcp_adapters` (already in pyproject) |
| Tool wrapping as `BaseTool` | `langchain_mcp_adapters.tools.load_mcp_tools` | same |
| Prompt wrapping | `langchain_mcp_adapters.prompts.load_mcp_prompts` | same |
| Budgeted listing formatter | `format_skills_within_budget` (rename to `format_entries_within_budget`) | companion draft, `skills/budget.py` |
| Per-thread delta tracking | `LoopState` (extend with `sent_mcp_tool_names`, `invoked_mcp_tools`, `disabled_mcp_servers`) | `core/loop/state/schemas.py` (already extended by companion draft) |
| Path-glob matching for `tool_filter` | `fnmatch` (stdlib) | n/a |
| Event registration | `register_event`, `custom_event` | `core/events/catalog.py:567,116` |
| Internal pub/sub for `list_changed` propagation | `InternalEventBus.emit/subscribe` | `core/events/internal_bus.py:25` |
| Policy check at invoke time | `PolicyProtocol.check("mcp", "call", target=...)` | `protocols/policy.py` (already grants `Permission("mcp","connect","*")` in built-in profiles) |
| Env var interpolation | `config.secret_resolver` | `config/settings.py` |
| System-prompt assembly hook | `SystemPromptOptimizationMiddleware._get_prompt_for_complexity` | `middleware/system_prompt_optimization.py:286` |
| Subprocess management | `asyncio.subprocess` + `signal` (no extra dep) | stdlib |

---

## 8. Connection lifecycle

### Startup (daemon init)

```
MCPRegistry.initialize():
  resolved = [resolve_env_vars(s) for s in config.mcp_servers if s.enabled]
  stdio, remote = partition(resolved, by=lambda s: s.transport == STDIO)
  await asyncio.gather(
    connect_batched(stdio, batch_size=3),
    connect_batched(remote, batch_size=20),
  )
  emit MCPRegistryInitializedEvent(connected=N, failed=M)
```

`connect(server)` per server:
1. Build transport via `transports.py:make_transport(server)`
2. Open `langchain_mcp_adapters` client session
3. Fetch tools, prompts, resources in parallel (`asyncio.gather`)
4. Apply `tool_filter` (allowlist), apply name mangling (`build_mcp_tool_name`)
5. Subscribe to `list_changed` notifications (per kind)
6. Store in `registry.connections[name]` and per-kind dicts
7. Emit `soothe.mcp.server.connected` event

On failure: emit `soothe.mcp.server.connect_failed` with error class; for remote transports schedule reconnect.

### `list_changed` handling

```
on tools/list_changed from server S:
  invalidate registry.tools[S]
  tools = await fetch_tools(S)
  registry.tools[S] = [build_tool(t, server=S) for t in tools]
  emit soothe.mcp.list_changed(server=S, kind="tools", count=len(tools))
  # ToolSearchMiddleware reads from registry on next turn — no push needed
```

Same for `prompts/list_changed` and `resources/list_changed`. Per-server LRU cache cleared and rebuilt; updates are coalesced via a 16ms debounce (port of `MCP_BATCH_FLUSH_MS`) using `asyncio.call_later`.

### Reconnect

Remote transports only (parity with Claude Code; stdio servers' state is too fragile to auto-respawn):
- `MAX_RECONNECT_ATTEMPTS = 5`, `INITIAL_BACKOFF_S = 1.0`, `MAX_BACKOFF_S = 30.0`
- Backoff = `min(MAX, INITIAL * 2^attempt) + jitter(0, 0.5)`
- Each attempt fires `soothe.mcp.server.reconnecting` event; success → `connected`; exhausted → `connect_failed_terminal`
- User can force reconnect via `/mcp reconnect <server>` (slash command — extend `command_registry.py`)

### Shutdown

```
MCPRegistry.shutdown():
  for conn in self.connections.values():
    if conn.transport == STDIO:
      await cleanup_subprocess(conn)   # SIGINT → poll → SIGTERM → failsafe
    else:
      await conn.client.aclose()
  emit MCPRegistryShutdownEvent
```

Called from daemon signal handler (`SIGTERM`, `SIGINT`), with a 5s aggregate deadline to avoid hung shutdowns.

---

## 9. Tool / prompt / resource surfacing

### Tools (deferred-by-default)

`MCPRegistry.always_loaded_tools(workspace) -> list[BaseTool]`:
- Returns tools from servers where `defer == False`, filtered by `PolicyProtocol.check("mcp", "call", server, tool)`
- These join the `tools=` array passed to `create_deep_agent` at build time (same path as built-in tools)

`MCPRegistry.deferred_tools(workspace) -> list[MCPToolDescriptor]`:
- Returns descriptors (name + description + server + tags) for `defer == True` servers
- Consumed by `ToolSearchMiddleware`

`ToolSearchMiddleware` flow per turn:
1. Compute `new = deferred_tools - LoopState.sent_mcp_tool_names`
2. If `new`, render `<AVAILABLE_MCP_TOOLS>` block (budgeted) and append to static tier
3. Mark new tools as `sent`
4. On `mcp_tool_search(query)` invocation: rank by token-overlap (`description.lower()` contains query terms) + tag match; return top-k as a tool-result message
5. On any `mcp__<server>__<tool>` call: add to `LoopState.invoked_mcp_tools` so the tool's full schema enters the tool list on subsequent turns

### Prompts (slash commands)

`MCPRegistry.prompts[server]` is a list of `PromptCommand` instances. `wire_entries_for_agent_config` merges them with local skills, producing slash entries named `mcp__<sanitizedServer>__<sanitizedPrompt>`. The existing `/skill:` slash-command machinery handles invocation; the prompt body is fetched lazily via `connection.client.get_prompt(name, args)` on each invoke (not cached — prompts are cheap and arg-dependent).

### Resources (`@server:uri` attachments)

New attachment extractor `extract_mcp_resource_mentions(content)` (parallel to `extract_at_mentioned_files`) yields `(server, uri)` tuples. Resolved by `MCPRegistry.read_resource(server, uri)` and wrapped in:
```xml
<MCP_RESOURCE server="..." uri="...">
{contents}
</MCP_RESOURCE>
```
Two synthetic built-in tools — `mcp_resources_list` and `mcp_resources_read` — are injected once any connected server advertises `resources` capability. These are **not** deferred (small, high-value, infrequently used; mirrors Claude Code's `ListMcpResourcesTool` / `ReadMcpResourceTool`).

---

## 10. Telemetry & events

Public event family (registered via `register_event` in `core/events/catalog.py`):

| Event type | Fields | Fired when |
|---|---|---|
| `soothe.mcp.server.connected` | `server`, `transport`, `tool_count`, `prompt_count`, `resource_count`, `latency_ms` | After successful connect |
| `soothe.mcp.server.disconnected` | `server`, `reason`, `was_clean` | On `onclose` |
| `soothe.mcp.server.reconnecting` | `server`, `attempt`, `backoff_s` | Before reconnect attempt |
| `soothe.mcp.server.connect_failed` | `server`, `transport`, `error_class`, `attempt`, `is_terminal` | On connect failure |
| `soothe.mcp.list_changed` | `server`, `kind` (`tools`/`prompts`/`resources`), `old_count`, `new_count` | On notification |
| `soothe.mcp.tool.invoked` | `server`, `tool`, `latency_ms`, `success`, `result_chars` | After tool call |
| `soothe.mcp.tool.timeout` | `server`, `tool`, `timeout_s` | On per-call timeout |
| `soothe.mcp.resource.read` | `server`, `uri`, `chars`, `latency_ms` | On `@server:uri` resolution |
| `soothe.mcp.prompt.invoked` | `server`, `prompt`, `latency_ms` | On slash-command invocation |
| `soothe.mcp.tool_search.queried` | `query`, `match_count` | On `mcp_tool_search` call |

Internal events (via `InternalEventBus`):
- `InternalMCPServerStateChanged` — coordinates cache invalidation across middlewares without leaking to wire
- `InternalMCPToolPromotedEvent` — `ToolSearchMiddleware` → tool-pool refresher

---

## 11. Edge cases

- **Server name collision** (two configs with `name="github"`) → validation error at `SootheConfig` parse time
- **Tool name collision** between built-in soothe tool and `mcp__github__create_issue` → impossible by construction (mangling prefix `mcp__` is reserved); enforced in `name_utils.build_mcp_tool_name`
- **`tool_filter` evicts a tool that arrives via `list_changed`** → re-applied on every cache rebuild; never appears in registry
- **Server returns malformed JSON in `tools/list`** → tool skipped, logged, `soothe.mcp.tools.malformed` counter incremented; other tools still loaded
- **Subprocess hangs on shutdown** → cleanup ladder caps at 600ms then `kill -9`; logged as `soothe.mcp.cleanup.force_killed`
- **Env var referenced by `env:` is missing** → connect-time `ValueError` with the var name; server stays in `connect_failed` state until config changes
- **Workspace switch mid-thread** → `MCPRegistry.always_loaded_tools(workspace)` re-evaluates policy; no connection churn (connections are workspace-agnostic; only the view is filtered)
- **Daemon restart with in-flight tool call** → call returns `soothe.mcp.daemon_restart_during_call` error; thread retries on next user turn (no auto-retry — preserves user-visible failure mode)
- **`list_changed` flood from a buggy server** → 16ms debounce coalesces; if rate > 10Hz for 30s, server marked `unstable`, list_changed temporarily ignored, event emitted
- **Resource URI that requires server roundtrip per fetch** → cached per-thread in `LoopState.cached_mcp_resources` (LRU 32 entries) so repeated `@server:uri` in a loop doesn't re-fetch

---

## 12. Auth (v1: bearer + headers)

`MCPAuthHeaders.headers` are passed verbatim to the transport's HTTP layer (`langchain_mcp_adapters` accepts a `headers` dict for SSE and streamable_http). `${ENV_VAR}` interpolation runs via `config.secret_resolver` at connect time.

```yaml
mcp_servers:
  - name: linear
    transport: streamable_http
    url: https://mcp.linear.app/sse
    auth:
      headers:
        Authorization: "Bearer ${LINEAR_MCP_TOKEN}"
        X-Workspace-Id: "${LINEAR_WORKSPACE_ID}"
```

`auth.py` exposes an `AuthProvider` protocol stub (no implementations beyond `StaticHeadersProvider` in v1) so OAuth can be added without touching transport code:

```python
class AuthProvider(Protocol):
    async def headers(self) -> dict[str, str]: ...
    async def on_401(self) -> bool: ...  # returns True if retry should happen
```

This carve-out is the **only** code path OAuth needs to plug into. The OAuth RFC (deferred) adds `OAuthAuthProvider(AuthProvider)` with PKCE + DCR + refresh + step-up, mirroring Claude Code's `auth.ts`.

---

## 13. Permissions integration

`PolicyProtocol` already has `Permission("mcp", "connect", "*")` in built-in profiles. Extend with:
- `Permission("mcp", "call", "<server>:<tool>")` — checked in `MCPTool.call` before dispatch
- `Permission("mcp", "read_resource", "<server>:<uri-prefix>")` — checked in `MCPRegistry.read_resource`
- `Permission("mcp", "invoke_prompt", "<server>:<prompt>")` — checked in slash-command dispatch

Per-tool deny: a `denied_mcp_tools: list[str]` on `SootheConfig.policy` (or via the existing `ConfigDrivenPolicy` rules) blocks `mcp__<server>__<tool>` at invoke time. Matching follows the same `mcp__server__*` / `mcp__server` wildcard semantics Claude Code uses (`permissions.ts:236-269`).

---

## 14. Verification

### Unit tests (`packages/soothe/tests/unit/mcp/`)

- `test_name_utils.py` — mangling, parsing, collision avoidance
- `test_config_validation.py` — XOR command/url, transport-specific required fields, env interpolation
- `test_transport_factory.py` — each transport maps to correct `langchain_mcp_adapters` connection spec
- `test_reconnect_backoff.py` — exponential backoff math, max attempts, jitter
- `test_tool_filter.py` — fnmatch globs, allowlist semantics
- `test_cleanup_ladder.py` — `SIGINT → SIGTERM → failsafe`, no double-close

### Middleware tests (`packages/soothe/tests/unit/middleware/`)

- `test_tool_search_middleware_budget.py` — deferred tools fit budget, deltas suppress re-emission
- `test_tool_search_middleware_promotion.py` — invoked deferred tool moves to `LoopState.invoked_mcp_tools`
- `test_mcp_resource_attachment.py` — `@server:uri` extraction, `<MCP_RESOURCE>` envelope

### Registry tests

- `test_mcp_registry_initialize.py` — concurrent batched connect, partial-failure handling
- `test_mcp_registry_list_changed.py` — debounce, cache invalidation, event emission
- `test_mcp_registry_reconnect.py` — remote retries, stdio does not retry

### Integration tests (`packages/soothe/tests/integration/mcp/`)

- `test_stdio_echo_server.py` — fixture stdio server (Python script implementing trivial MCP `echo` tool); full connect → tool call → result
- `test_streamable_http_server.py` — fixture aiohttp server speaking MCP; bearer-token auth
- `test_progressive_mcp_tool_surfacing.py` — end-to-end: configure 50 deferred tools, agent prompt mentions one by name, verify `mcp_tool_search` finds and promotes it

### Manual smoke (CLAUDE.md Rule #5)

```bash
cd /Users/xiamingchen/Workspace/mirasurf/soothe
./scripts/verify_finally.sh                # mandatory: format + lint + 900+ unit tests

# Daemon smoke with a real MCP server
soothe daemon start --config /tmp/mcp-test.yml   # uses --mcp-config under the hood
# /tmp/mcp-test.yml configures e.g. modelcontextprotocol/server-filesystem via stdio

# Attach CLI, type /mcp → viewer shows connected server + tool list (no longer empty)
# Prompt: "search MCP tools for file"
#   → model calls mcp_tool_search → result shows filesystem tools
#   → model calls mcp__filesystem__read_file
# Confirm via Langfuse:
#   - <AVAILABLE_MCP_TOOLS> block in static tier with budget telemetry
#   - soothe.mcp.tool.invoked event in stream
#   - LoopState.invoked_mcp_tools contains "mcp__filesystem__read_file"
```

---

## 15. Open questions

1. **OAuth scope** — deferred to `RFC-NNN-mcp-oauth.md`. Token storage (OS keychain via `keyring` Python lib vs file with `0600` perms vs encrypted at rest via daemon-owned key) is the most contentious sub-decision.
2. **Plugin-system integration (RFC-600)** — RFC-600 currently covers Tools and Subagents. Should MCP servers become a plugin extension point (so a plugin can ship its own MCP server config)? Recommendation: yes, but as a follow-on after this draft lands. Hook would be a new `MCPServerExtensionPoint` in `plugin/manifest.py` exposing the same `MCPServerConfig` shape.
3. **Resource attachment caching scope** — per-thread (current proposal) vs per-loop vs per-process? Per-thread is the safest default but the same resource fetched across many threads burns server roundtrips. Recommend per-thread for v1, revisit if `soothe.mcp.resource.read` telemetry shows hot duplicates.
4. **Multi-scope config (claude code's local/project/user/enterprise model)** — explicitly out of scope for v1. Soothe is daemon-owned, so per-user/per-project scoping has different semantics than Claude Code's per-CLI-invocation model. Worth its own RFC once a real multi-tenant use case appears.
5. **In-process MCP transport** (Claude Code's `InProcessTransport` for Chrome / Computer Use) — not needed v1. If soothe-internal tools ever want to expose themselves *as* MCP (e.g. for cross-language access), revisit.
6. **`stdio` auto-reconnect** — Claude Code deliberately doesn't. Soothe inherits that choice; user must `/mcp reconnect <server>` after stdio crash. Re-evaluate if telemetry shows high stdio crash rate.
7. **Cleanup of pre-existing broken code** — `core/thread/manager.py:24,553`, the buggy `server.name` reference in `mcp_check.py:28`, the orphaned TUI viewer empty-state, and the unimplemented `--mcp-config` hint — these are all addressed by this draft, but listed separately here so they don't get lost as "ambient cleanup".
