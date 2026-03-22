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

## Run Command

The main command for interacting with Soothe.

```bash
# Interactive TUI mode
soothe run

# Headless mode with prompt
soothe run "Your prompt here"

# Resume a thread
soothe run --thread <thread-id>

# Autonomous mode
soothe run --autonomous "Optimize the simulation parameters"

# With custom config
soothe run --config custom.yml "Your prompt"
```

**Options**:
- `--thread <id>` - Resume a specific thread
- `--autonomous` - Enable autonomous iteration mode
- `--max-iterations <n>` - Set iteration limit for autonomous mode
- `--config <file>` - Use custom configuration file
- `--format <format>` - Output format (text, jsonl)
- `--progress-verbosity <level>` - Verbosity level (minimal, normal, detailed, debug)

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

# Archive a thread
soothe thread archive <thread-id>

# Delete a thread permanently
soothe thread delete <thread-id>

# Export thread to file
soothe thread export <thread-id> --output thread.json
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

# Attach to running daemon
soothe server attach
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

Manage API keys for WebSocket and HTTP REST.

```bash
# Create API key
soothe auth create-key --description "Web UI" --permissions read,write

# List all API keys
soothe auth list-keys

# Revoke an API key
soothe auth revoke-key <key-id>
```

**API Key Format**: `sk_live_<random-string>`

**Permissions**:
- `read` - Read threads, messages, configuration
- `write` - Create threads, send input, modify configuration

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
soothe run "Analyze the performance bottlenecks in this codebase"
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
soothe run --thread abc123 "Continue with the analysis"
```

### Background Processing

```bash
# Start daemon
soothe server start

# Run in detached mode
soothe run "Long running task" &

# Check status later
soothe server status
```

## Related Guides

- [Getting Started](getting-started.md) - Basic installation and usage
- [TUI Guide](tui-guide.md) - Interactive terminal interface
- [Configuration Guide](configuration.md) - Customize Soothe's behavior
- [Thread Management](thread-management.md) - Working with conversation threads