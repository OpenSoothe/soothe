# CLI Reference

Complete command-line interface documentation for Soothe.

## Main Entry Points

```bash
# Interactive TUI mode (default)
soothe

# Headless single-prompt mode
soothe "Analyze the data"

# Use custom config
soothe --config custom.yml

# Headless mode with JSONL output
soothe "Analyze data" --format jsonl

# Set progress verbosity
soothe "Complex task" --progress-verbosity detailed
```

## Autopilot Command

Run tasks in autonomous mode:

```bash
# Autonomous execution
soothe autopilot "Research quantum computing advances"

# With iteration limit
soothe autopilot "Build a web scraper" --max-iterations 15

# With custom config
soothe autopilot "Analyze codebase" --config custom.yml

# JSONL output
soothe autopilot "Complex task" --format jsonl
```

**Options**:
- `--max-iterations <n>` - Maximum autonomous iterations (default: 10)
- `--config <file>` - Use custom configuration file
- `--format <format>` - Output format

## Thread Management

Manage conversation threads.

```bash
# List all threads
soothe thread list

# Show thread details
soothe thread show <thread-id>

# Continue a previous thread
soothe thread continue <thread-id>

# Continue via running daemon
soothe thread continue --daemon <thread-id>

# Start a new thread
soothe thread continue --new

# Archive a thread
soothe thread archive <thread-id>

# Delete a thread permanently
soothe thread delete <thread-id>

# Export thread to file
soothe thread export <thread-id> --output thread.json

# Show thread statistics
soothe thread stats <thread-id>

# Add tags to a thread
soothe thread tag <thread-id> research analysis

# Remove tags from a thread
soothe thread tag <thread-id> research --remove
```

## Server Management

Manage the Soothe daemon process.

```bash
# Start daemon in background
soothe server start

# Check daemon status
soothe server status

# Stop daemon gracefully
soothe server stop

# Restart daemon
soothe server restart
```

**Note**: The `server attach` command was removed in RFC-0017. To reconnect to a running daemon, use:
```bash
soothe thread continue --daemon
```

**Server Status Output**:
```
Daemon Status: running
PID: 12345
Uptime: 2 hours
Transports:
  - Unix Socket: ✅ Enabled (~/.soothe/soothe.sock)
  - WebSocket: ❌ Disabled
  - HTTP REST: ❌ Disabled
Active Threads: 3
```

## Authentication Management

**Note**: Soothe does not include built-in authentication commands. Authentication is handled by external services (reverse proxies, API gateways). See [Authentication Guide](authentication.md) for deployment patterns with nginx, Caddy, or Traefik.

## Configuration Management

```bash
# Show current configuration
soothe config show

# Initialize default config
soothe config init

# Validate configuration file
soothe config validate --config custom.yml
```

## Agent Management

```bash
# List available subagents
soothe agent list

# Show subagent status
soothe agent status <agent-name>
```

## Global Options

These options apply to all commands:

- `--config <file>` - Path to YAML configuration file
- `--help` - Show help message
- `--version` - Show version information

## Examples

### Quick Analysis

```bash
soothe "Analyze the performance bottlenecks in this codebase"
```

### Autonomous Optimization

```bash
soothe autopilot "Optimize the database queries for better performance" --max-iterations 20
```

### Resume Previous Work

```bash
# List threads
soothe thread list

# Continue specific thread
soothe thread continue abc123
```

### Background Processing

```bash
# Start daemon
soothe server start

# Run in detached mode
soothe "Long running task" &

# Check status later
soothe server status
```

## Related Guides

- [Getting Started](getting-started.md) - Basic installation and usage
- [TUI Guide](tui-guide.md) - Interactive terminal interface
- [Configuration Guide](configuration.md) - Customize Soothe's behavior
- [Thread Management](thread-management.md) - Working with conversation threads