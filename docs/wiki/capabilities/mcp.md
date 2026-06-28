# MCP Integration

**MCP (Model Context Protocol)** integration provides standardized access to external tools, prompts, and resources. Soothe implements a daemon-singleton MCP subsystem (RFC-412) that wraps `langchain_mcp_adapters.MultiServerMCPClient` with progressive disclosure, policy gating, and resource management.

## Overview

### Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│  SootheDaemon                                                       │
│  self._mcp_registry = MCPRegistry(config.mcp_servers)              │
└────────────────────────┬───────────────────────────────────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────────────┐
│  MCPRegistry (daemon singleton)                                     │
│  wraps MultiServerMCPClient                                         │
│  owns connections, tools, prompts, resources indices                │
│  handles list_changed, reconnect                                    │
└────────────────────────┬───────────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
    always-loaded  deferred tools  prompts/resources
    (defer=False)  (defer=True)   (slash + @server:uri)
          │              │              │
          ▼              ▼              ▼
┌─────────────────┐ ┌─────────────────┐ ┌──────────────────────────┐
│ AgentBuilder    │ │ MCPToolSearch   │ │ wire_entries +          │
│ .all_tools      │ │ Middleware      │ │ AttachmentProcessor     │
│ + mcp_always    │ │                 │ │                          │
└─────────────────┘ │ <AVAILABLE_     │ │ /mcp__server__prompt    │
                    │ MCP_TOOLS>      │ │ @server:uri →           │
                    │ mcp_tool_search │ │ <MCP_RESOURCE>          │
                    └─────────────────┘ └──────────────────────────┘
          │              │              │
          └──────────────┴──────────────┘
                         │
                         ▼
┌────────────────────────────────────────────────────────────────────┐
│  state["mcp_activation"]                                            │
│  { sent_mcp_tool_names, invoked_mcp_tools, disabled_mcp_servers }  │
└────────────────────────┬───────────────────────────────────────────┘
                         │ snapshot at iteration boundary
                         ▼
┌────────────────────────────────────────────────────────────────────┐
│  LoopState                                                          │
│  .sent_mcp_tool_names                                               │
│  .invoked_mcp_tools                                                 │
│  .disabled_mcp_servers                                              │
│  .cached_mcp_resources                                              │
└────────────────────────────────────────────────────────────────────┘
```

### Key Components

| Component | Purpose |
|-----------|---------|
| **MCPRegistry** | Daemon-singleton connection manager |
| **MCPConnection** | Per-server connection state |
| **MCPToolSearchMiddleware** | Progressive disclosure middleware |
| **format_mcp_tools_within_budget** | Budgeted tool listing |
| **mcp_tool_search** | Search-and-promote tool |
| **mcp_resources_list/read** | Synthetic resource tools |

### Integration with langchain_mcp_adapters

Soothe **wraps, not replaces** `langchain_mcp_adapters.MultiServerMCPClient`:

- **Delegates connection management** to the library
- **Adds progressive disclosure** (deferred tools surfaced via search)
- **Adds policy gating** (every operation checked via PolicyProtocol)
- **Adds reconnect scheduling** (automatic recovery for remote transports)

## MCP Server Configuration

### Server Types

**Transport types** (MCPTransport enum):
- `stdio`: Local subprocess (most common)
- `sse`: Server-Sent Events (HTTP)
- `streamable_http`: HTTP with streaming
- `websocket`: WebSocket transport

### Configuration Schema

```yaml
mcp_servers:
  - name: filesystem               # Required: unique server ID
    transport: stdio               # Required: stdio | sse | streamable_http | websocket
    command: ["mcp-server-filesystem", "--root", "/workspace"]  # stdio: command + args
    env:                           # Environment variables (optional)
      PATH: "/usr/local/bin"
      DEBUG: "1"
    defer: true                    # Deferred loading (default: true)
    enabled: true                  # Enable server (default: true)
    tool_filter:                   # Tool allowlist (optional)
      - "read_file"
      - "write_file"
      - "list_directory"
    timeout_seconds: 30            # Connection timeout (default: 30)
    
  - name: web-tools
    transport: sse                 # Remote transport
    url: "https://api.mcp-tools.com/sse"  # Required for remote
    auth:                          # Authentication (optional)
      headers:
        Authorization: "Bearer ${MCP_API_KEY}"  # ${ENV} interpolation
    defer: false                   # Always-loaded
    enabled: true
```

### Environment Variable Interpolation

MCP config supports `${ENV_VAR}` syntax for secrets:

```yaml
mcp_servers:
  - name: api-server
    transport: sse
    url: "https://api.example.com/mcp"
    auth:
      headers:
        X-API-Key: "${MCP_API_KEY}"  # Resolved from environment
    env:
      DATABASE_URL: "${DATABASE_URL}"
```

The `secret_resolver` from SootheConfig resolves placeholders before connection.

### Tool Filtering

Server-level tool filtering via fnmatch patterns:

```yaml
mcp_servers:
  - name: filesystem
    tool_filter:
      - "read_*"      # Allow all read operations
      - "list_*"      # Allow all list operations
      - "write_file"  # Allow specific tool
```

Filtering applied after connection, before tool registration.

## Progressive Disclosure

### Deferred vs Always-Loaded

MCP tools are **deferred by default** to avoid context bloat:

| Mode | Tools Available | When |
|------|----------------|------|
| **defer=True** | Listed in `<AVAILABLE_MCP_TOOLS>` block | First turn (static tier) |
| **defer=False** | Added to `AgentBuilder.all_tools` | Always available |

**Rationale**: MCP servers can expose hundreds of tools. Loading all into context would overwhelm the LLM. Progressive disclosure mirrors the RFC-105 skill loading pattern.

### Disclosure Flow

**Turn 1**:
1. `SystemPromptOptimizationMiddleware._compose_mcp_tools_block(state)` runs
2. Candidates = `mcp_registry.deferred_tools(workspace)` (defer=True servers, policy-filtered)
3. Delta = candidates - `LoopState.sent_mcp_tool_names` (new tools only)
4. Listing = `format_mcp_tools_within_budget(delta, budget_chars=2000)`
5. Block emitted as `<AVAILABLE_MCP_TOOLS>` in system prompt
6. Names recorded in `state["mcp_activation"]["sent"]`

**Turn 2+**:
1. Model calls `mcp_tool_search(query="search files", limit=5)`
2. Middleware searches by name/description overlap
3. Returns top-k matches (detailed descriptions)
4. On `mcp__<server>__<tool>` invocation → promotion
5. Tool added to `LoopState.invoked_mcp_tools`
6. Tool becomes always-available on subsequent turns

### Budget Management

`format_mcp_tools_within_budget()` ensures listing stays under character budget:

```python
def format_mcp_tools_within_budget(
    descriptors: list[MCPToolDescriptor],
    budget_chars: int = 2000
) -> str:
    """Format MCP tools within character budget.
    
    Returns:
        Markdown listing with tool names and brief descriptions.
    """
    listing = []
    total_chars = 0
    
    for desc in descriptors:
        entry = f"- {desc.name}: {desc.description[:100]}"
        if total_chars + len(entry) > budget_chars:
            break
        listing.append(entry)
        total_chars += len(entry)
    
    return "\n".join(listing)
```

### Search-and-Promote Tool

**mcp_tool_search** synthetic tool:

```python
class MCPToolSearchTool(BaseTool):
    """Search MCP tools by name/description."""
    name: str = "mcp_tool_search"
    description: str = "Search available MCP tools. Returns top matches with full descriptions."
    
    def _run(self, query: str, limit: int = 5) -> str:
        """Search tools."""
        matches = search_mcp_tools(query, limit)
        # Promote found tools to always-available
        promote_tools(matches)
        return format_search_results(matches)
```

## Prompts as Slash Commands

### Slash Command Integration

MCP prompts surfaced as slash commands: `/mcp__<server>__<prompt>`

**Integration flow**:
1. `wire_entries_for_agent_config()` merges `mcp_registry.prompts` with local skills
2. Each prompt becomes a slash entry with `source="mcp"`
3. Invocation fetches prompt body lazily (not cached — arg-dependent)

**Example**:
```python
# MCP server exposes prompt: "review-code"
# Slash command: /mcp__filesystem__review-code

wire_entry = WireEntry(
    name="/mcp__filesystem__review-code",
    content="",  # Lazy fetch
    source="mcp",
    server="filesystem",
    prompt="review-code"
)
```

### Lazy Fetch

Prompt content fetched on invocation (argument-dependent):

```python
# On slash command invoke
prompt_content = await mcp_registry.get_prompt(
    server_name="filesystem",
    prompt_name="review-code",
    arguments={"language": "python"}
)
```

## Resources as Attachments

### Attachment Syntax

MCP resources referenced via `@server:uri` syntax:

```
@filesystem:/src/auth.py
@database:table/users
@api:endpoint/v1/data
```

### Integration Flow

1. `extract_mcp_resource_mentions(content)` yields `(server, uri)` tuples from message
2. `MCPRegistry.read_resource(server, uri)` → fetch from MCP server
3. Wrapped in `<MCP_RESOURCE server="..." uri="...">{contents}</MCP_RESOURCE>`
4. Injected into system prompt as attachment block

**Example**:
```python
# Message: "Check @filesystem:/src/auth.py for auth logic"

# Extraction
mentions = extract_mcp_resource_mentions(message)
# [('filesystem', '/src/auth.py')]

# Fetch
content = await mcp_registry.read_resource('filesystem', '/src/auth.py')

# Injection
attachment = f"<MCP_RESOURCE server='filesystem' uri='/src/auth.py'>{content}</MCP_RESOURCE>"
```

### Synthetic Tools

Two synthetic tools for resource exploration:

```python
class MCPResourcesListTool(BaseTool):
    """List available MCP resources."""
    name: str = "mcp_resources_list"
    description: str = "List resources from MCP server."
    
    def _run(self, server: str) -> str:
        """List resources."""
        resources = mcp_registry.list_resources(server)
        return format_resource_list(resources)

class MCPResourcesReadTool(BaseTool):
    """Read MCP resource."""
    name: str = "mcp_resources_read"
    description: str = "Read resource content from MCP server."
    
    def _run(self, server: str, uri: str) -> str:
        """Read resource."""
        content = mcp_registry.read_resource(server, uri)
        return content
```

Injected once any resource-capable server connects.

## Policy-Gated Access

### Permission Model

Every MCP operation passes through PolicyProtocol:

| Operation | Permission String |
|-----------|-------------------|
| Tool invocation | `"mcp:call:<server>:<tool>"` |
| Prompt invocation | `"mcp:invoke:<server>:<prompt>"` |
| Resource read | `"mcp:read:<server>:<uri>"` |
| Resource list | `"mcp:list:<server>"` |

**Example**:
```python
# Policy check before tool call
allowed = await policy.check(
    Permission("mcp", "call", "filesystem:read_file")
)
if not allowed:
    raise PermissionError("MCP tool filesystem:read_file not permitted")

# Policy check before resource read
allowed = await policy.check(
    Permission("mcp", "read", "database:table/users")
)
if not allowed:
    raise PermissionError("MCP resource database:table/users not accessible")
```

### Workspace Filtering

MCP tools filtered by workspace boundary:

```python
def always_loaded_tools(self, workspace: str) -> list[BaseTool]:
    """Get always-loaded tools filtered by workspace."""
    tools = []
    for server_name, server_tools in self._tools.items():
        if not self._defer[server_name]:  # defer=False
            for tool in server_tools:
                # Policy check
                allowed = policy.check(Permission("mcp", "call", f"{server_name}:{tool.name}"))
                if allowed:
                    tools.append(tool)
    return tools
```

## Connection Management

### Batched Connection

MCP servers connected in batches to avoid overwhelming the system:

| Transport | Batch Size | Reason |
|-----------|------------|--------|
| `stdio` | 3 concurrent | Subprocess spawning overhead |
| `sse/http/websocket` | 20 concurrent | Network I/O efficient |

**Implementation**:
```python
async def initialize(self) -> None:
    """Connect all enabled servers concurrently."""
    # Partition by transport
    stdio_servers = [s for s in enabled if s.transport == MCPTransport.STDIO]
    remote_servers = [s for s in enabled if s.transport != MCPTransport.STDIO]
    
    # Connect stdio in batches of 3
    await connect_batched(stdio_servers, batch_size=STDIO_BATCH_SIZE)
    
    # Connect remote in batches of 20
    await connect_batched(remote_servers, batch_size=REMOTE_BATCH_SIZE)
```

### Reconnect Scheduling

Remote transports auto-reconnect on disconnect:

**Pattern** (exponential backoff):
- Max attempts: 5
- Initial delay: 1s
- Max delay: 30s
- Jitter: ±0.5s

**Events emitted**:
- `soothe.mcp.server.disconnected` → on disconnect
- `soothe.mcp.server.reconnecting` → on attempt
- `soothe.mcp.server.connected` → on success
- `soothe.mcp.server.connect_failed_terminal` → on exhausted

**Stdio servers do not auto-reconnect** — user must manually `/mcp reconnect <server>`.

### list_changed Notifications

MCP servers send `tools/list_changed`, `prompts/list_changed`, `resources/list_changed` notifications:

**Handling**:
1. Invalidate per-server cache
2. Re-fetch tools/prompts/resources
3. 16ms debounce to coalesce rapid updates
4. Emit `soothe.mcp.list_changed` event
5. Next turn picks up delta

### Shutdown

Graceful shutdown with deadline enforcement:

```python
async def shutdown(self, deadline_seconds: float = 5.0) -> None:
    """Shutdown MCP connections gracefully."""
    # For stdio: cleanup ladder
    # SIGINT → 100ms poll → SIGTERM → 600ms failsafe → kill -9
    
    # For remote: session.close() then client.__aexit__()
    
    # Emit shutdown event
    emit_mcp_registry_shutdown()
```

## Wire Events

### Server Events

```python
class MCPServerConnectedEvent(SootheEvent):
    type: str = "soothe.mcp.server.connected"
    server_name: str
    transport: str
    tools_count: int

class MCPServerDisconnectedEvent(SootheEvent):
    type: str = "soothe.mcp.server.disconnected"
    server_name: str
    transport: str

class MCPServerReconnectingEvent(SootheEvent):
    type: str = "soothe.mcp.server.reconnecting"
    server_name: str
    attempt: int
    max_attempts: int

class MCPServerConnectFailedEvent(SootheEvent):
    type: str = "soothe.mcp.server.connect_failed"
    server_name: str
    error: str
    is_terminal: bool  # Exhausted attempts
```

### Operation Events

```python
class MCPToolInvokeEvent(SootheEvent):
    type: str = "soothe.mcp.tool.invoke"
    server_name: str
    tool_name: str
    arguments: dict

class MCPResourceReadEvent(SootheEvent):
    type: str = "soothe.mcp.resource.read"
    server_name: str
    uri: str

class MCPListChangedEvent(SootheEvent):
    type: str = "soothe.mcp.list_changed"
    server_name: str
    change_type: str  # "tools" | "prompts" | "resources"
```

## Implementation Details

### MCPRegistry

```python
class MCPRegistry:
    """Daemon-singleton MCP connection manager (RFC-412)."""
    
    def __init__(self, servers: list[MCPServerConfig], secret_resolver: callable):
        self._servers = servers
        self._secret_resolver = secret_resolver
        self._client: MultiServerMCPClient = None
        self._connections: dict[str, MCPConnection] = {}
        self._tools: dict[str, list[BaseTool]] = {}
        self._prompts: dict[str, list[dict]] = {}
        self._resources: dict[str, list[dict]] = {}
        self._defer: dict[str, bool] = {}
    
    async def initialize(self) -> None:
        """Connect all enabled servers."""
        # Build connection specs
        connections = build_connection_specs(servers)
        
        # Create MultiServerMCPClient
        self._client = MultiServerMCPClient(connections)
        
        # Connect in batches
        await connect_batched(servers)
        
        # Fetch tools/prompts/resources
        await fetch_all_capabilities()
    
    def always_loaded_tools(self, workspace: str) -> list[BaseTool]:
        """Get defer=False tools filtered by workspace."""
        return filter_tools(defer=False, workspace)
    
    def deferred_tools(self, workspace: str) -> list[BaseTool]:
        """Get defer=True tools filtered by workspace."""
        return filter_tools(defer=True, workspace)
    
    async def read_resource(self, server: str, uri: str) -> str:
        """Read resource from MCP server."""
        return await self._client.get_resources(server, uris=[uri])
    
    async def get_prompt(self, server: str, prompt: str, arguments: dict) -> str:
        """Fetch prompt from MCP server."""
        return await self._client.get_prompt(server, prompt, arguments)
```

### MCPConnection

```python
class MCPConnection:
    """Per-server connection state."""
    
    server_name: str
    transport: MCPTransport
    tools: list[BaseTool]
    prompts: list[dict]
    resources: list[dict]
    status: str  # "connected" | "disconnected" | "connecting"
    reconnect_attempts: int
```

## Usage Examples

### Configure MCP Servers

```yaml
# config.yml
mcp_servers:
  - name: filesystem
    transport: stdio
    command: ["mcp-server-filesystem", "--root", "/workspace"]
    defer: true
    
  - name: web-tools
    transport: sse
    url: "https://api.mcp-tools.com/sse"
    auth:
      headers:
        Authorization: "Bearer ${MCP_API_KEY}"
    defer: false
```

### Use MCP Tools

```python
# First turn: tools listed in <AVAILABLE_MCP_TOOLS>
# - mcp__filesystem__read_file: Read file contents
# - mcp__filesystem__write_file: Write file contents
# - mcp__web-tools__search: Search the web

# Agent calls mcp_tool_search
matches = mcp_tool_search("search", limit=5)
# Returns:
# - mcp__web-tools__search: Full-text web search with ranking
# - mcp__filesystem__search_files: Search file names

# Agent invokes tool
result = mcp__web-tools__search(query="Python asyncio patterns")
# Tool promoted to always-available
```

### Use MCP Prompts

```python
# Slash command
/mcp__filesystem__review-code language=python

# Fetches prompt body
prompt = await mcp_registry.get_prompt(
    "filesystem",
    "review-code",
    {"language": "python"}
)
```

### Use MCP Resources

```python
# Attachment syntax
message = "Check @filesystem:/src/auth.py for auth logic"

# Extraction + fetch + injection
attachment = process_mcp_resource_attachments(message)
# <MCP_RESOURCE server='filesystem' uri='/src/auth.py'>
# def authenticate(user, password):
#     ...
# </MCP_RESOURCE>
```

## Extension Pattern

### Creating Custom MCP Server

MCP servers are external processes exposing tools via the MCP protocol. See [MCP specification](https://modelcontextprotocol.io) for implementation details.

**Example MCP server (Python)**:
```python
from mcp.server import Server
from mcp.types import Tool, TextContent

server = Server("my-custom-server")

@server.tool()
async def my_custom_tool(arg: str) -> list[TextContent]:
    """My custom MCP tool."""
    result = process_arg(arg)
    return [TextContent(text=f"Result: {result}")]

# Run as stdio transport
await server.run()
```

**Configuration**:
```yaml
mcp_servers:
  - name: my-custom
    transport: stdio
    command: ["python", "-m", "my_mcp_server"]
    defer: true
```

## Best Practices

1. **Defer by default**: Set `defer: true` for most MCP servers to avoid context bloat
2. **Use tool_filter**: Restrict exposed tools to relevant subset
3. **Secure auth headers**: Use `${ENV_VAR}` interpolation, never hardcode secrets
4. **Handle disconnects**: Implement fallback behavior for transient failures
5. **Budget listing**: Keep `<AVAILABLE_MCP_TOOLS>` under 2000 chars
6. **Test connectivity**: Use `soothed doctor` to verify MCP server health

## Troubleshooting

### Common Issues

1. **ImportError on MCP load**:
   - Install `langchain-mcp-adapters>=0.2.0`
   - Check pyproject.toml dependencies

2. **Server connection timeout**:
   - Increase `timeout_seconds` in config
   - Check network connectivity for remote transports
   - Verify MCP server process is running (stdio)

3. **Tool not found in search**:
   - Check server `defer: true` setting
   - Verify `tool_filter` allows the tool
   - Ensure policy permits `mcp:call:<server>:<tool>`

4. **Resource read permission denied**:
   - Check policy `mcp:read:<server>:<uri>`
   - Verify workspace boundary (if applicable)

### Debugging Tips

```bash
# Check MCP server health
soothed doctor --mcp

# Enable MCP debug logs
SOOTHE_LOG_LEVEL=DEBUG soothe -p "use MCP tools"

# Monitor MCP events
grep -i "soothe.mcp.*" ~/.soothe/logs/soothe.log

# Check connection status
grep -i "mcp.*connected" ~/.soothe/logs/soothe.log
```

## Related RFCs

| RFC | Title | Key Sections |
|-----|-------|--------------|
| [RFC-412](../../specs/RFC-412-mcp-management.md) | MCP Management | Full specification |
| [RFC-105](../../specs/RFC-105-progressive-skill-loading.md) | Progressive Skill Loading | Progressive disclosure pattern |
| [RFC-305](../../specs/RFC-305-policy-protocol-architecture.md) | Policy Protocol | Permission model |
| [RFC-600](../../specs/RFC-600-plugin-extension-system.md) | Plugin Extension System | MCP integration |

---

**Previous**: [Tools System](tools.md) | **Next**: [Extension Patterns](extension-patterns.md)