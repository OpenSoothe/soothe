# IG-409: Restore client workspace propagation through `loop_new`

**Status:** Completed
**Goal:** Fix regression introduced by IG-408 where the user's CWD is no longer propagated to the daemon, causing the agent to operate in `~/.soothe/Workspace/<loop_id>/` instead of the user's project directory.

## Problem

`soothe --no-tui -p "..."` invoked from `~/Workspace/mirasurf/soothe` shows the agent
operating in `~/.soothe/Workspace/019e0a95-04da-7f02-ba7f-6ff2546c26a9` and reporting
the workspace is empty.

Root cause: in commit `ef535080` (IG-408), `bootstrap_loop_session` was rewritten
to discard the `workspace` argument:

```python
_ = workspace  # Loop workspaces are resolved on the daemon host per loop_id.
```

The new `loop_new` payload contains no workspace hint, so
`bind_execution_thread_for_loop` always falls back to
`resolve_loop_daemon_workspace(loop_id)` (the per-loop scratch dir from IG-300).

## Files touched

- `packages/soothe-sdk/src/soothe_sdk/client/session.py` — forward `workspace` in the `loop_new` request payload.
- `packages/soothe-sdk/src/soothe_sdk/client/websocket.py` — `send_loop_new` accepts an optional `workspace` argument for symmetry.
- `packages/soothe/src/soothe/daemon/message_router.py` — `_handle_loop_new` validates the workspace via `validate_client_workspace` and persists it as `client_workspace` in `metadata.json`. Invalid values are dropped (loop creation still succeeds).
- `packages/soothe/src/soothe/daemon/loop_isolation.py` — `bind_execution_thread_for_loop` prefers `metadata['client_workspace']` over `resolve_loop_daemon_workspace(loop_id)`, with a graceful fallback when the path is missing or no longer a directory.

## Tests

- `packages/soothe-sdk/tests/unit/test_session_bootstrap.py` — assert `loop_new` payload carries `workspace` (and is omitted when caller passes `None`).
- `packages/soothe/tests/unit/daemon/test_loop_new_client_workspace.py` — new: persistence in `metadata.json`, rejection of system dirs, fallback when missing, and that `bind_execution_thread_for_loop` registers the client workspace via `_thread_registry.set_workspace`.

## Done

- New behavior verified against the BM-001 workspace injection benchmark cases.
- All workspace-related unit tests pass (27 in core/utils, 5 new in daemon, 3 in SDK session bootstrap).
