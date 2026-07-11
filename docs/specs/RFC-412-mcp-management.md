# RFC-412: MCP Management

**RFC**: 412
**Title**: MCP Management
**Status**: Draft
**Kind**: Implementation Interface Design
**Created**: 2026-05-29
**Last Updated**: 2026-07-11
**Authors**: Platonic brainstorming session
**Design Draft**: [2026-05-29-mcp-management-design.md](../archive/drafts/2026-05-29-mcp-management-design.md)
**Revision Draft**: [2026-07-11-mcp-progressive-loading-design.md](../drafts/2026-07-11-mcp-progressive-loading-design.md)
**Depends On**: RFC-100 (CoreAgent Runtime), RFC-101 (Tool Interface), RFC-105 (Progressive Skill Loading), RFC-305 (Policy Protocol Architecture), RFC-600 (Plugin Extension System)

## Abstract

This RFC defines a working daemon-singleton MCP subsystem: per-server connection sharing across threads via `langchain_mcp_adapters.MultiServerMCPClient`, progressive MCP tool surfacing through `ProgressiveMCPRegistry` + `MCPActivationMiddleware` (deferred-by-default, budgeted listing, `search_mcp_tools`, search-and-promote, per-hop tool binding), MCP prompts as slash commands (`mcp__<server>__<prompt>`), MCP resources as `@server:uri` attachments, and bearer-token/headers auth for remote transports. OAuth is explicitly deferred to a follow-on RFC. The `MCPRegistry` is a daemon-owned singleton parallel to `_skill_index`; it wraps `MultiServerMCPClient` and provides filtered per-thread views for tool assembly, progressive disclosure, and policy enforcement.

### Revision 2026-07-11 — Progressive loading runtime (tools parity)

**Problem addressed**: Baseline MCP infrastructure landed (`MCPRegistry`, `<AVAILABLE_MCP_TOOLS>`, `format_mcp_tools_within_budget`) but progressive disclosure is **listing-only**. Deferred tools (`defer: true`) appear in the prompt but are not bound in `tools=`; `mcp_tool_search` was never implemented; `MCPToolSearchMiddleware` records telemetry only.

**Changes**:

1. **Tools-parity activation** — MCP progressive loading mirrors `ProgressiveToolMiddleware` (not skills): deferred tools are `BaseTool` callables promoted into the bound tool array, not injected as instruction bodies.
2. **`ProgressiveMCPRegistry`** — stateless facade (`partition`, `new_for_thread`, `mark_sent`, `mark_promoted`, `search_deferred`, `bound_tools`) parallel to `ProgressiveToolRegistry`.
3. **`MCPActivationMiddleware`** — replaces `MCPToolSearchMiddleware`; owns `search_mcp_tools` handler, invoke-time promotion, and `awrap_model_call` filtering.
4. **`search_mcp_tools`** — separate discovery stub (not merged into `search_tools`); registered whenever the registry has deferred tools.
5. **Unified `mcp_activation` state** — `{sent, promoted}` graph dict (same shape as `tool_activation`); LoopState fields renamed to `mcp_activation_sent` / `mcp_activation_promoted`.
6. **Full catalog at build** — `MCPRegistry.all_tools()` registers every MCP `BaseTool`; middleware binds `always_loaded ∪ promoted` per hop.

## Motivation

### Problem: MCP is entirely non-functional

Soothe today has zero functional MCP surface:

- `MCPServerConfig` at `config/models.py:165` is missing `name`, transport enum, `headers`, `env` interpolation, per-server tool filters, and timeouts. The daemon health check at `soothe_daemon/health/checks/mcp_check.py:28` calls `server.name` which doesn't exist on the model.
- The `soothe.mcp` package **does not exist**. `core/thread/manager.py:24` imports `MCPSessionManager` inside `TYPE_CHECKING`; line 553 runtime import in `_ensure_mcp_session` raises `ImportError` on every thread create/resume; silently swallowed.
- `langchain-mcp-adapters>=0.2.0` is declared in `pyproject.toml` and installed but **never imported** in any `packages/` source.
- Data path severed in three places: `_resolver_tools.py` ignores `config.mcp_servers`; `_builder.py` never receives MCP tools; `_ensure_mcp_session` return value discarded.
- TUI `/mcp` viewer always renders "No MCP servers configured" — `mcp_server_info` never wired.
- `--mcp-config` CLI flag referenced in hint text but **not implemented**.
- `docs/user_guide.md` links to `docs/wiki/mcp-servers.md` which **does not exist**.

### Reference: Claude Code's MCP stack

Claude Code has a mature MCP system (~5K LOC) with patterns directly applicable:

1. **Daemon-singleton connections** — memoized `connectToServer` per `(name, config)`, batch-spawned at startup (3 stdio / 20 remote).
2. **Progressive tool disclosure** — `isDeferredTool` keeps MCP tools out of the default tool array; model discovers them via `ToolSearchTool`; servers opt out via `_meta['anthropic/alwaysLoad']`.
3. **Prompts as slash commands** — `mcp__<server>__<prompt>`.
4. **Resources as `@server:uri`** attachments with synthetic `ListMcpResourcesTool` / `ReadMcpResourceTool`.
5. **Per-server reconnect** — exponential backoff for remote transports; stdio does not auto-reconnect.
6. **OAuth** (~2.4K LOC) — deferred to follow-on RFC.

### Design goals

1. **Working MCP baseline** — fix all broken paths; real connections, real tool calls, real prompt/resource surfacing.
2. **Daemon-singleton connections** — one `MultiServerMCPClient` per process, shared across threads; per-thread views are policy-filtered subsets.
3. **Progressive tool disclosure** — MCP tools are deferred by default (same context-budget rationale as RFC-105 skills and `progressive_tools`); surfaced via `MCPActivationMiddleware` and `search_mcp_tools`, with per-hop binding parity to `ProgressiveToolMiddleware`.
4. **Policy-gated access** — every MCP tool call, resource read, and prompt invocation passes through `PolicyProtocol`.
5. **No reinvention of `langchain_mcp_adapters`** — wrap `MultiServerMCPClient`, not replace it; use its connection types, tool loading, prompt loading, and resource loading directly.

## Scope

- New: `MCPRegistry` (daemon singleton), `MCPConnection` (per-server state), `ProgressiveMCPRegistry` (stateless progressive facade), `MCPActivationMiddleware` (search, promote, bind), `format_mcp_tools_within_budget` (budgeted listing), `ProgressiveMCPConfig` (tunables), `<AVAILABLE_MCP_TOOLS>` and `<MCP_RESOURCE>` system-prompt blocks, `search_mcp_tools` built-in tool, `mcp_resources_list` / `mcp_resources_read` synthetic tools, MCP event family, `--mcp-config` daemon flag, extended `MCPServerConfig` with `name`, `MCPTransport` enum, `auth`, `defer`, `tool_filter`, timeouts.
- Modified: `AgentBuilder.build()` (append `mcp_registry.all_tools()` full catalog; register `search_mcp_tools` when enabled), `build_soothe_middleware_stack` (insert `MCPActivationMiddleware`), `SystemPromptMiddleware` (`_compose_mcp_tools_block` reads `mcp_activation`), `LoopState` (`mcp_activation_sent`, `mcp_activation_promoted`, `disabled_mcp_servers`, `cached_mcp_resources`), executor snapshot/rehydrate, `wire_entries_for_agent_config` (merge MCP prompts), `SootheDaemon` registry lifecycle.
- Removed: `MCPToolSearchMiddleware` (replaced by `MCPActivationMiddleware`); flat `sent_mcp_tool_names` / `invoked_mcp_tools` dict state (migrated to `mcp_activation`).
- Removed: broken `from soothe.mcp.loader import …` import in `manager.py:553`, buggy `server.name` reference in `mcp_check.py:28`.

## Non-Goals

- OAuth with PKCE + dynamic client registration + refresh + step-up — largest single piece of Claude Code's MCP stack; warrants its own RFC.
- Multi-scope config merging (Claude Code's enterprise/local/project/user model) — daemon-owned soothe has different scoping semantics; revisit when a real multi-tenant use case appears.
- In-process MCP transport (Chrome / Computer Use) — not needed until soothe-internal tools expose themselves as MCP.
- MCP-provided skills — `langchain_mcp_adapters` does not expose a "skills" concept; this is Claude Code-specific and not in the MCP spec.
- Plugin-system integration (RFC-600 `MCPServerExtensionPoint`) — follow-on after this RFC lands.

## Guiding Principles

1. **Wrap, not replace** — `MCPRegistry` wraps `MultiServerMCPClient`; soothe adds progressive disclosure, policy gating, and reconnect, but delegates connection management to the library.
2. **Daemon singleton, per-thread views** — connections are shared; policy and `defer` create filtered views per workspace/thread. No per-thread subprocess spawning.
3. **Progressive disclosure parity with builtin tools** — `MCPActivationMiddleware` mirrors `ProgressiveToolMiddleware`: budgeted listing, delta tracking, `search_mcp_tools`, promote-on-invoke, and `awrap_model_call` re-binding. Skills parity applies only to the listing algorithm (`format_mcp_tools_within_budget`); activation is tool-binding, not body injection. `search_mcp_tools` remains separate from `search_tools` and `search_skills`.
4. **Policy-first dispatch** — every MCP operation is gated by `PolicyProtocol`; `Permission("mcp","call","server:tool")` is checked before tool invocation.
5. **Graceful degradation** — a failing MCP server does not block other servers or the agent loop; partial connectivity is acceptable.

## Architecture

### Component overview

```
                   ┌─────────────────────────────────┐
                   │  SootheDaemon.__init__          │  (existing, extended)
                   │  self._mcp_registry =           │
                   │    MCPRegistry(config.mcp_servers)│
                   └──────────────┬──────────────────┘
                                  │
                                  ▼
                   ┌─────────────────────────────────┐
                   │  MCPRegistry (daemon singleton) │
                   │  wraps MultiServerMCPClient      │
                   │  owns connections, tools,        │
                   │  prompts, resources indices      │
                   │  handles list_changed, reconnect │
                   └──────────────┬──────────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │             │             │
          always-loaded     deferred tools   prompts/resources
          (defer=False)     (defer=True)     (slash + @server:uri)
                    │             │             │
                    ▼             ▼             ▼
         ┌──────────────┐  ┌────────────────────────────┐  ┌────────────────────┐
         │ AgentBuilder │  │ ProgressiveMCPRegistry +   │  │ wire_entries +     │
         │ all_tools += │  │ MCPActivationMiddleware    │  │ AttachmentProcessor│
         │ all_tools()  │  │                            │  │                    │
         │ (full catalog)│ │ <AVAILABLE_MCP_TOOLS>      │  │ /mcp__server__prompt│
         └──────────────┘  │ search_mcp_tools           │  │ @server:uri →      │
                           │ awrap_model_call: bind     │  │ <MCP_RESOURCE>     │
                           │   core ∪ promoted          │  └────────────────────┘
                           └────────────────────────────┘
                                  │
                                  ▼
                   ┌─────────────────────────────────┐
                   │ state["mcp_activation"] =       │
                   │   { sent, promoted }          │
                   │ state["disabled_mcp_servers"] │
                   └────────────────┬────────────────┘
                                    │ snapshot at iteration boundary
                                    ▼
                   ┌─────────────────────────────────┐
                   │  LoopState                      │
                   │  .mcp_activation_sent           │
                   │  .mcp_activation_promoted       │
                   │  .disabled_mcp_servers          │
                   │  .cached_mcp_resources          │
                   └─────────────────────────────────┘
```

### Progressive disclosure symmetry

| Concern | Builtin tools | Skills | MCP tools |
|---------|---------------|--------|-----------|
| Registry | `ProgressiveToolRegistry` | `ProgressiveSkillRegistry` | `ProgressiveMCPRegistry` |
| Middleware | `ProgressiveToolMiddleware` | `SkillActivationMiddleware` | `MCPActivationMiddleware` |
| State key | `tool_activation` | `skill_activation` | `mcp_activation` |
| State shape | `{sent, promoted}` | `{sent, activated, invoked, invoked_bodies, …}` | `{sent, promoted}` |
| Discovery tool | `search_tools` | `search_skills` + `invoke_skill` | `search_mcp_tools` |
| Activation | bind `BaseTool` | inject `<SKILL_CONTEXT>` | bind `BaseTool` |
| Prompt block | `<AVAILABLE_TOOLS>` | `<AVAILABLE_SKILLS>` | `<AVAILABLE_MCP_TOOLS>` |
| Core tier | `core_tools` config | `core_skills` + builtin | `defer: false` servers |

### Data flow

#### Flow 1: Daemon startup — connect all MCP servers

1. `SootheDaemon.__init__` creates `self._mcp_registry = MCPRegistry(config.mcp_servers)`.
2. `SootheDaemon.start()` calls `await mcp_registry.initialize()`.
3. `MCPRegistry.initialize()` resolves env vars, partitions servers by transport, builds `connections` dict mapping `{server_name: StdioConnection | SSEConnection | StreamableHttpConnection | WebsocketConnection}`.
4. Creates `MultiServerMCPClient(connections, tool_name_prefix=False)`.
5. Batched connect: `asyncio.gather` with batch_size 3 (stdio) / 20 (remote).
6. Per-server: fetch tools (`get_tools(server_name)`), prompts (`get_prompt`), resources (`get_resources`).
7. Apply `tool_filter` (fnmatch allowlist), apply name mangling (`build_mcp_tool_name`), store in per-server dicts.
8. Emit `soothe.mcp.server.connected` events.

#### Flow 2: Agent build — full MCP catalog + core binding

1. `AgentBuilder.build()` receives `mcp_registry: MCPRegistry | None`.
2. `build()` calls `resolve_tools(config.tools, ...)` → `config_tools`.
3. Appends **all** MCP tools via `mcp_registry.all_tools()` (full catalog — both `defer=True` and `defer=False` servers, policy-filtered).
4. When the registry has ≥1 deferred tool, appends `search_mcp_tools` stub.
5. Passes `mcp_registry` to `build_soothe_middleware_stack`; `MCPActivationMiddleware.set_tool_catalog(all_mcp_tools)` registers the catalog for per-hop binding.
6. **Per-hop binding** (not at build): only `always_loaded_tools()` ∪ `mcp_activation.promoted` appear in `tools=` sent to the model. Deferred tools remain in the catalog but are filtered out until promoted.

#### Flow 3: Progressive MCP tool disclosure (per turn)

1. `MCPActivationMiddleware.abefore_agent` lazy-inits `state["mcp_activation"]` (`{sent, promoted}`) if missing.
2. `SystemPromptMiddleware._compose_mcp_tools_block(state)` runs during `modify_request`.
3. `deferred = mcp_registry.deferred_tools(workspace)` — descriptors from servers with `defer=True`, policy-filtered.
4. `new = ProgressiveMCPRegistry.new_for_thread(activation, deferred)` — delta: not in `sent` and not in `promoted`.
5. `format_mcp_tools_within_budget(new, budget_chars)` returns listing under budget.
6. Block emitted as static-tier `<AVAILABLE_MCP_TOOLS>`; names marked into `activation["sent"]`.
7. When model calls `search_mcp_tools(query, limit)`: substring search on name/bare_name/description/server; `mark_promoted` matches; return top-k descriptions in ToolMessage.
8. `MCPActivationMiddleware.awrap_model_call`: bind `always_loaded ∪ promoted` MCP tools; pass through all non-MCP tools unchanged.
9. On successful `mcp__<server>__<tool>` invocation (no invalid-tool error): `mark_promoted([tool_name])` so the tool is bound on subsequent hops even without prior search.
10. Promoted tools are excluded from future `<AVAILABLE_MCP_TOOLS>` listings (already in `tools=`).

#### Flow 4: MCP prompts as slash commands

1. `wire_entries_for_agent_config` merges `mcp_registry.prompts` with local skills.
2. Each prompt becomes a slash entry `mcp__<sanitizedServer>__<sanitizedPrompt>` with `source="mcp"`.
3. On invocation: `MultiServerMCPClient.get_prompt(server_name, prompt_name, arguments=...)` fetches the prompt body lazily (not cached — arg-dependent).

#### Flow 5: MCP resources as `@server:uri` attachments

1. `extract_mcp_resource_mentions(content)` yields `(server, uri)` tuples from message content.
2. `MCPRegistry.read_resource(server, uri)` → `MultiServerMCPClient.get_resources(server_name, uris=uri)`.
3. Wrapped in `<MCP_RESOURCE server="..." uri="...">{contents}</MCP_RESOURCE>`.
4. Two synthetic tools `mcp_resources_list` and `mcp_resources_read` injected once any resource-capable server connects.

#### Flow 6: Iteration boundary snapshot

1. Executor at iteration boundary copies `state["mcp_activation"]["sent"]` → `LoopState.mcp_activation_sent` and `state["mcp_activation"]["promoted"]` → `LoopState.mcp_activation_promoted`.
2. Copies `state["disabled_mcp_servers"]` and `state["cached_mcp_resources"]` unchanged.
3. On resume, rehydrates `state["mcp_activation"]` and disabled/cache fields from `LoopState` before first `abefore_agent`.

#### Flow 7: list_changed notification

1. Server sends `tools/list_changed` / `prompts/list_changed` / `resources/list_changed`.
2. `MCPRegistry` handler invalidates per-server cache, re-fetches, updates dict.
3. 16ms debounce coalesces rapid updates.
4. Emits `soothe.mcp.list_changed` event; next turn picks up the delta.

#### Flow 8: Reconnect (remote transports only)

1. Remote transport disconnects → `onclose` handler clears cache, emits `soothe.mcp.server.disconnected`.
2. Schedule reconnect with exponential backoff (max 5 attempts, 1s initial, 30s cap, ±0.5s jitter).
3. Each attempt emits `soothe.mcp.server.reconnecting`; success → `connected`; exhausted → `connect_failed_terminal`.
4. Stdio servers do not auto-reconnect; user must `/mcp reconnect <server>`.

#### Flow 9: Shutdown

1. Daemon signal handler calls `await mcp_registry.shutdown()` with 5s aggregate deadline.
2. For stdio: cleanup ladder (SIGINT → 100ms poll → SIGTERM → 600ms failsafe → kill -9).
3. For remote: `session.close()` then `client.__aexit__()`.
4. Emits `MCPRegistryShutdownEvent`.

## Type Definitions

### Extended `MCPServerConfig`

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
    """Configuration for a single MCP server.

    Supports four transports via MCPTransport enum. Compatible with
    `langchain_mcp_adapters` connection types.

    Args:
        name: Required unique server identifier.
        transport: Transport type (stdio, sse, streamable_http, websocket).
        command: Subprocess command for stdio transport.
        args: Command arguments for stdio transport.
        env: Environment variables for stdio (supports ${ENV_VAR} interpolation).
        url: Server URL for remote transports.
        auth: Bearer/header auth configuration (v1; OAuth deferred).
        enabled: Per-server on/off toggle.
        defer: When True, tools are progressive (not in default tool array).
        tool_filter: Allowlist glob patterns for tool names (fnmatch).
        timeout_seconds: Connection timeout.
        request_timeout_seconds: Per-RPC timeout.
        tool_timeout_seconds: Tool-call hard cap.
    """
    name: str
    transport: MCPTransport = MCPTransport.STDIO
    # stdio
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    # remote
    url: str | None = None
    auth: MCPAuthHeaders | None = None
    # behavior
    enabled: bool = True
    defer: bool = True
    tool_filter: list[str] | None = None
    timeout_seconds: float = 30.0
    request_timeout_seconds: float = 60.0
    tool_timeout_seconds: float = 600.0

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> "MCPServerConfig":
        if self.transport == MCPTransport.STDIO:
            if not self.command:
                raise ValueError(f"Server '{self.name}': stdio requires 'command'")
            if self.url:
                raise ValueError(f"Server '{self.name}': stdio cannot have 'url'")
        else:
            if not self.url:
                raise ValueError(f"Server '{self.name}': {self.transport} requires 'url'")
            if self.command:
                raise ValueError(f"Server '{self.name}': {self.transport} cannot have 'command'")
        return self
```

Validation on `SootheConfig`:
- `name` values must be unique across `mcp_servers` (checked at parse time).
- `${ENV_VAR}` interpolation deferred to `MCPRegistry.initialize` via `config.secret_resolver`.

### `ProgressiveMCPConfig`

```python
class ProgressiveMCPConfig(BaseModel):
    """RFC-412: Tunables for progressive MCP tool listing and discovery."""
    budget_pct: float = Field(
        default=0.01,
        ge=0.0,
        le=1.0,
        description=(
            "Fraction of StrangeLoopConfig.context_window_limit (chars, not tokens) "
            "available for the <AVAILABLE_MCP_TOOLS> listing per turn."
        ),
    )
    max_listing_chars_per_entry: int = Field(
        default=250,
        ge=0,
        description="Hard per-entry character cap for tool description in the listing.",
    )
    min_listing_chars_per_entry: int = Field(
        default=20,
        ge=0,
        description="Below this, non-server-essential entries fall back to names-only mode.",
    )
```

Referenced as `config.progressive_mcp`. Same defaults and algorithm as `ProgressiveSkillsConfig`; typed to `MCPToolDescriptor` instead of `SkillIndexEntry`.

### `MCPConnection`

```python
@dataclass
class MCPConnection:
    name: str
    transport: MCPTransport
    status: str  # "connected" | "disconnected" | "reconnecting" | "connect_failed" | "connect_failed_terminal"
    last_error: str | None = None
    reconnect_attempt: int = 0
    tool_count: int = 0
    prompt_count: int = 0
    resource_count: int = 0
    connected_at: datetime | None = None
```

### `MCPToolDescriptor`

```python
@dataclass(frozen=True, slots=True)
class MCPToolDescriptor:
    name: str           # mangled: mcp__<server>__<tool>
    bare_name: str      # original tool name from the server
    description: str
    server: str         # server name
    is_essential: bool  # True if server has defer=False (always-loaded); used by budget formatter
```

### `MCPPromptDescriptor`

```python
@dataclass(frozen=True, slots=True)
class MCPPromptDescriptor:
    name: str           # mangled: mcp__<server>__<prompt>
    bare_name: str      # original prompt name from the server
    description: str | None
    server: str
```

### `MCPResourceDescriptor`

```python
@dataclass(frozen=True, slots=True)
class MCPResourceDescriptor:
    uri: str
    name: str | None
    description: str | None
    server: str
    mime_type: str | None
```

### Runtime state shape

```python
# state["mcp_activation"] — agent graph state, mutated by MCPActivationMiddleware
# and SystemPromptMiddleware._compose_mcp_tools_block
{
    "sent": set[str],      # mangled names already emitted in <AVAILABLE_MCP_TOOLS>
    "promoted": set[str],  # mangled names bound in tools= for this thread
}

# state["disabled_mcp_servers"] — separate key (not inside mcp_activation)
set[str]  # user-disabled servers for this thread

# LangGraph reducer: merge_mcp_activation — union sent and promoted
# (same semantics as merge_tool_activation)
```

### LoopState snapshot fields

```python
class LoopState(BaseModel):
    # ... existing fields (including RFC-105 skill fields) ...
    mcp_activation_sent: set[str] = Field(default_factory=set)
    mcp_activation_promoted: set[str] = Field(default_factory=set)
    disabled_mcp_servers: set[str] = Field(default_factory=set)
    cached_mcp_resources: dict[str, str] = Field(
        default_factory=dict,
        description="LRU cache for @server:uri resource content (keyed by 'server:uri').",
    )
```

**Migration note (2026-07-11)**: Replace legacy flat fields `sent_mcp_tool_names` and `invoked_mcp_tools` (dict) with the canonical `mcp_activation_*` pair. Promotion stores mangled tool names only — not invocation argument snapshots.

These fields are durable snapshots; middleware reads/writes agent graph state, never `LoopState` directly. Snapshot/rehydrate follows the same pattern as RFC-105's skill fields.

## API Contracts

### `MCPRegistry`

Location: `packages/soothe/src/soothe/mcp/registry.py`

```python
class MCPRegistry:
    def __init__(self, servers: list[MCPServerConfig]) -> None:
        """Initialize with server configs. Does not connect yet."""

    async def initialize(self) -> None:
        """Connect all enabled servers concurrently, fetch capabilities.
        Creates MultiServerMCPClient internally with tool_name_prefix=False."""

    async def shutdown(self, deadline_seconds: float = 5.0) -> None:
        """Close all connections with aggregate deadline. Cleanup ladder for stdio."""

    def always_loaded_tools(self, workspace: str | None = None) -> list[BaseTool]:
        """Return BaseTool instances from servers where defer=False,
        filtered by PolicyProtocol.check('mcp', 'call', server, tool)."""

    def all_tools(self, workspace: str | None = None) -> list[BaseTool]:
        """Return all connected MCP BaseTool instances (defer=True and defer=False),
        policy-filtered. Used as the full catalog at agent build; per-hop binding
        is enforced by MCPActivationMiddleware."""

    def deferred_tools(self, workspace: str | None = None) -> list[MCPToolDescriptor]:
        """Return descriptors for defer=True servers, policy-filtered."""

    def prompts(self) -> dict[str, list[MCPPromptDescriptor]]:
        """Return per-server prompt descriptors."""

    def resources(self) -> dict[str, list[MCPResourceDescriptor]]:
        """Return per-server resource descriptors."""

    async def invoke(self, server: str, tool: str, args: dict) -> Any:
        """Invoke a tool via MultiServerMCPClient. PolicyProtocol-checked."""

    async def read_resource(self, server: str, uri: str) -> str:
        """Read a resource via get_resources(). Returns string content
        (converts langchain Blob → str internally). PolicyProtocol-checked."""

    def connection_status(self) -> dict[str, MCPConnection]:
        """Return current status of all connections."""

    def subscribe_list_changed(self) -> None:
        """Arm list_changed handlers for all connected servers."""

    def register_thread(self, thread_id: str, workspace: str | None) -> None:
        """Register a thread for tracking (no-op connection; just cleanup tracking)."""
```

The registry wraps `MultiServerMCPClient` as its internal `_client`. It does not subclass it — composition over inheritance. The client is created in `initialize()` and closed in `shutdown()`.

### `format_mcp_tools_within_budget`

Location: `packages/soothe/src/soothe/mcp/budget.py`

```python
def format_mcp_tools_within_budget(
    entries: Sequence[MCPToolDescriptor],
    *,
    budget_chars: int,
    per_entry_cap_chars: int = 250,
    min_per_entry_chars: int = 20,
) -> tuple[str, BudgetTelemetry]:
    """Format MCP tool listing within a character budget.

    Same algorithm as format_skills_within_budget but typed to MCPToolDescriptor:
    - 'full' mode: under budget, every entry gets full description
    - 'truncated' mode: over budget, essential tools (is_essential=True) keep
      full description; others share remaining budget
    - 'names_only' mode: extreme case, non-essential entries become names-only

    Returns (formatted_text, telemetry).
    """
```

### `ProgressiveMCPRegistry`

Location: `packages/soothe/src/soothe/mcp/progressive_registry.py`

Stateless facade mirroring `ProgressiveToolRegistry`. All activation state lives in `state["mcp_activation"]`.

```python
class ProgressiveMCPRegistry:
    def __init__(self, always_loaded_names: frozenset[str]) -> None:
        """always_loaded_names = {t.name for t in registry.always_loaded_tools()}."""

    @staticmethod
    def init_activation_state() -> dict[str, set[str]]:
        return {"sent": set(), "promoted": set()}

    def partition(
        self, descriptors: Sequence[MCPToolDescriptor]
    ) -> tuple[list[MCPToolDescriptor], list[MCPToolDescriptor]]:
        """Core = is_essential (defer=False server); deferred = rest."""

    def bound_tool_names(self, activation: dict[str, Any]) -> set[str]:
        """always_loaded_names ∪ activation['promoted']."""

    def bound_tools(
        self, tools: Sequence[BaseTool], activation: dict[str, Any]
    ) -> list[BaseTool]:
        """Return tools where name is non-MCP OR name in bound_tool_names()."""

    def new_for_thread(
        self,
        activation: dict[str, Any],
        deferred: Sequence[MCPToolDescriptor],
    ) -> list[MCPToolDescriptor]:
        """Delta: deferred entries not in sent and not in promoted."""

    def mark_sent(self, activation: dict[str, Any], names: Iterable[str]) -> None: ...
    def mark_promoted(self, activation: dict[str, Any], names: Iterable[str]) -> None: ...

    def search_deferred(
        self,
        query: str,
        deferred: Sequence[MCPToolDescriptor],
        *,
        limit: int = 10,
    ) -> list[MCPToolDescriptor]:
        """Substring match on mangled name, bare_name, description, and server."""
```

### `MCPActivationMiddleware`

Location: `packages/soothe/src/soothe/middleware/mcp_activation.py`

Replaces `MCPToolSearchMiddleware`. Mirrors `ProgressiveToolMiddleware` responsibilities for the MCP domain.

```python
class MCPActivationMiddleware(AgentMiddleware):
    state_schema = MCPActivationState  # mcp_activation channel with merge_mcp_activation reducer

    def __init__(self, mcp_registry: MCPRegistry) -> None: ...

    def set_tool_catalog(self, tools: list[BaseTool]) -> None:
        """Called at agent build with mcp_registry.all_tools()."""

    async def abefore_agent(self, state, runtime) -> dict | None:
        """Lazy-init state['mcp_activation'] and state['disabled_mcp_servers']."""

    async def awrap_tool_call(self, request, handler):
        """Handle search_mcp_tools; promote on successful mcp__* invoke."""

    async def awrap_model_call(self, request, handler):
        """Override tools= to bound MCP subset (always_loaded ∪ promoted)."""
```

Order in `build_soothe_middleware_stack`:
`SoothePolicy → SkillActivation → MCPActivation (new) → ToolCallArgs → … → ProgressiveTool → SystemPrompt → …`

`MCPActivationMiddleware` sits after `SkillActivationMiddleware` and before `SystemPromptMiddleware`. It does **not** compose `<AVAILABLE_MCP_TOOLS>` — that remains in `SystemPromptMiddleware._compose_mcp_tools_block`.

### `search_mcp_tools` discovery stub

Location: `packages/soothe/src/soothe/mcp/discovery_tools.py`

```python
def create_search_mcp_tools_tool() -> StructuredTool:
    """Stub; search and promotion handled by MCPActivationMiddleware."""
```

Registered in `AgentBuilder.build()` whenever `mcp_registry` has ≥1 deferred tool. Always bound when registered (core tier for the thread).

### `_compose_mcp_tools_block` extension to `SystemPromptMiddleware`

Private helper in `packages/soothe/src/soothe/middleware/system_prompt.py`, invoked from `_get_prompt_for_complexity` (parallel to `_compose_skills_block`):

```python
def _compose_mcp_tools_block(self, state: dict) -> str | None:
    """Compose the static-tier <AVAILABLE_MCP_TOOLS> block.

    Reads state['mcp_activation']; uses ProgressiveMCPRegistry.new_for_thread
    for delta-only listing; excludes promoted tools. Marks sent names back
    into activation. MCP tools have no body-injection stage — promoted tools
    become callable via awrap_model_call binding instead.
    """
```

When MCP servers are connected, add static-tier guidance (in `<TOOL_SELECTION>` or `<MCP_TOOL_DISCOVERY>`):

```
Deferred MCP tools appear in AVAILABLE_MCP_TOOLS. Use search_mcp_tools(query) to find and
activate them, then call the exact mangled name mcp__<server>__<tool>.
```

### `build_mcp_tool_name` / `parse_mcp_tool_name`

Location: `packages/soothe/src/soothe/mcp/name_utils.py`

```python
def build_mcp_tool_name(server: str, tool: str) -> str:
    """Build mangled MCP tool name: mcp__<sanitized_server>__<sanitized_tool>.
    Non-[a-zA-Z0-9_-] chars replaced with '_'. 'mcp__' prefix is reserved."""

def parse_mcp_tool_name(name: str) -> tuple[str, str] | None:
    """Parse mangled name into (server, bare_tool). Returns None if not MCP."""
```

Because `MultiServerMCPClient` is initialized with `tool_name_prefix=False`, soothe controls the prefix convention entirely. `langchain_mcp_adapters`' default prefixing is bypassed.

### Transport factory

Location: `packages/soothe/src/soothe/mcp/transports.py`

```python
def make_connection_spec(server: MCPServerConfig) -> StdioConnection | SSEConnection | StreamableHttpConnection | WebsocketConnection:
    """Map MCPServerConfig to the appropriate langchain_mcp_adapters connection dict."""
```

Maps:

| `MCPTransport` | Returns | Key fields mapped |
|---|---|---|
| `STDIO` | `StdioConnection` | `command`, `args`, `env` (interpolated), `cwd` (derived from daemon workspace) |
| `SSE` | `SSEConnection` | `url`, `headers` (from `auth.headers`, interpolated), `timeout` (float → seconds) |
| `STREAMABLE_HTTP` | `StreamableHttpConnection` | `url`, `headers`, `timeout` (note: `timedelta`, not `float` — transport factory converts from `MCPServerConfig.timeout_seconds`) |
| `WEBSOCKET` | `WebsocketConnection` | `url` |

### Registry injection path

`MCPRegistry` is daemon-owned; the injection path mirrors `_skill_index`:

1. `SootheDaemon.__init__` (line 87): `self._mcp_registry = MCPRegistry(config.mcp_servers)`
2. `SootheRunner` receives `mcp_registry` from daemon at construction.
3. `AgentBuilder.__init__` receives `mcp_registry: MCPRegistry | None = None`.
4. `build_soothe_middleware_stack(config, policy, mcp_registry=mcp_registry)` passes registry to `MCPActivationMiddleware` and `SystemPromptMiddleware`.
5. `SystemPromptMiddleware` receives `mcp_registry` via construction-time reference.

## Events

MCP events are self-registered via `register_event()` in `packages/soothe/src/soothe/mcp/events.py` (IG-052 per-module pattern — not added to `core/events/catalog.py`).

### Public events

```python
class MCPServerConnectedEvent(SootheEvent):
    type: str = "soothe.mcp.server.connected"
    server: str
    transport: str
    tool_count: int
    prompt_count: int
    resource_count: int
    latency_ms: float

class MCPServerDisconnectedEvent(SootheEvent):
    type: str = "soothe.mcp.server.disconnected"
    server: str
    reason: str
    was_clean: bool

class MCPServerReconnectingEvent(SootheEvent):
    type: str = "soothe.mcp.server.reconnecting"
    server: str
    attempt: int
    backoff_s: float

class MCPServerConnectFailedEvent(SootheEvent):
    type: str = "soothe.mcp.server.connect_failed"
    server: str
    transport: str
    error_class: str
    attempt: int
    is_terminal: bool

class MCPListChangedEvent(SootheEvent):
    type: str = "soothe.mcp.list_changed"
    server: str
    kind: str  # "tools" | "prompts" | "resources"
    old_count: int
    new_count: int

class MCPToolInvokedEvent(SootheEvent):
    type: str = "soothe.mcp.tool.invoked"
    server: str
    tool: str
    latency_ms: float
    success: bool
    result_chars: int

class MCPToolTimeoutEvent(SootheEvent):
    type: str = "soothe.mcp.tool.timeout"
    server: str
    tool: str
    timeout_s: float

class MCPResourceReadEvent(SootheEvent):
    type: str = "soothe.mcp.resource.read"
    server: str
    uri: str
    chars: int
    latency_ms: float

class MCPPromptInvokedEvent(SootheEvent):
    type: str = "soothe.mcp.prompt.invoked"
    server: str
    prompt: str
    latency_ms: float

class MCPToolSearchQueriedEvent(SootheEvent):
    type: str = "soothe.mcp.tool_search.queried"
    query: str
    match_count: int
```

### Internal events

```python
class InternalMCPServerStateChanged(BaseModel):
    server: str
    new_status: str

class InternalMCPToolPromotedEvent(BaseModel):
    server: str
    tool: str
    thread_id: str
```

Naming follows the four-segment convention (`soothe.<domain>.<component>.<action>`). Domain is `mcp` (new; reserves `soothe.mcp.*`).

## Module Layout

### New files

- `packages/soothe/src/soothe/mcp/__init__.py` — Public re-exports
- `packages/soothe/src/soothe/mcp/registry.py` — `MCPRegistry`
- `packages/soothe/src/soothe/mcp/connection.py` — `MCPConnection` dataclass
- `packages/soothe/src/soothe/mcp/loader.py` — Adapter providing `load_mcp_tools` and `MCPSessionManager` for backward compat with existing import sites in `manager.py`
- `packages/soothe/src/soothe/mcp/transports.py` — Transport factory
- `packages/soothe/src/soothe/mcp/auth.py` — `MCPAuthHeaders` interpolation + `AuthProvider` protocol stub
- `packages/soothe/src/soothe/mcp/name_utils.py` — `build_mcp_tool_name` / `parse_mcp_tool_name`
- `packages/soothe/src/soothe/mcp/reconnect.py` — Exponential-backoff scheduler
- `packages/soothe/src/soothe/mcp/cleanup.py` — Subprocess cleanup ladder
- `packages/soothe/src/soothe/mcp/events.py` — Event model definitions + `register_event` calls
- `packages/soothe/src/soothe/mcp/budget.py` — `format_mcp_tools_within_budget`
- `packages/soothe/src/soothe/mcp/progressive_registry.py` — `ProgressiveMCPRegistry`, `merge_mcp_activation`
- `packages/soothe/src/soothe/mcp/discovery_tools.py` — `create_search_mcp_tools_tool`
- `packages/soothe/src/soothe/middleware/mcp_activation.py` — `MCPActivationMiddleware`

**Removed** (2026-07-11 revision):

- `packages/soothe/src/soothe/middleware/mcp_tool_search.py` — replaced by `mcp_activation.py`

### Modified files

| File | Change |
|---|---|
| `config/models.py:165` | Replace `MCPServerConfig` with extended schema; add `ProgressiveMCPConfig` (after `ProgressiveSkillsConfig` at line 1504) |
| `config/settings.py` | Add `mcp_servers` unique-name validation; add `progressive_mcp: ProgressiveMCPConfig` field |
| `core/agent/_builder.py` | Append `mcp_registry.all_tools()` after `resolve_tools`; register `search_mcp_tools` when enabled; pass catalog to `MCPActivationMiddleware` |
| `middleware/_builder.py` | Insert `MCPActivationMiddleware` at position 1c (after SkillActivation) |
| `middleware/system_prompt.py` | `_compose_mcp_tools_block` uses `mcp_activation` + `ProgressiveMCPRegistry` |
| `foundation/sloop/state/schemas.py` | `mcp_activation_sent`, `mcp_activation_promoted`, `disabled_mcp_servers`, `cached_mcp_resources` |
| `foundation/sloop/engine/executor.py` | Snapshot/rehydrate `mcp_activation` ↔ LoopState |
| `skills/catalog.py:127` | Merge `mcp_registry.prompts` into wire entries with `source="mcp"` |
| `soothe_daemon/server.py` (near lines 87-116) | Add `self._mcp_registry`; call `initialize()` in `start()`, `shutdown()` on signal |
| `soothe_daemon/health/checks/mcp_check.py` | Rewrite: validate `server.name`, check command/path, use `MCPRegistry.connection_status()` |
| `soothe_cli/tui/widgets/mcp_viewer.py` | Wire `mcp_server_info` from `GET /mcp/status` |
| `soothe_cli/cli/main.py` | Implement `--mcp-config <path>` daemon-startup flag |
| `config/config.template.yml`, `config/develop/config.yml` | Mirror extended `mcp_servers` schema + `progressive_mcp` section |
| `core/governance/config_policy.py` | Add `action_type="mcp_call"` → `Permission("mcp","call",...)`, `action_type="mcp_read_resource"` → `Permission("mcp","read_resource",...)`, `action_type="mcp_invoke_prompt"` → `Permission("mcp","invoke_prompt",...)` to `_extract_required_permission`; add these permissions to `standard` and `privileged` profiles |

## Reused Primitives

| Need | API | Source |
|---|---|---|
| Transport + connection management | `MultiServerMCPClient`, `StdioConnection`, `SSEConnection`, `StreamableHttpConnection`, `WebsocketConnection` | `langchain_mcp_adapters.client` |
| Tool loading as `BaseTool` | `MCPTool` (which is `mcp.types.Tool` adapted to `StructuredTool`), `get_tools(server_name)` | `langchain_mcp_adapters.tools` / `langchain_mcp_adapters.client` |
| Prompt loading | `get_prompt(server_name, prompt_name, *, arguments=None)` | `langchain_mcp_adapters.client` |
| Resource loading | `get_resources(server_name=None, *, uris=None)` → `list[Blob]` (needs Blob→str conversion) | `langchain_mcp_adapters.client` |
| Budgeted listing algorithm | `format_mcp_tools_within_budget` (new, mirrors `format_skills_within_budget`) | `mcp/budget.py` |
| Per-thread delta tracking | `LoopState.mcp_activation_sent`, `mcp_activation_promoted` | `foundation/sloop/state/schemas.py` |
| Per-hop tool binding | `ProgressiveMCPRegistry.bound_tools` + `MCPActivationMiddleware.awrap_model_call` | `mcp/progressive_registry.py`, `middleware/mcp_activation.py` |
| Builtin tools parity reference | `ProgressiveToolRegistry`, `ProgressiveToolMiddleware` | `toolkits/progressive/registry.py`, `middleware/progressive_tools.py` |
| Path-glob matching | `fnmatch` (stdlib) | n/a |
| Event registration | `register_event` (called from `mcp/events.py`) | `core/events/catalog.py` |
| Internal pub/sub | `InternalEventBus.emit/subscribe` | `core/events/internal_bus.py` |
| Policy check | `PolicyProtocol.check("mcp", "call", ...)` | `protocols/policy.py` |
| Env var interpolation | `config.secret_resolver` | `config/settings.py` |
| System-prompt assembly | `SystemPromptOptimizationMiddleware._compose_mcp_tools_block` | `middleware/system_prompt_optimization.py` |
| Budget config shape | `ProgressiveMCPConfig` (mirrors `ProgressiveSkillsConfig`) | `config/models.py` |
| Daemon singleton pattern | `SootheDaemon._skill_index` flow | `soothe_daemon/server.py:116` |

## Cost Model

| Stage | What lives in context | Approximate cost |
|---|---|---|
| Registry init | nothing — server-side only | 0 tokens |
| Always-loaded tools (defer=False) | full tool schemas in `tools=` | per-tool, same as built-in tools |
| Deferred listing | name + ≤250-char desc per tool (delta-only; excludes promoted) | ≤ 1% of window (~2K tokens on 200K) |
| Tool search result | top-k matches from `search_mcp_tools`; promotes for next hop | per-query, only when invoked |
| Promoted deferred tool | full tool schema in `tools=` from next hop onward | per-tool, same as built-in tools |
| Prompts (slash) | not in context — lazy fetch | 0 tokens until invoked |
| Resources | `@server:uri` → `<MCP_RESOURCE>` block | per-attachment, semi-static tier |

For a workspace with 3 MCP servers (50 tools total, 1 server always-loaded with 5 tools, 2 deferred with 45 tools), turn-0 cost is ~5 tool schemas (core tier) + ~45 name/description listings budgeted to ~2K tokens. After the model calls `search_mcp_tools` for one tool, that tool is promoted — its full schema enters the next hop's `tools=` via `awrap_model_call`. Direct `mcp__*` invocation without prior search also promotes (parity with `ProgressiveToolMiddleware`).

## Concurrency & Edge Cases

- **Server name collision** — two configs with `name="github"` → `ValueError` at `SootheConfig` parse time.
- **Tool name collision** — `mcp__` prefix is reserved; `build_mcp_tool_name` enforces it. `tool_name_prefix=False` on `MultiServerMCPClient` avoids double-prefixing.
- **`tool_filter` on `list_changed` additions** — re-applied on every cache rebuild; filtered-out tools never appear.
- **Malformed `tools/list` response** — tool skipped, logged, counter incremented; other tools still loaded.
- **Stdio subprocess hangs on shutdown** — cleanup ladder caps at 600ms then `kill -9`.
- **Missing env var** — connect-time `ValueError`; server stays `connect_failed`.
- **Disabled server mid-thread** — `disabled_mcp_servers` excludes all `mcp__<server>__*` from `awrap_model_call` binding; `awrap_tool_call` returns error without promotion.
- **Invalid tool / transport error** — no promotion (mirror `ProgressiveToolMiddleware._should_promote_after_invoke`).
- **Workspace switch mid-thread** — `always_loaded_tools(workspace)` and `all_tools(workspace)` re-evaluate policy; no connection churn.
- **Daemon restart with in-flight call** — call returns error; thread retries on next user turn (no auto-retry).
- **`list_changed` flood** — 16ms debounce coalesces; rate > 10Hz for 30s → server marked `unstable`, notifications temporarily ignored.
- **Resource LRU cache** — `LoopState.cached_mcp_resources` (32 entries) prevents re-fetching the same `@server:uri` in a loop.
- **WebSocket auth** — `WebsocketConnection` in `langchain_mcp_adapters` does not support `headers` or `auth` in its current API. WebSocket servers requiring auth need a workaround (e.g. token in URL query string) until upstream adds support.

## Error Handling

- **Connect failure** — per-server: emit `soothe.mcp.server.connect_failed`; for remote, schedule reconnect; for stdio, mark `connect_failed` (no auto-reconnect). Other servers proceed normally.
- **Reconnect exhaustion** — emit `soothe.mcp.server.connect_failed_terminal` with `is_terminal=True`; server remains disconnected until config change or `/mcp reconnect`.
- **Tool call timeout** — enforced at `tool_timeout_seconds`; emit `soothe.mcp.tool.timeout`; return error to model.
- **Policy denial** — `PolicyProtocol.check` returns deny; tool call blocked; error message includes the denied permission.
- **Malformed tool response** — logged, error returned to model; other tools unaffected.
- **Shutdown deadline exceeded** — force kill remaining subprocesses; log which servers were not cleanly closed.

## Verification Plan

### Unit tests (`packages/soothe/tests/unit/mcp/`)

- `test_name_utils.py` — mangling, parsing, collision avoidance, no double-prefixing
- `test_config_validation.py` — XOR command/url, transport-specific fields, env interpolation, unique names
- `test_transport_factory.py` — each transport maps to correct `langchain_mcp_adapters` type
- `test_reconnect_backoff.py` — exponential math, max attempts, jitter
- `test_tool_filter.py` — fnmatch globs, allowlist semantics, re-application on list_changed
- `test_cleanup_ladder.py` — SIGINT → SIGTERM → failsafe, no double-close
- `test_budget_formatter.py` — full/truncated/names_only modes; essential vs non-essential
- `test_progressive_registry.py` — partition, search_deferred, new_for_thread, bound_tools

### Middleware tests (`packages/soothe/tests/unit/middleware/`)

- `test_mcp_activation.py` — `search_mcp_tools` promotion, `awrap_model_call` binding, invoke-time promotion, disabled-server rejection
- `test_mcp_resource_attachment.py` — `@server:uri` extraction, `<MCP_RESOURCE>` envelope
- Extend `test_system_prompt.py` — `_compose_mcp_tools_block` delta, promoted exclusion

### Registry tests

- `test_mcp_registry_initialize.py` — concurrent batched connect, partial-failure handling
- `test_mcp_registry_list_changed.py` — debounce, cache invalidation, event emission
- `test_mcp_registry_reconnect.py` — remote retries, stdio no retry

### Integration tests (`packages/soothe/tests/integration/mcp/`)

- `test_stdio_echo_server.py` — fixture stdio echo server; connect → call → result
- `test_streamable_http_server.py` — fixture HTTP server; bearer auth
- `test_progressive_mcp_tool_surfacing.py` — 50 deferred tools, search → promote

### Manual smoke

```bash
cd /Users/xiamingchen/Workspace/mirasurf/soothe
./scripts/verify_finally.sh
soothe daemon start --config /tmp/mcp-test.yml
# /mcp → viewer shows connected server
# "search MCP tools for file" → search_mcp_tools → mcp__filesystem__read_file
# Langfuse: <AVAILABLE_MCP_TOOLS> block, soothe.mcp.tool.invoked event
```

## Implementation Status (2026-07-11)

| Component | Status |
|-----------|--------|
| `MCPRegistry`, transports, reconnect, events | Landed |
| `ProgressiveMCPRegistry`, `mcp_activation` state | Landed (IG-576) |
| `MCPActivationMiddleware` + `awrap_model_call` binding | Landed (IG-576) |
| `search_mcp_tools` (auto when deferred tools exist) | Landed (IG-576) |
| `format_mcp_tools_within_budget`, `<AVAILABLE_MCP_TOOLS>` | Landed |
| `mcp_resources_list` / `mcp_resources_read` | Landed |
| MCP prompts in wire entries | Landed |
| Policy gating on MCP operations | Partial |
| `list_changed` notification handling | Partial (placeholder) |

## Open Questions

1. **OAuth scope** — deferred to follow-on RFC. Token storage (keyring vs file vs encrypted) is the most contentious sub-decision.
2. **Plugin-system integration** — `MCPServerExtensionPoint` in `plugin/manifest.py` as a follow-on.
3. **Resource caching scope** — per-thread for v1; revisit if telemetry shows hot cross-thread duplicates.
4. **Multi-scope config** — out of scope for v1; daemon-owned soothe has different semantics.
5. **In-process MCP transport** — not needed until soothe-internal tools want MCP exposure.
6. **Stdio auto-reconnect** — inherits Claude Code's "no auto-reconnect for stdio" choice.
7. **WebSocket auth** — `WebsocketConnection` lacks `headers` support; workaround or upstream fix needed.
8. **`search_mcp_tools` vs unified search** — rejected for v1; keep separate from `search_tools` / `search_skills` (domain separation).
9. **Semantic MCP tool search / intent prefetch** — deferred to P2; substring `search_deferred` is sufficient for v1.
10. **Per-tool `_meta['anthropic/alwaysLoad']`** — deferred; server-level `defer: false` is the v1 always-load mechanism.

## Naming Conventions

- Block names: `<AVAILABLE_MCP_TOOLS>` (static tier listing) and `<MCP_RESOURCE>` (semi-static resource) — bracketed XML-style tags consistent with RFC-104's `<SOOTHE_*>` convention.
- Tool names: `mcp__<server>__<tool>` — reserved prefix; `build_mcp_tool_name` enforces sanitization.
- Slash commands: `/mcp__<server>__<prompt>` — same mangling convention.
- Event domain: `mcp` (new; reserves `soothe.mcp.*`).
- State key: `state["mcp_activation"]` — `{sent, promoted}` consistent with `state["tool_activation"]`.
- Discovery tool: `search_mcp_tools` (not `mcp_tool_search`).
- Config field: `SootheConfig.progressive_mcp` (snake_case) matching `SootheConfig.progressive_skills` and `SootheConfig.progressive_tools`.

## Related Documents

- [RFC-100: CoreAgent Runtime](RFC-100-coreagent-runtime.md)
- [RFC-101: Tool Interface](RFC-101-tool-interface.md)
- [RFC-105: Progressive Skill Loading](RFC-105-progressive-skill-loading.md)
- [RFC-214: StrangeLoop Loop Message Surface](RFC-214-strangeloop-loop-message-surface.md)
- [RFC-305: Policy Protocol Architecture](RFC-305-policy-protocol-architecture.md)
- [RFC-600: Plugin Extension System](RFC-600-plugin-extension-system.md)
- [Design Draft: MCP Management](../archive/drafts/2026-05-29-mcp-management-design.md)
- [Revision Draft: MCP Progressive Loading](../drafts/2026-07-11-mcp-progressive-loading-design.md)
- [RFC Standard](./rfc-standard.md)
- [RFC Index](./rfc-index.md)