---
title: "Client & Plugin SDK API"
parent: API Reference
nav_order: 3
description: >-
  The soothe_sdk package — slim contracts for plugin authors and shared wire/display/protocol APIs.
  Transport lives in soothe-client-python (soothe_client).
---

# Plugin & Contracts SDK (`soothe_sdk`)

The `soothe_sdk` package is the public API surface for **plugin authors** who extend the agent with custom tools, subagents, and events, plus **shared contracts** (wire codec, paths, display/UX helpers, protocols) used by daemon, CLI, and clients.

The WebSocket transport client lives in **`soothe-client-python`** (`soothe_client`), not in this package.

> **Source**: `packages/soothe-sdk/src/soothe_sdk/`
> **Package**: `soothe-sdk` · **Python**: `>=3.11` · **Stability**: ✅ Stable (1.0.0+)
> **Install constraint**: `soothe-sdk>=1.0.0,<2.0.0`

Root package exports **version metadata only**. Always import from subpackages.

---

## Transport client

> **Source**: `client/python/src/soothe_client/`

```python
from soothe_client import WebSocketClient

client = WebSocketClient("ws://localhost:8765", client_id="my-app")
await client.connect()
await client.wait_for_daemon_ready()
```

Wire codec and path constants remain in the SDK:

```python
from soothe_sdk.wire import ProtocolError, messages_from_wire_dicts
from soothe_sdk.paths import SOOTHE_HOME, SOOTHE_DATA_DIR
```

---

## Plugin Decorators

> **Source**: `packages/soothe-sdk/src/soothe_sdk/plugin/`

### `@plugin` / `@tool` / `@subagent` / `@tool_group`

```python
from soothe_sdk.plugin import plugin, tool, subagent, tool_group

@plugin(name="file-utils", version="1.0.0", description="File utilities")
class FileUtilsPlugin:
    @tool(name="read_json", description="Read and parse a JSON file")
    def read_json(self, path: str) -> dict:
        import json
        with open(path) as f:
            return json.load(f)
```

Types: `PluginManifest`, `PluginContext`, `PluginHealth` (full names; short aliases removed in 1.0.0).

> **Gotcha**: Prefer stdlib imports inside tool bodies to keep plugin import fast.

---

## Event System

> **Source**: `packages/soothe-sdk/src/soothe_sdk/core/events.py`

```python
from soothe_sdk.core.events import SootheEvent
from soothe_sdk.plugin import register_event

class FileProcessedEvent(SootheEvent):
    type: str = "soothe.file_processor.processed"
    file_path: str
    lines_processed: int
    status: str

register_event(
    FileProcessedEvent,
    summary_template="Processed {file_path}: {lines_processed} lines ({status})",
)
```

---

## Protocol Interfaces

> **Source**: `packages/soothe-sdk/src/soothe_sdk/protocols/`

Import from `soothe_sdk.protocols` (`AsyncPersistStore`, `VectorStoreProtocol`, `PermissionSet`, `ActionRequest`, `PolicyContext`). Plugin authors can type-check without depending on the daemon package.

---

## Utility Functions

```python
from soothe_sdk.plugin import emit_progress
from soothe_sdk.utils.formatting import format_cli_error

await emit_progress("Processing batch 3/10", percentage=30.0, data={"batch_id": 3})
```

---

## Breaking changes in 1.0.0

| Removed | Use instead |
|---------|-------------|
| `soothe_sdk.client.*` | `soothe_sdk.wire` / `soothe_sdk.paths`; transport → `soothe_client` |
| `soothe_sdk.langchain_wire` | `soothe_sdk.wire.codec` |
| `from soothe_sdk import plugin, …` | `from soothe_sdk.plugin import …` |
| `Manifest` / `Context` / `Health` / `Depends` | `PluginManifest` / `PluginContext` / `PluginHealth` / `library` |
