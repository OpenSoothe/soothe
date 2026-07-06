---
title: API Reference
parent: Wiki
has_children: true
nav_order: 9
description: >-
  Core, daemon, and SDK package API knowledge articles.
permalink: /wiki/api-reference/
---

# API Knowledge Articles

These articles explain the *why* and *how* of each Soothe package — architectural decisions, integration points, workflows, and gotchas. For exhaustive field/method references, consult the source files linked in each article.

## Articles

| Article | Package | Role | Stability |
|---------|---------|------|-----------|
| [Core API](core-api.md) | `soothe` | Layer 1–2: configuration, protocols, agent construction, runner | ⚠️ Beta |
| [Daemon API](daemon-api.md) | `soothe_daemon` | Layer 3: background server, multi-transport, goal dispatch | ⚠️ Alpha |
| [SDK API](sdk-api.md) | `soothe_sdk` | Client & plugin development: WebSocket client, decorators, events | ✅ Stable |

### Core (`soothe`) — Framework Foundation

The configuration model, protocol abstractions, agent construction pipeline, and execution runner. Defines the three-layer architecture (CoreAgent → SootheRunner → SootheDaemon) and the protocol system that makes every capability pluggable.

### Daemon (`soothe_daemon`) — Server Infrastructure

Long-running background server hosting `SootheRunner` instances. Manages WebSocket IPC, 16+ messaging platform channels, client sessions, RPC commands, health checks, and daemon-owned autopilot goal dispatch.

### SDK (`soothe_sdk`) — Client & Plugin API

Public API for two audiences: client developers connecting to a daemon (WebSocket client, RPC helpers) and plugin authors extending the agent (decorators for tools, subagents, events). Re-exports core protocols so plugins have zero hard dependency on the daemon package.

## Architectural Layering

```
Layer 3  SootheDaemon    — IPC, transports, background scheduling
Layer 2  SootheRunner    — goal orchestration, strange-loop, protocols
Layer 1  CoreAgent       — pure execution: tools, subagents, middleware
```

Each layer has a strict contract: Layer 1 knows nothing about goals; Layer 2 knows nothing about the network; Layer 3 coordinates everything. This enables embedding `CoreAgent` in any async process, using `SootheRunner` for agentic loops without a daemon, and running the full daemon for multi-client deployments.

## Import Paths

| Package | Primary Imports |
|---------|----------------|
| `soothe` | `from soothe.config import SootheConfig` · `from soothe.foundation.core.agent import CoreAgent, create_soothe_agent` · `from soothe.runner import SootheRunner` · `from soothe.protocols import MemoryProtocol, DurabilityProtocol` |
| `soothe_daemon` | `from soothe_daemon import SootheDaemon, run_daemon` · `from soothe_daemon.bootstrap import pid_path` |
| `soothe_sdk` | `from soothe_sdk.client import WebSocketClient` · `from soothe_sdk import plugin, tool, subagent` · `from soothe_sdk.core.events import SootheEvent` · `from soothe_sdk.protocols import AsyncPersistStore, VectorStoreProtocol` |

## Version Compatibility

- **Python**: `>=3.11`
- **SDK version constraint**: `>=0.5.0,<1.0.0` (see `__soothe_required_version__`)
- **LangChain**: Compatible with `langchain-core`, `langchain-community`

## Related Documentation

- [Architecture Overview](../architecture/index.md) — System architecture and design
- [Protocols Layer](../protocols/index.md) — Protocol specifications
- [Capabilities Layer](../capabilities/index.md) — Subagents, tools, MCP
- [Configuration Guide](../configuration-guide/index.md) — Configuration reference
- [RFC Specifications](../../specs/) — Detailed RFCs for each component
