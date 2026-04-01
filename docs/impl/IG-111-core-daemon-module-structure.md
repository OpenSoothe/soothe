# IG-111: Core / Daemon Module Structure Refactoring

**Guide**: 111
**Title**: Core and Daemon Module Structure — Foundation, Logging, Health
**Status**: In Progress
**Created**: 2026-04-02
**Related**: RFC-001, IG-100, IG-110

## Overview

This guide tracks a three-part structural refactoring of the `soothe.core` and
`soothe.daemon` packages. The goal is clear layer boundaries, no cross-layer imports,
and well-grouped foundation primitives.

## Changes

### 1. `soothe.logging` — new shared package

**Problem**: `core` hard-imported from two packages it should not depend on:
- `core/runner/__init__.py` → `soothe.ux.core.logging_setup.set_thread_id`
- `core/thread/executor.py` → `soothe.daemon.thread_logger.ThreadLogger`
- `core/thread/manager.py` → `soothe.daemon.thread_logger.ThreadLogger`

**Solution**: Extract all logging primitives into `src/soothe/logging/`:
- `context.py` — `_current_thread_id` ContextVar, `set_thread_id()`, `get_thread_id()`
- `setup.py` — `setup_logging()`, `ThreadFormatter`, LangSmith status logging
- `thread_logger.py` — `ThreadLogger`, `InputHistory`

`ux/core/logging_setup.py` and `daemon/thread_logger.py` are deleted; all callers updated.

### 2. `core/foundation/` — framework base primitives

**Problem**: Framework-wide base types (`SootheEvent`, `VerbosityTier`,
`INVALID_WORKSPACE_DIRS`) were flat files alongside runner-specific helpers.

**Solution**: Group them under `src/soothe/core/foundation/`:
- `base_events.py` — event base classes
- `types.py` — workspace security constants
- `verbosity_tier.py` — verbosity tier enum and event classification

Old files deleted; all ~20 callers updated to `soothe.core.foundation.*`.

### 3. `core/health/` moved to `daemon/health/`

**Problem**: The health-check package checks daemon socket connectivity and PID
files, requiring imports of daemon-layer paths. Keeping it in `core` forced
`core/health` to import `soothe.daemon` (creating a `core → daemon` circular risk).

**Solution**: Move the entire `core/health/` subtree to `daemon/health/`. The
external CLI entry point (`ux/cli/commands/health_cmd.py`) and tests are updated.

`socket_path()` is added to `daemon/paths.py` and re-exported from `daemon/__init__.py`
so `daemon/health/checks/daemon_check.py` can use it cleanly.

## Affected files

| Category | Files |
|----------|-------|
| New `soothe.logging` | `logging/__init__.py`, `context.py`, `setup.py`, `thread_logger.py` |
| New `core.foundation` | `core/foundation/__init__.py`, `base_events.py`, `types.py`, `verbosity_tier.py` |
| Moved health | All 14 files under `core/health/` → `daemon/health/` |
| Deleted | `ux/core/logging_setup.py`, `daemon/thread_logger.py`, `core/base_events.py`, `core/types.py`, `core/verbosity_tier.py`, `core/health/` |
| Updated callers | ~30 files across core, daemon, ux, subagents, tests |

## Verification

```bash
./scripts/verify_finally.sh
```

## References

- Prior art: [IG-110](IG-110-daemon-refactoring.md) — daemon state isolation
- [IG-100](IG-100-coreagent-self-contained-interface.md) — CoreAgent interface
- [RFC-001](../specs/RFC-001-core-modules-architecture.md) — core module architecture
