# IG-430: Ephemeral loop GC

## Goal

Support ephemeral AgentLoops via `loop_new.is_ephemeral`, track workspace and message activity in metadata, and purge idle ephemeral loops from the daemon on a schedule while retaining workspace directories.

## Behavior

- **`loop_new`**: optional `is_ephemeral` (default false). Persists `current_workspace`, `last_message_at` (initial = now).
- **`loop_input`**: updates `last_message_at` on successful enqueue.
- **`bind_execution_thread_for_loop`**: refreshes `current_workspace` when workspace is resolved.
- **GC**: daemon task scans ephemeral loops with no `loop_input` for `ephemeral_loop_gc.idle_hours` (default 24). Purges DB rows, `data/loops/{id}`, and thread persistence; does **not** delete `$SOOTHE_HOME/workspaces/`.

## Config

`daemon_config.yml` → `ephemeral_loop_gc` (`enabled`, `interval_seconds`, `idle_hours`, `batch_size`).

## Files

- `packages/soothe/.../sqlite_backend.py`, `postgres_backend.py`, `manager.py`
- `packages/soothe-daemon/.../loop_gc.py`, `protocol/router.py`, `loop_isolation.py`, `server.py`, `config/`
- Clients: `client/typescript`, `client/go`, `soothe-sdk`

## Tests

- Unit: `packages/soothe/tests/unit/core/loop/state/persistence/test_ephemeral_loop_sqlite.py`, `packages/soothe-daemon/tests/unit/daemon/test_ephemeral_loop_gc.py`
- Integration: `packages/soothe-daemon/tests/integration/daemon/test_daemon_ephemeral_loop_gc.py` (`pytest --run-integration`)

## Status

Completed.
