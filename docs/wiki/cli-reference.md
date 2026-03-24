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

Manage conversation threads with a flat command structure.

```bash
# List all threads
soothe thread
soothe thread -l
soothe thread --list

# Filter by status
soothe thread -l --status active

# Show thread details
soothe thread <thread-id>
soothe thread --show <thread-id>

# Continue a previous thread
soothe thread -c <thread-id>
soothe thread --continue <thread-id>

# Continue via running daemon
soothe thread -c --daemon <thread-id>

# Start a new thread
soothe thread -c --new

# Archive a thread
soothe thread -a <thread-id>
soothe thread --archive <thread-id>

# Delete a thread permanently
soothe thread -d <thread-id>
soothe thread --delete <thread-id>
soothe thread -d <thread-id> --yes  # Skip confirmation

# Export thread to file
soothe thread -e <thread-id> --output thread.json
soothe thread --export <thread-id> -o thread.json
soothe thread -e <thread-id> -o thread.md --format md

# Show thread statistics
soothe thread --stats <thread-id>

# Add tags to a thread
soothe thread --tag <thread-id> research analysis

# Remove tags from a thread
soothe thread --tag <thread-id> research --remove
```

**Thread Options**:
- `-l, --list` - List all threads
- `-s, --show` - Show thread details (default when thread-id provided)
- `-c, --continue` - Continue thread in TUI
- `-a, --archive` - Archive thread
- `-d, --delete` - Delete thread
- `-e, --export` - Export thread
- `--stats` - Show thread statistics
- `--tag` - Add/remove tags
- `--status <status>` - Filter by status (active, archived)
- `--daemon` - Attach to running daemon (with --continue)
- `--new` - Create new thread (with --continue)
- `-y, --yes` - Skip confirmation
- `-o, --output <file>` - Output file path (with --export)
- `-f, --format <fmt>` - Export format: jsonl or md (default: jsonl)
- `--remove` - Remove tags instead of adding

## Daemon Management

Manage the Soothe daemon process.

```bash
# Start daemon in background
soothe daemon start

# Start in foreground
soothe daemon start --foreground

# Stop daemon gracefully
soothe daemon stop

# Show daemon status
soothe daemon status

# Restart daemon
soothe daemon restart
```

**Daemon Commands**:
- `start` - Start daemon in background
- `stop` - Stop daemon gracefully
- `status` - Show daemon status
- `restart` - Restart daemon

**Daemon Status Output**:
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
# Show current configuration (default)
soothe config
soothe config -s
soothe config --show

# Show as JSON
soothe config -s --format json

# Show sensitive values
soothe config -s --show-sensitive

# Initialize default config
soothe config -i
soothe config --init
soothe config -i --force  # Overwrite existing

# Validate configuration file
soothe config --validate
soothe config --validate --config custom.yml
```

**Config Options**:
- `-s, --show` - Show current configuration (default action)
- `-i, --init` - Initialize default configuration
- `--validate` - Validate configuration file
- `--force` - Force overwrite (with --init)
- `-f, --format <fmt>` - Output format: json or summary (default: summary)
- `--show-sensitive` - Show sensitive values like API keys

## Agent Management

```bash
# List available agents (default)
soothe agent
soothe agent -l
soothe agent --list

# Filter by status
soothe agent -l --enabled
soothe agent -l --disabled

# Show agent status
soothe agent --status
```

**Agent Options**:
- `-l, --list` - List available agents (default action)
- `--status` - Show detailed agent status
- `--enabled` - Show only enabled agents
- `--disabled` - Show only disabled agents

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
soothe thread -l

# Continue specific thread
soothe thread -c abc123
```

### Background Processing

```bash
# Start daemon
soothe daemon -s

# Run in detached mode
soothe "Long running task" &

# Check status later
soothe daemon
```

## Related Guides

- [Getting Started](getting-started.md) - Basic installation and usage
- [TUI Guide](tui-guide.md) - Interactive terminal interface
- [Configuration Guide](configuration.md) - Customize Soothe's behavior
- [Thread Management](thread-management.md) - Working with conversation threads
