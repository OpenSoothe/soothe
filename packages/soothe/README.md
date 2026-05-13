# Soothe

Goal-driven multi-agent orchestration framework (in-process agent core).

## Installation

For the full agent runtime with daemon server and CLI:

```bash
pip install soothe soothe-daemon soothe-cli
```

For library use only (no daemon/CLI):

```bash
pip install soothe
```

## Architecture

This package provides the **in-process agent core**:
- `SootheRunner` - Agent orchestration
- `SootheConfig` - Configuration
- Protocols, backends, tools, subagents

## Related Packages

| Package | Purpose |
|---------|---------|
| `soothe-daemon` | Long-running server with WebSocket/HTTP transports |
| `soothe-cli` | CLI client with TUI |
| `soothe-sdk` | Shared types and WebSocket client |

## Testing

```bash
uv run pytest tests/unit/ -v
```