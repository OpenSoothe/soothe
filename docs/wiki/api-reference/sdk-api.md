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

##### `send()`

```python
async def send(message: dict[str, Any]) -> None
```

Send a raw message dict to the daemon.

**Parameters**:
- `message`: Message dict to send

**Example**:
```python
await client.send({"type": "daemon_status"})
```

##### `read_event()`

```python
async def read_event() -> dict[str, Any] | None
```

Read the next event from the daemon. Returns `None` on EOF.

**Returns**: Parsed event dict, or `None` on connection close.

**Example**:
```python
async for _ in range(100):
    event = await client.read_event()
    if event is None:
        break
    print(event.get("type"))
```

##### `send_input()`

```python
async def send_input(
    loop_id: str,
    text: str,
    *,
    autonomous: bool = False,
    max_iterations: int | None = None,
    preferred_subagent: str | None = None,
    model: str | None = None,
    model_params: dict[str, Any] | None = None,
    attachments: list[dict[str, str]] | None = None,
    intent_hint: str | None = None,
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str | None = None,
    response_schema_strict: bool | None = None,
    clarification_mode: str | None = None,
    clarification_answer: bool = False,
    clarification_answers: list[str] | None = None,
) -> None
```

Send user input to the daemon for a subscribed loop (`loop_input`).

**Parameters**:
- `loop_id`: Loop identifier for the subscribed loop
- `text`: User input text
- `autonomous`: Enable autonomous iteration mode
- `max_iterations`: Maximum iterations for autonomous mode
- `preferred_subagent`: Preferred subagent hint for routing
- `model`: Provider:model override string
- `model_params`: Additional model parameters
- `attachments`: Image attachments (mime_type + base64 data)
- `intent_hint`: Suggested intent (e.g. `quiz`, `direct_llm`)
- `response_schema`: Request strict JSON output
- `clarification_mode`: RFC-622 clarification relay mode (`"auto"` / `"manual"`)
- `clarification_answer`: Treat this input as the answer to a pending clarification

**Example**:
```python
await client.send_input("loop_abc123", "What is the capital of France?")
```

##### `send_loop_subscribe()`

```python
async def send_loop_subscribe(
    loop_id: str,
    *,
    stream_delivery: str = "adaptive",
    request_id: str | None = None,
) -> None
```

Subscribe client to loop events for real-time event streaming.

**Parameters**:
- `loop_id`: Loop identifier
- `stream_delivery`: One of `batch` | `adaptive` (default) | `streaming`
- `request_id`: Optional request correlation ID

##### `send_loop_new()`

```python
async def send_loop_new(
    *,
    client_workspace: str | None = None,
    user_id: str | None = None,
    client_workspace_id: str | None = None,
    workspace: str | None = None,
    is_ephemeral: bool = False,
    request_id: str | None = None,
) -> None
```

Create a new loop via daemon RPC.

##### `send_loop_list()`

```python
async def send_loop_list(
    filter_dict: dict[str, Any] | None = None,
    *,
    limit: int = 20,
    request_id: str | None = None,
) -> None
```

Request StrangeLoop instances via daemon RPC.

##### `send_loop_get()`

```python
async def send_loop_get(
    loop_id: str,
    *,
    verbose: bool = False,
    request_id: str | None = None,
) -> None
```

Request loop details via daemon RPC.

##### `send_loop_messages()`

```python
async def send_loop_messages(
    loop_id: str,
    *,
    limit: int = 20,
    offset: int = 0,
    include_events: bool = False,
    request_id: str | None = None,
) -> None
```

Request persisted conversation/activity rows.

##### `send_loop_detach()`

```python
async def send_loop_detach(
    loop_id: str,
    *,
    request_id: str | None = None,
) -> None
```

Unsubscribe from loop events while the loop continues running.

##### `send_loop_delete()`

```python
async def send_loop_delete(
    loop_id: str,
    *,
    request_id: str | None = None,
) -> None
```

Request loop deletion via daemon RPC.

##### `fetch_daemon_status()`

```python
async def fetch_daemon_status(
    *,
    timeout: float = 5.0,
    min_interval_s: float = 1.0,
) -> dict[str, Any]
```

Fetch `daemon_status_response` with TTL cache and in-flight coalescing.

**Returns**: Daemon status response dict with `state`, `version`, `uptime_seconds`, `active_loops`, etc.

**Example**:
```python
status = await client.fetch_daemon_status()
if status["state"] == "ready":
    print(f"Daemon ready (v{status['version']})")
```

##### `request_response()`

```python
async def request_response(
    payload: dict[str, Any],
    *,
    response_type: str,
    timeout: float = 5.0,
) -> dict[str, Any]
```

Send a request and wait for a matching response type.

**Parameters**:
- `payload`: Request payload to send
- `response_type`: Expected response message type
- `timeout`: Maximum seconds to wait

**Returns**: Matching response dict

**Raises**:
- `TimeoutError`: If no matching response is received
- `RuntimeError`: If the daemon returns an error

##### `send_command()`

```python
async def send_command(cmd: str) -> None
```

Send a slash command to the daemon.

**Parameters**:
- `cmd`: Command string

##### `list_skills()`

```python
async def list_skills(*, timeout: float = 15.0) -> dict[str, Any]
```

Request wire-safe skill metadata from the daemon.

##### `invoke_skill()`

```python
async def invoke_skill(
    skill: str,
    args: str = "",
    *,
    timeout: float = 120.0,
    clarification_mode: str | None = None,
) -> dict[str, Any]
```

Resolve a skill on the daemon and receive echo before streaming.

##### `wait_for_daemon_ready()`

```python
async def wait_for_daemon_ready(ready_timeout_s: float = 10.0) -> dict[str, Any]
```

Wait for a daemon readiness message and require ready state.

**Returns**: The `daemon_ready` event on success.

**Raises**:
- `RuntimeError`: If daemon reports `error` or `degraded`
- `TimeoutError`: If timeout expires

##### Properties

- `client_id` (str): Get the client identifier
- `is_connected` (bool): Check if connected to the daemon
- `is_connection_alive()` (bool): Check if WebSocket connection is actually alive

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
- `on_load(context: Context) -> None`: Called when plugin is loaded
- `on_unload() -> None`: Called when plugin is unloaded
- `health_check() -> PluginHealth`: Return plugin health status

**Example**:
```python
from soothe_sdk import plugin, tool, Context, Health

@plugin(
    name="my-plugin",
    version="1.0.0",
    description="My awesome plugin",
    depends=["utils-plugin"],
)
class MyPlugin:
    def __init__(self):
        self.config = None
    
    async def on_load(self, context: Context):
        """Initialize plugin with context."""
        self.config = context.config
        context.logger.info(f"Loaded my-plugin v1.0.0")
    
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
    context: Context,
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
from soothe_sdk import plugin, subagent, Context, SootheConfigProtocol
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
        context: Context,
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
    """Base class for all Soothe progress events."""
    
    type: str
    """Event type identifier (e.g., 'soothe.tool.execution.started')."""
    
    model_config = ConfigDict(extra="allow")
    """Allows subclasses to add extra fields."""
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict for wire-format emission."""
        ...
    
    def emit(self, logger: logging.Logger) -> None:
        """Emit this event via the LangGraph stream writer (daemon-side)."""
        ...
```

Event subclasses (e.g. `LifecycleEvent`, `ProtocolEvent`, `SubagentEvent`, `OutputEvent`, `ErrorEvent`) inherit from `SootheEvent` and add their own fields. The `ErrorEvent` subclass adds a required `error: str` field.```

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
VerbosityLevel = Literal["quiet", "normal", "debug"]
"""User-configured verbosity level for filtering display content."""

# quiet   - Minimal output (errors only)
# normal  - Standard output (important events)
# debug   - All output (all events including debug)
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

- **[Core API Reference](core-api.md)** - Core framework API
- **[Daemon API Reference](daemon-api.md)** - Daemon server API
- **[Capabilities: Extension Patterns](../capabilities/extension-patterns.md)** - Plugin development guide
- **[RFC-600 Plugin System](../../specs/RFC-600-plugin-extension-system.md)** - Plugin specification