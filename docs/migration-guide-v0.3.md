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

---

## v0.4.0 Breaking Changes: SDK Module Structure Refactoring

**Release date:** 2026-04-17  
**Breaking change:** All SDK import paths changed  
**No backward compatibility:** Direct breaking change, update imports before upgrading

### Overview

SDK refactored to match langchain-core patterns:
- Minimal `__init__.py` (version only, no re-exports)
- Core concepts at root level (events, exceptions, verbosity)
- Purpose packages for subsystems (plugin/, client/, ux/, utils/, protocols/)
- 15 root files → 3 core files + organized packages

### Quick Migration

**Update all `from soothe_sdk import` statements to package-level imports:**

```python
# Before (v0.3.x)
from soothe_sdk import plugin, tool, WebSocketClient, setup_logging

# After (v0.4.0)
from soothe_sdk.plugin import plugin, tool
from soothe_sdk.client import WebSocketClient
from soothe_sdk.utils import setup_logging
```

**Core imports unchanged (still at root level):**

```python
# These stay at root level - NO CHANGE
from soothe_sdk.events import SootheEvent, LifecycleEvent
from soothe_sdk.exceptions import PluginError, ValidationError
from soothe_sdk.verbosity import VerbosityTier, should_show
```

### Complete Import Mapping Table

| Old Import (v0.3.x) | New Import (v0.4.0) | Package |
|---------------------|---------------------|---------|
| **Plugin API** |
| `from soothe_sdk import plugin` | `from soothe_sdk.plugin import plugin` | plugin |
| `from soothe_sdk import tool` | `from soothe_sdk.plugin import tool` | plugin |
| `from soothe_sdk import tool_group` | `from soothe_sdk.plugin import tool_group` | plugin |
| `from soothe_sdk import subagent` | `from soothe_sdk.plugin import subagent` | plugin |
| `from soothe_sdk import PluginManifest` | `from soothe_sdk.plugin import Manifest` | plugin |
| `from soothe_sdk import PluginContext` | `from soothe_sdk.plugin import Context` | plugin |
| `from soothe_sdk import PluginHealth` | `from soothe_sdk.plugin import Health` | plugin |
| `from soothe_sdk import register_event` | `from soothe_sdk.plugin import register_event` | plugin |
| `from soothe_sdk import emit_progress` | `from soothe_sdk.plugin import emit_progress` | plugin |
| **Client Utilities** |
| `from soothe_sdk import WebSocketClient` | `from soothe_sdk.client import WebSocketClient` | client |
| `from soothe_sdk import VerbosityLevel` | `from soothe_sdk.client import VerbosityLevel` | client |
| `from soothe_sdk import bootstrap_thread_session` | `from soothe_sdk.client import bootstrap_thread_session` | client |
| `from soothe_sdk import connect_websocket_with_retries` | `from soothe_sdk.client import connect_websocket_with_retries` | client |
| `from soothe_sdk import websocket_url_from_config` | `from soothe_sdk.client import websocket_url_from_config` | client |
| `from soothe_sdk import check_daemon_status` | `from soothe_sdk.client import check_daemon_status` | client |
| `from soothe_sdk import is_daemon_live` | `from soothe_sdk.client import is_daemon_live` | client |
| `from soothe_sdk import request_daemon_shutdown` | `from soothe_sdk.client import request_daemon_shutdown` | client |
| `from soothe_sdk import fetch_skills_catalog` | `from soothe_sdk.client import fetch_skills_catalog` | client |
| `from soothe_sdk import fetch_config_section` | `from soothe_sdk.client import fetch_config_section` | client |
| `from soothe_sdk import encode` | `from soothe_sdk.client.protocol import encode` | client |
| `from soothe_sdk import decode` | `from soothe_sdk.client.protocol import decode` | client |
| `from soothe_sdk import Plan` | `from soothe_sdk.client.schemas import Plan` | client |
| `from soothe_sdk import PlanStep` | `from soothe_sdk.client.schemas import PlanStep` | client |
| `from soothe_sdk import ToolOutput` | `from soothe_sdk.client.schemas import ToolOutput` | client |
| `from soothe_sdk import SOOTHE_HOME` | `from soothe_sdk.client.config import SOOTHE_HOME` | client |
| `from soothe_sdk import DEFAULT_EXECUTE_TIMEOUT` | `from soothe_sdk.client.config import DEFAULT_EXECUTE_TIMEOUT` | client |
| **Protocols** |
| `from soothe_sdk import PersistStore` | `from soothe_sdk.protocols import PersistStore` | protocols |
| `from soothe_sdk import VectorRecord` | `from soothe_sdk.protocols import VectorRecord` | protocols |
| `from soothe_sdk import VectorStoreProtocol` | `from soothe_sdk.protocols import VectorStoreProtocol` | protocols |
| `from soothe_sdk import Permission` | `from soothe_sdk.protocols import Permission` | protocols |
| `from soothe_sdk import PermissionSet` | `from soothe_sdk.protocols import PermissionSet` | protocols |
| `from soothe_sdk import ActionRequest` | `from soothe_sdk.protocols import ActionRequest` | protocols |
| `from soothe_sdk import PolicyContext` | `from soothe_sdk.protocols import PolicyContext` | protocols |
| `from soothe_sdk import PolicyDecision` | `from soothe_sdk.protocols import PolicyDecision` | protocols |
| `from soothe_sdk import PolicyProfile` | `from soothe_sdk.protocols import PolicyProfile` | protocols |
| `from soothe_sdk import PolicyProtocol` | `from soothe_sdk.protocols import PolicyProtocol` | protocols |
| **Utilities** |
| `from soothe_sdk import setup_logging` | `from soothe_sdk.utils import setup_logging` | utils |
| `from soothe_sdk import GlobalInputHistory` | `from soothe_sdk.utils import GlobalInputHistory` | utils |
| `from soothe_sdk import VERBOSITY_TO_LOG_LEVEL` | `from soothe_sdk.utils import VERBOSITY_TO_LOG_LEVEL` | utils |
| `from soothe_sdk import format_cli_error` | `from soothe_sdk.utils import format_cli_error` | utils |
| `from soothe_sdk import log_preview` | `from soothe_sdk.utils import log_preview` | utils |
| `from soothe_sdk import convert_and_abbreviate_path` | `from soothe_sdk.utils import convert_and_abbreviate_path` | utils |
| `from soothe_sdk import parse_autopilot_goals` | `from soothe_sdk.utils import parse_autopilot_goals` | utils |
| `from soothe_sdk import get_tool_display_name` | `from soothe_sdk.utils import get_tool_display_name` | utils |
| `from soothe_sdk import _TASK_NAME_RE` | `from soothe_sdk.utils import _TASK_NAME_RE` | utils |
| `from soothe_sdk import resolve_provider_env` | `from soothe_sdk.utils import resolve_provider_env` | utils |
| `from soothe_sdk import INVALID_WORKSPACE_DIRS` | `from soothe_sdk.utils import INVALID_WORKSPACE_DIRS` | utils |
| **UX/Display** |
| `from soothe_sdk import ESSENTIAL_EVENT_TYPES` | `from soothe_sdk.ux import ESSENTIAL_EVENT_TYPES` | ux |
| `from soothe_sdk import strip_internal_tags` | `from soothe_sdk.ux import strip_internal_tags` | ux |
| `from soothe_sdk import INTERNAL_JSON_KEYS` | `from soothe_sdk.ux import INTERNAL_JSON_KEYS` | ux |
| `from soothe_sdk import classify_event_to_tier` | `from soothe_sdk.ux import classify_event_to_tier` | ux |
| **Core (Unchanged)** |
| `from soothe_sdk import SootheEvent` | `from soothe_sdk.events import SootheEvent` | **root** |
| `from soothe_sdk import LifecycleEvent` | `from soothe_sdk.events import LifecycleEvent` | **root** |
| `from soothe_sdk import ProtocolEvent` | `from soothe_sdk.events import ProtocolEvent` | **root** |
| `from soothe_sdk import SubagentEvent` | `from soothe_sdk.events import SubagentEvent` | **root** |
| `from soothe_sdk import OutputEvent` | `from soothe_sdk.events import OutputEvent` | **root** |
| `from soothe_sdk import ErrorEvent` | `from soothe_sdk.events import ErrorEvent` | **root** |
| `from soothe_sdk import PluginError` | `from soothe_sdk.exceptions import PluginError` | **root** |
| `from soothe_sdk import ValidationError` | `from soothe_sdk.exceptions import ValidationError` | **root** |
| `from soothe_sdk import DependencyError` | `from soothe_sdk.exceptions import DependencyError` | **root** |
| `from soothe_sdk import VerbosityTier` | `from soothe_sdk.verbosity import VerbosityTier` | **root** |
| `from soothe_sdk import should_show` | `from soothe_sdk.verbosity import should_show` | **root** |

### Package Structure Reference

```
soothe_sdk/
├── events.py           # Core: Base event classes (SootheEvent, etc.)
├── exceptions.py       # Core: All exception types
├── verbosity.py        # Core: VerbosityTier, should_show()
│
├── plugin/             # Plugin development API
│   ├── decorators.py   # @plugin, @tool, @tool_group, @subagent
│   ├── manifest.py     # PluginManifest (import as Manifest)
│   ├── context.py      # PluginContext (import as Context)
│   ├── health.py       # PluginHealth
│   ├── depends.py      # depends.library() helper
│   ├── registry.py     # register_event()
│   └── emit.py         # emit_progress(), set_stream_writer()
│
├── client/             # WebSocket client utilities
│   ├── websocket.py    # WebSocketClient
│   ├── session.py      # Session bootstrap functions
│   ├── helpers.py      # Daemon communication helpers
│   ├── protocol.py     # Wire protocol encode/decode
│   ├── schemas.py      # Plan, PlanStep, ToolOutput
│   └── config.py       # SOOTHE_HOME, DEFAULT_EXECUTE_TIMEOUT
│
├── protocols/          # Protocol definitions (stable interfaces)
│   ├── persistence.py  # PersistStore
│   ├── policy.py       # PolicyProtocol + permission types
│   └── vector_store.py # VectorStoreProtocol
│
├── ux/                 # Display/UX concerns
│   ├── types.py        # ESSENTIAL_EVENT_TYPES
│   ├── internal.py     # strip_internal_tags, INTERNAL_JSON_KEYS
│   └── classification.py # classify_event_to_tier()
│
├── utils/              # Shared utilities
│   ├── logging.py      # setup_logging, GlobalInputHistory
│   ├── display.py      # Formatting utilities
│   ├── parsing.py      # Parsing utilities
│   └── workspace.py    # Workspace constants
│
└── types/              # DEPRECATED (empty, will be removed)
```

### Migration Steps

**1. Update all import statements**

```bash
# Example migration
# Old code:
from soothe_sdk import plugin, tool, WebSocketClient

# New code:
from soothe_sdk.plugin import plugin, tool
from soothe_sdk.client import WebSocketClient
```

**2. Update type imports**

```python
# Old:
from soothe_sdk import PluginManifest, PluginContext

# New:
from soothe_sdk.plugin import Manifest, Context
```

**3. Update utility imports**

```python
# Old:
from soothe_sdk import setup_logging, format_cli_error

# New:
from soothe_sdk.utils import setup_logging, format_cli_error
```

**4. Update protocol imports**

```python
# Old:
from soothe_sdk import PersistStore, PolicyProtocol

# New:
from soothe_sdk.protocols import PersistStore, PolicyProtocol
```

**5. Test your code**

```bash
# Run tests after updating imports
pytest tests/
```

### Benefits

- **Matches langchain patterns** - Familiar to ecosystem developers
- **Clear purpose boundaries** - plugin/, client/, ux/, utils/, protocols/
- **Better performance** - Minimal __init__.py loads faster
- **Easier navigation** - Organized package structure
- **Future-proof** - Scales well with new features

### Breaking Change Details

**Why no backward compatibility?**

Cleaner architecture without maintenance burden. Faster migration (1-2 weeks vs 7 months).

**Action required:**

Update all imports before upgrading to v0.4.0. Version bump signals breaking change.

**Deprecation timeline:**

- v0.4.0 released: 2026-04-17 (breaking change)
- No compatibility period
- Users must update imports immediately

### See Also

- [RFC-610: SDK Module Structure Refactoring](docs/specs/RFC-610-sdk-module-structure-refactoring.md)
- [IG-185: Implementation Guide](docs/impl/IG-185-sdk-module-structure-refactoring.md)
- [Final Status Report](docs/impl/IG-185-final-status-report.md)

---

## Next Steps

After migration to v0.4.0:

1. Review new SDK package structure
2. Test your code with updated imports
3. Report issues at GitHub Issues

Migration complete! 🎉