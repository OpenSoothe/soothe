---
title: API Reference
parent: Wiki
has_children: true
nav_order: 12
description: >-
  Core, daemon, and SDK package API knowledge articles.
permalink: /wiki/api-reference/
---

# API Knowledge Articles

These articles explain the *why* and *how* of each Soothe package — architectural decisions, integration points, workflows, and gotchas. For exhaustive field/method references, consult the source files linked in each article.

## Articles

| Article | Package | Role | Stability |
|---------|---------|------|-----------|
| [Core API](core-api.md) | `soothe` | CoreAgent & SootheRunner: configuration, protocols, agent construction, runner | ⚠️ Beta |
| [Daemon API](daemon-api.md) | `soothe_daemon` | SootheDaemon: background server, multi-transport, goal dispatch | ⚠️ Alpha |
| [SDK API](sdk-api.md) | `soothe_sdk` | Plugin & contracts: decorators, events, wire, paths | ✅ Stable |

### Core (`soothe`) — Framework Foundation

The configuration model, protocol abstractions, agent construction pipeline, and execution runner. Defines the three-tier architecture (CoreAgent → SootheRunner → SootheDaemon) and the protocol system that makes every capability pluggable.

### Daemon (`soothe_daemon`) — Server Infrastructure

Long-running background server hosting `SootheRunner` instances. Manages WebSocket IPC, 15 messaging platform channels, client sessions, RPC commands, health checks, and daemon-owned autopilot goal dispatch.

### SDK (`soothe_sdk`) — Client & Plugin API

Public API for plugin authors (decorators for tools, subagents, events) and shared contracts (wire, paths, display). Transport clients live in `soothe-client-python`.

## Architectural Tiers

```
SootheDaemon    — IPC, transports, background scheduling
SootheRunner    — goal orchestration, strange-loop, protocols
CoreAgent       — pure execution: tools, subagents, middleware
```

Each tier has a strict contract: CoreAgent knows nothing about goals; SootheRunner knows nothing about the network; SootheDaemon coordinates everything. This enables embedding `CoreAgent` in any async process, using `SootheRunner` for agentic loops without a daemon, and running the full daemon for multi-client deployments.

## Import Paths

| Package | Primary Imports |
|---------|----------------|
| `soothe` | `from soothe.config import SootheConfig` · `from soothe.foundation.core.agent import CoreAgent, create_soothe_agent` · `from soothe.runner import SootheRunner` · `from soothe.protocols import MemoryProtocol, DurabilityProtocol` |
| `soothe_daemon` | `from soothe_daemon import SootheDaemon, run_daemon` · `from soothe_daemon.bootstrap import pid_path` |
| `soothe_sdk` | `from soothe_sdk.plugin import plugin, tool, subagent` · `from soothe_sdk.core.events import SootheEvent` · `from soothe_sdk.wire import ProtocolError` · `from soothe_sdk.protocols import AsyncPersistStore, VectorStoreProtocol` · transport: `from soothe_client import WebSocketClient` |

## Version Compatibility

- **Python**: `>=3.11`
- **SDK version constraint**: `soothe-sdk>=1.0.0,<2.0.0`
- **LangChain**: Compatible with `langchain-core`, `langchain-community`

## Related Documentation

- [Architecture Overview](../architecture/index.md) — System architecture and design
- [Protocols Layer](../protocols/index.md) — Protocol specifications
- [Capabilities Layer](../capabilities/index.md) — Subagents, tools, MCP
- [Configuration Guide](../configuration-guide/index.md) — Configuration reference
- [RFC Specifications](../../specs/) — Detailed RFCs for each component
