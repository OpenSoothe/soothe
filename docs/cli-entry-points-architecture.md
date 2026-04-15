# CLI Entry Points Architecture

## Overview

This document clarifies the entry points architecture following the CLI-daemon split (IG-173).

## Package Structure

### soothe-sdk (Shared SDK)
- **Purpose**: Shared types, protocols, WebSocket client
- **Entry Points**: None (library package)
- **Install**: `pip install soothe-sdk`

### soothe-cli (CLI Client)
- **Purpose**: CLI client (Typer CLI + Textual TUI) - connects to daemon via WebSocket
- **Entry Points**: `soothe`
- **Install**: `pip install soothe-cli`

### soothe (Daemon Server)
- **Purpose**: Daemon server (agent runtime, protocols, backends)
- **Entry Points**: `soothe-daemon`
- **Optional Dependencies**: `[cli]` - includes soothe-cli
- **Install**: `pip install soothe` (daemon only) or `pip install soothe[cli]` (daemon + client)

## Entry Points

| Command | Package | Purpose |
|---------|---------|---------|
| `soothe` | soothe-cli | CLI client (TUI, thread management, config) |
| `soothe-daemon` | soothe | Daemon management (start/stop/status/doctor/restart) |

## Usage Patterns

### Option 1: Separate Installation
```bash
# Install daemon on server
pip install soothe

# Install client on workstation
pip install soothe-cli

# Start daemon (on server)
soothe-daemon start

# Connect from client (on workstation)
soothe --websocket-host server-host --websocket-port 8765
```

### Option 2: Combined Installation
```bash
# Install both daemon and client
pip install soothe[cli]

# Start daemon
soothe-daemon start

# Connect from client (same machine)
soothe
```

### Option 3: All Optional Features
```bash
# Install everything including all optional dependencies
pip install soothe[all]

# This includes:
# - daemon server (soothe)
# - CLI client (soothe-cli via [cli])
# - research tools ([research])
# - websearch ([websearch])
# - tabular processing ([tabular])
# - document handling ([document])
# - media processing ([media])
# - video processing ([video])
# - Claude subagent ([claude])
```

## Migration from Old Architecture

### Before (Monolithic)
```bash
# Single package with conflicting entry points
pip install soothe

# Commands (confusing):
soothe              # Daemon management OR client (conflict!)
soothe daemon start # Nested pattern (not implemented)
```

### After (Split Architecture)
```bash
# Clear separation
pip install soothe        # Daemon server
pip install soothe-cli    # CLI client

# Commands (clear):
soothe-daemon start       # Start daemon
soothe                    # Run client
```

## Command Reference

### Daemon Management (`soothe-daemon`)
```bash
soothe-daemon start      # Start daemon
soothe-daemon stop       # Stop daemon
soothe-daemon status     # Show daemon status
soothe-daemon restart    # Restart daemon
soothe-daemon doctor     # Run health checks
```

### Client Commands (`soothe`)
```bash
soothe                           # Launch TUI (interactive)
soothe -p "your query"           # Single prompt (headless)
soothe thread list               # List threads
soothe thread continue <id>      # Continue thread
soothe thread show <id>          # Show thread details
soothe config show               # Show configuration
soothe config init               # Initialize config
soothe agent list                # List agents
```

## Configuration Files

| File | Package | Purpose |
|------|---------|---------|
| `~/.soothe/config/config.yml` | soothe (daemon) | Agent configuration, providers, persistence |
| `~/.soothe/config/cli_config.yml` | soothe-cli (client) | UI settings, WebSocket connection |

## Architecture Benefits

1. **Clean Separation**: CLI never imports daemon runtime code
2. **Reduced Dependencies**: Client only needs typer, textual, rich, websockets, soothe-sdk
3. **Independent Deployment**: Daemon on server, client on lightweight workstation
4. **No Entry Point Conflicts**: Clear ownership of `soothe` command
5. **Flexible Installation**: Choose daemon-only, client-only, or combined

## See Also

- [IG-173: CLI-Daemon Split Refactoring](docs/impl/IG-173-cli-daemon-split-refactoring.md)
- [RFC-500: CLI TUI Architecture](docs/specs/RFC-500-cli-tui-architecture.md)
- [CLI Reference](docs/wiki/cli-reference.md)
- [Daemon Management](docs/wiki/daemon-management.md)