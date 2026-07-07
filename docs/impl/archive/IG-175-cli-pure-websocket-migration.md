# IG-175: CLI Pure WebSocket Migration

**Status**: Draft
**Started**: 2026-04-15
**Depends on**: IG-174 (Phase 1 complete), RFC-400 (daemon communication)
**Priority**: High - Completes CLI architectural independence

---

## Overview

Complete the migration of soothe-cli to communicate **exclusively** via WebSocket RPC with the daemon. After IG-174 Phase 1, all shared types are in soothe-sdk. This guide addresses the remaining 16 `soothe_daemon.*` imports and architectural coupling points to make the CLI a pure WebSocket client.

**Goal**: Zero `soothe_daemon.*` imports in soothe-cli. All operations via daemon WebSocket RPC or SDK utilities.

---

## Current State

### Remaining `soothe_daemon` Imports (16 statements, 5 files)

| File | Import | Count | Category |
|------|--------|-------|----------|
| `cli/commands/thread_cmd.py` | `SootheRunner`, `ThreadContextManager` | 10 | Thread CRUD (direct backend access) |
| `cli/stream/pipeline.py` | `event_catalog.REGISTRY` | 1 | Event verbosity classification |
| `tui/textual_adapter.py` | `event_catalog.{AGENT_LOOP_COMPLETED, CHITCHAT_RESPONSE, FINAL_REPORT}` | 1 | Event type constants |
| `tui/model_config.py` | `config.env._resolve_provider_env` | 2 | Provider API base URL resolution |
| `shared/suppression_state.py` | `config.constants.DEFAULT_AGENT_LOOP_MAX_ITERATIONS` | 1 | Constant for loop detection |

### Remaining Runtime Coupling (1 statement)

| File | Coupling | Category |
|------|----------|----------|
| `cli/commands/config_cmd.py` | `importlib.resources.files("soothe.config")` | Config template access |

### TODO Markers (17 total)

**Phase 2 - Backend execution via daemon RPC (8):**
- `thread_cmd.py:314` - Thread inspection via daemon WebSocket RPC
- `thread_cmd.py:335` - ThreadLogger logs via daemon RPC
- `thread_cmd.py:419` - Thread export via daemon WebSocket RPC
- `config_cmd.py:177` - File write via daemon RPC
- `tui/config.py:1908` - OpenRouter version check via daemon RPC
- `tui/file_ops.py:14` - Backend protocol via daemon RPC
- `tui/file_ops.py:225` - File ops via daemon RPC
- `tui/agent.py:17` - Backend execution via daemon WebSocket RPC
- `tui/app.py:83` - Backend execution via daemon WebSocket RPC

**Phase 5 - CLI-specific config (4):**
- `tui/thread_backend_bridge.py:8` - CLI-specific config class complete
- `tui/soothe_backend_adapter.py:9` - CLI-specific config class complete
- `tui/daemon_session.py:20` - CLI-specific config class complete
- `tui/app.py:85` - CLI-specific config class complete

**Standalone (4):**
- `tui/app.py:5270` - Plan tree widget toggle
- `tui/app.py:5275` - Memory stats query
- `tui/app.py:5280` - Context stats query
- `tui/app.py:5285` - Active policy display

---

## Implementation Plan

### Task 1: Move Event Constants to SDK

**Problem**: `pipeline.py` and `textual_adapter.py` import event type constants and the REGISTRY from `soothe_daemon.core.event_catalog`.

**Solution**: Move the needed constants and verbosity classification to `soothe_sdk`.

**Changes**:

1. **`soothe_sdk/event_constants.py`** (new or extend `events.py`):
   - Add string constants: `AGENT_LOOP_COMPLETED`, `CHITCHAT_RESPONSE`, `FINAL_REPORT`
   - Add `DEFAULT_AGENT_LOOP_MAX_ITERATIONS` constant (currently `10`)

2. **`soothe_sdk/verbosity.py`** (extend):
   - Add a `get_event_verbosity(event_type: str) -> VerbosityTier` function
   - This replaces `REGISTRY.get_verbosity()` with a client-side classification
   - The daemon can provide a verbosity map via the existing `config_get` RPC, or the SDK hardcodes a sensible default map that covers all known event types

3. **Update CLI files**:
   - `cli/stream/pipeline.py:117`: Replace `from soothe_daemon.core.event_catalog import REGISTRY` with SDK verbosity function
   - `tui/textual_adapter.py:214`: Replace `from soothe_daemon.core.event_catalog import ...` with SDK constants
   - `shared/suppression_state.py:12`: Replace `from soothe_daemon.config.constants import DEFAULT_AGENT_LOOP_MAX_ITERATIONS` with SDK constant

**Daemon-side RPC** (optional enhancement): Add `event_registry` section to `config_get` response so CLI can fetch the full event-to-verbosity mapping at startup.

**Files**: 3 CLI files updated, 1-2 SDK files updated

---

### Task 2: Move Provider Env Resolution to SDK

**Problem**: `model_config.py` imports `_resolve_provider_env` from `soothe_daemon.config.env` (2 call sites).

**Solution**: Move environment variable resolution logic to SDK.

**Changes**:

1. **`soothe_sdk/utils.py`** (extend):
   - Add `resolve_provider_env(value: str, provider_name: str, field_name: str) -> str`
   - This is a simple `${ENV_VAR}` string interpolation function - no daemon dependency

2. **Update CLI files**:
   - `tui/model_config.py:104`: Replace `from soothe_daemon.config.env import _resolve_provider_env`
   - `tui/model_config.py:424`: Replace second occurrence

**Files**: 1 CLI file updated, 1 SDK file updated

---

### Task 3: Thread CRUD via Daemon WebSocket RPC

**Problem**: `thread_cmd.py` imports `SootheRunner` and `ThreadContextManager` (10 imports) for direct backend access when daemon is not running.

**Solution**: Require daemon to be running for all thread operations. Remove direct backend fallback paths.

**Changes**:

1. **New daemon RPC endpoints** (in `message_router.py`):
   - `thread_inspect` / `thread_inspect_response` - Thread details + conversation history
   - `thread_export` / `thread_export_response` - Thread export (jsonl/md)
   - `thread_tag` / `thread_tag_response` - Tag/untag threads

   Note: `thread_list`, `thread_get`, `thread_archive`, `thread_delete` already exist.

2. **New SDK client methods** (in `websocket.py`):
   - `send_thread_inspect(thread_id)` / response handling
   - `send_thread_export(thread_id, format)` / response handling
   - `send_thread_tag(thread_id, tags)` / response handling

3. **Rewrite `thread_cmd.py`**:
   - Remove all `from soothe_daemon.*` imports
   - Remove `_thread_list_direct()` fallback
   - All commands use `WebSocketClient` exclusively
   - If daemon is not running, print clear error: "Daemon not running. Start with `soothe daemon start`"
   - `thread_show` -> uses `thread_inspect` RPC (replaces SootheRunner + ThreadLogger)
   - `thread_delete` -> uses existing `thread_delete` RPC (already in message_router)
   - `thread_export` -> uses new `thread_export` RPC
   - `thread_stats` -> uses `thread_inspect` RPC with stats data
   - `thread_tag` -> uses new `thread_tag` RPC

**Files**: 1 CLI file rewritten, 1 daemon file updated, 1 SDK file updated

---

### Task 4: Remove Config Template Runtime Access

**Problem**: `config_cmd.py:158` uses `importlib.resources.files("soothe.config")` to access `config.yml` template.

**Solution**: Bundle config template in soothe-sdk or soothe-cli package.

**Changes**:

1. **Option A (recommended)**: Copy `config.yml` template into `soothe_sdk/templates/`
   - `soothe_sdk/templates/config.yml` - Default config template
   - CLI reads from `soothe_sdk.templates` instead of `soothe.config`

2. **Update `config_cmd.py`**:
   - Replace `files("soothe.config")` with `files("soothe_sdk.templates")`
   - Keep filesystem fallback for development mode

**Files**: 1 CLI file updated, 1 SDK template added

---

### Task 5: Complete CLIConfig Migration (Phase 5 TODOs)

**Problem**: 4 files have `TODO IG-174 Phase 5: CLI-specific config class complete` markers. These files still accept `SootheConfig` in signatures.

**Solution**: Update type signatures to use `CLIConfig`. The `CLIConfig` class already exists with compatibility properties.

**Changes**:

1. **`tui/thread_backend_bridge.py`**: Change `config: SootheConfig` -> `config: CLIConfig`
2. **`tui/soothe_backend_adapter.py`**: Change `config: SootheConfig` -> `config: CLIConfig`
3. **`tui/daemon_session.py`**: Change to accept `CLIConfig` or extract ws_url directly
4. **`tui/app.py`**: Update config instantiation to use `CLIConfig`
5. **`cli/execution/daemon.py`**: Change `cfg: SootheConfig` -> `cfg: CLIConfig`

**Files**: 5 CLI files updated

---

### Task 6: Resolve File Ops Preview (Phase 2 TODO)

**Problem**: `file_ops.py` has `build_approval_preview()` for `edit_file` that returns a placeholder error because it cannot perform string replacement preview without backend access.

**Solution**: Perform string replacement preview locally (CLI reads files from filesystem).

**Changes**:

1. **`tui/file_ops.py`**: Implement `edit_file` preview using local filesystem read + Python `str.replace()` - no daemon dependency needed since CLI has filesystem access to the same files the agent operates on
2. Remove TODO markers

**Files**: 1 CLI file updated

---

### Task 7: Clean Up Remaining TODOs

**Problem**: Miscellaneous TODOs that need resolution.

**Changes**:

1. **`tui/config.py:1908`** (OpenRouter version check): Remove or implement via HTTP request to OpenRouter API directly (no daemon needed)
2. **`tui/agent.py:17`** (Backend execution TODO): Remove comment - backend execution is correct for local agent creation (the TUI creates the agent locally; this is the deepagents `FilesystemBackend`/`LocalShellBackend`, not the soothe daemon backend)
3. **`tui/app.py:83-85`**: Remove stale TODO comments
4. **`tui/app.py:5270-5285`** (Plan tree, memory/context/policy stats): These are UI feature TODOs, not migration items. Leave as-is or implement via daemon RPC queries.

**Files**: 3-4 CLI files updated

---

## Execution Order

| Order | Task | Impact | Dependencies |
|-------|------|--------|-------------|
| 1 | Task 1: Event constants to SDK | Removes 3 daemon imports | None |
| 2 | Task 2: Provider env to SDK | Removes 2 daemon imports | None |
| 3 | Task 3: Thread CRUD via RPC | Removes 10 daemon imports | Daemon RPC endpoints |
| 4 | Task 4: Config template access | Removes 1 runtime coupling | None |
| 5 | Task 5: CLIConfig migration | Completes type migration | Tasks 1-4 |
| 6 | Task 6: File ops preview | Removes 2 TODOs | None |
| 7 | Task 7: Clean up TODOs | Removes remaining markers | Tasks 1-6 |

Tasks 1, 2, 4, 6 can execute in parallel (no dependencies between them).
Task 3 is the largest and requires daemon-side changes.
Tasks 5 and 7 are cleanup that should run last.

---

## Verification

After each task:
```bash
# Check for remaining daemon imports
grep -rn "from soothe_daemon" packages/soothe-cli/src/
grep -rn "import soothe_daemon" packages/soothe-cli/src/
grep -rn 'files("soothe\.' packages/soothe-cli/src/

# Run verification suite
./scripts/verify_finally.sh
```

**Final target**: Zero matches from all grep commands above.

---

## Success Criteria

- Zero `soothe_daemon.*` imports in soothe-cli
- Zero `soothe.*` runtime access in soothe-cli (only `soothe_sdk`)
- All thread CRUD operations work via daemon WebSocket RPC
- CLI fails gracefully when daemon is not running
- All 900+ tests pass
- Clean `./scripts/verify_finally.sh`

---

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Thread commands require daemon running | Clear error message + daemon auto-start in `run_headless()` already exists |
| Event verbosity classification drift | SDK provides sensible defaults; daemon can override via `config_get` |
| `tui/agent.py` uses deepagents backends directly | This is correct - TUI creates the agent locally with deepagents primitives. Not a daemon dependency. |

---

## Related Documents

- [IG-174: CLI Import Violations Fix](./IG-174-cli-import-violations-fix.md)
- [IG-173: CLI-Daemon Split Refactoring](./IG-173-cli-daemon-split-refactoring.md)
- [RFC-400: Daemon Communication Protocol](../specs/RFC-400-daemon-communication.md)
- [IG-174 Optimization Report](../IG-174-optimization-complete.md)
