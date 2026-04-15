# Soothe: Protocol-Driven Multi-Agent Orchestration Framework

> **⚠️ IMPORTANT**: This monolithic package is **DEPRECATED**. Use the new split packages instead.

## New Architecture (v0.3.0+)

Soothe has been refactored into three independent packages:

```
packages/
├── soothe-sdk (v0.2.0)     # Shared SDK - WebSocket client, protocol, types
├── soothe-cli (v0.1.0)     # CLI client - WebSocket-only communication  
└── soothe-daemon (v0.3.0)  # Daemon server - Agent runtime
```

### Installation

**Recommended: Install both CLI and daemon**

```bash
pip install soothe-cli soothe-daemon[all]
```

**Alternative: Install separately**

```bash
# CLI only (connects to remote daemon)
pip install soothe-cli

# Daemon only (for server deployment)
pip install soothe-daemon[all]

# SDK only (for plugin development)
pip install soothe-sdk
```

### Quick Start

```bash
# Start daemon server
soothe-daemon start

# Use CLI client
soothe                    # Interactive TUI mode
soothe -p "your query"    # Headless single-prompt mode

# Check daemon status
soothe-daemon status

# Health checks
soothe-daemon doctor
```

## Architecture

### Communication Model

CLI and daemon communicate via WebSocket only:

```
┌─────────────┐                WebSocket                ┌──────────────┐
│  soothe-cli │ ──────────────────────────────────────▶ │ soothe-daemon│
│  (Client)   │                                              │  (Server)    │
│  ~10 deps   │ ◀────────────────────────────────────── │  ~50 deps    │
└─────────────┘                                              └──────────────┘
```

**Key Principle**: CLI has **ZERO** daemon runtime dependencies.

### Package Responsibilities

**soothe-sdk**:
- WebSocket client (`WebSocketClient`)
- Protocol encode/decode
- Base event types
- Verbosity tier system
- **Dependencies**: pydantic, websockets (minimal)

**soothe-cli**:
- CLI commands (thread, config, agent, autopilot)
- TUI application (Textual)
- Event processor and display
- **Dependencies**: soothe-sdk, typer, textual, rich (~10 deps)
- **Entry point**: `soothe` command

**soothe-daemon**:
- WebSocket + HTTP transports
- Agent runner and factory
- Tools and subagents
- Thread persistence
- **Dependencies**: soothe-sdk, langchain, langgraph (~50 deps)
- **Entry point**: `soothe-daemon` command

## Configuration

### CLI Config (NEW)

```yaml
# ~/.soothe/cli_config.yml
websocket:
  host: "localhost"
  port: 8765

ui:
  verbosity: "normal"
```

### Daemon Config (UNCHANGED)

```yaml
# ~/.soothe/config.yml
daemon:
  transports:
    websocket:
      host: "localhost"
      port: 8765

providers:
  openai:
    api_key: "${OPENAI_API_KEY}"
```

## Migration from Old Package

**This package (soothe v0.2.x) is deprecated.**

### Quick Migration

```bash
# Uninstall old package
pip uninstall soothe

# Install new packages
pip install soothe-cli soothe-daemon[all]

# Update commands
soothe-daemon start    # (was: soothe daemon start)
soothe-daemon doctor   # (was: soothe doctor)
soothe -p "query"      # (unchanged)
```

### Command Changes

| Old Command | New Command | Package |
|-------------|-------------|---------|
| `soothe daemon start` | `soothe-daemon start` | daemon |
| `soothe daemon stop` | `soothe-daemon stop` | daemon |
| `soothe daemon status` | `soothe-daemon status` | daemon |
| `soothe doctor` | `soothe-daemon doctor` | daemon |
| `soothe -p "..."` | `soothe -p "..."` | CLI (unchanged) |
| `soothe thread list` | `soothe thread list` | CLI (unchanged) |

### Full Migration Guide

See:
- **MIGRATION.md**: Quick reference
- **docs/migration-guide-v0.3.md**: Detailed migration steps
- **docs/cli-daemon-architecture.md**: Architecture overview

## Benefits of Split Architecture

- **Dependency reduction**: CLI has ~10 deps (vs ~50 in old package)
- **Flexible deployment**: CLI and daemon can run on separate machines
- **Clean separation**: WebSocket-only communication
- **Better maintainability**: Independent testing and development

## Documentation

- **Architecture**: [docs/cli-daemon-architecture.md](docs/cli-daemon-architecture.md)
- **Migration**: [docs/migration-guide-v0.3.md](docs/migration-guide-v0.3.md)
- **RFCs**: [docs/specs/](docs/specs/)
- **Implementation**: [docs/impl/](docs/impl/)

## Development

### Monorepo Structure

```
Soothe/
├── packages/
│   ├── soothe-sdk/
│   ├── soothe-cli/
│   └── soothe-daemon/
├── tests/
├── docs/
└── examples/
```

### Testing

```bash
# Test SDK
pytest packages/soothe-sdk/tests/

# Test CLI
pytest packages/soothe-cli/tests/

# Test daemon
pytest packages/soothe-daemon/tests/

# Integration tests
pytest tests/integration/
```

## Support

- **GitHub**: https://github.com/caesar0301/soothe
- **Issues**: https://github.com/caesar0301/soothe/issues
- **Documentation**: https://soothe.readthedocs.io

## License

MIT License

---

**⚠️ WARNING**: This `soothe` package is deprecated. Migrate to `soothe-cli` and `soothe-daemon` immediately.
