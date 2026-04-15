# CLI Import Violations Analysis

## Overview

The CLI package (soothe-cli) has **40 files** importing from the daemon runtime package (soothe), violating the architectural boundary defined in IG-173. According to the CLI-daemon split design, CLI should only communicate with daemon via WebSocket using soothe-sdk.

**Total CLI source files**: ~38,000 lines across many files
**Files with violations**: 40 files
**Total import statements**: 48+ violations

## Severity Classification

### 🔴 CRITICAL (2 violations) - Direct daemon runtime coupling

**Files:**
- `tui/app.py` - Imports `SootheDaemon` for auto-start check
- `cli/execution/headless.py` - Imports `SootheDaemon` for daemon auto-start

**Impact:** CLI cannot run independently; requires daemon runtime to be present.

**Fix:** Remove daemon lifecycle from CLI. Use WebSocket client only.

---

### 🟠 HIGH (21 violations) - Core architectural violations

#### Config Imports (17 violations)
**Files:** sessions.py, theme.py, model_config.py, update_check.py, chat_input.py, autopilot_screen.py, autopilot_dashboard.py, config.py, soothe_backend_adapter.py, thread_backend_bridge.py, daemon_session.py, shared/config_loader.py, cli/execution/headless.py, cli/execution/launcher.py, cli/execution/daemon.py, tui/app.py

**Imports:**
- `soothe.config.SOOTHE_HOME` - Config directory path
- `soothe.config.SootheConfig` - Configuration class
- `soothe.config.DEFAULT_EXECUTE_TIMEOUT` - Timeout constant
- `soothe.profiles._openrouter` - OpenRouter profile

**Impact:** CLI needs daemon config structure to function.

**Fix:** 
1. Move config constants to SDK (SOOTHE_HOME, DEFAULT_EXECUTE_TIMEOUT)
2. Create minimal CLI config class in soothe-cli
3. Config should be loaded via WebSocket from daemon

#### Backend Imports (4 violations)
**Files:** agent.py, app.py, file_ops.py

**Imports:**
- `soothe.backends.CompositeBackend` - Backend composition
- `soothe.backends.LocalShellBackend` - Local shell execution
- `soothe.backends.protocol.BackendProtocol` - Backend protocol
- `soothe.backends.utils.perform_string_replacement` - File operations

**Impact:** CLI attempts to execute operations locally, bypassing daemon.

**Fix:** Remove backend execution from CLI. All operations should go through daemon via WebSocket.

---

### 🟡 MEDIUM (7 violations) - Protocol and skills violations

#### Skills Imports (3 violations)
**Files:** skills/invocation.py, skills/load.py

**Imports:**
- `soothe.skills.get_built_in_skills_paths` - Skills discovery
- `soothe.skills.catalog.parse_skill_directory` - Skill parsing

**Impact:** CLI tries to load skills locally instead of requesting from daemon.

**Fix:** Skills should be discovered and invoked via daemon RPC (RFC-400 skills_list RPC exists).

#### Protocol Imports (4 violations)
**Files:** shared/event_processor.py, processor_state.py, renderer_protocol.py, cli/renderer.py

**Imports:**
- `soothe.protocols.planner.Plan` - Plan protocol
- `soothe.protocols.planner.PlanStep` - Plan step

**Impact:** CLI needs plan types for rendering.

**Fix:** Move plan schemas to SDK as wire-safe types (for WebSocket protocol).

---

### 🟢 LOW (18 violations) - Utilities and helpers

#### Utils Imports (5 violations)
**Files:** autopilot_dashboard.py, shared/tui_trace_log.py, presentation_engine.py, shared/message_processing.py, cli/execution/daemon.py

**Imports:**
- `soothe.utils.goal_parsing.parse_autopilot_goals`
- `soothe.utils.text_preview.log_preview`
- `soothe.utils.path_display.convert_and_abbreviate_path`
- `soothe.utils.error_format.format_cli_error`

**Fix:** Move utility functions to SDK or duplicate in CLI package.

#### Logging Imports (2 violations)
**Files:** widgets/history.py, shared/__init__.py

**Imports:**
- `soothe.logging.global_history.GlobalInputHistory`
- `soothe.logging.setup_logging`

**Fix:** Move logging utilities to SDK.

#### Cognition Imports (3 violations)
**Files:** shared/tool_output_formatter.py, tool_formatters/structured.py, fallback.py

**Imports:**
- `soothe.cognition.agent_loop.core.schemas.ToolOutput`

**Fix:** Move ToolOutput schema to SDK as wire-safe type.

#### Other Low-Priority Imports (8 violations)
- `soothe.foundation.strip_internal_tags` (1)
- `soothe.plan.rich_tree._TASK_NAME_RE` (1)
- `soothe.subagents.research.events.SUBAGENT_RESEARCH_INTERNAL_LLM` (1)
- `soothe.tools.display_names.get_tool_display_name` (1)

**Fix:** Move to SDK or duplicate in CLI.

---

## Root Causes

1. **Incomplete refactoring** - CLI/TUI code was copied from monolithic package without removing daemon dependencies
2. **Config coupling** - Config structure is shared between daemon and CLI
3. **Local execution remnants** - CLI still has code for local backend execution
4. **Missing SDK types** - Wire-safe protocol types not in SDK yet
5. **Auto-start daemon** - CLI tries to manage daemon lifecycle directly

## Recommended Fix Strategy

### Phase 1: Move Shared Types to SDK (Week 1)
**Priority: HIGH**

Move these to soothe-sdk:
- Config constants (SOOTHE_HOME, DEFAULT_EXECUTE_TIMEOUT)
- Protocol wire-safe types (Plan, PlanStep, ToolOutput)
- Event type constants (SUBAGENT_RESEARCH_INTERNAL_LLM)
- Utility functions (strip_internal_tags, format_cli_error, etc.)

**Files to update:** 30+ CLI files

### Phase 2: Remove Backend Execution (Week 2)
**Priority: HIGH**

Remove from CLI:
- Backend imports (CompositeBackend, LocalShellBackend)
- Local file execution code
- Replace with WebSocket daemon requests

**Files to update:** agent.py, app.py, file_ops.py

### Phase 3: Daemon Lifecycle Decoupling (Week 3)
**Priority: CRITICAL**

Remove from CLI:
- `SootheDaemon` imports
- Daemon auto-start logic
- Replace with WebSocket connection with retries

**Files to update:** app.py, headless.py

### Phase 4: Skills via Daemon RPC (Week 4)
**Priority: MEDIUM**

Use daemon RPC instead of local skill loading:
- Replace skills imports with WebSocket RPC calls
- Use existing `skills_list` and `invoke_skill` RPC from RFC-400

**Files to update:** skills/invocation.py, skills/load.py

### Phase 5: Create CLI-specific Config (Week 5)
**Priority: HIGH**

Create minimal CLI config:
- CLI-specific config file (cli_config.yml)
- Only WebSocket connection settings
- UI preferences (theme, verbosity)

**Files to update:** All config-using files

---

## Impact Assessment

**If violations remain:**
- ❌ CLI cannot be installed without daemon dependencies (100+ packages)
- ❌ CLI cannot run independently on lightweight machines
- ❌ Architectural boundary is violated
- ❌ Workspace benefits (independent deployment) not realized

**If violations are fixed:**
- ✅ CLI package: ~10 dependencies (typer, textual, rich, websockets, soothe-sdk)
- ✅ Daemon package: 100+ dependencies (langchain, langgraph, etc.)
- ✅ Independent deployment possible
- ✅ Clean architectural separation

---

## Verification

After fixes, run:
```bash
./scripts/verify_finally.sh --deps
```

Expected output:
```
✓ CLI package does not import daemon runtime
✓ SDK package is independent
✓ Workspace packages are in sync
```

---

## Related Documents

- [IG-173: CLI-Daemon Split Refactoring](docs/impl/IG-173-cli-daemon-split-refactoring.md)
- [RFC-400: Daemon Communication Protocol](docs/specs/RFC-400-daemon-communication.md)
- [CLI Entry Points Architecture](docs/cli-entry-points-architecture.md)

---

## Notes

This analysis was generated from the current codebase state on feat/cli branch. The violations are documented in IG-173 as "known violations deferred for future cleanup" during Phase 2 of the CLI-daemon split.

Estimated effort: 5 weeks to fully resolve all violations.

**Current status:** 40 files with violations, 48+ import statements requiring fixes.