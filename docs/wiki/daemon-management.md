# Daemon Management

Manage the Soothe daemon process for background execution.

## What is the Daemon?

The Soothe daemon is a background process that:
- Runs Soothe continuously without a TUI
- Enables detached execution
- Supports multiple transports (Unix Socket, WebSocket, HTTP REST)
- Allows multiple clients to connect
- Maintains thread state

## Server Lifecycle

### Start Daemon

Start the daemon in the background:

```bash
soothe server start
```

**Output**:
```
Daemon started successfully
PID: 12345
Socket: ~/.soothe/soothe.sock
Status: running
```

### Check Status

View daemon status:

```bash
soothe server status
```

**Output**:
```
Daemon Status: running
PID: 12345
Uptime: 2 hours
Transports:
  - Unix Socket: ✅ Enabled (~/.soothe/soothe.sock)
  - WebSocket: ❌ Disabled
  - HTTP REST: ❌ Disabled
Active Threads: 3
Memory Usage: 256 MB
```

### Stop Daemon

Gracefully stop the daemon:

```bash
soothe server stop
```

**Output**:
```
Stopping daemon (PID: 12345)...
Saving thread state...
Daemon stopped successfully
```

### Attach to Daemon

**Note**: The `soothe server attach` command was removed in RFC-0017. To reconnect to a running daemon, use:

```bash
# Resume last active thread via daemon
soothe thread continue --daemon

# Resume specific thread via daemon
soothe thread continue --daemon <thread-id>
```

This opens the TUI and connects to the already-running daemon.

## Detached Execution

### Detach from TUI

Keep daemon running after closing TUI:

```bash
# In TUI
/detach

# Or use keyboard shortcut
Ctrl+D
```

The daemon continues running in the background.

### Reattach Later

Reconnect to the daemon:

```bash
# Resume via running daemon
soothe thread continue --daemon
```

## When to Use Daemon Mode

### Background Processing

Run long tasks without keeping the TUI open:

```bash
# Start daemon
soothe server start

# Run task in background
soothe "Analyze the entire codebase" &

# Detach and close terminal
# Task continues running
```

### Multiple Clients

Connect multiple clients to the same daemon:
- CLI client
- TUI client
- Web UI (via WebSocket)
- REST API client

### 24/7 Availability

Keep Soothe running continuously:
- Always ready for queries
- No startup latency
- Maintains context and memory

## Logs

Daemon logs are stored in:

```bash
~/.soothe/logs/
├── daemon.log          # Main daemon log
├── daemon-2026-03-22.log  # Daily logs
└── threads/
    ├── abc123.log      # Per-thread logs
    └── def456.log
```

### View Logs

```bash
# Tail daemon log
tail -f ~/.soothe/logs/daemon.log

# View specific thread log
tail -f ~/.soothe/logs/threads/abc123.log
```

### Debug Mode

Enable verbose logging:

```bash
export SOOTHE_DEBUG=true
soothe server start
```

## Configuration

Configure daemon behavior in `~/.soothe/config.yml`:

```yaml
daemon:
  # Transport configuration
  transports:
    unix_socket:
      enabled: true
      path: "~/.soothe/soothe.sock"

    websocket:
      enabled: false
      host: "127.0.0.1"
      port: 8765

    http_rest:
      enabled: false
      host: "127.0.0.1"
      port: 8766

  # Logging
  log_level: "INFO"  # DEBUG, INFO, WARNING, ERROR
  log_dir: "~/.soothe/logs"

  # Thread management
  max_threads: 100
  thread_timeout: 3600  # 1 hour
```

## Monitoring

### Resource Usage

Monitor daemon resource usage:

```bash
# Check memory and CPU
ps aux | grep soothe

# Use system monitor
htop -p $(pgrep -f "soothe daemon")
```

### Health Checks

For HTTP REST transport:

```bash
curl http://localhost:8766/api/v1/health
```

**Response**:
```json
{
  "status": "healthy",
  "uptime": 7200,
  "active_threads": 3,
  "memory_mb": 256
}
```

## Troubleshooting

### Daemon Won't Start

**Error**: `Address already in use`

**Solution**: Socket file exists from previous run
```bash
rm ~/.soothe/soothe.sock
soothe server start
```

### Daemon Not Responding

**Solution**: Restart the daemon
```bash
soothe server stop
soothe server start
```

### Can't Connect to Daemon

**Error**: `No daemon running`

**Solution**: Start daemon first, then use thread continue
```bash
soothe server start
soothe thread continue --daemon
```

## Related Guides

- [Multi-Transport Setup](multi-transport.md) - Configure WebSocket and HTTP REST
- [Thread Management](thread-management.md) - Work with threads
- [Troubleshooting](troubleshooting.md) - Common daemon issues