# Soothe Daemon Server

Agent runtime server with WebSocket/HTTP transport.

## Installation

```bash
pip install soothed
```

## Usage

The `soothed` command manages the server:

```bash
# Start daemon (foreground)
soothed start --foreground

# Start daemon (background)
soothed start

# Check status
soothed status

# Stop daemon
soothed stop

# Health checks
soothed doctor
```

## Architecture

This package is the **server** component that runs the agent runtime:

- **WebSocket transport** - primary bidirectional streaming
- **HTTP REST transport** - optional REST API
- **Full agent runtime** - langchain, langgraph, tools, subagents
- **Thread persistence** - RocksDB, SQLite, PostgreSQL support

## Dependencies

- `soothe-sdk>=0.2.0` - Shared types, protocol
- `deepagents>=0.4.10` - Agent orchestration
- `langchain>=1.2.11` - LLM framework
- `langgraph>=1.1.1` - Graph-based workflows

## Configuration

Daemon uses `config.yml` (same as original Soothe):

```yaml
daemon:
  transports:
    websocket:
      host: "localhost"
      port: 8765

providers:
  openai:
    api_key: "${OPENAI_API_KEY}"
    
tools: [...]
subagents: [...]
```

## Related Packages

- **soothe-cli**: Client package (CLI/TUI)
- **soothe-sdk**: Shared SDK (types, client utilities)

## Testing

Run daemon package unit tests from this package directory:

```bash
uv run pytest tests/unit/ -v
```
