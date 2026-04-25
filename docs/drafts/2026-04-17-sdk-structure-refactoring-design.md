# soothe-sdk Module Structure Refactoring Design

**Date:** 2026-04-17  
**Status:** Draft - Pending User Review  
**Approach:** Hybrid (Core at Root + Purpose Packages) with Minimal Exports  
**Compatibility:** Direct breaking change (no backward compatibility layer)

---

## Executive Summary

Refactor soothe-sdk module structure to match langchain-core patterns and improve organization. Current structure has 15 flat root-level files with unclear boundaries. New structure groups functionality by purpose (plugin/, client/, ux/, utils/) while keeping core concepts (events, exceptions, verbosity) at root level.

**Key decisions:**
- Keep protocols/ subpackage (organized by protocol type)
- Move plugin types to plugin/ package (deprecate types/)
- Minimal __init__.py (version only, no re-exports)
- Merge client config files into single client/config.py
- Keep all exceptions in root exceptions.py

**Breaking change:** All imports change (no compatibility layer). Timeline: 1-2 weeks.

---

## Problem Statement

### Current Structure Issues

1. **Flat root with 15 files** - Hard to navigate, no semantic grouping
2. **Mixed purposes** - utils.py, logging_utils.py misplaced at root
3. **Ambiguous naming** - protocols/ vs potential protocol/, utils.py too generic
4. **Unclear boundaries** - Plugin API scattered across decorators/, types/, depends.py, exceptions.py
5. **Doesn't match langchain/deepagents patterns** - Unfamiliar to ecosystem developers

### Current File Count

- **Total:** 32 files
- **Root level:** 15 files (events.py, exceptions.py, verbosity.py, utils.py, logging_utils.py, protocol.py, protocol_schemas.py, config_constants.py, config_types.py, internal.py, ux_types.py, workspace_types.py, depends.py, progress.py, events_registry.py)
- **Subpackages:** 17 files (decorators/ 3, client/ 3, protocols/ 3, types/ 3)

### Circular Import Analysis

**Result:** No circular imports detected. Clean dependency graph.

**Import pattern:**
- Subpackages import from root (decorators → types, client → protocol)
- Root doesn't import back from subpackages
- Only 2 root-to-root imports (events_registry → events + verbosity)

---

## Design Goals

1. **Match langchain/deepagents patterns** - Familiar to ecosystem developers
2. **Clear purpose boundaries** - plugin/, client/, ux/, protocols/, utils/
3. **Scalable structure** - Add core concepts as root files, subsystems as packages
4. **Better organization** - Reduce root clutter, group related functionality
5. **Clear ownership** - Plugin owns its types, client owns its config
6. **No circular imports** - Maintain clean dependency graph

---

## Proposed Module Structure

```
soothe_sdk/
├── __init__.py                     # __version__ = "0.3.0" (minimal, no re-exports)
│
├── events.py                       # Base event classes (SootheEvent, LifecycleEvent, ProtocolEvent, SubagentEvent, OutputEvent, ErrorEvent)
├── exceptions.py                   # All exception types (PluginError, DiscoveryError, ValidationError, DependencyError, InitializationError, ToolCreationError, SubagentCreationError)
├── verbosity.py                    # VerbosityTier enum, VerbosityLevel literal, should_show()
│
├── protocols/                      # Protocol definitions (stable interfaces for plugin authors)
│   ├── __init__.py                 # Export: PersistStore, PolicyProtocol, VectorStoreProtocol, Permission, PermissionSet, ActionRequest, PolicyContext, PolicyDecision, PolicyProfile, VectorRecord
│   ├── persistence.py              # PersistStore protocol (key-value persistence interface)
│   ├── policy.py                   # PolicyProtocol + permission types (access control)
│   └── vector_store.py             # VectorStoreProtocol + VectorRecord (vector database abstraction)
│
├── client/                         # WebSocket client utilities
│   ├── __init__.py                 # Export: WebSocketClient, VerbosityLevel, bootstrap_thread_session, connect_websocket_with_retries, websocket_url_from_config, check_daemon_status, is_daemon_live, request_daemon_shutdown, fetch_skills_catalog, fetch_config_section
│   ├── websocket.py                # WebSocketClient implementation
│   ├── session.py                  # bootstrap_thread_session, connect_websocket_with_retries
│   ├── helpers.py                  # Daemon communication helpers
│   ├── protocol.py                 # Wire protocol encode(), decode()
│   ├── schemas.py                  # Wire-safe schemas: Plan, PlanStep, ToolOutput
│   └── config.py                   # Client config: SOOTHE_HOME, DEFAULT_EXECUTE_TIMEOUT, MinimalConfigProtocol, ClientSettings (merged from config_constants.py + config_types.py)
│
├── plugin/                         # Plugin development API
│   ├── __init__.py                 # Export: @plugin, @tool, @tool_group, @subagent, Manifest, Context, Health, Depends, register_event, emit_progress
│   ├── decorators.py               # @plugin, @tool, @tool_group, @subagent decorators (merged from decorators/plugin.py, decorators/tool.py, decorators/subagent.py)
│   ├── manifest.py                 # PluginManifest type (moved from types/manifest.py)
│   ├── context.py                  # PluginContext, SootheConfigProtocol (moved from types/context.py)
│   ├── health.py                   # PluginHealth (moved from types/health.py)
│   ├── depends.py                  # depends.library() helper (moved from root depends.py)
│   ├── registry.py                 # register_event() function (moved from events_registry.py)
│   └── emit.py                     # emit_progress(), set_stream_writer() (moved from progress.py)
│
├── ux/                             # Display and UX concerns
│   ├── __init__.py                 # Export: ESSENTIAL_EVENT_TYPES, strip_internal_tags, INTERNAL_JSON_KEYS, classify_event_to_tier
│   ├── types.py                    # ESSENTIAL_EVENT_TYPES constant (moved from ux_types.py)
│   ├── internal.py                 # strip_internal_tags(), INTERNAL_JSON_KEYS (moved from internal.py)
│   └── classification.py           # classify_event_to_tier() function (moved from verbosity.py)
│
├── utils/                          # Shared utilities (langchain pattern)
│   ├── __init__.py                 # Export: setup_logging, GlobalInputHistory, format_cli_error, log_preview, convert_and_abbreviate_path, parse_autopilot_goals, get_tool_display_name, _TASK_NAME_RE, resolve_provider_env, is_path_argument, VERBOSITY_TO_LOG_LEVEL, INVALID_WORKSPACE_DIRS
│   ├── logging.py                  # setup_logging(), GlobalInputHistory class, VERBOSITY_TO_LOG_LEVEL dict (moved from logging_utils.py)
│   ├── display.py                  # format_cli_error(), log_preview(), convert_and_abbreviate_path(), get_tool_display_name() (extracted from utils.py)
│   ├── parsing.py                  # parse_autopilot_goals(), _TASK_NAME_RE regex, resolve_provider_env() (extracted from utils.py)
│   └── workspace.py                # INVALID_WORKSPACE_DIRS constant, is_path_argument regex (moved from workspace_types.py)
│
└── types/                          # DEPRECATED - empty package
    └── __init__.py                 # Empty (no exports)
```

### File Count Changes

- **Before:** 32 files (15 root + 17 subpackages)
- **After:** 27 files (3 root + 24 subpackages)
- **Reduction:** 5 files eliminated via merging and consolidation

---

## Key Structural Decisions

### Decision 1: Protocols Handling

**Option chosen:** Keep `protocols/` subpackage (3 files)

**Reasons:**
- Organized by protocol type (persistence/policy/vector)
- Matches daemon backend structure
- Easier to add new protocols without bloating single file
- Policy protocol is largest (183 lines), deserves separate file

**Alternative considered:** Merge into single protocols.py (langchain pattern) - rejected because policy.py is substantial and protocols are likely to grow.

---

### Decision 2: Types Package Handling

**Option chosen:** Move plugin types to `plugin/` package, deprecate `types/`

**Reasons:**
- PluginManifest, PluginContext, PluginHealth are all plugin-related
- Clear ownership - plugin owns its own types
- Eliminates vague "types" catch-all category
- Aligns with purpose packages philosophy

**Migration:**
- types/manifest.py → plugin/manifest.py
- types/context.py → plugin/context.py
- types/health.py → plugin/health.py

---

### Decision 3: __init__.py Export Strategy

**Option chosen:** Minimal __init__.py (version only, no re-exports)

**Reasons:**
- Matches langchain-core pattern exactly
- Faster import (no loading of 50+ modules at package init)
- Clear separation: core concepts at root, packages for subsystems
- Forces users to use explicit imports (more discoverable structure)

**Alternative considered:** Re-export all public API - rejected because:
- Large __init__.py (197 lines) is slow and maintenance burden
- Doesn't match langchain minimal pattern
- Re-exporting from 15+ files creates tight coupling

---

### Decision 4: Client Config Organization

**Option chosen:** Merge into single `client/config.py`

**Reasons:**
- Both files are tiny (~75 lines total)
- Single file is simpler (langchain pattern)
- Clear ownership - client package owns its config
- Both serve same purpose - client configuration

**Files merged:**
- config_constants.py (25 lines) - SOOTHE_HOME, DEFAULT_EXECUTE_TIMEOUT
- config_types.py (50 lines) - MinimalConfigProtocol, ClientSettings

---

### Decision 5: Exceptions Organization

**Option chosen:** Keep all exceptions in root `exceptions.py`

**Reasons:**
- Langchain-core pattern (single exceptions.py file)
- Simpler for users (single import location)
- Exceptions are core concept (belong at root level)
- Small file (~50 lines, 7 exception types)
- No package needed for simple type definitions

---

## File Migration Mapping

### Root Files → New Locations

| Old Location | New Location | Action |
|-------------|-------------|--------|
| config_constants.py | client/config.py | Merge with config_types.py |
| config_types.py | client/config.py | Merge with config_constants.py |
| protocol.py | client/protocol.py | Move |
| protocol_schemas.py | client/schemas.py | Move + rename |
| depends.py | plugin/depends.py | Move |
| events_registry.py | plugin/registry.py | Move + rename |
| progress.py | plugin/emit.py | Move + rename |
| internal.py | ux/internal.py | Move |
| ux_types.py | ux/types.py | Move + rename |
| logging_utils.py | utils/logging.py | Move + rename |
| workspace_types.py | utils/workspace.py | Move + rename |
| utils.py | utils/display.py, utils/parsing.py | Split |

### Subpackage Files → New Locations

| Old Location | New Location | Action |
|-------------|-------------|--------|
| decorators/plugin.py | plugin/decorators.py | Merge with decorators/tool.py + decorators/subagent.py |
| decorators/tool.py | plugin/decorators.py | Merge |
| decorators/subagent.py | plugin/decorators.py | Merge |
| types/manifest.py | plugin/manifest.py | Move |
| types/context.py | plugin/context.py | Move |
| types/health.py | plugin/health.py | Move |

### Files Staying at Root

| File | Action |
|-----|--------|
| events.py | Keep at root (core concept) |
| exceptions.py | Keep at root (core concept) |
| verbosity.py | Keep at root (core concept), move classify_event_to_tier() to ux/classification.py |

### Files in Existing Packages

| Package | Files | Action |
|---------|-------|--------|
| protocols/ | persistence.py, policy.py, vector_store.py | Keep unchanged |
| client/ | websocket.py, session.py, helpers.py | Keep unchanged |
| types/ | __init__.py | Deprecate (empty) |

---

## Import Migration Guide

### Core Imports (Unchanged Paths)

```python
# Still at root level (no change)
from soothe_sdk.events import SootheEvent, LifecycleEvent, ProtocolEvent, SubagentEvent, OutputEvent, ErrorEvent
from soothe_sdk.exceptions import PluginError, ValidationError, DependencyError, InitializationError, ToolCreationError, SubagentCreationError
from soothe_sdk.verbosity import VerbosityTier, VerbosityLevel, should_show
```

### Plugin API Imports

```python
# Before:
from soothe_sdk import plugin, tool, subagent, tool_group
from soothe_sdk import PluginManifest, PluginContext, PluginHealth
from soothe_sdk import register_event, emit_progress
from soothe_sdk import Depends

# After:
from soothe_sdk.plugin import plugin, tool, subagent, tool_group
from soothe_sdk.plugin import Manifest, Context, Health
from soothe_sdk.plugin import register_event, emit_progress
from soothe_sdk.plugin import Depends
```

### Client Utilities Imports

```python
# Before:
from soothe_sdk import WebSocketClient, VerbosityLevel
from soothe_sdk import bootstrap_thread_session, connect_websocket_with_retries
from soothe_sdk import websocket_url_from_config, check_daemon_status, is_daemon_live
from soothe_sdk import request_daemon_shutdown, fetch_skills_catalog, fetch_config_section
from soothe_sdk import encode, decode
from soothe_sdk import Plan, PlanStep, ToolOutput
from soothe_sdk import SOOTHE_HOME, DEFAULT_EXECUTE_TIMEOUT

# After:
from soothe_sdk.client import WebSocketClient, VerbosityLevel
from soothe_sdk.client import bootstrap_thread_session, connect_websocket_with_retries
from soothe_sdk.client import websocket_url_from_config, check_daemon_status, is_daemon_live
from soothe_sdk.client import request_daemon_shutdown, fetch_skills_catalog, fetch_config_section
from soothe_sdk.client.protocol import encode, decode
from soothe_sdk.client.schemas import Plan, PlanStep, ToolOutput
from soothe_sdk.client.config import SOOTHE_HOME, DEFAULT_EXECUTE_TIMEOUT
```

### Protocols Imports

```python
# Before:
from soothe_sdk import PersistStore, VectorRecord, VectorStoreProtocol
from soothe_sdk import Permission, PermissionSet, ActionRequest, PolicyContext, PolicyDecision, PolicyProfile, PolicyProtocol

# After:
from soothe_sdk.protocols import PersistStore, VectorRecord, VectorStoreProtocol
from soothe_sdk.protocols import Permission, PermissionSet, ActionRequest, PolicyContext, PolicyDecision, PolicyProfile, PolicyProtocol
```

### Utilities Imports

```python
# Before:
from soothe_sdk import setup_logging, GlobalInputHistory, VERBOSITY_TO_LOG_LEVEL
from soothe_sdk import format_cli_error, log_preview, convert_and_abbreviate_path
from soothe_sdk import parse_autopilot_goals, get_tool_display_name, _TASK_NAME_RE
from soothe_sdk import resolve_provider_env, is_path_argument
from soothe_sdk import INVALID_WORKSPACE_DIRS

# After:
from soothe_sdk.utils import setup_logging, GlobalInputHistory, VERBOSITY_TO_LOG_LEVEL
from soothe_sdk.utils import format_cli_error, log_preview, convert_and_abbreviate_path
from soothe_sdk.utils import parse_autopilot_goals, get_tool_display_name, _TASK_NAME_RE
from soothe_sdk.utils import resolve_provider_env, is_path_argument
from soothe_sdk.utils import INVALID_WORKSPACE_DIRS
```

### UX Imports

```python
# Before:
from soothe_sdk import ESSENTIAL_EVENT_TYPES
from soothe_sdk import strip_internal_tags, INTERNAL_JSON_KEYS

# After:
from soothe_sdk.ux import ESSENTIAL_EVENT_TYPES
from soothe_sdk.ux import strip_internal_tags, INTERNAL_JSON_KEYS
```

**Note:** `classify_event_to_tier()` moved to ux/classification.py, but also kept in verbosity.py for backward compatibility during transition.

---

## Complete Import Mapping Table

| Old Import (v0.3.x) | New Import (v0.4.0) | Package |
|---------------------|---------------------|---------|
| `from soothe_sdk import plugin` | `from soothe_sdk.plugin import plugin` | plugin |
| `from soothe_sdk import tool` | `from soothe_sdk.plugin import tool` | plugin |
| `from soothe_sdk import tool_group` | `from soothe_sdk.plugin import tool_group` | plugin |
| `from soothe_sdk import subagent` | `from soothe_sdk.plugin import subagent` | plugin |
| `from soothe_sdk import PluginManifest` | `from soothe_sdk.plugin import Manifest` | plugin |
| `from soothe_sdk import PluginContext` | `from soothe_sdk.plugin import Context` | plugin |
| `from soothe_sdk import PluginHealth` | `from soothe_sdk.plugin import Health` | plugin |
| `from soothe_sdk import register_event` | `from soothe_sdk.plugin import register_event` | plugin |
| `from soothe_sdk import emit_progress` | `from soothe_sdk.plugin import emit_progress` | plugin |
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
| `from soothe_sdk import is_path_argument` | `from soothe_sdk.utils import is_path_argument` | utils |
| `from soothe_sdk import INVALID_WORKSPACE_DIRS` | `from soothe_sdk.utils import INVALID_WORKSPACE_DIRS` | utils |
| `from soothe_sdk import ESSENTIAL_EVENT_TYPES` | `from soothe_sdk.ux import ESSENTIAL_EVENT_TYPES` | ux |
| `from soothe_sdk import strip_internal_tags` | `from soothe_sdk.ux import strip_internal_tags` | ux |
| `from soothe_sdk import INTERNAL_JSON_KEYS` | `from soothe_sdk.ux import INTERNAL_JSON_KEYS` | ux |
| `from soothe_sdk.events import SootheEvent` | `from soothe_sdk.events import SootheEvent` | **NO CHANGE** |
| `from soothe_sdk.exceptions import PluginError` | `from soothe_sdk.exceptions import PluginError` | **NO CHANGE** |
| `from soothe_sdk.verbosity import VerbosityTier` | `from soothe_sdk.verbosity import VerbosityTier` | **NO CHANGE** |

---

## Migration Strategy

### Phase 1: soothe-sdk Refactor (Week 1, Days 1-3)

**Step 1: Create new directory structure**
- Create directories: plugin/, ux/, utils/
- Ensure protocols/, client/ exist

**Step 2: Move files (batch operations)**
- decorators/* → plugin/decorators.py (merge 3 files)
- types/manifest.py → plugin/manifest.py
- types/context.py → plugin/context.py
- types/health.py → plugin/health.py
- depends.py → plugin/depends.py
- events_registry.py → plugin/registry.py
- progress.py → plugin/emit.py
- protocol.py → client/protocol.py
- protocol_schemas.py → client/schemas.py
- config_constants.py + config_types.py → client/config.py (merge)
- logging_utils.py → utils/logging.py
- utils.py content → utils/display.py + utils/parsing.py (split)
- workspace_types.py → utils/workspace.py
- ux_types.py → ux/types.py
- internal.py → ux/internal.py
- Extract classify_event_to_tier logic from verbosity.py → ux/classification.py

**Step 3: Create package __init__.py files**
- plugin/__init__.py - export decorators, types, registry, emit, depends
- client/__init__.py - export WebSocketClient, helpers, VerbosityLevel, etc.
- ux/__init__.py - export ESSENTIAL_EVENT_TYPES, strip_internal_tags, classification
- utils/__init__.py - export all utility functions
- protocols/__init__.py - unchanged (already exists)
- types/__init__.py - empty (deprecated)

**Step 4: Update SDK internal imports**
- events_registry.py imports from events.py + verbosity.py (update after moving)
- decorators/*.py imports from types/*.py (update after moving)
- client/*.py imports from protocol.py (update after moving)

**Step 5: Run SDK tests**
- Run packages/soothe-sdk/tests/
- Fix any import errors within SDK itself
- Verify no circular imports

---

### Phase 2: soothe-cli Imports Update (Week 1, Day 4)

**Scope:** ~20-25 import statements in 10-15 files

**Affected files:**
- packages/soothe-cli/src/soothe_cli/config/cli_config.py
- packages/soothe-cli/src/soothe_cli/tui/*.py
- packages/soothe-cli/src/soothe_cli/headless/*.py
- packages/soothe-cli/src/soothe_cli/commands/*.py

**Update pattern:**
```python
# Find all imports:
grep -r "from soothe_sdk import" packages/soothe-cli/

# Update imports:
from soothe_sdk import plugin → from soothe_sdk.plugin import plugin
from soothe_sdk import WebSocketClient → from soothe_sdk.client import WebSocketClient
from soothe_sdk import format_cli_error → from soothe_sdk.utils import format_cli_error
```

**Testing:**
- Run packages/soothe-cli/tests/
- Test CLI commands: `soothe --help`, `soothe thread list`
- Test TUI launch: `soothe`
- Test headless mode: `soothe -p "test"`

---

### Phase 3: soothe (daemon) Imports Update (Week 1, Day 5)

**Scope:** ~30-40 import statements in 20-30 files

**Affected directories:**
- packages/soothe/src/soothe/core/
- packages/soothe/src/soothe/protocols/
- packages/soothe/src/soothe/backends/
- packages/soothe/src/soothe/tools/
- packages/soothe/src/soothe/subagents/
- packages/soothe/src/soothe/middleware/
- packages/soothe/src/soothe/daemon/

**Update pattern:**
```python
# Find all imports:
grep -r "from soothe_sdk import" packages/soothe/

# Update imports (automated script possible):
from soothe_sdk import plugin → from soothe_sdk.plugin import plugin
from soothe_sdk import encode, decode → from soothe_sdk.client.protocol import encode, decode
from soothe_sdk import SootheEvent → from soothe_sdk.events import SootheEvent (NO CHANGE)
from soothe_sdk import PolicyProtocol → from soothe_sdk.protocols import PolicyProtocol
```

**Testing:**
- Run packages/soothe/tests/
- Run daemon tests
- Test daemon commands: `soothed start`, `soothed doctor`

---

### Phase 4: Full Test Suite (Week 1, Day 6)

**Verification script:**
```bash
./scripts/verify_finally.sh
```

**What it runs:**
- Code formatting check (make format-check)
- Linting (make lint) - zero errors required
- Unit tests (make test-unit) - 900+ tests must pass

**Manual verification:**
- Import timing test: verify minimal __init__.py is faster
- Circular import detection: run import graph analysis
- Package imports: test each package __init__.py works standalone

**Fix any issues:**
- If tests fail: fix import paths, re-run tests
- If lint fails: fix formatting/linting errors
- If circular imports: adjust import structure

---

### Phase 5: Documentation Update (Week 1, Day 7)

**Files to update:**
- docs/cli-entry-points-architecture.md - update import examples
- docs/migration-guide-v0.3.md - add v0.4 breaking changes section
- CLAUDE.md - update SDK import patterns in "Quick Start" sections
- packages/soothe-sdk/README.md - update examples
- All markdown files with import code examples

**Migration guide content:**
```markdown
## v0.4.0 Breaking Changes

All SDK import paths have changed. No backward compatibility provided.

### Quick Migration Guide

[Complete import mapping table - 50 rows]

### Action Required

Update all `from soothe_sdk import` statements before upgrading to v0.4.0.
```

---

### Phase 6: Version Bump and Release (Week 2)

**Version changes:**
- soothe-sdk: v0.3.0 → v0.4.0 (breaking change)
- soothe-cli: v0.1.0 → v0.2.0 (dependency update)
- soothe (daemon): v0.3.0 → v0.4.0 (dependency update)

**pyproject.toml updates:**
```toml
# packages/soothe-sdk/pyproject.toml
version = "0.4.0"

# packages/soothe-cli/pyproject.toml
version = "0.2.0"
dependencies = ["soothe-sdk>=0.4.0"]

# packages/soothe/pyproject.toml
version = "0.4.0"
dependencies = ["soothe-sdk>=0.4.0"]
```

**Release notes:**
```markdown
# v0.4.0 - Breaking Changes

## SDK Module Structure Refactoring

All import paths have changed. See migration guide for complete mapping table.

### Key Changes:
- Plugin API moved to plugin/ package
- Client utilities moved to client/ package
- Utilities moved to utils/ package
- Core concepts (events, exceptions, verbosity) remain at root

### No Backward Compatibility

This is a direct breaking change. Update imports before upgrading.
```

---

## Package-by-Package Import Count

| Package | Import Statements | Affected Files | Est. Time |
|---------|-------------------|----------------|-----------|
| soothe-sdk (internal) | ~15 | 5 files | 0.5 day |
| soothe-cli | ~20-25 | 10-15 files | 1 day |
| soothe (daemon) | ~30-40 | 20-30 files | 1 day |
| soothe-sdk tests | ~40-50 | 10-15 files | 0.5 day |
| **Total** | **~110-130** | **~45-65 files** | **3 days** |

---

## Testing Strategy

### Pre-Refactor Tests

**Baseline verification:**
- All 900+ tests pass with current structure
- Import analysis: no circular imports
- Current import paths work

### Post-Refactor Tests

**Core tests:**
- All 900+ tests pass with new imports
- `./scripts/verify_finally.sh` passes (format, lint, tests)

**Import-specific tests:**
- Import timing: measure __init__.py load time (should be faster)
- Package isolation: each package __init__.py imports successfully
- Circular import check: re-run dependency graph analysis
- Import completeness: grep verifies all imports updated

**Integration tests:**
- CLI commands work: `soothe --help`, `soothe thread list`, `soothe -p "test"`
- Daemon commands work: `soothed start`, `soothed doctor`
- WebSocket connection: CLI connects to daemon successfully
- Plugin loading: daemon loads plugins with new structure

**Edge case tests:**
- Import from multiple packages in same file
- Nested imports (package.module.submodule)
- Re-imports (import same module multiple times)
- Import aliases work: `from soothe_sdk.plugin import plugin as p`

---

## Risks and Mitigation

### Risk 1: Breaking Third-Party Plugins

**Impact:** High - all community plugins break

**Mitigation:**
- Clear migration guide with complete import mapping table
- Version bump to v0.4.0 signals breaking change
- Release notes highlight required import updates
- Documentation examples show new imports
- GitHub issue template for migration questions

**Action:** Plugin authors must manually update imports

---

### Risk 2: Import Errors During Migration

**Impact:** Medium - tests will catch, but time-consuming to fix

**Mitigation:**
- Batch-by-batch execution (SDK → CLI → Daemon → Tests)
- Run tests after each batch
- Comprehensive grep search before starting: `grep -r "from soothe_sdk import" packages/`
- Use import linting tool if available
- Fix batch before proceeding to next

**Recovery:** If errors found, fix immediately, re-run tests

---

### Risk 3: Missed Imports in Large Codebase

**Impact:** Medium - could cause runtime failures

**Mitigation:**
- Pre-refactor grep: find all affected imports
- Automated search: `find packages/ -name "*.py" -exec grep "from soothe_sdk import" {} \;`
- Import linting: use tools like `pylint`, `import-linter`
- Test suite coverage: 900+ tests catch most missed imports
- Final verification: `./scripts/verify_finally.sh` ensures completeness

**Verification:** Multi-layer checking (grep + linting + tests)

---

### Risk 4: Circular Imports Introduced

**Impact:** High - could break runtime

**Mitigation:**
- Pre-refactor analysis: verify no circular imports currently
- Keep protocols/ separate (no imports from other SDK modules)
- Each package __init__.py only imports from its own files
- Import graph analysis after refactor
- Test each package imports independently

**Verification:** Python import analysis script

---

### Risk 5: Performance Regression

**Impact:** Low - but measurable

**Mitigation:**
- Measure import time before and after
- Minimal __init__.py should improve performance
- Benchmark: `python -c "import soothe_sdk; print('loaded')"`
- If regression detected: investigate specific package imports

**Success criteria:** Import time ≤ current time (or better)

---

## Benefits

### For Plugin Developers

1. **Familiar structure** - Matches langchain/deepagents patterns
2. **Clear purpose packages** - plugin/ contains all plugin API
3. **Discoverable** - Package __init__.py shows available exports
4. **Scalable** - New features added to appropriate packages
5. **Clean imports** - No flat 15-file root to navigate

### For Framework Developers

1. **Better organization** - Related functionality grouped together
2. **Easier maintenance** - Clear module ownership
3. **Reduced clutter** - 15 root files → 3 core files
4. **Clear boundaries** - plugin vs client vs utils separation
5. **Langchain alignment** - Ecosystem patterns followed

### For Users

1. **Easier navigation** - Purpose packages obvious
2. **Better performance** - Minimal __init__.py loads faster
3. **Explicit imports** - Know exactly what's imported
4. **Consistent naming** - utils/ package, not utils.py file
5. **Future-proof** - Structure scales well

---

## Success Criteria

1. ✓ All 900+ tests pass with new structure
2. ✓ No circular imports detected (import graph analysis)
3. ✓ soothe-cli imports updated (20-25 statements)
4. ✓ soothe (daemon) imports updated (30-40 statements)
5. ✓ soothe-sdk tests updated (40-50 statements)
6. ✓ Documentation updated (all markdown files)
7. ✓ Migration guide published (complete mapping table)
8. ✓ `./scripts/verify_finally.sh` passes (format, lint, tests)
9. ✓ Import time improved (benchmark minimal __init__.py)
10. ✓ Version bumped to v0.4.0 (breaking change signaled)

---

## Timeline Summary

**Week 1 (Days 1-7): Complete refactor**
- Day 1-3: SDK structure reorganization (file moves, merges, splits)
- Day 4: CLI imports update (~20-25 statements)
- Day 5: Daemon imports update (~30-40 statements)
- Day 6: Full test suite + verification
- Day 7: Documentation update

**Week 2: Version bump and release**
- Version bump to v0.4.0 (breaking change)
- Update all pyproject.toml files
- Publish migration guide
- Release notes with breaking change warning

**Total: 1-2 weeks** (streamlined, no compatibility layer)

---

## Next Steps

After this design is approved, proceed to:

1. **Platonic Coding Phase 1:** Generate RFC-XXX (SDK Module Structure Refactoring)
2. **Platonic Coding Phase 1:** Run `specs-refine` to validate RFC against existing specs
3. **Platonic Coding Phase 2:** Create implementation guide (IG-184)
4. **Platonic Coding Phase 2:** Execute refactoring following migration plan

---

## Appendix: Package __init__.py Export Lists

### soothe_sdk/__init__.py

```python
"""Soothe SDK - Minimal __init__.py matching langchain-core pattern."""

__version__ = "0.4.0"
__soothe_required_version__ = ">=0.4.0,<1.0.0"

# No re-exports - use package imports:
# from soothe_sdk.events import SootheEvent
# from soothe_sdk.plugin import plugin, tool
# from soothe_sdk.client import WebSocketClient
```

### soothe_sdk/plugin/__init__.py

```python
"""Plugin development API for Soothe."""

from soothe_sdk.plugin.decorators import plugin, tool, tool_group, subagent
from soothe_sdk.plugin.manifest import PluginManifest as Manifest
from soothe_sdk.plugin.context import PluginContext as Context, SootheConfigProtocol
from soothe_sdk.plugin.health import PluginHealth as Health
from soothe_sdk.plugin.depends import library as Depends
from soothe_sdk.plugin.registry import register_event
from soothe_sdk.plugin.emit import emit_progress, set_stream_writer

__all__ = [
    "plugin",
    "tool",
    "tool_group",
    "subagent",
    "Manifest",
    "Context",
    "SootheConfigProtocol",
    "Health",
    "Depends",
    "register_event",
    "emit_progress",
    "set_stream_writer",
]
```

### soothe_sdk/client/__init__.py

```python
"""WebSocket client utilities for connecting to Soothe daemon."""

from soothe_sdk.client.websocket import WebSocketClient, VerbosityLevel
from soothe_sdk.client.session import (
    bootstrap_thread_session,
    connect_websocket_with_retries,
)
from soothe_sdk.client.helpers import (
    websocket_url_from_config,
    check_daemon_status,
    is_daemon_live,
    request_daemon_shutdown,
    fetch_skills_catalog,
    fetch_config_section,
)

__all__ = [
    "WebSocketClient",
    "VerbosityLevel",
    "bootstrap_thread_session",
    "connect_websocket_with_retries",
    "websocket_url_from_config",
    "check_daemon_status",
    "is_daemon_live",
    "request_daemon_shutdown",
    "fetch_skills_catalog",
    "fetch_config_section",
]
```

### soothe_sdk/ux/__init__.py

```python
"""Display and UX concerns for event processing."""

from soothe_sdk.ux.types import ESSENTIAL_EVENT_TYPES
from soothe_sdk.ux.internal import strip_internal_tags, INTERNAL_JSON_KEYS
from soothe_sdk.ux.classification import classify_event_to_tier

__all__ = [
    "ESSENTIAL_EVENT_TYPES",
    "strip_internal_tags",
    "INTERNAL_JSON_KEYS",
    "classify_event_to_tier",
]
```

### soothe_sdk/utils/__init__.py

```python
"""Shared utilities for SDK, CLI, and daemon."""

from soothe_sdk.utils.logging import (
    setup_logging,
    GlobalInputHistory,
    VERBOSITY_TO_LOG_LEVEL,
)
from soothe_sdk.utils.display import (
    format_cli_error,
    log_preview,
    convert_and_abbreviate_path,
    get_tool_display_name,
)
from soothe_sdk.utils.parsing import (
    parse_autopilot_goals,
    _TASK_NAME_RE,
    resolve_provider_env,
)
from soothe_sdk.utils.workspace import INVALID_WORKSPACE_DIRS, is_path_argument

__all__ = [
    "setup_logging",
    "GlobalInputHistory",
    "VERBOSITY_TO_LOG_LEVEL",
    "format_cli_error",
    "log_preview",
    "convert_and_abbreviate_path",
    "get_tool_display_name",
    "parse_autopilot_goals",
    "_TASK_NAME_RE",
    "resolve_provider_env",
    "INVALID_WORKSPACE_DIRS",
    "is_path_argument",
]
```

### soothe_sdk/protocols/__init__.py

```python
"""Protocol definitions for Soothe plugin authors."""

from soothe_sdk.protocols.persistence import PersistStore
from soothe_sdk.protocols.policy import (
    ActionRequest,
    Permission,
    PermissionSet,
    PolicyContext,
    PolicyDecision,
    PolicyProfile,
    PolicyProtocol,
)
from soothe_sdk.protocols.vector_store import VectorRecord, VectorStoreProtocol

__all__ = [
    "PersistStore",
    "Permission",
    "PermissionSet",
    "ActionRequest",
    "PolicyContext",
    "PolicyDecision",
    "PolicyProfile",
    "PolicyProtocol",
    "VectorRecord",
    "VectorStoreProtocol",
]
```

---

**Design Status:** Complete and ready for user review before Platonic Coding Phase 1 (RFC formalization).