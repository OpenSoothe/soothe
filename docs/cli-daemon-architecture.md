# CLI-Daemon Split Architecture

## Overview

Soothe has been refactored from a monolithic package into three independent packages in a monorepo structure:

```
packages/
├── soothe-sdk (v0.2.0)     # Shared SDK - WebSocket client, protocol, types
├── soothe-cli (v0.1.0)     # CLI client - WebSocket-only communication
└── soothe-daemon (v0.3.0)  # Daemon server - Agent runtime
```

## Architecture

### Communication Model

The CLI and daemon communicate via WebSocket only:

```
┌─────────────┐                WebSocket                ┌──────────────┐
│  soothe-cli │ ──────────────────────────────────────▶ │ soothe-daemon│
│  (Client)   │                                              │  (Server)    │
│             │ ◀────────────────────────────────────── │              │
│  Lightweight│                Events/Responses          │  Heavy runtime│
└─────────────┘                                              └──────────────┘
       │                                                            │
       │                                                            │
       ▼                                                            ▼
 soothe-sdk                                                   soothe-sdk
  (Shared)                                                      (Shared)
```

**Key Principle**: CLI NEVER imports daemon runtime modules (runner, tools, subagents, protocols).

### Package Responsibilities

**soothe-sdk** (Shared Primitives):
- WebSocket client (`WebSocketClient`)
- Protocol encode/decode
- Base event types (`SootheEvent`, `ErrorEvent`, etc.)
- Verbosity tier system
- Internal tag stripping utilities
- Security constants (`INVALID_WORKSPACE_DIRS`)
- **Dependencies**: pydantic, langchain-core, websockets (minimal)

**soothe-cli** (Client):
- CLI commands (thread, config, agent, autopilot)
- TUI application (Textual)
- Event processor and display policy
- Tool output formatters
- **Entry point**: `soothe` command
- **Dependencies**: soothe-sdk, typer, textual, rich, websockets (~10 deps)
- **NO daemon dependencies**: Zero imports from runtime

**soothe-daemon** (Server):
- Daemon server (WebSocket + HTTP transports)
- Agent runner and factory
- Tools and subagents implementations
- Protocols (planner, policy, durability)
- Thread persistence
- **Entry point**: `soothe-daemon` command
- **Dependencies**: soothe-sdk + langchain + langgraph + all runtime deps (~50 deps)

## Installation

### Install Full System (CLI + Daemon)

```bash
# Install both CLI and daemon
pip install soothe-cli soothe-daemon

# Or with optional extras
pip install soothe-cli soothe-daemon[research,websearch]
```

### Install CLI Only (Lightweight)

```bash
# Install just the client (connects to remote daemon)
pip install soothe-cli

# ~10 dependencies vs ~50 for full installation
```

### Install Daemon Only (Server)

```bash
# Install just the server (for remote deployment)
pip install soothe-daemon[all]

# Includes all optional extras: research, websearch, media, etc.
```

## Usage

### Start Daemon (Server)

```bash
# Start daemon in foreground
soothe-daemon start --foreground

# Start daemon in background (default)
soothe-daemon start

# Check daemon status
soothe-daemon status

# Stop daemon
soothe-daemon stop

# Run health checks
soothe-daemon doctor
```

### Use CLI (Client)

```bash
# Interactive TUI mode (connects to daemon)
soothe

# Headless single-prompt mode
soothe -p "Research AI advances"

# Thread management
soothe thread list
soothe thread continue abc123

# Configuration
soothe config show
```

## Configuration

### Daemon Configuration (config.yml)

Same as original Soothe configuration:

```yaml
# ~/.soothe/config.yml
daemon:
  transports:
    websocket:
      host: "localhost"
      port: 8765
      enabled: true

providers:
  openai:
    api_key: "${OPENAI_API_KEY}"

tools: [...]
subagents: [...]
```

### CLI Configuration (cli_config.yml)

New lightweight config for CLI client:

```yaml
# ~/.soothe/cli_config.yml
websocket:
  host: "localhost"
  port: 8765
  retry_count: 40
  retry_delay_s: 0.25

ui:
  verbosity: "normal"
  format: "text"

tui:
  theme: "default"
  show_token_usage: true
```

**Note**: Users must ensure websocket host/port match between `cli_config.yml` and `config.yml`.

## Benefits

### Dependency Reduction

**Before (Monolithic)**:
- soothe package: ~50 dependencies (langchain, langgraph, tools, etc.)

**After (Split)**:
- soothe-cli: ~10 dependencies (typer, textual, rich, SDK)
- soothe-daemon: ~50 dependencies (full runtime)
- soothe-sdk: ~3 dependencies (pydantic, websockets, langchain-core)

**Result**: CLI users install 80% fewer dependencies.

### Deployment Flexibility

- **CLI on lightweight machine**: Install only `soothe-cli`, connect to remote daemon
- **Daemon on server**: Install `soothe-daemon` on powerful server
- **Full installation**: Both on same machine for local development

### Architecture Cleanliness

- **Clear separation**: Client vs server responsibilities
- **Protocol-based communication**: WebSocket protocol documented in RFC-400
- **Independent testing**: CLI and daemon tested separately
- **Better maintainability**: Changes to CLI don't affect daemon runtime

## Migration from Original Soothe

### Command Changes

**Old Commands** → **New Commands**:

| Old | New | Package |
|-----|-----|---------|
| `soothe daemon start` | `soothe-daemon start` | daemon |
| `soothe daemon stop` | `soothe-daemon stop` | daemon |
| `soothe daemon status` | `soothe-daemon status` | daemon |
| `soothe daemon restart` | `soothe-daemon restart` | daemon |
| `soothe doctor` | `soothe-daemon doctor` | daemon |
| `soothe -p "..."` | `soothe -p "..."` | CLI (unchanged) |
| `soothe thread list` | `soothe thread list` | CLI (unchanged) |

**Summary**: Daemon/doctor commands moved to `soothe-daemon`. Other commands unchanged in CLI.

### Config Changes

**New CLI Config**:
- Create `~/.soothe/cli_config.yml` for CLI-specific settings
- Daemon config (`~/.soothe/config.yml`) unchanged

### Import Changes (For Developers)

**Old**:
```python
from soothe.daemon.websocket_client import WebSocketClient
from soothe.daemon.protocol import encode, decode
from soothe.foundation import SootheEvent, VerbosityTier
```

**New**:
```python
from soothe_sdk.client import WebSocketClient
from soothe_sdk.protocol import encode, decode
from soothe_sdk import SootheEvent, VerbosityTier
```

**Backward Compatibility**: Old imports still work (main package re-exports from SDK).

## Development

### Monorepo Structure

```
Soothe/
├── packages/
│   ├── soothe-sdk/
│   │   ├── src/soothe_sdk/
│   │   └── pyproject.toml
│   ├── soothe-cli/
│   │   ├── src/soothe_cli/
│   │   └── pyproject.toml
│   └── soothe-daemon/
│   │   ├── src/soothe_daemon/
│   │   └── pyproject.toml
├── tests/
│   ├── integration/  # Cross-package tests
│   └── unit/
└── docs/
```

### Testing Individual Packages

```bash
# Test SDK
cd packages/soothe-sdk
pytest tests/

# Test CLI
cd packages/soothe-cli
pytest tests/

# Test daemon
cd packages/soothe-daemon
pytest tests/

# Integration tests (all packages)
pytest tests/integration/
```

### Building Packages

```bash
# Build SDK
cd packages/soothe-sdk
python -m build

# Build CLI
cd packages/soothe-cli
python -m build

# Build daemon
cd packages/soothe-daemon
python -m build
```

## Technical Details

### WebSocket Protocol

See RFC-400 for full protocol specification. Key message types:

**Client → Server**:
- `input`: User query
- `thread_list`: Request thread list
- `resume_thread`: Resume existing thread
- `subscribe_thread`: Subscribe to thread events

**Server → Client**:
- `event`: Stream event from runner
- `status`: Daemon status
- `thread_list_response`: Thread metadata
- `error`: Error message

### Import Constraints

**Enforced Constraints**:
1. CLI MUST NOT import `soothe_daemon.core.*`
2. CLI MUST NOT import `soothe_daemon.tools.*`
3. CLI MUST NOT import `soothe_daemon.subagents.*`
4. CLI MUST NOT import `soothe_daemon.protocols.*`

**Allowed Imports**:
- CLI → `soothe_sdk.*` (WebSocket client, protocol, types)
- CLI → Standard library, typer, textual, rich
- Daemon → `soothe_sdk.*` + daemon runtime modules

## Future Work

### Phase 3 (Complete)
- Integration tests
- WebSocket communication tests
- Package publishing

### Phase 4 (Pending)
- User migration guide
- Updated documentation
- Example scripts

### Phase 5 (Pending)
- Deprecate original `soothe` package
- Remove old source files
- Final release

## References

- **Implementation Guide**: IG-173
- **RFC-400**: Daemon Communication Protocol
- **RFC-0013**: Multi-transport daemon architecture
- **RFC-0022**: Verbosity filtering

## Support

For questions or issues:
- GitHub Issues: https://github.com/caesar0301/soothe/issues
- Documentation: https://soothe.readthedocs.io