# RFC-412: MCP Management

**RFC**: 412
**Title**: MCP Management
**Status**: Draft
**Kind**: Implementation Interface Design
**Created**: 2026-05-29
**Last Updated**: 2026-05-29
**Authors**: Platonic brainstorming session
**Design Draft**: [2026-05-29-mcp-management-design.md](../drafts/2026-05-29-mcp-management-design.md)
**Depends On**: RFC-100 (CoreAgent Runtime), RFC-101 (Tool Interface), RFC-105 (Progressive Skill Loading), RFC-305 (Policy Protocol Architecture), RFC-600 (Plugin Extension System)

## Abstract

This RFC replaces the broken/stubbed MCP loader path with a working daemon-singleton MCP subsystem: per-server connection sharing across threads via `langchain_mcp_adapters.MultiServerMCPClient`, progressive MCP tool surfacing through a new `MCPToolSearchMiddleware` (deferred-by-default, budgeted listing, search-and-promote), MCP prompts as slash commands (`mcp__<server>__<prompt>`), MCP resources as `@server:uri` attachments, and bearer-token/headers auth for remote transports. OAuth is explicitly deferred to a follow-on RFC. The `MCPRegistry` is a daemon-owned singleton parallel to `_skill_index`; it wraps `MultiServerMCPClient` and provides filtered per-thread views for tool assembly, progressive disclosure, and policy enforcement.

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
3. **Progressive tool disclosure** — MCP tools are deferred by default (same context-budget rationale as RFC-105 skills); surfaced via `MCPToolSearchMiddleware` and `mcp_tool_search`.
4. **Policy-gated access** — every MCP tool call, resource read, and prompt invocation passes through `PolicyProtocol`.
5. **No reinvention of `langchain_mcp_adapters`** — wrap `MultiServerMCPClient`, not replace it; use its connection types, tool loading, prompt loading, and resource loading directly.

## Scope

- New: `MCPRegistry` (daemon singleton), `MCPConnection` (per-server state), `MCPToolSearchMiddleware` (progressive disclosure), `format_mcp_tools_within_budget` (budgeted listing), `ProgressiveMCPConfig` (tunables), `<AVAILABLE_MCP_TOOLS>` and `<MCP_RESOURCE>` system-prompt blocks, `mcp_tool_search` built-in tool, `mcp_resources_list` / `mcp_resources_read` synthetic tools, MCP event family, `--mcp-config` daemon flag, extended `MCPServerConfig` with `name`, `MCPTransport` enum, `auth`, `defer`, `tool_filter`, timeouts.
- Modified: `AgentBuilder.__init__` (new `mcp_registry` param), `build_soothe_middleware_stack` (insert `MCPToolSearchMiddleware`), `SystemPromptOptimizationMiddleware` (add `_compose_mcp_tools_block`), `ThreadContextManager._ensure_mcp_session` (replace with registry registration), `LoopState` (three new MCP fields), `wire_entries_for_agent_config` (merge MCP prompts), `SootheDaemon.__init__` / `.start()` (registry lifecycle), `mcp_check.py` (rewrite), `mcp_viewer.py` (wire data), `soothe_cli/main.py` (implement `--mcp-config`).
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
3. **Progressive disclosure parity with skills** — `MCPToolSearchMiddleware` mirrors the RFC-105 pattern: budgeted listing, delta tracking, search-and-promote. The model gets `mcp_tool_search` as a separate tool from skill discovery.
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
         ┌──────────────┐  ┌────────────────┐  ┌────────────────────┐
         │ AgentBuilder │  │ MCPToolSearch  │  │ wire_entries +     │
         │ .all_tools   │  │ Middleware      │  │ AttachmentProcessor│
         │ + mcp_always │  │                │  │                    │
         └──────────────┘  │ <AVAILABLE_    │  │ /mcp__server__prompt│
                           │ MCP_TOOLS>     │  │ @server:uri →      │
                           │ mcp_tool_search│  │ <MCP_RESOURCE>     │
                           └────────────────┘  └────────────────────┘
                                  │
                                  ▼
                   ┌─────────────────────────────────┐
                   │ state["mcp_activation"] =       │
                   │   { sent_mcp_tool_names,        │
                   │     invoked_mcp_tools,           │
                   │     disabled_mcp_servers }       │
                   └────────────────┬────────────────┘
                                    │ snapshot at iteration boundary
                                    ▼
                   ┌─────────────────────────────────┐
                   │  LoopState                      │
                   │  .sent_mcp_tool_names           │
                   │  .invoked_mcp_tools             │
                   │  .disabled_mcp_servers          │
                   │  .cached_mcp_resources          │
                   └─────────────────────────────────┘
```

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

#### Flow 2: Agent build — always-loaded MCP tools

1. `AgentBuilder.__init__` receives `mcp_registry: MCPRegistry | None`.
2. `build()` calls `resolve_tools(config.tools, ...)` → `config_tools`.
3. Appends `mcp_registry.always_loaded_tools(workspace)` (servers with `defer=False`, policy-filtered).
4. Passes `mcp_registry` to `build_soothe_middleware_stack(config, policy, mcp_registry=mcp_registry)`.

#### Flow 3: Progressive MCP tool disclosure (per turn)

1. `SystemPromptOptimizationMiddleware._compose_mcp_tools_block(state)` runs during `modify_request`.
2. Reads `state["mcp_activation"]` (empty dict on first turn, initialized by `MCPToolSearchMiddleware.abefore_agent`).
3. `candidates = mcp_registry.deferred_tools(workspace)` — tools from servers with `defer=True`, policy-filtered.
4. `new = candidates - LoopState.sent_mcp_tool_names` (delta-only).
5. `format_mcp_tools_within_budget(new, budget_chars)` returns listing under budget.
6. Block emitted as static-tier `<AVAILABLE_MCP_TOOLS>`; names marked into `state["mcp_activation"]["sent"]`.
7. When model calls `mcp_tool_search(query, limit)`: search by name/description overlap, return top-k matches.
8. On `mcp__<server>__<tool>` invocation: add to `LoopState.invoked_mcp_tools` so the tool becomes always-available on subsequent turns (promotion).

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

1. `StrangeLoop` at iteration boundary copies `state["mcp_activation"]` into `LoopState` fields.
2. On resume, rehydrates `state["mcp_activation"]` from `LoopState`.

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
    """RFC-412: Tunables for progressive MCP tool listing budget."""
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
# state["mcp_activation"] — agent graph state, mutated by middleware
{
    "sent_mcp_tool_names": set[str],          # tool names already in <AVAILABLE_MCP_TOOLS>
    "invoked_mcp_tools": set[str],            # tools promoted to always-available after invocation
    "disabled_mcp_servers": set[str],         # user-disabled servers for this thread
}
```

### LoopState snapshot fields

```python
class LoopState(BaseModel):
    # ... existing fields (including RFC-105 skill fields) ...
    sent_mcp_tool_names: set[str] = Field(default_factory=set)
    invoked_mcp_tools: set[str] = Field(default_factory=set)
    disabled_mcp_servers: set[str] = Field(default_factory=set)
    cached_mcp_resources: dict[str, str] = Field(
        default_factory=dict,
        description="LRU cache for @server:uri resource content (keyed by 'server:uri').",
    )
```

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

### `MCPToolSearchMiddleware`

Location: `packages/soothe/src/soothe/middleware/mcp_tool_search.py`

```python
class MCPToolSearchMiddleware(AgentMiddleware):
    def __init__(
        self,
        mcp_registry: MCPRegistry,
        config: SootheConfig,
    ) -> None: ...

    async def abefore_agent(self, state, runtime) -> dict | None:
        """Lazy-init state['mcp_activation'] if missing; rehydrate from
        LoopState snapshot if StrangeLoop placed it there."""

    # Does NOT use modify_request for the <AVAILABLE_MCP_TOOLS> block.
    # Delegates to SystemPromptOptimizationMiddleware._compose_mcp_tools_block(state).
    # This middleware owns: (1) abefore_agent state init, (2) mcp_tool_search tool,
    # (3) promotion of invoked tools into LoopState.invoked_mcp_tools.
```

Order in `build_soothe_middleware_stack`:
`SoothePolicy → SkillActivation → MCPToolSearch (new) → ToolConcurrency → NetworkToolErrors → SystemPromptOptimization → …`

### `_compose_mcp_tools_block` extension to `SystemPromptOptimizationMiddleware`

Private helper added to `packages/soothe/src/soothe/middleware/system_prompt_optimization.py`, invoked from `_get_prompt_for_complexity` (parallel to `_compose_skills_block`):

```python
def _compose_mcp_tools_block(
    self,
    state: dict,
    config: SootheConfig,
    mcp_registry: MCPRegistry,
) -> tuple[str, str]:
    """Compose the static-tier <AVAILABLE_MCP_TOOLS> block.

    Returns:
        (available_mcp_tools_block, "") — empty second element because
        MCP tools don't have a body-injection stage (promoted tools become
        always-available via LoopState.invoked_mcp_tools instead).
    """
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
4. `build_soothe_middleware_stack(config, policy, mcp_registry=mcp_registry)` passes it to `MCPToolSearchMiddleware`.
5. `SystemPromptOptimizationMiddleware` receives `mcp_registry` via a reference stored at construction time.

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
- `packages/soothe/src/soothe/middleware/mcp_tool_search.py` — `MCPToolSearchMiddleware`

### Modified files

| File | Change |
|---|---|
| `config/models.py:165` | Replace `MCPServerConfig` with extended schema; add `ProgressiveMCPConfig` (after `ProgressiveSkillsConfig` at line 1504) |
| `config/settings.py` | Add `mcp_servers` unique-name validation; add `progressive_mcp: ProgressiveMCPConfig` field |
| `core/agent/_builder.py` | Add `mcp_registry: MCPRegistry | None = None` param; append `mcp_registry.always_loaded_tools(workspace)` after `resolve_tools`; pass `mcp_registry` to middleware stack |
| `core/thread/manager.py:24,547-559` | Replace broken import + `_ensure_mcp_session` with `_register_thread_with_mcp(thread_id)` |
| `middleware/_builder.py` | Add `mcp_registry` param; insert `MCPToolSearchMiddleware` at position 1c (after SkillActivation, before ToolConcurrency) |
| `middleware/system_prompt_optimization.py` | Add `_compose_mcp_tools_block(state)` method; wire into `_get_prompt_for_complexity` |
| `core/loop/state/schemas.py:860` | Add `sent_mcp_tool_names`, `invoked_mcp_tools`, `disabled_mcp_servers`, `cached_mcp_resources` |
| `core/loop/engine/strange_loop.py` | Iteration-boundary snapshot/rehydrate of `state["mcp_activation"]` ↔ `LoopState` |
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
| Per-thread delta tracking | `LoopState.sent_mcp_tool_names`, `invoked_mcp_tools`, etc. | `core/loop/state/schemas.py` |
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
| Deferred listing | name + ≤250-char desc per tool (delta-only) | ≤ 1% of window (~2K tokens on 200K) |
| Tool search result | top-k matches | per-query, only when invoked |
| Prompts (slash) | not in context — lazy fetch | 0 tokens until invoked |
| Resources | `@server:uri` → `<MCP_RESOURCE>` block | per-attachment, semi-static tier |

For a workspace with 3 MCP servers (50 tools total, 1 server always-loaded with 5 tools, 2 deferred with 45 tools), turn-0 cost is ~5 tool schemas + ~45 name/description listings budgeted to ~2K tokens. After the model invokes `mcp_tool_search` for one tool, that tool gets promoted to always-available — its full schema enters the next turn's `tools=`.

## Concurrency & Edge Cases

- **Server name collision** — two configs with `name="github"` → `ValueError` at `SootheConfig` parse time.
- **Tool name collision** — `mcp__` prefix is reserved; `build_mcp_tool_name` enforces it. `tool_name_prefix=False` on `MultiServerMCPClient` avoids double-prefixing.
- **`tool_filter` on `list_changed` additions** — re-applied on every cache rebuild; filtered-out tools never appear.
- **Malformed `tools/list` response** — tool skipped, logged, counter incremented; other tools still loaded.
- **Stdio subprocess hangs on shutdown** — cleanup ladder caps at 600ms then `kill -9`.
- **Missing env var** — connect-time `ValueError`; server stays `connect_failed`.
- **Workspace switch mid-thread** — `always_loaded_tools(workspace)` re-evaluates policy; no connection churn.
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

### Middleware tests (`packages/soothe/tests/unit/middleware/`)

- `test_mcp_tool_search_middleware.py` — budget compliance, delta suppression, tool promotion
- `test_mcp_resource_attachment.py` — `@server:uri` extraction, `<MCP_RESOURCE>` envelope

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
# "search MCP tools for file" → mcp_tool_search → mcp__filesystem__read_file
# Langfuse: <AVAILABLE_MCP_TOOLS> block, soothe.mcp.tool.invoked event
```

## Open Questions

1. **OAuth scope** — deferred to follow-on RFC. Token storage (keyring vs file vs encrypted) is the most contentious sub-decision.
2. **Plugin-system integration** — `MCPServerExtensionPoint` in `plugin/manifest.py` as a follow-on.
3. **Resource caching scope** — per-thread for v1; revisit if telemetry shows hot cross-thread duplicates.
4. **Multi-scope config** — out of scope for v1; daemon-owned soothe has different semantics.
5. **In-process MCP transport** — not needed until soothe-internal tools want MCP exposure.
6. **Stdio auto-reconnect** — inherits Claude Code's "no auto-reconnect for stdio" choice.
7. **WebSocket auth** — `WebsocketConnection` lacks `headers` support; workaround or upstream fix needed.
8. **Ambient cleanup** — broken `manager.py` imports, `mcp_check.py` name bug, TUI empty-state, `--mcp-config` hint — all addressed here but tracked separately so they don't get lost.

## Naming Conventions

- Block names: `<AVAILABLE_MCP_TOOLS>` (static tier listing) and `<MCP_RESOURCE>` (semi-static resource) — bracketed XML-style tags consistent with RFC-104's `<SOOTHE_*>` convention.
- Tool names: `mcp__<server>__<tool>` — reserved prefix; `build_mcp_tool_name` enforces sanitization.
- Slash commands: `/mcp__<server>__<prompt>` — same mangling convention.
- Event domain: `mcp` (new; reserves `soothe.mcp.*`).
- State key: `state["mcp_activation"]` — singular noun consistent with `state["skill_activation"]`.
- Config field: `SootheConfig.progressive_mcp` (snake_case) matching `SootheConfig.progressive_skills`.

## Related Documents

- [RFC-100: CoreAgent Runtime](RFC-100-coreagent-runtime.md)
- [RFC-105: Progressive Skill Loading](RFC-105-progressive-skill-loading.md)
- [RFC-214: StrangeLoop Loop Message Surface](RFC-214-strangeloop-loop-message-surface.md)
- [RFC-305: Policy Protocol Architecture](RFC-305-policy-protocol-architecture.md)
- [RFC-600: Plugin Extension System](RFC-600-plugin-extension-system.md)
- [Design Draft: MCP Management](../drafts/2026-05-29-mcp-management-design.md)
- [RFC Standard](./rfc-standard.md)
- [RFC Index](./rfc-index.md)