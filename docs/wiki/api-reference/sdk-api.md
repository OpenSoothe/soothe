# Client & Plugin SDK (`soothe_sdk`)

The `soothe_sdk` package is the public API surface for two audiences: **client developers** who build applications that talk to a running daemon, and **plugin authors** who extend the agent with custom tools, subagents, and events. It is intentionally lightweight — it re-exports the protocol definitions from the core package so plugins can type-check without depending on the daemon.

> **Source**: `packages/soothe-sdk/src/soothe_sdk/`
> **Package**: `soothe-sdk` · **Python**: `>=3.11` · **Stability**: ✅ Stable (client/plugin), ⚠️ Beta (protocols)
> **Version constraint**: `__soothe_required_version__ = ">=0.5.0,<1.0.0"`

---

## WebSocket Client

> **Source**: `packages/soothe-sdk/src/soothe_sdk/client/websocket.py`

`WebSocketClient` is the bidirectional communication client for talking to a Soothe daemon. It handles connection lifecycle, the RFC-0013 handshake protocol, background event reading, and high-level RPC helpers.

### Key Design Decisions

- **Background reader task** — The client spawns a background `asyncio.Task` that continuously drains the WebSocket into an inbound queue. This prevents the daemon from being blocked by a stalled consumer (e.g., a heavy Textual UI on the same event loop). Without this, a slow UI render would backpressure the daemon's send path.
- **Bounded inbound queue** — Default capacity 10,000 events. Overflow drops events with a counter (`_inbound_dropped`), preventing unbounded memory growth.
- **Frame size coordination** — Default `max_frame_size` is 10 MiB, matching the daemon default. The `websockets` library defaults to 1 MiB, which silently closes the connection (code 1009) on large events. If you customize the daemon's frame size, update the client's too.
- **Transitional state handling** — If the daemon reports `starting` or `warming` on connect, the client polls every 50ms until `ready` (RFC-450). The daemon does not re-push `daemon_ready` on state transition, so proactive re-requesting is required.

### Connection Lifecycle

```python
from soothe_sdk.client import WebSocketClient

client = WebSocketClient("ws://localhost:8765", client_id="my-app")
await client.connect()
await client.wait_for_daemon_ready()  # blocks until daemon is ready
# ... send_input, read_event, etc. ...
await client.close()
```

### High-Level RPC Helpers

Beyond raw `send()`/`read_event()`, the client provides typed helpers that handle the wire protocol:

| Method | Purpose |
|--------|---------|
| `send_loop_new()` | Create a new StrangeLoop on the daemon |
| `send_loop_subscribe(loop_id)` | Subscribe to a loop's event stream |
| `send_input(loop_id, text)` | Send user input to a subscribed loop |
| `send_loop_list()` / `send_loop_get()` | Query loop metadata |
| `send_loop_messages()` | Fetch persisted conversation/activity rows |
| `send_loop_detach()` | Unsubscribe while the loop keeps running |
| `send_loop_delete()` | Request loop deletion |
| `fetch_daemon_status()` | TTL-cached status with in-flight coalescing |
| `send_command(cmd)` | Send a slash command (`/memory`, `/thread`, etc.) |
| `list_skills()` / `invoke_skill()` | Skill discovery and invocation |
| `request_response(payload, response_type)` | Request-response with timeout + error handling |

`send_input()` is the most feature-rich — it supports autonomous mode, max iterations, preferred subagent routing, model overrides, image attachments, intent hints, response schema enforcement, and RFC-622 clarification relay. See the source docstring for full parameter details.

### `fetch_daemon_status()` Coalescing

This method uses a TTL cache (default 5s timeout, 1s min interval) and *in-flight request coalescing* — if two callers request status simultaneously, only one RPC is sent and both receive the same result. This prevents status-polling storms from multiple UI components.

---

## Plugin Decorators

> **Source**: `packages/soothe-sdk/src/soothe_sdk/plugin/`

The plugin system uses a decorator-based API inspired by FastAPI. Decorators attach metadata to classes and functions; the daemon's plugin loader discovers and instantiates them at startup.

### `@plugin` — Plugin Definition

Marks a class as a Soothe plugin. The class can implement lifecycle hooks:
- `async on_load(context)` — called when the plugin is loaded; receives a `Context` with config, logger, and workspace access
- `async on_unload()` — cleanup hook
- `health_check() -> Health` — returns plugin health status

The `depends` parameter declares load-order dependencies (plugin names), and `priority` (higher = earlier) controls ordering when dependencies don't dictate it.

### `@tool` — Tool Definition

Defines an LLM-callable tool within a plugin. The decorator captures a name (defaults to function name), description (fed to the LLM), category, timeout, and workspace requirement. The function's signature is introspected for the tool's input schema.

### `@subagent` — Subagent Definition

Defines a subagent factory. Unlike tools (which are simple functions), subagents are async factory functions that receive a `model`, `config`, and `context`, and return a `CompiledSubAgent` from deepagents. This is because subagents need their own tool set, system prompt, and model configuration.

### `@tool_group` — Tool Grouping

Groups related tools into a namespace. Tools within a group share a class instance, enabling shared state (e.g., a database connection opened in `on_load`).

### Minimal Plugin Example

```python
from soothe_sdk import plugin, tool

@plugin(name="file-utils", version="1.0.0", description="File utilities")
class FileUtilsPlugin:
    @tool(name="read_json", description="Read and parse a JSON file", category="file")
    def read_json(self, path: str) -> dict:
        import json
        with open(path) as f:
            return json.load(f)
```

> **Gotcha**: Tool functions should use stdlib imports inside the function body, not at module top-level. This keeps plugin import fast and avoids pulling heavy dependencies when the tool isn't used.

---

## Event System

> **Source**: `packages/soothe-sdk/src/soothe_sdk/core/events.py`

### SootheEvent

`SootheEvent` is the base class for all progress events. It's a Pydantic model with `model_config = ConfigDict(extra="allow")`, meaning subclasses can add arbitrary fields without redefining the base. Every event has a `type` string (e.g., `soothe.tool.execution.started`).

The `emit()` method pushes the event through the LangGraph stream writer (daemon-side), and `to_dict()` serializes it for wire transmission. The event hierarchy includes `LifecycleEvent`, `ProtocolEvent`, `SubagentEvent`, `OutputEvent`, and `ErrorEvent` (which adds a required `error: str` field).

### Custom Event Registration

```python
from soothe_sdk import register_event
from soothe_sdk.core.events import SootheEvent

class FileProcessedEvent(SootheEvent):
    type: str = "soothe.file_processor.processed"
    file_path: str
    lines_processed: int
    status: str

register_event(FileProcessedEvent, summary_template="Processed {file_path}: {lines_processed} lines ({status})")
```

`register_event()` adds the event type to the daemon's event catalog with an optional summary template. The template uses `{field}` placeholders that are filled from the event instance — this is how the CLI renders human-readable progress lines from structured events.

### SubagentEvent

A specialized event for subagent lifecycle: `started`, `completed`, `failed`. Carries `subagent_name`, `description`, `status`, `result`, `error`, and `duration_seconds`. Emitted automatically by the StrangeLoop when delegating to subagents.

---

## Protocol Interfaces

> **Source**: `packages/soothe-sdk/src/soothe_sdk/protocols/`

The SDK re-exports the same protocol definitions as the core package (see [Core API: Protocol Definitions](core-api.md#protocol-definitions)). This is intentional — plugin authors can depend on `soothe_sdk.protocols` without importing the full `soothe` package.

### AsyncPersistStore

Async key-value store with `get(key) -> bytes | None`, `set(key, value: bytes)`, `delete(key)`, and `list_keys(prefix)`. Values are raw bytes — serialization is the caller's responsibility. Implementations: `SQLitePersistStore`, `PostgreSQLPersistStore`.

### VectorStoreProtocol

Vector database operations: `add_vectors(records)`, `search(query_vector, k, filter)`, `delete_vector(id)`. Returns `(vector_id, score)` tuples from search. Implementations: `PGVectorStore`, `SQLiteVecStore`, `WeaviateStore`.

### PermissionSet & Policy Types

`PermissionSet` holds a list of `Permission` objects (category/action/scope triples). The `allows(action, category, scope)` method checks if a permission is granted, supporting wildcards (`*` scope matches any). `ActionRequest` and `PolicyContext` are the inputs to `PolicyProtocol.check()` — see [Core API](core-api.md) for the policy enforcement flow.

---

## Utility Functions

### `emit_progress()`

```python
from soothe_sdk import emit_progress

await emit_progress("Processing batch 3/10", percentage=30.0, data={"batch_id": 3})
```

Emits a progress event during tool execution. Must be called from within a tool that's running inside the daemon's LangGraph stream context — it uses `contextvars` to find the active stream writer. Calling it outside a tool execution context is a no-op (not an error).

### `format_cli_error()`

Formats exceptions for CLI display with configurable verbosity (`quiet`, `normal`, `verbose`, `debug`) and optional traceback inclusion. Used by the CLI to produce consistent error output.

---

## Configuration Types

### VerbosityLevel & VerbosityTier

`VerbosityLevel` is a `Literal["quiet", "normal", "debug"]` — the user-configured verbosity that controls which events are displayed. `VerbosityTier` maps verbosity levels to allowed event types, enabling progressive disclosure: `quiet` shows only errors, `normal` shows important lifecycle events, `debug` shows everything including internal protocol events.

The tier system is how a single event stream serves both end-users (who want clean output) and developers (who want full observability) — the same events are emitted regardless; only the *filtering* changes.

---

## See Also

- [Core API](core-api.md) — Protocol definitions and backend implementations
- [Daemon API](daemon-api.md) — The server this client connects to
- [Capabilities: Extension Patterns](../capabilities/extension-patterns.md) — Plugin development guide
- [RFC-600 Plugin System](../../specs/RFC-600-plugin-extension-system.md) — Plugin specification
