# Soothe CLI Client

WebSocket-based CLI client for Soothe daemon.

## Installation

```bash
pip install soothe-cli
```

## Usage

The `soothe` command provides both CLI and TUI interfaces:

```bash
# Interactive TUI mode
soothe

# Headless single-prompt mode
soothe -p "Research AI advances"

# Thread management
soothe thread list
soothe thread continue abc123

# Configuration
soothe config show
```

## Architecture

This package is the **client** component that communicates with the Soothe daemon via WebSocket.

- **No direct dependencies on daemon runtime** - all communication through WebSocket
- **Lightweight dependencies** - only typer, textual, rich, and SDK
- **WebSocket-only transport** - bidirectional streaming protocol

## Dependencies

- `soothe-sdk>=0.2.0` - WebSocket client, protocol, types
- `typer>=0.9.0` - CLI framework
- `textual>=0.40.0` - TUI framework
- `rich>=13.0.0` - Console output

## Configuration

CLI uses `cli_config.yml`:

```yaml
websocket:
  host: "localhost"
  port: 8765

ui:
  verbosity: "normal"
  format: "text"

tui:
  theme: "default"
```

## Related Packages

- **soothe-daemon**: Server package (agent runtime)
- **soothe-sdk**: Shared SDK (WebSocket client, types)
