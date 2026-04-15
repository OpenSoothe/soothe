# Soothe: Protocol-Driven Multi-Agent Orchestration Framework

Soothe is a protocol-driven orchestration framework for building 24/7 autonomous agents. It extends deepagents with planning, context engineering, security policy, durability, and remote agent interop.

## Architecture (v0.3.0+)

Soothe has been refactored into four independent packages:

```
packages/
├── soothe-sdk (v0.2.0)        # Shared SDK - WebSocket client, protocol, types
├── soothe-cli (v0.1.0)        # CLI client - WebSocket-only communication
├── soothe (v0.3.0)            # Daemon server - Agent runtime (main package)
└── soothe-community (v0.1.0)  # Community plugins - Optional tools/subagents
```

### Package Overview

**soothe-sdk** - Shared Primitives (~3 deps):
- WebSocket client (`WebSocketClient`)
- Protocol encode/decode
- Base event types
- Verbosity tier system
- Plugin decorators (`@plugin`, `@tool`, `@subagent`)

**soothe-cli** - Client Package (~10 deps):
- CLI commands (thread, config, agent, autopilot)
- TUI application (Textual)
- Event processor and display
- WebSocket-only communication (NO daemon runtime imports)

**soothe** - Server Package (~50 deps):
- WebSocket + HTTP transports
- Agent runner and factory
- Tools and subagents
- Thread persistence
- Protocols (planner, policy, durability)
- Optional: soothe[cli] to install client alongside server

**soothe-community** - Community Plugins Package (~9 deps):
- PaperScout: ArXiv paper discovery and analysis
- Skillify: Skill extraction and management
- Weaver: Context weaving and memory synthesis

## Installation

### Development (from monorepo)

```bash
git clone https://github.com/caesar0301/soothe.git
cd soothe

# Install packages in editable mode
pip install -e packages/soothe-sdk
pip install -e packages/soothe-cli
pip install -e packages/soothe[all]
pip install -e packages/soothe-community  # Optional
```

### From PyPI (when published)

```bash
# Install daemon server (main package)
pip install soothe[all]

# Install CLI client separately
pip install soothe-cli

# Or install daemon with CLI as optional dependency
pip install soothe[all,cli]

# Optional: install community plugins
pip install soothe-community
```

## Quick Start

```bash
# Start daemon server
soothe-daemon start

# Use CLI client
soothe                    # Interactive TUI mode
soothe -p "your query"    # Headless single-prompt mode

# Thread management
soothe thread list
soothe thread continue abc123

# Daemon management
soothe-daemon status
soothe-daemon doctor      # Health checks
```

## Communication Architecture

CLI and daemon communicate via WebSocket only:

```
┌─────────────┐                WebSocket                ┌──────────────┐
│  soothe-cli │ ──────────────────────────────────────▶ │    soothe    │
│  (Client)   │                                              │  (Server)    │
│  ~10 deps   │ ◀────────────────────────────────────── │  ~50 deps    │
└─────────────┘                                              └──────────────┘
```

**Key Principle**: CLI has **ZERO** daemon runtime dependencies - WebSocket-only communication ensures complete independence.

## Configuration

### CLI Config

```yaml
# ~/.soothe/cli_config.yml
websocket:
  host: "localhost"
  port: 8765

ui:
  verbosity: "normal"
```

### Daemon Config

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

## Documentation

- **Architecture**: [docs/cli-daemon-architecture.md](docs/cli-daemon-architecture.md)
- **RFCs**: [docs/specs/](docs/specs/)
- **Implementation Guides**: [docs/impl/](docs/impl/)
- **Daemon RFC**: RFC-400 - Daemon Communication Protocol

## Development

### Monorepo Structure

```
Soothe/
├── packages/
│   ├── soothe-sdk/
│   ├── soothe-cli/
│   ├── soothe/
│   └── soothe-community/
├── tests/
│   ├── integration/
│   └── unit/
├── docs/
└── examples/
```

### Testing

```bash
# Test individual packages
pytest packages/soothe-sdk/tests/
pytest packages/soothe-cli/tests/
pytest packages/soothe/tests/

# Integration tests
pytest tests/integration/
```

### Building

```bash
# Build individual packages
cd packages/soothe-sdk && python -m build
cd packages/soothe-cli && python -m build
cd packages/soothe && python -m build
cd packages/soothe-community && python -m build
```

## Benefits

- **Dependency reduction**: CLI has ~10 deps (vs ~50 for full stack)
- **Flexible deployment**: CLI and daemon on separate machines
- **Clean architecture**: WebSocket-only communication
- **Independent testing**: Packages tested separately

## Support

- **GitHub**: https://github.com/caesar0301/soothe
- **Issues**: https://github.com/caesar0301/soothe/issues
- **Docs**: https://soothe.readthedocs.io

## License

MIT License
