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

# Autopilot job from GOAL.md (greenfield-system rail)
soothe autopilot submit --file GOAL.md --rail greenfield-system -w /path/to/repo
soothe autopilot top

# Loop management
soothe loop list
soothe loop continue loop_abc123
```

## Architecture

This package is the **client** component that communicates with the Soothe daemon via WebSocket.

- **No direct dependencies on daemon runtime** - all communication through WebSocket
- **Lightweight dependencies** - only typer, textual, rich, and SDK
- **WebSocket-only transport** - bidirectional streaming protocol

## Dependencies

- `soothe-sdk>=1.0.0` - events, display, wire contracts
- `typer>=0.9.0` - CLI framework
- `textual>=8.0.0` - TUI framework
- `rich>=13.0.0` - Console output

## Configuration

CLI client settings are passed as global flags on every `soothe` invocation:

```bash
# Connect to a daemon on a non-default host/port
soothe --daemon-host 127.0.0.1 --daemon-port 8765

# Enable debug logging for ~/.soothe/logs/cli.log
soothe --log-level DEBUG

# Disable Markdown rendering in the TUI
soothe --no-render-markdown
```

| Flag | Default | Description |
|------|---------|-------------|
| `--daemon-host` | `127.0.0.1` | Daemon WebSocket host |
| `--daemon-port` | `8765` | Daemon WebSocket port |
| `--log-level` | `INFO` | CLI log level (`SOOTHE_LOG_LEVEL` env overrides) |
| `--render-markdown` / `--no-render-markdown` | enabled | Markdown rendering in TUI |
| `--soothe-home` | `~/.soothe` | Soothe home directory |
| `--streaming` / `--no-streaming` | daemon default | Override output streaming |
| `--streaming-mode` | daemon default | `streaming` or `batch` |

Global flags apply to subcommands too, e.g. `soothe --daemon-port 9000 loop list`.

## Related Packages

- **soothed**: Server package (agent runtime)
- **soothe-sdk**: Shared SDK (WebSocket client, types)
