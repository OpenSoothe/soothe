# IG-351: CLI Module and Shared Modules Reorganization

**Status**: In Progress
**Started**: 2026-05-02
**Implementation Guide Number**: IG-351

## Overview

Additional refactoring beyond IG-350 to:
1. Clean stale build artifacts from deleted modules
2. Correct loop_commands.py module placement
3. Reorganize shared/ package by functionality
4. Remove deprecated --config CLI parameter

## Context

**Why this additional refactoring is needed**:
- IG-350 focused on CLI dead code removal and file moves (headless_renderer, task_scope_display, utils.py)
- Stale pycache remains from IG-350 deletions
- `loop_commands.py` (26KB, 870 lines) still misplaced at soothe_cli level (not addressed in IG-350)
- `shared/` package has 25 files approaching organizational limit (not addressed in IG-350)
- Deprecated `--config` parameter still present (not addressed in IG-350)

**Previous Work (IG-350)**:
- Deleted cli/utils.py (make_tool_block unused)
- Moved headless_renderer.py → execution/headless_renderer.py
- Moved task_scope_display.py → stream/task_scope.py
- Removed unused pipeline handlers and context fields
- Simplified formatter.py and display_line.py

**Current Architecture**:
- Excellent RFC-0019 unified event processing architecture in shared/
- Clean dependency hierarchy, no circular dependencies
- Heavy reuse: 33 files import from shared/
- CLI and TUI both depend on shared, not on each other

## Implementation Plan

### Phase 1: Cleanup Stale Pycache (15 min)

**Objective**: Remove stale build artifacts from IG-350 deletions

**Actions**:
1. Remove stale pycache from deleted/moved modules:
   - `cli/__pycache__/utils.cpython-*.pyc` (deleted in IG-350)
   - Other stale pycache from IG-350 moves
2. Clean all stale pycache recursively in packages/soothe-cli
3. Verify cleanup: `find packages/soothe-cli -name "*.pyc"`

**Files affected**: None (build artifacts only)

### Phase 2: Structural Reorganization (2-3 hours)

#### Step 1: Move loop_commands.py (30 min)

**Objective**: Correct module placement to align with architecture

**Actions**:
- Source: `packages/soothe-cli/src/soothe_cli/loop_commands.py`
- Target: `packages/soothe-cli/src/soothe_cli/cli/commands/loop_cmd.py`
- Update import in: `cli/main.py`
- Change: `from soothe_cli.loop_commands import loop_app` → `from soothe_cli.cli.commands.loop_cmd import loop_app`

**Rationale**: loop_commands.py is a CLI command module (Typer app with 9 commands), not a shared utility. Should be alongside thread_cmd.py, autopilot_cmd.py, run_cmd.py.

**Files affected**: 2 files (loop_commands.py, main.py)

#### Step 2: Reorganize shared/ Package (1.5 hours)

**Objective**: Group 25 files by functionality for better organization and scalability

**New structure**:
```
shared/
├── __init__.py              # Re-export key APIs
├── core/                    # RFC-0019 unified event processing
│   ├── __init__.py
│   ├── event_processor.py
│   ├── renderer_protocol.py
│   ├── processor_state.py
│   └── presentation_engine.py
├── tools/                   # Tool call/result handling
│   ├── __init__.py
│   ├── tool_call_resolution.py
│   ├── tool_card_payload.py
│   ├── tool_card_visibility.py
│   ├── tool_output_formatter.py
│   ├── tool_message_format.py
│   ├── message_processing.py
│   ├── rendering.py
│   └── tool_formatters/     # Existing subpackage (keep as-is)
│       ├── __init__.py
│       └── ... (9 formatter classes)
├── commands/                # Slash command routing
│   ├── __init__.py
│   ├── slash_commands.py
│   ├── command_router.py
│   └── subagent_routing.py
├── events/                  # Event handling and filtering
│   ├── __init__.py
│   ├── essential_events.py
│   ├── stream_accumulator.py
│   ├── display_policy.py
│   ├── tui_trace_log.py
│   └── explore_task_display.py
├── rendering/               # Rendering base classes
│   ├── __init__.py
│   ├── renderer_base.py
│   └── async_renderer_protocol.py
└── config_loader.py         # Standalone config utility (top-level)
```

**File distribution**:
- core/: 4 files (event_processor, renderer_protocol, processor_state, presentation_engine)
- tools/: 7 files + tool_formatters/ subpackage = 16 total
- commands/: 3 files (slash_commands, command_router, subagent_routing)
- events/: 5 files (essential_events, stream_accumulator, display_policy, tui_trace_log, explore_task_display)
- rendering/: 2 files (renderer_base, async_renderer_protocol)
- Top-level: config_loader.py

**Files affected**: 25 files moved + new __init__.py files for each subdir

#### Step 3: Update Import Paths (45 min)

**Objective**: Fix all imports to reflect new shared/ structure

**Import mapping table**:

| Old Path | New Path | Files Affected |
|----------|----------|----------------|
| `from soothe_cli.shared import EventProcessor` | `from soothe_cli.shared.core import EventProcessor` | cli/execution/daemon.py, cli/commands/run_cmd.py, cli/commands/thread_cmd.py, cli/stream/pipeline.py |
| `from soothe_cli.shared import RendererProtocol` | `from soothe_cli.shared.rendering import RendererProtocol` | cli/execution/headless_renderer.py, tui/textual_adapter.py |
| `from soothe_cli.shared import tool_call_resolution` | `from soothe_cli.shared.tools import tool_call_resolution` | shared/core/event_processor.py, shared/tools/tool_output_formatter.py, tui/tool_display.py |
| `from soothe_cli.shared import essential_events` | `from soothe_cli.shared.events import essential_events` | cli/execution/daemon.py, cli/commands/run_cmd.py, cli/commands/thread_cmd.py, shared/core/event_processor.py |
| `from soothe_cli.shared import display_policy` | `from soothe_cli.shared.events import display_policy` | shared/core/event_processor.py |
| `from soothe_cli.shared import slash_commands` | `from soothe_cli.shared.commands import slash_commands` | cli/stream/formatter.py, tui/widgets/chat_input.py, tui/widgets/autocomplete.py, tui/input.py |
| `from soothe_cli.shared import subagent_routing` | `from soothe_cli.shared.commands import subagent_routing` | cli/commands/run_cmd.py, cli/commands/thread_cmd.py, shared/core/event_processor.py |
| `from soothe_cli.shared.tool_formatters import ...` | `from soothe_cli.shared.tools.tool_formatters import ...` | shared/tools/tool_output_formatter.py, tui/tool_display.py |
| `from soothe_cli.loop_commands import loop_app` | `from soothe_cli.cli.commands.loop_cmd import loop_app` | cli/main.py |

**Note**: `config_loader.py` stays at shared/ top level, so `load_config` import path unchanged.

**Affected files**:
- CLI modules: cli/commands/, cli/execution/, cli/stream/ (7 files)
- TUI modules: tui/textual_adapter.py, tui/app.py, tui/tool_display.py, tui/widgets/ (6+ files)
- Shared internal: shared/core/event_processor.py, shared/tools/tool_output_formatter.py (2 files)
- Test modules: packages/soothe-cli/tests/unit/ux/cli/, tests/unit/ux/tui/ (multiple files)
- Total: 33+ files

**Facade pattern** in shared/__init__.py:
```python
# shared/__init__.py - Re-export common APIs for backward compatibility
from soothe_cli.shared.core.event_processor import EventProcessor
from soothe_cli.shared.core.renderer_protocol import RendererProtocol
from soothe_cli.shared.config_loader import load_config

__all__ = ["EventProcessor", "RendererProtocol", "load_config"]
```

**Files affected**: 33+ files

#### Step 4: Remove Deprecated --config Parameter (15 min)

**Objective**: Eliminate deprecated CLI parameter

**Actions**:
- Remove from `cli/commands/run_cmd.py`:
  - Remove `config` parameter from function signature
  - Remove deprecation docstring comment
  - Update `Args:` section in docstring
- Remove from `cli/main.py`:
  - Remove `--config` CLI option
  - Remove deprecation help text

**Files affected**: 2 files (run_cmd.py, main.py)

**Risk**: May break existing user scripts using --config flag (user accepted this risk)

### Phase 3: Verification (15 min)

**Objective**: Ensure all changes work correctly

**Verification steps**:
```bash
# 1. Import resolution tests
python -c "from soothe_cli.cli.commands.loop_cmd import loop_app"
python -c "from soothe_cli.shared.core import EventProcessor, RendererProtocol"
python -c "from soothe_cli.shared.tools import tool_call_resolution"
python -c "from soothe_cli.shared.commands import slash_commands"
python -c "from soothe_cli.shared.events import essential_events"
python -c "from soothe_cli.shared.rendering import renderer_base"

# 2. Full verification suite (MANDATORY per CLAUDE.md)
./scripts/verify_finally.sh

# 3. Specific functionality tests
soothe loop list     # Test moved loop commands
soothe thread --help # Test thread diagnostics
soothe --help        # Verify --config removed
soothe run "test"    # Test headless mode

# 4. Unit tests (900+ must pass)
make test-unit

# 5. Linting (zero errors)
make lint
```

## Success Criteria

- ✅ No stale pycache files remain
- ✅ loop_commands.py moved to cli/commands/loop_cmd.py
- ✅ shared/ reorganized into 5 functional subdirs
- ✅ All 33+ importing files updated successfully
- ✅ Deprecated --config parameter removed
- ✅ All imports resolve correctly
- ✅ All 900+ unit tests pass
- ✅ Zero linting errors
- ✅ CLI commands work (loop, thread, run, autopilot)
- ✅ TUI mode works with new imports

## Risk Assessment

**Risk Level**: Low (organizational changes, no logic modifications)

**Breaking Changes**:
- Import paths only (internal API)
- --config parameter removed (CLI API)

**User Impact**: Minimal (CLI commands unchanged from user perspective, except --config removal)

## Dependencies

- IG-350 (completed): CLI dead code removal and file moves

## References

- RFC-0019: Unified event processing architecture
- IG-350: CLI module refactor (dead code cleanup)
- Plan file: `/Users/xiamingchen/.claude/plans/peaceful-prancing-bird.md`

## Timeline

- Phase 1: 15 min (pycache cleanup)
- Phase 2: 2-3 hours (structural reorganization)
- Phase 3: 15 min (verification)
- Total: ~3 hours

## Notes

This IG complements IG-350 by addressing remaining organizational issues:
- IG-350: Dead code removal, file moves (headless_renderer, task_scope_display), simplification
- IG-351: Stale pycache cleanup, loop_commands.py move, shared/ reorganization, --config removal

User decisions confirmed:
1. ✅ Reorganize shared/ into 5 subdirs (accepted organizational effort)
2. ✅ Remove deprecated --config immediately (accepted breaking change risk)
3. ✅ Clean pycache only (no investigation needed)
4. ✅ Update test imports to match new structure