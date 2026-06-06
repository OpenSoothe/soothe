# SDK API Reference

The Soothe SDK (`soothe_sdk`) provides client and plugin development APIs for building applications that communicate with the Soothe daemon.

**Package**: `soothe-sdk`  
**Import**: `from soothe_sdk import ...`  
**Python**: `>=3.11`

---

## Table of Contents

1. [WebSocket Client](#websocket-client)
2. [Plugin Decorators](#plugin-decorators)
3. [Event System](#event-system)
4. [Protocol Interfaces](#protocol-interfaces)
5. [Utility Functions](#utility-functions)

---

## WebSocket Client

### WebSocketClient

**Import**: `from soothe_sdk.client import WebSocketClient`

WebSocket client for bidirectional communication with the Soothe daemon.

#### Constructor

```python
WebSocketClient(
    url: str = "ws://localhost:8765",
    *,
    client_id: str | None = None,
    max_frame_size: int = 10 * 1024 * 1024,  # 10 MiB
)
```

**Parameters**:
- `url`: WebSocket URL of the daemon (default: `ws://localhost:8765`)
- `client_id`: Optional client identifier for log differentiation. Auto-generated if not provided (8 hex chars)
- `max_frame_size`: Maximum incoming WebSocket message size in bytes. Should match daemon's `transport.websocket.max_frame_size`

**Example**:
```python
from soothe_sdk.client import WebSocketClient

# Connect to local daemon
client = WebSocketClient("ws://localhost:8765", client_id="my-app")

# Connect to remote daemon with custom frame size
client = WebSocketClient(
    url="wss://soothe.example.com/ws",
    client_id="remote-client",
    max_frame_size=20 * 1024 * 1024,  # 20 MiB
)
```

#### Methods

##### `connect()`

```python
async def connect() -> None
```

Connect to the daemon.

**Raises**:
- `ConnectionError`: If connection fails

**Example**:
```python
import asyncio
from soothe_sdk.client import WebSocketClient

async def main():
    client = WebSocketClient()
    await client.connect()
    print("Connected to daemon")

asyncio.run(main())
```

##### `close()`

```python
async def close() -> None
```

Close the connection to the daemon.

**Example**:
```python
client = WebSocketClient()
await client.connect()
# ... use client ...
await client.close()
```

##### `send_query()`

```python
async def send_query(
    query: str,
    *,
    thread_id: str | None = None,
    workspace: str | None = None,
    verbosity: str = "normal",
    mode: str = "agentic",
    intent: str | None = None,
    autopilot_job: dict | None = None,
) -> str
```

Send a query to the daemon and return the thread ID.

**Parameters**:
- `query`: User query text
- `thread_id`: Optional thread ID for conversation continuity
- `workspace`: Optional workspace path for file operations
- `verbosity`: Verbosity level (`"quiet"`, `"normal"`, `"verbose"`, `"debug"`)
- `mode`: Execution mode (`"agentic"`, `"stream"`)
- `intent`: Optional intent hint (`"plan"`, `"act"`, `"ask"`)
- `autopilot_job`: Optional autopilot job descriptor

**Returns**: Thread ID for the conversation

**Example**:
```python
# Simple query
thread_id = await client.send_query("What is the capital of France?")

# Continue conversation
await client.send_query(
    "What about Germany?",
    thread_id=thread_id
)

# With workspace
thread_id = await client.send_query(
    "Read the README.md file",
    workspace="/home/user/projects/myapp"
)
```

##### `stream_events()`

```python
async def stream_events() -> AsyncGenerator[dict[str, Any], None]
```

Stream events from the daemon as an async generator.

**Yields**: Event dictionaries with the structure:
```python
{
    "type": "event_type",
    "namespace": "soothe",
    "mode": "custom",
    "data": {...}
}
```

**Example**:
```python
async def process_query(query: str):
    client = WebSocketClient()
    await client.connect()
    
    thread_id = await client.send_query(query)
    
    async for event in client.stream_events():
        event_type = event.get("type")
        
        if event_type == "assistant_output":
            content = event.get("data", {}).get("content", "")
            print(content, end="", flush=True)
        
        elif event_type == "tool_start":
            tool_name = event.get("data", {}).get("name")
            print(f"\n[Tool: {tool_name}]")
        
        elif event_type == "loop_complete":
            print("\n[Done]")
            break
    
    await client.close()
```

##### `daemon_status()`

```python
async def daemon_status() -> dict[str, Any]
```

Get the current status of the daemon.

**Returns**: Status dictionary with structure:
```python
{
    "state": "ready" | "starting" | "warming" | "error",
    "version": "1.2.3",
    "uptime_seconds": 1234.56,
    "active_loops": 2,
    "protocol_statuses": {...},
}
```

**Example**:
```python
status = await client.daemon_status()
if status["state"] == "ready":
    print(f"Daemon ready (v{status['version']})")
else:
    print(f"Daemon not ready: {status['state']}")
```

##### `subscribe_loop()`

```python
async def subscribe_loop(
    thread_id: str,
    loop_id: str | None = None
) -> str
```

Subscribe to events for a specific AgentLoop.

**Parameters**:
- `thread_id`: Thread ID to subscribe to
- `loop_id`: Optional loop ID. If not provided, a new one is generated

**Returns**: Loop ID for the subscription

**Example**:
```python
loop_id = await client.subscribe_loop(thread_id)
print(f"Subscribed to loop {loop_id}")

# Stream events for this loop
async for event in client.stream_events():
    if event.get("loop_id") == loop_id:
        # Process event
        pass
```

##### `send_control()`

```python
async def send_control(
    command: str,
    *,
    thread_id: str | None = None,
    loop_id: str | None = None,
    params: dict | None = None,
) -> None
```

Send a control message to the daemon.

**Parameters**:
- `command`: Control command (e.g., `"cancel"`, `"pause"`, `"resume"`)
- `thread_id`: Optional thread ID
- `loop_id`: Optional loop ID
- `params`: Optional command parameters

**Example**:
```python
# Cancel current execution
await client.send_control("cancel", loop_id=loop_id)

# Pause execution
await client.send_control("pause", loop_id=loop_id)
```

---

## Plugin Decorators

### @plugin

**Import**: `from soothe_sdk import plugin`

Decorator for defining a Soothe plugin.

#### Signature

```python
@plugin(
    name: str,
    version: str = "0.1.0",
    description: str = "",
    depends: list[str] | None = None,
    priority: int = 0,
)
class MyPlugin:
    ...
```

**Parameters**:
- `name`: Plugin name (must be unique)
- `version`: Plugin version (semantic versioning)
- `description`: Human-readable description
- `depends`: List of dependency plugin names
- `priority`: Load priority (higher = earlier)

**Plugin Methods**:
- `on_load(context: PluginContext) -> None`: Called when plugin is loaded
- `on_unload() -> None`: Called when plugin is unloaded
- `health_check() -> PluginHealth`: Return plugin health status

**Example**:
```python
from soothe_sdk import plugin, tool, PluginContext, Health

@plugin(
    name="my-plugin",
    version="1.0.0",
    description="My awesome plugin",
    depends=["utils-plugin"],
)
class MyPlugin:
    def __init__(self):
        self.config = None
    
    async def on_load(self, context: PluginContext):
        """Initialize plugin with context."""
        self.config = context.config
        print(f"Loaded {context.plugin_name} v{context.plugin_version}")
    
    async def on_unload(self):
        """Cleanup when unloading."""
        print("Unloading plugin")
    
    def health_check(self) -> Health:
        """Return plugin health."""
        return Health(
            status="healthy",
            details={"tools": 2}
        )
    
    @tool(name="my_tool", description="Does something")
    def my_tool(self, query: str) -> str:
        return f"Result: {query}"
```

---

### @tool

**Import**: `from soothe_sdk import tool`

Decorator for defining a tool within a plugin.

#### Signature

```python
@tool(
    name: str | None = None,
    description: str = "",
    category: str = "general",
    timeout: float | None = None,
    requires_workspace: bool = False,
)
def my_tool(arg: str) -> str:
    ...
```

**Parameters**:
- `name`: Tool name (defaults to function name)
- `description`: Tool description for LLM
- `category`: Tool category for organization
- `timeout`: Execution timeout in seconds
- `requires_workspace`: Whether tool needs workspace access

**Example**:
```python
from soothe_sdk import plugin, tool

@plugin(name="utils", version="1.0.0")
class UtilsPlugin:
    @tool(
        name="read_json",
        description="Read and parse a JSON file",
        category="file",
        timeout=10.0,
    )
    def read_json(self, path: str) -> dict:
        """Read a JSON file from workspace.
        
        Args:
            path: Relative path to JSON file
            
        Returns:
            Parsed JSON data
        """
        import json
        from pathlib import Path
        
        full_path = Path(self.workspace) / path
        with open(full_path) as f:
            return json.load(f)
    
    @tool(
        name="search_files",
        description="Search for files matching a pattern",
        category="search",
    )
    def search_files(self, pattern: str, directory: str = ".") -> list[str]:
        """Search for files by glob pattern.
        
        Args:
            pattern: Glob pattern (e.g., "*.py")
            directory: Directory to search in
            
        Returns:
            List of matching file paths
        """
        from pathlib import Path
        
        base = Path(self.workspace) / directory
        return [str(p.relative_to(self.workspace)) for p in base.glob(pattern)]
```

---

### @subagent

**Import**: `from soothe_sdk import subagent`

Decorator for defining a subagent within a plugin.

#### Signature

```python
@subagent(
    name: str | None = None,
    description: str = "",
    model_role: str = "subagent",
    timeout: float | None = None,
)
async def create_subagent(
    model,
    config: SootheConfigProtocol,
    context: PluginContext,
) -> CompiledSubAgent:
    ...
```

**Parameters**:
- `name`: Subagent name (defaults to function name)
- `description`: Subagent description for delegation
- `model_role`: Model role for LLM selection
- `timeout`: Execution timeout in seconds

**Returns**: `CompiledSubAgent` from deepagents

**Example**:
```python
from soothe_sdk import plugin, subagent, PluginContext, SootheConfigProtocol
from deepagents import CompiledSubAgent, SubAgent

@plugin(name="research", version="1.0.0")
class ResearchPlugin:
    @subagent(
        name="web-researcher",
        description="Research a topic using web search",
        model_role="subagent",
        timeout=60.0,
    )
    async def create_researcher(
        self,
        model,
        config: SootheConfigProtocol,
        context: PluginContext,
    ) -> CompiledSubAgent:
        """Create web research subagent.
        
        Args:
            model: LLM model instance
            config: Soothe configuration
            context: Plugin context
            
        Returns:
            Compiled subagent for web research
        """
        from langchain_core.tools import Tool
        
        # Define tools
        tools = [
            Tool(
                name="web_search",
                description="Search the web",
                func=self._web_search,
            ),
            Tool(
                name="extract_content",
                description="Extract content from URL",
                func=self._extract_content,
            ),
        ]
        
        # Create subagent
        agent = SubAgent(
            name="web-researcher",
            model=model,
            tools=tools,
            system_prompt=(
                "You are a web research specialist. "
                "Search for information and provide comprehensive summaries."
            ),
        )
        
        return agent.compile()
```

---

### @tool_group

**Import**: `from soothe_sdk import tool_group`

Decorator for grouping related tools.

#### Signature

```python
@tool_group(
    name: str,
    description: str = "",
    category: str = "general",
)
class MyToolGroup:
    ...
```

**Example**:
```python
from soothe_sdk import plugin, tool_group, tool

@plugin(name="data-tools", version="1.0.0")
class DataToolsPlugin:
    @tool_group(name="csv", description="CSV file operations")
    class CSVTools:
        @tool(name="read_csv", description="Read CSV file")
        def read(self, path: str) -> list[dict]:
            import csv
            with open(path, newline="") as f:
                return list(csv.DictReader(f))
        
        @tool(name="write_csv", description="Write CSV file")
        def write(self, path: str, data: list[dict]) -> int:
            import csv
            with open(path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=data[0].keys())
                writer.writeheader()
                writer.writerows(data)
                return len(data)
```

---

## Event System

### SootheEvent

**Import**: `from soothe_sdk.core.events import SootheEvent`

Base class for all Soothe events.

#### Definition

```python
class SootheEvent(BaseModel):
    """Base event type for all Soothe events."""
    
    type: str
    """Event type identifier (e.g., 'soothe.tool.started')."""
    
    timestamp: float = Field(default_factory=lambda: time.time())
    """Unix timestamp when event was created."""
    
    loop_id: str | None = None
    """AgentLoop ID if event is loop-scoped."""
    
    thread_id: str | None = None
    """Thread ID for persistence scope."""
```

**Example**:
```python
from soothe_sdk.core.events import SootheEvent

class MyCustomEvent(SootheEvent):
    """Custom event for my plugin."""
    
    type: str = "soothe.my_plugin.custom"
    data: str
    count: int = 0

# Create event
event = MyCustomEvent(
    data="Hello",
    count=42,
    loop_id="loop-123",
    thread_id="thread-456",
)

# Serialize
print(event.model_dump_json())
```

---

### register_event()

**Import**: `from soothe_sdk import register_event`

Register a custom event type in the event catalog.

#### Signature

```python
def register_event(
    event_class: type[SootheEvent],
    *,
    summary_template: str | None = None,
) -> None:
```

**Parameters**:
- `event_class`: Event class to register
- `summary_template`: Optional template for event summaries

**Example**:
```python
from soothe_sdk import register_event
from soothe_sdk.core.events import SootheEvent

class FileProcessedEvent(SootheEvent):
    """Event emitted when a file is processed."""
    
    type: str = "soothe.file_processor.processed"
    file_path: str
    lines_processed: int
    status: str  # "success" | "error"

# Register with summary template
register_event(
    FileProcessedEvent,
    summary_template="Processed {file_path}: {lines_processed} lines ({status})",
)

# Now the event will be recognized and logged with the summary
```

---

### SubagentEvent

**Import**: `from soothe_sdk import SubagentEvent`

Event type for subagent lifecycle events.

#### Definition

```python
class SubagentEvent(SootheEvent):
    """Subagent lifecycle event."""
    
    type: str  # soothe.subagent.started, soothe.subagent.completed, etc.
    subagent_name: str
    """Name of the subagent."""
    
    description: str | None = None
    """Description of the subagent's task."""
    
    status: str = "running"
    """Status: 'running', 'completed', 'failed'."""
    
    result: str | None = None
    """Result summary when completed."""
    
    error: str | None = None
    """Error message if failed."""
    
    duration_seconds: float | None = None
    """Duration of subagent execution."""
```

**Example**:
```python
from soothe_sdk import SubagentEvent

# Subagent started
started = SubagentEvent(
    type="soothe.subagent.started",
    subagent_name="web-researcher",
    description="Research quantum computing",
    loop_id="loop-123",
)

# Subagent completed
completed = SubagentEvent(
    type="soothe.subagent.completed",
    subagent_name="web-researcher",
    status="completed",
    result="Found 15 relevant articles",
    duration_seconds=12.5,
    loop_id="loop-123",
)
```

---

## Protocol Interfaces

### AsyncPersistStore

**Import**: `from soothe_sdk.protocols import AsyncPersistStore`

Protocol for key-value persistence (RFC-302).

#### Definition

```python
class AsyncPersistStore(Protocol):
    """Async key-value store protocol."""
    
    async def get(self, key: str) -> bytes | None:
        """Get value by key.
        
        Args:
            key: Key to retrieve
            
        Returns:
            Value bytes or None if not found
        """
        ...
    
    async def set(self, key: str, value: bytes) -> None:
        """Set key to value.
        
        Args:
            key: Key to set
            value: Value bytes
        """
        ...
    
    async def delete(self, key: str) -> None:
        """Delete key.
        
        Args:
            key: Key to delete
        """
        ...
    
    async def list_keys(self, prefix: str) -> list[str]:
        """List keys with prefix.
        
        Args:
            prefix: Key prefix to filter
            
        Returns:
            List of matching keys
        """
        ...
```

**Implementations**:
- `soothe.backends.persistence.sqlite.SqlitePersistStore`
- `soothe.backends.persistence.postgres.PostgresPersistStore`

**Example**:
```python
from soothe_sdk.protocols import AsyncPersistStore

async def save_result(store: AsyncPersistStore, task_id: str, result: dict):
    """Save task result to store."""
    import json
    
    await store.set(
        f"task:{task_id}",
        json.dumps(result).encode("utf-8")
    )
    
async def load_result(store: AsyncPersistStore, task_id: str) -> dict | None:
    """Load task result from store."""
    import json
    
    data = await store.get(f"task:{task_id}")
    if data:
        return json.loads(data.decode("utf-8"))
    return None
```

---

### VectorStoreProtocol

**Import**: `from soothe_sdk.protocols import VectorStoreProtocol`

Protocol for vector database operations (RFC-303).

#### Definition

```python
class VectorStoreProtocol(Protocol):
    """Vector database protocol."""
    
    async def add_vectors(
        self,
        vectors: list[VectorRecord],
    ) -> list[str]:
        """Add vectors to the store.
        
        Args:
            vectors: List of vector records to add
            
        Returns:
            List of vector IDs
        """
        ...
    
    async def search(
        self,
        query_vector: list[float],
        k: int = 5,
        filter: dict | None = None,
    ) -> list[tuple[str, float]]:
        """Search for similar vectors.
        
        Args:
            query_vector: Query vector
            k: Number of results to return
            filter: Optional metadata filter
            
        Returns:
            List of (vector_id, similarity_score) tuples
        """
        ...
    
    async def delete_vector(self, vector_id: str) -> None:
        """Delete a vector by ID.
        
        Args:
            vector_id: ID of vector to delete
        """
        ...
```

**Implementations**:
- `soothe.backends.vector_store.pgvector.PGVectorStore`
- `soothe.backends.vector_store.sqlite_vec.SqliteVecStore`
- `soothe.backends.vector_store.weaviate.WeaviateStore`

**Example**:
```python
from soothe_sdk.protocols import VectorStoreProtocol, VectorRecord

async def index_document(
    store: VectorStoreProtocol,
    doc_id: str,
    content: str,
    embedding: list[float],
):
    """Index a document with its embedding."""
    record = VectorRecord(
        id=doc_id,
        vector=embedding,
        metadata={
            "content": content,
            "timestamp": time.time(),
        }
    )
    
    await store.add_vectors([record])

async def search_similar(
    store: VectorStoreProtocol,
    query_embedding: list[float],
    top_k: int = 10,
) -> list[str]:
    """Search for similar documents."""
    results = await store.search(
        query_vector=query_embedding,
        k=top_k,
    )
    
    return [doc_id for doc_id, score in results]
```

---

### PermissionSet

**Import**: `from soothe_sdk.protocols import PermissionSet`

Permission set for policy-based access control.

#### Definition

```python
class PermissionSet(BaseModel):
    """Set of permissions for policy enforcement."""
    
    permissions: list[Permission]
    """List of granted permissions."""
    
    def allows(self, action: str, category: str, scope: str = "*") -> bool:
        """Check if permission is granted.
        
        Args:
            action: Action to check (e.g., 'read', 'write')
            category: Resource category (e.g., 'file', 'tool')
            scope: Resource scope (e.g., 'workspace', 'system')
            
        Returns:
            True if permission is granted
        """
        ...
```

**Example**:
```python
from soothe_sdk.protocols import PermissionSet, Permission

# Create permission set
perms = PermissionSet(permissions=[
    Permission(
        category="file",
        action="read",
        scope="workspace",
    ),
    Permission(
        category="file",
        action="write",
        scope="workspace",
    ),
    Permission(
        category="tool",
        action="execute",
        scope="safe",
    ),
])

# Check permissions
if perms.allows("read", "file", "workspace"):
    print("Can read workspace files")

if not perms.allows("execute", "tool", "system"):
    print("Cannot execute system tools")
```

---

### PolicyContext

**Import**: `from soothe_sdk.protocols import PolicyContext`

Context for policy evaluation.

#### Definition

```python
class PolicyContext(BaseModel):
    """Context for policy evaluation."""
    
    user_id: str | None = None
    """User identifier."""
    
    workspace: str | None = None
    """Current workspace path."""
    
    thread_id: str | None = None
    """Current thread ID."""
    
    loop_id: str | None = None
    """Current loop ID."""
    
    metadata: dict[str, Any] = Field(default_factory=dict)
    """Additional context metadata."""
```

---

### ActionRequest

**Import**: `from soothe_sdk.protocols import ActionRequest`

Request for action authorization.

#### Definition

```python
class ActionRequest(BaseModel):
    """Request for action authorization."""
    
    category: str
    """Action category (e.g., 'file', 'tool', 'subagent')."""
    
    action: str
    """Action type (e.g., 'read', 'write', 'execute')."""
    
    scope: str = "*"
    """Action scope (e.g., 'workspace', 'system')."""
    
    resource: str | None = None
    """Specific resource identifier."""
    
    context: PolicyContext | None = None
    """Policy evaluation context."""
```

---

## Utility Functions

### emit_progress()

**Import**: `from soothe_sdk import emit_progress`

Emit a progress event during tool execution.

#### Signature

```python
async def emit_progress(
    message: str,
    *,
    percentage: float | None = None,
    data: dict | None = None,
) -> None:
```

**Parameters**:
- `message`: Progress message
- `percentage`: Optional progress percentage (0-100)
- `data`: Optional additional data

**Example**:
```python
from soothe_sdk import plugin, tool, emit_progress

@plugin(name="downloader", version="1.0.0")
class DownloaderPlugin:
    @tool(name="download_file", description="Download a large file")
    async def download_file(self, url: str, path: str) -> str:
        """Download file with progress updates."""
        import aiohttp
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                total = int(resp.headers.get("content-length", 0))
                downloaded = 0
                
                with open(path, "wb") as f:
                    async for chunk in resp.content.iter_chunked(8192):
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total > 0:
                            pct = (downloaded / total) * 100
                            await emit_progress(
                                f"Downloaded {downloaded}/{total} bytes",
                                percentage=pct,
                                data={"url": url}
                            )
        
        return f"Downloaded to {path}"
```

---

### format_cli_error()

**Import**: `from soothe_sdk.utils.formatting import format_cli_error`

Format an error for CLI display.

#### Signature

```python
def format_cli_error(
    error: Exception,
    *,
    include_traceback: bool = False,
    verbosity: str = "normal",
) -> str:
```

**Parameters**:
- `error`: Exception to format
- `include_traceback`: Include full traceback
- `verbosity`: Verbosity level (`"quiet"`, `"normal"`, `"verbose"`, `"debug"`)

**Returns**: Formatted error string

**Example**:
```python
from soothe_sdk.utils.formatting import format_cli_error

try:
    # ... some operation ...
    pass
except Exception as e:
    error_msg = format_cli_error(
        e,
        include_traceback=True,
        verbosity="verbose",
    )
    print(error_msg)
```

---

## Configuration Types

### VerbosityLevel

**Import**: `from soothe_sdk.core.types import VerbosityLevel`

Enum for verbosity levels.

```python
class VerbosityLevel(str, Enum):
    """Verbosity levels for event filtering."""
    
    QUIET = "quiet"
    """Minimal output - errors only."""
    
    NORMAL = "normal"
    """Standard output - important events."""
    
    VERBOSE = "verbose"
    """Detailed output - most events."""
    
    DEBUG = "debug"
    """All output - all events including debug."""
```

---

### VerbosityTier

**Import**: `from soothe_sdk import VerbosityTier`

Tier definitions for event filtering.

```python
class VerbosityTier(BaseModel):
    """Tier definition for event filtering."""
    
    level: VerbosityLevel
    """Verbosity level."""
    
    event_types: list[str]
    """Event types included at this level."""
    
    min_level: VerbosityLevel | None = None
    """Minimum level required."""
```

---

## See Also

- **[REST API Reference](rest-api.md)** - HTTP REST endpoints
- **[Core API Reference](core-api.md)** - Core framework API
- **[Capabilities: Extension Patterns](../capabilities/extension-patterns.md)** - Plugin development guide
- **[RFC-600 Plugin System](../../specs/RFC-600-plugin-extension-system.md)** - Plugin specification