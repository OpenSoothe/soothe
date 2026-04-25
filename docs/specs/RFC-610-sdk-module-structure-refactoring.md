# RFC-610: SDK Module Structure Refactoring

**RFC**: 610  
**Title**: SDK Module Structure Refactoring  
**Status**: Draft  
**Kind**: Architecture Design  
**Created**: 2026-04-17  
**Dependencies**: RFC-600, RFC-400, RFC-173 (IG-173 CLI-Daemon Split)  
**Related**: RFC-174 (IG-174 CLI Import Violations Fix), RFC-175 (IG-175 WebSocket Migration)

## Abstract

This RFC defines a comprehensive refactoring of the soothe-sdk module structure to align with langchain-core patterns and improve module organization. The refactoring reorganizes 32 files across 4 purpose packages (plugin/, client/, ux/, utils/, protocols/) while keeping core concepts (events, exceptions, verbosity) at the root level. The design eliminates the flat 15-file root structure, establishes clear ownership boundaries, and reduces file count by 5 through strategic merges and splits. This is a direct breaking change with no backward compatibility layer, requiring all internal packages (CLI + daemon) and third-party plugins to update import paths simultaneously.

## Problem Statement

The current soothe-sdk module structure exhibits several organizational deficiencies:

1. **Flat root with 15 files** - No semantic grouping, hard to navigate, unclear boundaries
2. **Mixed purposes** - Utility files (`utils.py`, `logging_utils.py`) misplaced at root level
3. **Ambiguous naming** - `protocols/` vs potential `protocol/` naming collision, `utils.py` too generic
4. **Scattered plugin API** - Plugin-related code spread across `decorators/`, `types/`, `depends.py`, `exceptions.py`
5. **Langchain ecosystem mismatch** - Structure unfamiliar to plugin developers accustomed to langchain-core patterns

### Current Structure Analysis

**File distribution:**
- Total: 32 files
- Root level: 15 files (events, exceptions, verbosity, utils, logging_utils, protocol, protocol_schemas, config_constants, config_types, internal, ux_types, workspace_types, depends, progress, events_registry)
- Subpackages: 17 files (decorators/ 3, client/ 3, protocols/ 3, types/ 3)

**Circular import analysis:**
- Result: No circular imports detected
- Dependency graph: Clean, subpackages import from root but root doesn't import back
- Root-to-root imports: Only 2 (events_registry → events + verbosity)

**Key problems identified:**
- Plugin API spread across 4 locations (decorators/, types/, depends.py, exceptions.py)
- Client utilities spread across 2 locations (client/, utils.py)
- Config files split unnecessarily (config_constants.py + config_types.py)
- Decorators split into 3 separate files (plugin.py, tool.py, subagent.py)
- No clear package-level ownership (types/ contains only plugin-specific types)

## Design Goals

1. **Match langchain/deepagents patterns** - Familiar structure for ecosystem developers
2. **Clear purpose boundaries** - Organize by function: plugin/, client/, ux/, utils/, protocols/
3. **Scalable architecture** - Core concepts at root, subsystems in packages
4. **Better organization** - Reduce root clutter from 15 files to 3 core files
5. **Clear ownership** - Each package owns its types and utilities
6. **Maintain clean imports** - No circular dependencies introduced
7. **Minimal public API** - Reduce __init__.py size from 197 lines to version-only

## Guiding Principles

1. **Core Concepts at Root** - Events, exceptions, verbosity remain at root level (langchain pattern)
2. **Purpose Packages** - Organize subsystems by clear functional purpose
3. **Single File per Concept** - Merge related small files (decorators, config) following langchain
4. **utils Package, Not File** - Convert flat utils.py to utils/ package with focused modules
5. **Package Ownership** - Plugin owns its types, client owns its config
6. **No Backward Compatibility** - Direct breaking change for cleaner architecture
7. **Langchain Alignment** - Follow langchain-core minimal __init__.py pattern

## Architecture

### Proposed Module Structure

```
soothe_sdk/
├── __init__.py                     # Minimal: __version__ only (no re-exports)
│
├── events.py                       # Core: Base event classes
├── exceptions.py                   # Core: All exception types
├── verbosity.py                    # Core: Verbosity tier system
│
├── protocols/                      # Protocol definitions (stable interfaces)
│   ├── __init__.py                 # Export: PersistStore, PolicyProtocol, VectorStoreProtocol, etc.
│   ├── persistence.py              # PersistStore protocol
│   ├── policy.py                   # PolicyProtocol + permission types
│   └── vector_store.py             # VectorStoreProtocol + VectorRecord
│
├── client/                         # Client utilities
│   ├── __init__.py                 # Export: WebSocketClient, bootstrap_*, helpers
│   ├── websocket.py                # WebSocket client
│   ├── session.py                  # Session bootstrap
│   ├── helpers.py                  # Daemon communication
│   ├── protocol.py                 # Wire protocol encode/decode
│   ├── schemas.py                  # Wire-safe schemas (Plan, PlanStep, ToolOutput)
│   └── config.py                   # Merged: config_constants + config_types
│
├── plugin/                         # Plugin API
│   ├── __init__.py                 # Export: @plugin, @tool, @subagent, Manifest, Context, etc.
│   ├── decorators.py               # Merged: @plugin, @tool, @tool_group, @subagent
│   ├── manifest.py                 # PluginManifest (moved from types/)
│   ├── context.py                  # PluginContext (moved from types/)
│   ├── health.py                   # PluginHealth (moved from types/)
│   ├── depends.py                  # depends.library() helper
│   ├── registry.py                 # register_event() function
│   └── emit.py                     # emit_progress() function
│
├── ux/                             # Display/UX concerns
│   ├── __init__.py                 # Export: ESSENTIAL_EVENT_TYPES, strip_internal_tags
│   ├── types.py                    # UX event types
│   ├── internal.py                 # Text stripping logic
│   └── classification.py           # Event classification (moved from verbosity)
│
├── utils/                          # Utilities (langchain pattern)
│   ├── __init__.py                 # Export: setup_logging, GlobalInputHistory, etc.
│   ├── logging.py                  # Logging utilities (moved from logging_utils.py)
│   ├── display.py                  # Formatting utilities (from utils.py)
│   ├── parsing.py                  # Parsing utilities (from utils.py)
│   └── workspace.py                # Workspace constants (moved from workspace_types.py)
│
└── types/                          # DEPRECATED (empty)
    └── __init__.py                 # Empty, no exports
```

### Structural Decisions

#### Decision 1: Protocols Package (Keep)

**Rationale:** Keep `protocols/` as subpackage rather than merge into single `protocols.py`
- Organized by protocol type (persistence/policy/vector)
- Policy protocol is substantial (183 lines)
- Matches daemon backend structure
- Easier to add new protocols without file bloat
- Total: 3 files (~300 lines) - reasonable for subpackage

**Rejected alternative:** Merge into `protocols.py` (langchain flat-file pattern)
- Would create single large file (~300 lines)
- Policy protocol complexity deserves separate file
- Protocol growth likely, subpackage scales better

#### Decision 2: Plugin Types Migration

**Rationale:** Move plugin types from `types/` to `plugin/` package
- PluginManifest, PluginContext, PluginHealth are all plugin-specific
- Clear ownership - plugin package owns its types
- Eliminates vague "types" catch-all category
- Aligns with purpose package philosophy

**Migration:**
- types/manifest.py → plugin/manifest.py
- types/context.py → plugin/context.py  
- types/health.py → plugin/health.py

#### Decision 3: Minimal __init__.py

**Rationale:** Reduce __init__.py from 197 lines (50+ exports) to version-only
- Matches langchain-core pattern exactly
- Faster import (no loading of all modules at init)
- Clear separation: packages for subsystems, root for core concepts
- Forces explicit imports (more discoverable structure)
- Reduces maintenance burden

**Current:** Re-exports all 50+ public API items  
**New:** Only `__version__` and `__soothe_required_version__`

#### Decision 4: Client Config Merge

**Rationale:** Merge config_constants.py + config_types.py into single `client/config.py`
- Both files are tiny (~75 lines total)
- Single file simpler (langchain pattern)
- Clear ownership - client owns its config
- Both serve same purpose - client configuration

**Files merged:**
- config_constants.py (25 lines) - SOOTHE_HOME, DEFAULT_EXECUTE_TIMEOUT
- config_types.py (50 lines) - MinimalConfigProtocol

#### Decision 5: Exceptions Consolidation

**Rationale:** Keep all exceptions in root `exceptions.py` (no package split)
- Langchain-core pattern (single exceptions.py file)
- Simpler for users (single import location)
- Exceptions are core concept (belong at root)
- Small file (~50 lines, 7 types)
- No package needed for simple type definitions

**Rejected alternative:** Split into plugin/exceptions.py + general exceptions
- Fragments exceptions (harder to find)
- Over-engineers for only 7 types
- Inconsistent with langchain patterns

### File Migration Mapping

#### Root Files → New Locations

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
| utils.py | utils/display.py + utils/parsing.py | Split content |

#### Subpackage Files → New Locations

| Old Location | New Location | Action |
|-------------|-------------|--------|
| decorators/plugin.py | plugin/decorators.py | Merge all 3 decorator files |
| decorators/tool.py | plugin/decorators.py | Merge |
| decorators/subagent.py | plugin/decorators.py | Merge |
| types/manifest.py | plugin/manifest.py | Move |
| types/context.py | plugin/context.py | Move |
| types/health.py | plugin/health.py | Move |

#### Files Remaining at Root

| File | Action |
|-----|--------|
| events.py | Keep (core concept) |
| exceptions.py | Keep (core concept) |
| verbosity.py | Keep (core concept), move classify_event_to_tier to ux/classification.py |

### File Count Impact

- **Before:** 32 files (15 root + 17 subpackages)
- **After:** 27 files (3 root + 24 subpackages)
- **Reduction:** 5 files eliminated via merging and consolidation

## Specification

### Import Path Changes

#### Core Imports (Unchanged)

```python
# Still at root level - no change
from soothe_sdk.events import SootheEvent, LifecycleEvent
from soothe_sdk.exceptions import PluginError, ValidationError
from soothe_sdk.verbosity import VerbosityTier, should_show
```

#### Plugin API Imports

```python
# Before:
from soothe_sdk import plugin, tool, subagent, Manifest
from soothe_sdk import register_event, emit_progress

# After:
from soothe_sdk.plugin import plugin, tool, subagent
from soothe_sdk.plugin import Manifest, register_event, emit_progress
```

#### Client Imports

```python
# Before:
from soothe_sdk import WebSocketClient, encode, decode
from soothe_sdk import SOOTHE_HOME

# After:
from soothe_sdk.client import WebSocketClient
from soothe_sdk.client.protocol import encode, decode
from soothe_sdk.client.config import SOOTHE_HOME
```

#### Utilities Imports

```python
# Before:
from soothe_sdk import setup_logging, format_cli_error

# After:
from soothe_sdk.utils import setup_logging, format_cli_error
```

#### Protocols Imports

```python
# Before:
from soothe_sdk import PersistStore, PolicyProtocol

# After:
from soothe_sdk.protocols import PersistStore, PolicyProtocol
```

### Complete Import Mapping Table

| Old Import (v0.3.x) | New Import (v0.4.0) |
|---------------------|---------------------|
| `from soothe_sdk import plugin` | `from soothe_sdk.plugin import plugin` |
| `from soothe_sdk import tool` | `from soothe_sdk.plugin import tool` |
| `from soothe_sdk import subagent` | `from soothe_sdk.plugin import subagent` |
| `from soothe_sdk import Manifest` | `from soothe_sdk.plugin import Manifest` |
| `from soothe_sdk import WebSocketClient` | `from soothe_sdk.client import WebSocketClient` |
| `from soothe_sdk import encode, decode` | `from soothe_sdk.client.protocol import encode, decode` |
| `from soothe_sdk import SOOTHE_HOME` | `from soothe_sdk.client.config import SOOTHE_HOME` |
| `from soothe_sdk import PersistStore` | `from soothe_sdk.protocols import PersistStore` |
| `from soothe_sdk import setup_logging` | `from soothe_sdk.utils import setup_logging` |
| `from soothe_sdk import format_cli_error` | `from soothe_sdk.utils import format_cli_error` |
| `from soothe_sdk.events import SootheEvent` | **NO CHANGE** |
| `from soothe_sdk.exceptions import PluginError` | **NO CHANGE** |
| `from soothe_sdk.verbosity import VerbosityTier` | **NO CHANGE** |

*(Full 50-row mapping table available in implementation guide)*

### Package __init__.py Specifications

#### soothe_sdk/__init__.py

```python
"""Soothe SDK - Minimal __init__.py matching langchain-core pattern."""

__version__ = "0.4.0"
__soothe_required_version__ = ">=0.4.0,<1.0.0"

# No re-exports - use package imports
```

#### soothe_sdk/plugin/__init__.py

```python
"""Plugin development API."""

from soothe_sdk.plugin.decorators import plugin, tool, tool_group, subagent
from soothe_sdk.plugin.manifest import PluginManifest as Manifest
from soothe_sdk.plugin.context import PluginContext as Context, SootheConfigProtocol
from soothe_sdk.plugin.health import PluginHealth as Health
from soothe_sdk.plugin.depends import library as Depends
from soothe_sdk.plugin.registry import register_event
from soothe_sdk.plugin.emit import emit_progress, set_stream_writer

__all__ = [
    "plugin", "tool", "tool_group", "subagent",
    "Manifest", "Context", "SootheConfigProtocol", "Health",
    "Depends", "register_event", "emit_progress", "set_stream_writer",
]
```

#### soothe_sdk/client/__init__.py

```python
"""WebSocket client utilities."""

from soothe_sdk.client.websocket import WebSocketClient, VerbosityLevel
from soothe_sdk.client.session import bootstrap_thread_session, connect_websocket_with_retries
from soothe_sdk.client.helpers import (
    websocket_url_from_config, check_daemon_status, is_daemon_live,
    request_daemon_shutdown, fetch_skills_catalog, fetch_config_section,
)

__all__ = [
    "WebSocketClient", "VerbosityLevel",
    "bootstrap_thread_session", "connect_websocket_with_retries",
    "websocket_url_from_config", "check_daemon_status",
    "is_daemon_live", "request_daemon_shutdown",
    "fetch_skills_catalog", "fetch_config_section",
]
```

*(Full __init__.py specs for all packages available in implementation guide)*

## Migration Strategy

### Breaking Change Policy

**No backward compatibility layer provided.** This is a direct breaking change requiring immediate import path updates across all dependent packages.

**Rationale:**
- Cleaner architecture (no maintenance burden)
- Faster migration (1-2 weeks vs 7 months)
- Clear breaking signal (v0.4.0 version bump)
- All internal packages updated simultaneously

### Migration Phases

#### Phase 1: SDK Structure Refactoring (Days 1-3)

1. Create new directory structure (plugin/, ux/, utils/)
2. Move files to new locations (batch operations)
3. Merge files (decorators → plugin/decorators.py, config → client/config.py)
4. Split files (utils.py → utils/display.py + utils/parsing.py)
5. Create package __init__.py files with exports
6. Update SDK internal imports (~15 statements)
7. Run SDK unit tests

#### Phase 2: soothe-cli Imports (Day 4)

- Update ~20-25 import statements in 10-15 files
- Affected: config, TUI, headless, commands modules
- Run CLI tests + integration tests

#### Phase 3: soothe (daemon) Imports (Day 5)

- Update ~30-40 import statements in 20-30 files
- Affected: core, protocols, backends, tools, subagents, middleware, daemon
- Run daemon tests + integration tests

#### Phase 4: Full Test Suite (Day 6)

- Run `./scripts/verify_finally.sh` (900+ tests)
- Import timing verification
- Circular import detection
- Package isolation tests

#### Phase 5: Documentation (Day 7)

- Update docs/cli-entry-points-architecture.md
- Update docs/migration-guide-v0.3.md (add v0.4 section)
- Update CLAUDE.md with new import patterns
- Update all markdown code examples

#### Phase 6: Version Bump (Week 2)

- soothe-sdk: v0.3.0 → v0.4.0
- soothe-cli: v0.1.0 → v0.2.0
- soothe (daemon): v0.3.0 → v0.4.0
- Publish migration guide + release notes

**Total timeline: 1-2 weeks**

### Import Count by Package

| Package | Import Statements | Affected Files | Est. Time |
|---------|-------------------|----------------|-----------|
| soothe-sdk (internal) | ~15 | 5 files | 0.5 day |
| soothe-cli | ~20-25 | 10-15 files | 1 day |
| soothe (daemon) | ~30-40 | 20-30 files | 1 day |
| soothe-sdk tests | ~40-50 | 10-15 files | 0.5 day |
| **Total** | **~110-130** | **~45-65 files** | **3 days** |

### Third-Party Plugin Migration

**Impact:** All community plugins break  
**Action required:** Manual import path updates  
**Mitigation:**
- Complete import mapping table in migration guide
- Version bump to v0.4.0 signals breaking change
- Release notes highlight required updates
- Documentation examples show new imports
- GitHub issue template for migration support

## Testing Strategy

### Pre-Refactor Baseline

- All 900+ tests pass with current structure
- Import analysis: no circular imports
- Current import paths verified working

### Post-Refactor Validation

- All 900+ tests pass with new imports
- `./scripts/verify_finally.sh` passes (format, lint, tests)
- Import timing: measure __init__.py load (should be faster)
- Package isolation: each package imports successfully
- Circular import check: dependency graph analysis
- Import completeness: grep verifies all imports updated

### Integration Tests

- CLI commands: `soothe --help`, `soothe thread list`, `soothe -p "test"`
- Daemon commands: `soothed start`, `soothed doctor`
- WebSocket connection: CLI connects to daemon
- Plugin loading: daemon loads plugins with new structure

## Risks and Mitigation

### Risk 1: Breaking Third-Party Plugins

**Impact:** High - all community plugins require manual updates  
**Mitigation:**
- Complete import mapping table (50+ entries)
- Version bump to v0.4.0 (breaking signal)
- Comprehensive migration guide
- Release notes with required actions
- GitHub issue template for support

### Risk 2: Import Errors During Migration

**Impact:** Medium - tests catch errors but time-consuming  
**Mitigation:**
- Batch-by-batch execution (SDK → CLI → Daemon → Tests)
- Run tests after each batch
- Pre-refactor grep search: find all imports
- Import linting tools
- Fix batch before proceeding

### Risk 3: Missed Imports

**Impact:** Medium - could cause runtime failures  
**Mitigation:**
- Multi-layer checking (grep + linting + tests)
- 900+ test coverage
- Final verification script
- Comprehensive code search

### Risk 4: Circular Imports Introduced

**Impact:** High - could break runtime  
**Mitigation:**
- Pre-refactor analysis: verify clean state
- Keep protocols/ separate (no SDK imports)
- Package __init__.py only imports own files
- Post-refactor graph analysis
- Package isolation tests

### Risk 5: Performance Regression

**Impact:** Low - but measurable  
**Mitigation:**
- Benchmark import time before/after
- Minimal __init__.py should improve performance
- If regression detected: investigate specific package imports

## Success Criteria

1. ✓ All 900+ tests pass with new structure
2. ✓ No circular imports detected (graph analysis)
3. ✓ soothe-cli imports updated (~20-25 statements)
4. ✓ soothe (daemon) imports updated (~30-40 statements)
5. ✓ soothe-sdk tests updated (~40-50 statements)
6. ✓ Documentation updated (all markdown files)
7. ✓ Migration guide published (complete mapping)
8. ✓ `./scripts/verify_finally.sh` passes
9. ✓ Import time improved (minimal __init__.py)
10. ✓ Version bumped to v0.4.0

## Benefits

### For Plugin Developers

1. **Familiar structure** - Matches langchain/deepagents patterns
2. **Clear purpose** - All plugin API in plugin/ package
3. **Discoverable** - Package __init__.py shows exports
4. **Scalable** - New features add to appropriate packages
5. **Clean imports** - No flat 15-file root

### For Framework Developers

1. **Better organization** - Related functionality grouped
2. **Easier maintenance** - Clear module ownership
3. **Reduced clutter** - 15 root → 3 core files
4. **Clear boundaries** - Purpose package separation
5. **Langchain alignment** - Ecosystem patterns

### For Users

1. **Easier navigation** - Purpose packages obvious
2. **Better performance** - Minimal __init__.py loads faster
3. **Explicit imports** - Clear what's imported
4. **Consistent naming** - utils/ package, not utils.py file
5. **Future-proof** - Structure scales well

## Implementation

**Implementation Guide:** IG-184 (to be created)  
**Estimated effort:** 1-2 weeks (no backward compatibility)  
**Breaking change:** Yes - all import paths change  
**Migration guide:** Required (docs/migration-guide-v0.3.md v0.4 section)

## References

- RFC-600: Plugin Extension System (plugin API context)
- RFC-400: Daemon Communication Protocol (client utilities context)
- IG-173: CLI-Daemon Split Refactoring (SDK package creation)
- IG-174: CLI Import Violations Fix (SDK Phase 1 exports)
- IG-175: WebSocket Migration (SDK client package)
- langchain-core structure pattern: `/opt/homebrew/lib/python3.14/site-packages/langchain_core/`