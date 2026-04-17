# Migration Guide: CLI-Daemon Split Architecture

This guide helps existing Soothe users migrate to the new split architecture (v0.3.0+).

## Overview of Changes

Soothe has been split into three packages:
- **soothe-sdk**: Shared utilities (WebSocket client, protocol)
- **soothe-cli**: Lightweight client (~10 deps)
- **soothe-daemon**: Server runtime (~50 deps)

## Quick Migration

### 1. Uninstall Old Package

```bash
pip uninstall soothe
```

### 2. Install New Packages

**Option A: Install both (recommended for local development)**

```bash
pip install soothe-cli soothe-daemon[all]
```

**Option B: Install CLI only (connects to remote daemon)**

```bash
pip install soothe-cli
```

**Option C: Install daemon only (for server deployment)**

```bash
pip install soothe-daemon[all]
```

### 3. Update Config Files

**Create CLI config** (new):

```bash
# Create ~/.soothe/config/cli_config.yml
mkdir -p ~/.soothe/config
cat > ~/.soothe/config/cli_config.yml << 'EOF'
verbosity: "normal"  # Client display preference (quiet|normal|detailed|debug)

websocket:
  host: "localhost"
  port: 8765
EOF
```

**Daemon config unchanged**: Your existing `~/.soothe/config/config.yml` works with daemon.

### Verbosity Architecture

**Important**: Verbosity is a **client-side display preference**, not a daemon setting.

- **CLI config** (`cli_config.yml`): `verbosity: detailed` controls what events are **displayed** to you
  - Client sends this to daemon when subscribing
  - Daemon filters events **per-client** before sending
  - Options: `quiet` (minimal), `normal` (default), `detailed` (subagent progress), `debug` (all internals)

- **Daemon config** (`config.yml`): `logging.file.level: DEBUG` controls daemon **log file** verbosity
  - Independent of client display
  - What daemon writes to `~/.soothe/logs/soothe-daemon.log`

**Example**: Multiple clients can connect with different verbosity levels. Each receives filtered events based on their preference, while daemon logs everything at its configured level.

### 4. Update Commands

**Daemon management commands moved to `soothe-daemon`**:

```bash
# Old command               → New command
soothe daemon start         → soothe-daemon start
soothe daemon stop          → soothe-daemon stop
soothe daemon status        → soothe-daemon status
soothe daemon restart       → soothe-daemon restart
soothe doctor               → soothe-daemon doctor

# These commands unchanged (CLI)
soothe -p "query"           → soothe -p "query"  (same)
soothe thread list          → soothe thread list (same)
soothe config show          → soothe config show (same)
```

## Detailed Migration Steps

### Step 1: Backup Configuration

```bash
# Backup existing config
cp ~/.soothe/config.yml ~/.soothe/config.yml.backup
```

### Step 2: Install New Packages

```bash
# Remove old package
pip uninstall -y soothe

# Install new packages
pip install soothe-cli soothe-daemon[all]

# Verify installation
pip list | grep soothe
```

Expected output:
```
soothe-cli      0.1.0
soothe-daemon   0.3.0
soothe-sdk      0.2.0
```

### Step 3: Create CLI Config

```bash
# Create CLI-specific config
mkdir -p ~/.soothe/config
cat > ~/.soothe/config/cli_config.yml << 'EOF'
verbosity: "normal"  # Client display preference (quiet|normal|detailed|debug)

websocket:
  host: "localhost"
  port: 8765
  retry_count: 40
  retry_delay_s: 0.25
  timeout_s: 5.0

ui:
  activity_max_lines: 300
  format: "text"

tui:
  theme: "default"
  show_token_usage: true
EOF
```

**Important**: Ensure websocket host/port match between:
- `cli_config.yml` (websocket.host, websocket.port, verbosity)
- `config.yml` (daemon.transports.websocket.host, daemon.transports.websocket.port)

### Step 4: Test Commands

```bash
# Test daemon commands
soothe-daemon --help
soothe-daemon doctor

# Test CLI commands
soothe --help
soothe thread list

# Test connection (start daemon first)
soothe-daemon start
soothe -p "test query"
```

### Step 5: Update Scripts/Automation

If you have scripts using old commands:

```bash
# Update daemon commands
sed -i 's/soothe daemon start/soothe-daemon start/g' your_script.sh
sed -i 's/soothe daemon stop/soothe-daemon stop/g' your_script.sh
sed -i 's/soothe daemon status/soothe-daemon status/g' your_script.sh
sed -i 's/soothe doctor/soothe-daemon doctor/g' your_script.sh
```

## Code Migration (For Developers)

### Import Updates

**Old imports** (still work via compatibility layer):

```python
from soothe.daemon.websocket_client import WebSocketClient
from soothe.daemon.protocol import encode, decode
from soothe.foundation import SootheEvent, VerbosityTier
```

**New recommended imports**:

```python
from soothe_sdk.client import WebSocketClient
from soothe_sdk.protocol import encode, decode
from soothe_sdk import SootheEvent, VerbosityTier
```

**Backward compatibility**: Old imports work but redirect to SDK. For new code, use SDK imports directly.

### Plugin Development

**No changes needed for existing plugins**. The SDK package maintains backward compatibility:

```python
# Plugin code (unchanged)
from soothe_sdk import plugin, tool, subagent

@plugin(name="my-plugin", version="1.0.0")
class MyPlugin:
    @tool(name="my_tool")
    def my_tool(self, arg: str) -> str:
        return f"Result: {arg}"
```

## Deployment Scenarios

### Scenario 1: Local Development (Both CLI + Daemon)

```bash
# Install both on local machine
pip install soothe-cli soothe-daemon[all]

# Start daemon locally
soothe-daemon start

# Use CLI
soothe
```

### Scenario 2: Remote Daemon (CLI Only Locally)

```bash
# On server: Install daemon
pip install soothe-daemon[all]
soothe-daemon start --foreground

# On local machine: Install CLI only
pip install soothe-cli

# Configure CLI to connect to remote daemon
cat > ~/.soothe/config/cli_config.yml << 'EOF'
websocket:
  host: "remote-server-ip"
  port: 8765
EOF

# Use CLI
soothe -p "query"
```

### Scenario 3: Multiple CLI Clients (One Daemon)

```bash
# On central server: Install daemon
pip install soothe-daemon[all]
soothe-daemon start

# On multiple client machines: Install CLI
pip install soothe-cli

# All clients connect to same daemon
# (Each client has cli_config.yml pointing to server)
```

## Configuration Details

### CLI Config (cli_config.yml)

```yaml
websocket:
  host: "localhost"          # Daemon WebSocket host
  port: 8765                 # Daemon WebSocket port
  retry_count: 40            # Connection retry attempts
  retry_delay_s: 0.25        # Retry delay (seconds)
  timeout_s: 5.0             # Connection timeout

ui:
  verbosity: "normal"        # quiet|minimal|normal|detailed|debug
  activity_max_lines: 300    # Max lines in activity view
  format: "text"             # Output format: text|jsonl

tui:
  theme: "default"           # TUI theme
  show_token_usage: true     # Show token usage in TUI
  show_cost_estimates: false # Show cost estimates

history:
  max_entries: 100           # History file max entries
  save_dir: "~/.soothe/history"
```

### Daemon Config (config.yml)

**Unchanged from original Soothe**. Uses same format:

```yaml
daemon:
  transports:
    websocket:
      host: "localhost"
      port: 8765
      enabled: true
    http:
      host: "localhost"
      port: 8080
      enabled: false

providers:
  openai:
    api_key: "${OPENAI_API_KEY}"

tools: [...]
subagents: [...]
```

## Troubleshooting

### Issue: CLI cannot connect to daemon

**Solution**: Ensure websocket config matches:

```bash
# Check daemon config
grep -A 5 "websocket:" ~/.soothe/config.yml

# Check CLI config
grep -A 5 "websocket:" ~/.soothe/config/cli_config.yml

# Ensure host/port match
```

### Issue: Old commands not found

**Solution**: Update to new commands:

```bash
# Wrong
soothe daemon start

# Correct
soothe-daemon start
```

### Issue: Import errors in custom scripts

**Solution**: Update imports to use SDK:

```python
# Old (deprecated)
from soothe.daemon.websocket_client import WebSocketClient

# New (recommended)
from soothe_sdk.client import WebSocketClient
```

### Issue: Daemon not starting

**Solution**: Check daemon status:

```bash
soothe-daemon status
soothe-daemon doctor
```

## Version Compatibility

| Package | Version | Compatible With |
|---------|---------|----------------|
| soothe-sdk | >=0.2.0 | CLI, Daemon |
| soothe-cli | >=0.1.0 | SDK >=0.2.0 |
| soothe-daemon | >=0.3.0 | SDK >=0.2.0 |
| soothe (old) | <0.3.0 | Deprecated |

**Note**: Old `soothe` package (v0.2.x) is deprecated. Migrate to new packages.

## Support

- **Documentation**: docs/cli-daemon-architecture.md
- **Implementation Guide**: docs/impl/IG-173
- **Issues**: GitHub Issues

## Next Steps

After migration:

1. Read [CLI-Daemon Architecture](cli-daemon-architecture.md)
2. Review [RFC-400](../specs/RFC-400-daemon-communication.md) for protocol details
3. Update any custom scripts or integrations
4. Test your workflows with new commands

Migration complete! 🎉