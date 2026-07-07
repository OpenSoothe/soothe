# IG-176: Move Rich Dependencies from Daemon to CLI

**Status**: ✅ Completed
**Started**: 2026-04-16
**Completed**: 2026-04-16
**RFCs**: RFC-400 (daemon communication), IG-113 (daemon no UX dependency)
**Priority**: High - Architectural violation

---

## Summary

Successfully moved all Rich-dependent rendering modules from daemon package to CLI package. Daemon now has zero UX dependencies and returns structured data via WebSocket events. CLI/TUI render data with Rich locally.

**Files Removed from Daemon**: 3 files (214 lines total)
- `soothe.plan.rich_tree.py` (56 lines)
- `soothe.plan/__init__.py` (5 lines)
- `soothe.foundation.slash_commands.py` (153 lines)

**Files Added to CLI**: 3 files
- `soothe_cli.plan.rich_tree.py` (56 lines)
- `soothe_cli.plan/__init__.py` (5 lines)
- `soothe_cli.shared.slash_commands.py` (185 lines)

**Daemon Changes**:
- Removed Rich imports from `_handlers.py`
- Refactored `_handle_command()` to return structured data
- Added data-fetching handlers for /plan, /memory, /policy, /history, /config

---

## Overview

Move all Rich-dependent rendering modules from daemon package to CLI package to enforce proper architectural boundaries. Daemon should return structured data; CLI/TUI should render it.

---

## Current Architectural Violation

IG-113 states "Daemon must not depend on UX", but current implementation violates this:

1. `daemon/_handlers.py:169` imports `rich.console.Console`
2. `soothe.foundation.slash_commands` uses Rich directly (Table, Panel)
3. `soothe.plan.rich_tree` uses Rich directly (Tree, Text)

**Correct architecture**:
- Daemon returns **structured data** (JSON/dicts) via WebSocket events
- CLI/TUI **render** that data with Rich
- No Rich imports in daemon package

---

## Implementation Plan

### Phase 1: Move Rich-Dependent Modules to CLI

1. **Move `soothe.plan.rich_tree` to CLI**
   - Create `packages/soothe-cli/src/soothe_cli/plan/` directory
   - Move `rich_tree.py` from daemon to CLI
   - Update imports in CLI consumers

2. **Move `soothe.foundation.slash_commands` to CLI**
   - Create `packages/soothe-cli/src/soothe_cli/shared/slash_commands.py`
   - Move all slash command handlers from daemon foundation
   - Keep daemon version minimal (data-only)

3. **Update daemon imports**
   - Remove Rich imports from `_handlers.py`
   - Remove `slash_commands` import from `foundation/__init__.py`
   - Delete `soothe.plan.rich_tree.py`

### Phase 2: Refactor Daemon Command Handlers

Replace Rich rendering with structured data responses:

1. **`_handle_command()` in daemon/_handlers.py**
   - Parse command type (e.g., "/plan", "/memory", "/policy")
   - Call runner methods to fetch data
   - Broadcast structured event with data
   - CLI renders from event data

2. **Daemon command events** (new event types):
   - `soothe.command.plan_response` - Plan data
   - `soothe.command.memory_response` - Memory stats
   - `soothe.command.policy_response` - Policy profile
   - `soothe.command.history_response` - Input history
   - `soothe.command.config_response` - Config summary

### Phase 3: CLI Slash Command Handlers

1. **CLI-side handlers** in `soothe_cli.shared.slash_commands`
   - Subscribe to daemon command_response events
   - Render data with Rich (Tree, Table, Panel)
   - Handle local commands (/help, /keymaps, /clear)

2. **TUI integration**
   - Import from `soothe_cli.shared.slash_commands`
   - Use Rich Tree for plan rendering

---

## Files to Move

### From Daemon to CLI

| File | From | To |
|------|------|-----|
| `rich_tree.py` | `soothe.plan.rich_tree` | `soothe_cli.plan.rich_tree` |
| `slash_commands.py` | `soothe.foundation.slash_commands` | `soothe_cli.shared.slash_commands` |

### Files to Update

| File | Changes |
|------|---------|
| `daemon/_handlers.py` | Remove Rich imports, return structured data |
| `foundation/__init__.py` | Remove slash_commands export |
| `plan/__init__.py` | Delete (no longer needed in daemon) |
| `CLI/TUI modules` | Import from CLI package |

---

## Verification

✅ All checks passed:

```bash
# Verify no Rich imports in daemon
PASS - No Rich imports in daemon/foundation

# Verify no Rich imports in daemon foundation
PASS - No Rich imports in foundation

# Verify plan directory removed from daemon
PASS - Plan directory removed from daemon

# Verify slash_commands removed from foundation
PASS - slash_commands.py removed from foundation

# Verify Rich modules moved to CLI
PASS - Rich modules successfully moved to CLI

# Run full verification
./scripts/verify_finally.sh
- Format: PASS (all packages)
- Linting: PASS (daemon has zero errors, SDK/CLI zero errors)
- Dependency validation: PASS (CLI does not import daemon)
```

---

## Expected Outcome

- Daemon package has **zero** Rich imports
- Daemon returns structured data via WebSocket events
- CLI/TUI render data with Rich locally
- All tests pass
- Proper architectural separation enforced