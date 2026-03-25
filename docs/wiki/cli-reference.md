# CLI Reference

Complete command-line interface documentation for Soothe.

## Command Structure

All Soothe commands follow a consistent 2-level nested pattern:

```
soothe <subcommand> <action> [options]
```

**Benefits**:
- Explicit actions - no ambiguity about what will happen
- Better discoverability - all actions visible in `--help`
- Consistent pattern across all commands
- Industry standard (matches git, docker, kubectl)

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

## Thread Management

Manage conversation threads with explicit actions.

### soothe thread list

List all conversation threads.

**Usage**: `soothe thread list [options]`

**Options**:
- `--status <status>` - Filter by status (active, archived)
- `--config <file>` - Use custom configuration file

**Examples**:
```bash
# List all threads
soothe thread list

# Filter by status
soothe thread list --status active
soothe thread list --status archived
```

### soothe thread show

Show thread details.

**Usage**: `soothe thread show <thread-id> [options]`

**Options**:
- `--config <file>` - Use custom configuration file

**Examples**:
```bash
soothe thread show abc123
```

### soothe thread continue

Continue a conversation thread in the TUI.

**Usage**: `soothe thread continue [thread-id] [options]`

**Arguments**:
- `thread-id` - Optional. Thread ID to continue. Omit to continue last active thread.

**Options**:
- `--daemon` - Attach to running daemon instead of standalone
- `--new` - Create a new thread instead of continuing
- `--config <file>` - Use custom configuration file

**Examples**:
```bash
# Continue specific thread
soothe thread continue abc123

# Continue via running daemon
soothe thread continue abc123 --daemon

# Start a new thread
soothe thread continue --new

# Continue last active thread
soothe thread continue
```

### soothe thread archive

Archive a thread.

**Usage**: `soothe thread archive <thread-id> [options]`

**Options**:
- `--config <file>` - Use custom configuration file

**Examples**:
```bash
soothe thread archive abc123
```

### soothe thread delete

Permanently delete a thread.

**Usage**: `soothe thread delete <thread-id> [options]`

**Options**:
- `--yes, -y` - Skip confirmation prompt
- `--config <file>` - Use custom configuration file

**Examples**:
```bash
# Delete with confirmation
soothe thread delete abc123

# Delete without confirmation
soothe thread delete abc123 --yes
```

### soothe thread export

Export thread conversation to a file.

**Usage**: `soothe thread export <thread-id> [options]`

**Options**:
- `--output, -o <file>` - Output file path
- `--format, -f <fmt>` - Export format: jsonl or md (default: jsonl)

**Examples**:
```bash
# Export to JSONL (default)
soothe thread export abc123 --output thread.json

# Export to Markdown
soothe thread export abc123 --output thread.md --format md
```

### soothe thread stats

Show thread execution statistics.

**Usage**: `soothe thread stats <thread-id> [options]`

**Options**:
- `--config <file>` - Use custom configuration file

**Examples**:
```bash
soothe thread stats abc123
```

### soothe thread tag

Add or remove tags from a thread.

**Usage**: `soothe thread tag <thread-id> <tags...> [options]`

**Arguments**:
- `thread-id` - Thread ID
- `tags` - One or more tags to add/remove

**Options**:
- `--remove` - Remove tags instead of adding
- `--config <file>` - Use custom configuration file

**Examples**:
```bash
# Add tags
soothe thread tag abc123 research analysis

# Remove tags
soothe thread tag abc123 research --remove
```

## Configuration Management

### soothe config show

Display current configuration.

**Usage**: `soothe config show [options]`

**Options**:
- `--format, -f <fmt>` - Output format: json or summary (default: summary)
- `--show-sensitive` - Show sensitive values like API keys
- `--config <file>` - Use custom configuration file

**Examples**:
```bash
# Summary view (default)
soothe config show

# Detailed JSON view
soothe config show --format json

# Include sensitive values
soothe config show --show-sensitive
```

### soothe config init

Initialize `~/.soothe` with default configuration.

**Usage**: `soothe config init [options]`

**Options**:
- `--force, -f` - Overwrite existing configuration without confirmation

**Examples**:
```bash
# Initialize with confirmation
soothe config init

# Force overwrite
soothe config init --force
```

### soothe config validate

Validate configuration file and show basic info.

**Usage**: `soothe config validate [options]`

**Options**:
- `--config <file>` - Use custom configuration file

**Examples**:
```bash
# Validate default config
soothe config validate

# Validate custom config
soothe config validate --config custom.yml
```

## Agent Management

### soothe agent list

List available agents and their status.

**Usage**: `soothe agent list [options]`

**Options**:
- `--enabled` - Show only enabled agents
- `--disabled` - Show only disabled agents
- `--config <file>` - Use custom configuration file

**Examples**:
```bash
# List all agents
soothe agent list

# Filter by status
soothe agent list --enabled
soothe agent list --disabled
```

### soothe agent status

Show detailed agent status.

**Usage**: `soothe agent status [options]`

**Options**:
- `--config <file>` - Use custom configuration file

**Examples**:
```bash
soothe agent status
```

## Daemon Management

Manage the Soothe daemon process.

### soothe daemon start

Start the Soothe daemon.

**Usage**: `soothe daemon start [options]`

**Options**:
- `--foreground` - Run in foreground (don't daemonize)
- `--config <file>` - Use custom configuration file

**Examples**:
```bash
# Start daemon in background
soothe daemon start

# Start in foreground
soothe daemon start --foreground
```

### soothe daemon stop

Stop the running Soothe daemon.

**Usage**: `soothe daemon stop`

**Examples**:
```bash
soothe daemon stop
```

### soothe daemon status

Show Soothe daemon status.

**Usage**: `soothe daemon status`

**Examples**:
```bash
soothe daemon status
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
```

### soothe daemon restart

Restart the Soothe daemon.

**Usage**: `soothe daemon restart [options]`

**Options**:
- `--config <file>` - Use custom configuration file

**Examples**:
```bash
soothe daemon restart
```

## Autopilot Mode

Run tasks in autonomous mode without user interaction.

### soothe autopilot run

Run autonomous agent loop for complex tasks.

**Usage**: `soothe autopilot run <prompt> [options]`

**Arguments**:
- `prompt` - Task for autonomous execution

**Options**:
- `--max-iterations <n>` - Maximum autonomous iterations (default: 10)
- `--format <fmt>` - Output format: text or jsonl (default: text)
- `--config <file>` - Use custom configuration file

**Examples**:
```bash
# Basic autonomous execution
soothe autopilot run "Research AI safety and summarize findings"

# Limit iterations for complex tasks
soothe autopilot run "Build a web scraper" --max-iterations 10

# Use custom config with JSON output
soothe autopilot run "Analyze codebase" --config custom.yml --format jsonl

# Long-running research task
soothe autopilot run "Investigate performance bottlenecks" --max-iterations 20
```

**Use Cases**:
- Long-running tasks that don't need user input
- Background execution of complex workflows
- Batch processing or research tasks
- Automated testing and validation

## Global Options

These options apply to all commands:

- `--config <file>` - Path to YAML configuration file
- `--help, -h` - Show help message
- `--version` - Show version information

## Common Patterns

### Quick Analysis

```bash
soothe "Analyze the performance bottlenecks in this codebase"
```

### Autonomous Optimization

```bash
soothe autopilot run "Optimize the database queries" --max-iterations 20
```

### Resume Previous Work

```bash
# List threads
soothe thread list

# Continue specific thread
soothe thread continue abc123

# Continue last active thread
soothe thread continue
```

### Background Processing

```bash
# Start daemon
soothe daemon start

# Run in detached mode
soothe "Long running task" &

# Check status later
soothe daemon status
```

### Thread Management

```bash
# List active threads
soothe thread list --status active

# Export thread for backup
soothe thread export abc123 --output backup.json

# Tag thread for organization
soothe thread tag abc123 research important
```

## Migration from Old Syntax

If you were using the old flat command syntax, here's how to migrate:

| Old Command | New Command |
|-------------|-------------|
| `soothe thread` | `soothe thread list` |
| `soothe thread -l` | `soothe thread list` |
| `soothe thread <id>` | `soothe thread show <id>` |
| `soothe thread -c <id>` | `soothe thread continue <id>` |
| `soothe thread -a <id>` | `soothe thread archive <id>` |
| `soothe thread -d <id>` | `soothe thread delete <id>` |
| `soothe thread -e <id>` | `soothe thread export <id>` |
| `soothe config` | `soothe config show` |
| `soothe config -i` | `soothe config init` |
| `soothe config --validate` | `soothe config validate` |
| `soothe agent` | `soothe agent list` |
| `soothe agent --status` | `soothe agent status` |
| `soothe autopilot "task"` | `soothe autopilot run "task"` |

## Related Guides

- [Getting Started](getting-started.md) - Basic installation and usage
- [TUI Guide](tui-guide.md) - Interactive terminal interface
- [Configuration Guide](configuration.md) - Customize Soothe's behavior
- [Thread Management](thread-management.md) - Working with conversation threads