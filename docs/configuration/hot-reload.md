# Configuration Hot-Reload

Soothe daemon supports hot-reloading of configuration files without requiring a full restart. This enables dynamic adjustments to agent and daemon settings during runtime.

## Overview

The hot-reload system provides:
- **File-based watching**: Automatic reload when YAML config files are modified
- **Signal-based triggering**: Manual reload via `SIGHUP` signal
- **Event bus integration**: `ConfigReloadedEvent` for downstream subscriber patterns
- **Debounced reloads**: Prevents rapid-fire reloads from editor saves

## Enabling Hot-Reload

### Programmatic Activation

Enable hot-reload on a running daemon instance:

```python
from soothe_daemon import SootheDaemon

daemon = SootheDaemon()
await daemon.start()

# Enable hot-reload for default config paths
daemon.enable_config_reload()

# Or specify custom paths
daemon.enable_config_reload(
    agent_config_path="/path/to/custom/config.yml",
    daemon_config_path="/path/to/custom/daemon.yml",
)
```

Default paths:
- Agent config: `~/.soothe/config/config.yml`
- Daemon config: `~/.soothe/config/daemon.yml`

### Disabling Hot-Reload

```python
daemon.disable_config_reload()
```

## Triggering Reloads

### File Edit Trigger

When hot-reload is enabled, modifying watched config files triggers automatic reload after a 1-second debounce period.

```bash
# Edit agent config
vim ~/.soothe/config/config.yml

# Edit daemon config
vim ~/.soothe/config/daemon.yml
```

### Signal Trigger (SIGHUP)

Send `SIGHUP` to the daemon process for immediate reload (bypasses debounce):

```bash
# Find daemon PID
cat ~/.soothe/daemon.pid

# Trigger reload
kill -SIGHUP <pid>
```

Or using `pgrep`:

```bash
kill -SIGHUP $(pgrep -f soothed)
```

The daemon logs confirm reload:

```
INFO: Received SIGHUP, triggering config reload
INFO: Agent config reloaded from ~/.soothe/config/config.yml
```

### CLI Trigger

Use the `soothe config reload` CLI command to trigger reload via WebSocket RPC:

```bash
# Trigger config reload
soothe config reload

# JSON output
soothe config reload --json
```

This sends a `config_reload` RPC request to the daemon, which triggers immediate reload of watched config files. The command requires:
- The daemon to be running
- Hot-reload enabled via `daemon.enable_config_reload()`

Output on success:

```
╭─ Config Reload ────────────────────────────╮
│ WebSocket URL: ws://127.0.0.1:8765         │
│ Status: Reload triggered                   │
│ Message: Config reload initiated           │
╰────────────────────────────────────────────╯
```

If hot-reload is not enabled, the command returns an error:

```
╭─ Config Reload ────────────────────────────╮
│ WebSocket URL: ws://127.0.0.1:8765         │
│ Status: Failed                             │
│ Error: Config hot-reload is not enabled    │
╰────────────────────────────────────────────╯
```

## ConfigReloadedEvent

When a configuration is reloaded, the daemon emits a `ConfigReloadedEvent` on the event bus for downstream subscribers.

### Event Structure

```python
from soothe.events import ConfigReloadedEvent, CONFIG_RELOADED

class ConfigReloadedEvent:
    type: str = "soothe.system.config.reloaded"  # CONFIG_RELOADED constant
    config_type: str          # "agent" or "daemon"
    old_config: dict[str, Any]  # Previous config state (serialized)
    new_config: dict[str, Any]  # New config state (serialized)
    timestamp: str            # ISO format timestamp
    error: str | None         # Error message if reload failed
```

### Subscriber Pattern

Subscribe to config reload events for reactive behavior:

```python
from soothe.events import REGISTRY, CONFIG_RELOADED

def on_config_reloaded(event: dict) -> None:
    if event.get("error"):
        print(f"Config reload failed: {event['error']}")
        return
    
    config_type = event.get("config_type")
    print(f"{config_type} config reloaded at {event['timestamp']}")
    
    # Compare old vs new for specific fields
    old_llm = event["old_config"].get("llm", {})
    new_llm = event["new_config"].get("llm", {})
    if old_llm.get("model") != new_llm.get("model"):
        print(f"LLM model changed: {old_llm.get('model')} → {new_llm.get('model')}")

# Register handler
REGISTRY.on(CONFIG_RELOADED, on_config_reloaded)
```

### WebSocket Client Notification

Clients connected via WebSocket receive config reload events:

```json
{
  "type": "event",
  "event_type": "config_reload",
  "config_type": "agent",
  "config_path": "~/.soothe/config/config.yml",
  "success": true,
  "error": null
}
```

## Reload Behavior

### Atomic Swap

Config reload performs an atomic swap of config instances:
- The daemon holds a lock (`_config_lock`) during reload
- Old config is serialized to dict before swap
- New config is loaded fresh from YAML file
- Active queries continue with their original config snapshot

### Supported Changes

Most configuration changes apply immediately:
- LLM model and parameters
- Tool timeouts and rate limits
- Middleware settings
- Verbosity levels
- Policy profiles

### Unsupported Changes

Some changes require daemon restart:
- Transport configuration (WebSocket/HTTP ports)
- Worker pool size
- Persistence backend settings

## Error Handling

### Validation Before Swap

When hot-reload is enabled via the daemon, configs are validated before the swap occurs:

1. YAML is parsed from the modified file
2. Pydantic validation runs against the config schema (`SootheConfig` or `SootheDaemonConfig`)
3. If validation passes, the new config replaces the old one atomically
4. If validation fails, the swap is skipped and an error event is emitted

This ensures invalid configs never corrupt the running daemon state.

### Validation Failure

If reload fails (invalid YAML, schema error, validation failure), the event includes error details:

```python
{
    "type": "soothe.system.config.reloaded",
    "config_type": "agent",
    "error": "Validation error: field 'llm.model' required but missing",
    "timestamp": "2025-07-05T14:00:00Z"
}
```

The daemon continues running with the previous valid config. The error is logged and subscribers receive the error event.

### Custom Validators

The `ConfigWatcher.watch_config()` method accepts an optional `validator` parameter for custom validation logic:

```python
from soothe.config.reload import ConfigWatcher

def my_validator(config: Any) -> bool:
    """Return True if config is valid, False otherwise."""
    if not hasattr(config, 'agent'):
        return False
    if not config.agent.llm.model:
        return False
    return True

watcher.watch_config(
    path="/path/to/config.yml",
    config_type="agent",
    loader=lambda: SootheConfig.from_yaml_file("/path/to/config.yml"),
    validator=my_validator,  # Custom validation before swap
)
```

## Implementation Details

### ConfigWatcher

The `ConfigWatcher` class handles file watching:

```python
from soothe.config.reload import ConfigWatcher, DEFAULT_CONFIG_PATH

watcher = ConfigWatcher(debounce_seconds=1.0)
watcher.watch_config(
    path=DEFAULT_CONFIG_PATH,
    config_type="agent",
    loader=lambda: SootheConfig.from_yaml_file(str(DEFAULT_CONFIG_PATH)),
    callback=on_reload,
)
watcher.start()

# Stop watching
watcher.stop()
```

### Debounce Logic

- File modifications trigger a 1-second debounce timer
- Multiple rapid saves (editor behavior) only trigger one reload
- SIGHUP signal bypasses debounce for immediate reload

### Thread Safety

- File watching runs in a background thread
- Config swap protected by `threading.RLock`
- Event bus dispatch uses `asyncio.call_soon_threadsafe`

## Audit Logging

The `ConfigWatcher` maintains an in-memory audit log of all reload attempts for observability and debugging.

### ReloadAuditEntry

Each reload attempt is recorded as a `ReloadAuditEntry`:

```python
from soothe.config.reload import ReloadAuditEntry

class ReloadAuditEntry:
    timestamp: str           # ISO format when reload occurred
    config_type: str         # "agent" or "daemon"
    config_path: str         # Path to the config file
    old_config_hash: str     # SHA256 hash (first 8 chars) of old config
    new_config_hash: str     # SHA256 hash (first 8 chars) of new config
    success: bool            # True if reload succeeded
    error: str | None        # Error message if failed
```

The truncated hash (8 characters) allows quick visual comparison without exposing full config contents.

### Accessing Audit History

```python
from soothe.config.reload import ConfigWatcher

watcher = ConfigWatcher()
watcher.start()

# Get reload history (most recent first)
history = watcher.get_reload_history(limit=10)

for entry in history:
    if entry.success:
        print(f"[{entry.timestamp}] {entry.config_type} reload: {entry.old_config_hash} → {entry.new_config_hash}")
    else:
        print(f"[{entry.timestamp}] {entry.config_type} reload FAILED: {entry.error}")
```

### Audit Log Configuration

```python
# Default: keeps last 100 entries
watcher = ConfigWatcher()

# Custom max entries
watcher = ConfigWatcher(max_audit_entries=50)

# Disable audit logging
watcher = ConfigWatcher(max_audit_entries=0)
```

### Direct Audit Log Access

```python
# Access the audit log directly
audit_log = watcher.audit_log
if audit_log:
    # Clear history
    audit_log.clear()
    
    # Get total entries
    total = len(audit_log.get_history())
```

### Event Integration

The audit entry is included in `ConfigReloadEvent` for callbacks:

```python
def on_reload(event: ConfigReloadEvent) -> None:
    if event.audit_entry:
        print(f"Reload hash: {event.audit_entry.old_config_hash} → {event.audit_entry.new_config_hash}")
```

And in `ConfigReloadedEvent` for event bus:

```python
{
    "type": "soothe.system.config.reloaded",
    "config_type": "agent",
    "config_path": "~/.soothe/config/config.yml",
    "old_config_hash": "a1b2c3d4",
    "new_config_hash": "e5f6g7h8",
    "timestamp": "2025-07-05T14:00:00Z",
    "success": true,
    "error": null
}
```

## Best Practices

1. **Validate config before edit**: Use `soothe config validate` to check syntax
2. **Monitor reload events**: Subscribe to `ConfigReloadedEvent` for audit logging
3. **Test critical changes**: Some settings may affect active sessions unexpectedly
4. **Use SIGHUP for production**: Signal-triggered reload is safer than file edits in production

## Related

- `soothe.config.reload` module: `ConfigWatcher`, `ConfigReloadEvent`
- `soothe.events`: `ConfigReloadedEvent`, `CONFIG_RELOADED`
- `soothe_daemon.server.core`: `SootheDaemon.enable_config_reload()`