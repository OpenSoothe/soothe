# IG-174: Fix CLI Import Violations - Complete Architectural Separation

**Status**: In Progress
**Started**: 2026-04-15
**RFCs**: IG-173 (CLI-daemon split), RFC-400 (daemon communication)
**Priority**: High - Critical for workspace benefits

---

## Overview

Eliminate all CLI import violations (40 files, 48+ statements) to achieve complete architectural separation between CLI client and daemon server. After completion, CLI will have only ~10 dependencies and can run independently.

---

## Current State Analysis

**Violation counts:**
- 🔴 Critical: 2 (daemon direct imports)
- 🟠 High: 21 (config + backends)
- 🟡 Medium: 7 (skills + protocols)
- 🟢 Low: 18 (utils + helpers)

**Root causes:**
1. Config coupling - shared structure between daemon and CLI
2. Backend execution remnants - local execution in CLI
3. Missing SDK types - wire-safe protocol types not in SDK
4. Daemon lifecycle coupling - auto-start in CLI
5. Skills local loading - should use daemon RPC

---

## Implementation Phases

### Phase 1: Move Shared Types to SDK (Priority: HIGH)

**Goal**: Move all shared constants, utilities, and types to soothe-sdk package.

**Files to create in SDK:**

1. **config_constants.py** - Config constants
   - `SOOTHE_HOME` (from `soothe.config.env`)
   - `DEFAULT_EXECUTE_TIMEOUT` (from `soothe.config.constants`)
   
2. **protocol_schemas.py** - Wire-safe protocol types
   - `Plan` schema (from `soothe.protocols.planner`)
   - `PlanStep` schema (from `soothe.protocols.planner`)
   - `ToolOutput` schema (from `soothe.cognition.agent_loop.core.schemas`)
   
3. **event_constants.py** - Event type constants (extend existing events.py)
   - `SUBAGENT_RESEARCH_INTERNAL_LLM` (from `soothe.subagents.research.events`)
   
4. **utils.py** - Shared utilities
   - `strip_internal_tags()` (from `soothe.foundation`)
   - `format_cli_error()` (from `soothe.utils.error_format`)
   - `log_preview()` (from `soothe.utils.text_preview`)
   - `convert_and_abbreviate_path()` (from `soothe.utils.path_display`)
   - `parse_autopilot_goals()` (from `soothe.utils.goal_parsing`)
   - `get_tool_display_name()` (from `soothe.tools.display_names`)
   - `_TASK_NAME_RE` pattern (from `soothe.plan.rich_tree`)
   
5. **logging_utils.py** - Logging utilities
   - `GlobalInputHistory` (from `soothe.logging.global_history`)
   - `setup_logging()` (from `soothe.logging`)
   
**Files to update in CLI:** ~30 files
- Replace all `from soothe.config import X` → `from soothe_sdk import X`
- Replace all `from soothe.protocols.planner import X` → `from soothe_sdk import X`
- Replace all `from soothe.cognition.agent_loop.core.schemas import X` → `from soothe_sdk import X`
- Replace all `from soothe.utils import X` → `from soothe_sdk import X`
- Replace all `from soothe.logging import X` → `from soote_sdk import X`

**Estimated effort:** 30 file updates, 5 new SDK files

**Verification:** Run `./scripts/verify_finally.sh --deps` - should show 0 violations except Phase 2-3

---

### Phase 2: Remove Backend Execution (Priority: HIGH)

**Goal:** Remove all backend execution code from CLI. All operations via daemon WebSocket.

**Files to update:**

1. **tui/agent.py** (HIGH)
   - Remove: `from soothe.backends import CompositeBackend, LocalShellBackend`
   - Action: Delete backend imports, remove local execution logic
   
2. **tui/app.py** (HIGH)
   - Remove: `from soothe.backends import CompositeBackend`
   - Action: Remove backend instantiation, use WebSocket only
   
3. **tui/file_ops.py** (HIGH)
   - Remove: `from soothe.backends.protocol import BackendProtocol`
   - Remove: `from soothe.backends.utils import perform_string_replacement`
   - Action: File operations via daemon RPC
   
4. **tui/tool_display.py** (LOW)
   - Remove: `from soothe.config import DEFAULT_EXECUTE_TIMEOUT`
   - Action: Timeout via WebSocket config

**Estimated effort:** 4 file updates, remove backend execution logic

**Verification:** CLI should not import any backend modules

---

### Phase 3: Daemon Lifecycle Decoupling (Priority: CRITICAL)

**Goal:** Remove direct daemon imports. CLI connects via WebSocket client only.

**Files to update:**

1. **tui/app.py** (CRITICAL)
   ```python
   # REMOVE:
   from soothe.daemon import SootheDaemon
   
   # REPLACE with:
   from soothe_sdk.client.websocket import WebSocketClient
   ```
   
   - Action: Remove daemon lifecycle management
   - Use WebSocket client connection with retries
   - Auto-connection logic via WebSocket
   
2. **cli/execution/headless.py** (CRITICAL)
   ```python
   # REMOVE:
   from soothe.daemon import SootheDaemon
   
   # REPLACE with:
   from soothe_sdk.client.websocket import WebSocketClient
   ```
   
   - Action: Remove daemon auto-start logic
   - Connect to daemon via WebSocket (assume daemon running or fail gracefully)

**Estimated effort:** 2 file updates, replace daemon lifecycle with WebSocket client

**Verification:** CLI should not import `soothe.daemon` directly

---

### Phase 4: Skills via Daemon RPC (Priority: MEDIUM)

**Goal:** Use daemon RPC for skills discovery and invocation instead of local loading.

**Files to update:**

1. **tui/skills/invocation.py** (MEDIUM)
   ```python
   # REMOVE:
   from soothe.skills import get_built_in_skills_paths
   from soothe.skills.catalog import parse_skill_directory
   
   # REPLACE with:
   # Request skills via daemon WebSocket RPC
   # Use RFC-400 skills_list and invoke_skill protocol
   ```
   
2. **tui/skills/load.py** (MEDIUM)
   ```python
   # REMOVE:
   from soothe.skills.catalog import (
   
   # REPLACE with:
   # Request skills catalog via daemon RPC
   ```

**Estimated effort:** 2 file updates, replace with daemon RPC calls

**Verification:** CLI should not import `soothe.skills` modules

---

### Phase 5: CLI-Specific Config (Priority: HIGH)

**Goal:** Create minimal CLI config that doesn't depend on daemon config structure.

**Approach:**

1. **Create CLI config class** in `soothe_cli/config/cli_config.py`
   ```python
   class CLIConfig:
       """CLI-specific configuration (lightweight)."""
       websocket_host: str = "localhost"
       websocket_port: int = 8765
       theme: str = "default"
       verbosity: str = "normal"
       history_file: Path = SOOTHE_HOME / "history.jsonl"
   ```

2. **Load daemon config via WebSocket** when needed
   - Request model catalog via daemon RPC
   - Request provider config via daemon RPC
   - CLI only needs connection settings locally

**Files to update:** All config-using files (~17 files)
   ```python
   # REMOVE:
   from soothe.config import SootheConfig
   
   # REPLACE with:
   from soothe_cli.config import CLIConfig
   # Request detailed config via daemon WebSocket when needed
   ```

**Estimated effort:** 17 file updates, 1 new CLI config module

**Verification:** CLI should not import `soothe.config.SootheConfig` (except via WebSocket)

---

## Execution Order

1. **Week 1**: Phase 1 (shared types to SDK) - Foundation for other phases
2. **Week 2**: Phase 3 (daemon lifecycle) - CRITICAL, enables independence
3. **Week 3**: Phase 5 (CLI config) - HIGH impact, 17 files
4. **Week 4**: Phase 2 (backends) - HIGH impact, local execution removal
5. **Week 5**: Phase 4 (skills) - MEDIUM, completes RPC usage

**Total effort:** 40 files updated, 6 new SDK/CLI modules created

---

## Verification

After each phase:
```bash
./scripts/verify_finally.sh --deps
```

Final goal:
```
✓ CLI package does not import daemon runtime
✓ SDK package is independent
✓ Workspace packages are in sync
✓ All checks passed!
```

---

## Success Criteria

- ✅ CLI package has zero imports from `soothe.*` (except `soothe_sdk`)
- ✅ CLI can be installed independently (pip install soothe-cli)
- ✅ CLI dependencies: ~10 packages (typer, textual, rich, websockets, soothe-sdk)
- ✅ All operations via WebSocket daemon RPC
- ✅ No backend execution in CLI
- ✅ No daemon lifecycle management in CLI
- ✅ Works with daemon running or fails gracefully

---

## Dependencies

- soothe-sdk v0.3.0 (new modules added)
- soothe-cli v0.2.0 (imports fixed)
- soothe (daemon) v0.4.0 (re-exports from SDK for backward compatibility)

---

## Rollback Plan

If issues arise:
1. Keep daemon imports via SDK compatibility layer
2. CLI can import from both SDK and daemon temporarily
3. Gradual migration over 10 weeks instead of 5

---

## Related Documents

- [CLI Import Violations Analysis](../cli-import-violations-analysis.md)
- [IG-173: CLI-Daemon Split Refactoring](./IG-173-cli-daemon-split-refactoring.md)
- [RFC-400: Daemon Communication Protocol](../specs/RFC-400-daemon-communication.md)

---

## Notes

This is the complete fix for IG-173's deferred Phase 2 cleanup work. After completion, the monorepo will have clean architectural separation and all workspace benefits will be realized.