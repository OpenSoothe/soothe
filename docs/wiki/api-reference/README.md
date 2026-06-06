# API Reference

This directory contains comprehensive API reference documentation for Soothe, organized by module and access method.

## Documentation Structure

### Python API

- **[SDK API](sdk-api.md)** - Client and plugin development API (`soothe_sdk`)
  - WebSocket client for daemon communication
  - Plugin decorators and context
  - Event system and types
  - Protocol interfaces

- **[Core API](core-api.md)** - Core framework API (`soothe`)
  - Configuration system
  - Protocol definitions
  - CoreAgent and AgentBuilder
  - SootheRunner
  - Backend implementations

- **[Daemon API](daemon-api.md)** - Daemon server API (`soothe_daemon`)
  - Server lifecycle management
  - Channel implementations
  - Bootstrap and configuration
  - Health checks

### REST API

- **[REST API Reference](rest-api.md)** - HTTP REST endpoints
  - Health and status endpoints
  - Configuration management
  - Autopilot job management
  - File operations
  - System operations

## Quick Reference

### Import Paths

**SDK (Client Development)**:
```python
from soothe_sdk import WebSocketClient, plugin, tool, subagent
from soothe_sdk.core.events import SootheEvent
from soothe_sdk.core.types import VerbosityLevel
from soothe_sdk.protocols import AsyncPersistStore, VectorStoreProtocol
```

**Core (Framework Development)**:
```python
from soothe.config import SootheConfig
from soothe.core.agent import CoreAgent, create_soothe_agent
from soothe.core.runner import SootheRunner
from soothe.protocols import MemoryProtocol, DurabilityProtocol
```

**Daemon (Server Development)**:
```python
from soothe_daemon import SootheDaemon, WebSocketClient
from soothe_daemon.bootstrap import run_daemon
```

### Version Compatibility

- **soothe-sdk**: `>=0.5.0,<1.0.0` (see `__soothe_required_version__`)
- **Python**: `>=3.11`
- **LangChain**: Compatible with langchain-core, langchain-community

## Related Documentation

- **[Architecture Overview](../architecture/README.md)** - System architecture and design
- **[Protocols Layer](../protocols/README.md)** - Protocol specifications
- **[Capabilities Layer](../capabilities/README.md)** - Subagents, tools, MCP
- **[Configuration Guide](../configuration.md)** - Configuration reference
- **[RFC Specifications](../../specs/)** - Detailed RFCs for each component

## API Stability

APIs are versioned according to the following stability tiers:

| Tier | Package | Stability | Compatibility |
|------|---------|-----------|---------------|
| **Stable** | `soothe.config` | ✅ Stable | Backward compatible |
| **Stable** | `soothe.protocols` | ✅ Stable | Backward compatible |
| **Stable** | `soothe_sdk.client` | ✅ Stable | Backward compatible |
| **Stable** | `soothe_sdk.plugin` | ✅ Stable | Backward compatible |
| **Beta** | `soothe.core.agent` | ⚠️ Beta | Minor breaking changes |
| **Beta** | `soothe.core.runner` | ⚠️ Beta | Minor breaking changes |
| **Alpha** | `soothe_daemon` | ⚠️ Alpha | Breaking changes possible |
| **Alpha** | REST API | ⚠️ Alpha | Breaking changes possible |

## Documentation Conventions

### Function Signatures

All functions are documented with:
- Full type hints using Python type annotations
- Google-style docstrings with Args, Returns, Raises sections
- Example usage where applicable
- Related RFC references for protocol-level APIs

### Code Examples

Code examples follow these conventions:
- All imports shown explicitly
- Type annotations used where helpful
- Async functions marked with `async`/`await`
- Error handling demonstrated where relevant

### Versioning

Each API includes:
- **Since**: Version when the API was introduced
- **Changed**: Notable changes in version history
- **Deprecated**: Deprecation notices with migration paths