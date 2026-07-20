# IG-574: Workspace mount lost after /clear and checkpoint save

**Created**: 2026-07-10  
**Status**: Implemented  
**Logs**: `deploy/logs/soothe.log`, `deploy/logs/daemon.log` (session 2026-07-10)  
**Related**: [RFC-621](../specs/RFC-621-workspace-host-convention.md), [IG-500](archive/IG-500-clear-loop-archival.md)

---

## Problem

After TUI `/clear` (client `loop_new`) or the second query on a loop, agent tools ran against an empty persisted workspace such as:

`/var/lib/soothe/data/workspaces/anonymous/ws_<hash>`

instead of the Docker bind mount:

`/var/lib/soothe/workspaces/glass3sdkdemo`

### Observed timeline (loop `56ff`)

| Time | Event | Workspace |
|------|--------|-----------|
| `loop_new` | Mapped client cwd correctly | `/var/lib/soothe/workspaces/glass3sdkdemo` |
| First query | No fallback warning | Mount path still in metadata |
| First checkpoint save | StrangeLoop JSONB replace | Daemon fields wiped |
| Second query | Host path fallback | Empty `ws_2369985fd36a7640` |

Log signature:

```
Client workspace not present on daemon host (/Users/chenxm/Workspace/glass3sdkdemo); using persisted layout
Resolved persisted loop workspace: ... -> /var/lib/soothe/data/workspaces/anonymous/ws_...
glob returned error: No files matched pattern '**/glassdemo' under /var/lib/soothe/data/worksp...
```

Same pattern on loop `1fc0` after the first goal: first execution used the mount; later turns fell back to `ws_9f316af4346a1f8a`.

### Root causes

1. **Checkpoint clobber** — `PostgreSQLPersistenceBackend.save_checkpoint` and `LoopPersistenceWriter._persist_goal_boundary_tx` replaced the entire `checkpoint_data` JSONB blob. `StrangeLoopCheckpoint` has no `current_workspace` field, so daemon metadata written at `loop_new` disappeared after the first save.

2. **No mount re-translation on fallback** — `resolve_loop_workspace` checked the host path literally inside the container. When `current_workspace` was missing, it fell back to `client_workspace` (host path), failed `exists()`, and created an empty per-loop persisted directory.

3. **`/clear` reinitialize** — Daemon `_cmd_clear` → `reinitialize_for_clear` minted a new `loop_id` without copying workspace metadata from the archived loop.

Mount configuration (`SOOTHE_WORKSPACE_HOST_ROOT`, `workspace_mount` in `deploy/config.prod.yml`) was correct; the bug was metadata lifecycle and resolution fallback.

---

## Fix

### 1. Preserve daemon metadata on checkpoint save

New module: `packages/soothe/src/soothe/foundation/sloop/state/persistence/daemon_loop_metadata.py`

Fields preserved across StrangeLoop writes:

- `current_workspace`
- `client_workspace`
- `client_workspace_id`
- `user_id`
- `workspace_mapping`
- `is_ephemeral`

Applied in:

- `postgres_backend.save_checkpoint` — merge before JSONB replace
- `loop_writer._persist_goal_boundary_tx` — same merge on goal-boundary writes
- `update_loop_metadata` — allow `workspace_mapping` in PostgreSQL allowed keys

### 2. Re-translate host paths via `workspace_mount`

`loop_workspace.resolve_loop_workspace` / `resolve_client_workspace_on_host`:

- Try literal path on daemon host
- Else map via `workspace_mapping`, explicit mount args, or config `workspace_mount`
- Else fall back to persisted `ws_<hash>` layout

Wire-through:

- `LoopRunRequest.workspace_mapping`
- `query/engine.py` and `loop_dispatcher.py` pass mapping from loop metadata

### 3. Inherit workspace on `/clear` reinitialize

`StrangeLoopStateManager.reinitialize_for_clear`:

- Load daemon workspace metadata from old loop
- After first checkpoint save on new loop, `update_loop_metadata` with inherited fields

TUI `/clear` uses client `loop_new` with cwd; fix (1) keeps that metadata across checkpoint saves. Fix (3) covers daemon slash `/clear`.

---

## Files changed

| Area | Files |
|------|--------|
| Metadata preservation | `daemon_loop_metadata.py`, `postgres_backend.py`, `loop_writer.py` |
| Resolution | `loop_workspace.py`, `core_resolution.py`, `runner.py` |
| Daemon wiring | `query/engine.py`, `loop_dispatcher.py` |
| Clear reinit | `sloop_manager.py` |
| Tests | `test_daemon_loop_metadata.py`, `test_loop_workspace_resolution.py`, `test_reinitialize_for_clear_workspace.py` |

---

## Verification

```bash
./scripts/verify_finally.sh
uv run pytest packages/soothe/tests/unit/core/workspace/test_loop_workspace_resolution.py \
  packages/soothe/tests/unit/core/loop/state/persistence/test_daemon_loop_metadata.py \
  packages/soothe/tests/unit/core/loop/state/test_reinitialize_for_clear_workspace.py
```

### Manual (Docker deploy)

1. Start stack from `deploy/` with `SOOTHE_WORKSPACE_HOST_ROOT` pointing at host projects.
2. TUI from `glass3sdkdemo`: run a query, `/clear`, run a second query touching repo files.
3. Confirm `soothe.log` shows mount path (not `data/workspaces/anonymous/ws_*`) and glob/find hits project files.

---

## Out of scope

- Dedicated PostgreSQL column for `current_workspace` (JSONB merge is sufficient for now).
- TUI `/clear` switching to daemon `_cmd_clear` archival path (still uses client `loop_new`).
