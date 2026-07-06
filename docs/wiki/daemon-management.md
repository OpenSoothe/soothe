---
title: "Daemon Management"
parent: Wiki
nav_order: 4.2
description: >-
  Manage the Soothe daemon process for background execution — start, stop, attach, and lifecycle control.
---

# Daemon Management

Manage the Soothe daemon process for background execution.

## What is the Daemon?

The Soothe daemon is a background process that:
- Runs Soothe continuously without a TUI
- Enables detached execution
- Supports WebSocket transport
- Allows multiple clients to connect
- Maintains thread state

## Server Lifecycle

### Start Daemon

Start the daemon in the background:

```bash
# Start daemon in background
soothed start

# Start in foreground (useful for debugging)
soothed start --foreground
```

**Output**:
```
Daemon started successfully
PID: 12345
WebSocket: ws://127.0.0.1:8765
Status: running
```

### Check Status

View daemon status:

```bash
soothed status
```

**Output**:
```
Daemon Status: running
PID: 12345
Uptime: 2 hours
Transports:
  - WebSocket: ✅ Enabled (ws://127.0.0.1:8765)
Active Threads: 3
Memory Usage: 256 MB
```

### Stop Daemon

Gracefully stop the daemon:

```bash
soothed stop
```

**Output**:
```
Stopping daemon (PID: 12345)...
Saving thread state...
Daemon stopped successfully
```

### Restart Daemon

Restart the daemon:

```bash
soothed restart
```

### Attach to Daemon

**Note**: To reconnect to a running daemon, use:

```bash
# Continue last active loop via daemon
soothe loop continue  # CLI auto-connects to running daemon

# Continue specific loop via daemon
soothe loop continue <loop-id>  # CLI auto-connects to running daemon
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
# Continue via running daemon
soothe loop continue  # CLI auto-connects to running daemon
```

## When to Use Daemon Mode

### Background Processing

Run long tasks without keeping the TUI open:

```bash
# Start daemon
soothed start

# Run task in background
soothe -p "Analyze the entire codebase" &

# Detach and close terminal
# Task continues running
```

### Multiple Clients

Connect multiple clients to the same daemon:
- CLI client
- TUI client
- Web UI (via WebSocket)

### 24/7 Availability

Keep Soothe running continuously:
- Always ready for queries
- No startup latency
- Maintains context and memory

## Logs

Daemon logs are stored in:

```bash
~/.soothe/logs/
├── soothed.log          # Daemon transport, sessions, routing (soothe_daemon.*)
├── soothe.log          # In-process agent core (soothe.*, soothe_plugins.*)
└── soothe-cli.log      # CLI client (when using soothe TUI/CLI)
```

### View Logs

```bash
# Daemon server (WebSocket, session lifecycle)
tail -f ~/.soothe/logs/soothed.log

# Agent execution inside the daemon process
tail -f ~/.soothe/logs/soothe.log

# View specific thread log
tail -f ~/.soothe/logs/threads/abc123.log
```

### Debug Mode

Enable verbose logging:

```bash
export SOOTHE_DEBUG=true
soothed start
```

## Configuration

Configure daemon behavior in `~/.soothe/config/daemon.yml`:

```yaml
# Transport configuration
transports:
  websocket:
    enabled: true
    host: "127.0.0.1"
    port: 8765

# Concurrency
max_concurrent_threads: 100
thread_max_age_hours: 24

# Logging (agent config in config.yml → observability)
# log_file_level: INFO  # DEBUG, INFO, WARNING, ERROR
```

## Monitoring

### Resource Usage

Monitor daemon resource usage:

```bash
# Check memory and CPU
ps aux | grep soothe

# Use system monitor
htop -p $(pgrep -f "soothed")
```

### Health Checks

Use the daemon doctor command:

```bash
soothed doctor
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

**Solution**: Port 8765 is already in use by a previous instance
```bash
soothed stop
soothed start
```

### Daemon Not Responding

**Solution**: Restart the daemon
```bash
soothed stop
soothed start
```

### Can't Connect to Daemon

**Error**: `No daemon running`

**Solution**: Start daemon first, then use loop continue
```bash
soothed start
soothe loop continue  # CLI auto-connects to running daemon
```

## Related Guides

- [Transport Setup](multi-transport.md) - Configure WebSocket
- [Thread Management](thread-management.md) - Work with threads
- [Troubleshooting](troubleshooting.md) - Common daemon issues
