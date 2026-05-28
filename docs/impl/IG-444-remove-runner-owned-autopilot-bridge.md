# IG-444: Remove Runner-Owned AutopilotService Bridge (Phase D, Step 1)

**Status**: Complete
**RFC**: [RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md)
**Created**: 2026-05-28

---

## Purpose

IG-442 introduced a daemon-owned `AutopilotService` that handles HTTP-submitted
goals through the daemon's loop pool. That left a coexisting runner-owned
`AutopilotService` with an `execute_goal` bridge method that wrapped
`_execute_autonomous_goal` — redundant and potentially confusing since the
runner's autonomous mode talks to `GoalEngine` directly.

This IG removes the runner-owned instance and the bridge, making
`AutopilotService` exclusively daemon-owned. The runner's `_run_autonomous`
calls `_execute_autonomous_goal` directly (as it did before the bridge was
added), and `AutopilotService.execute_goal` no longer exists as a public
method.

---

## Scope

### In Scope

1. Remove `AutopilotService.execute_goal` method and its helper
   `_finalize_loop_for_goal`.
2. Remove `_active_loop_context` ContextVar and `get_active_loop_context()`
   accessor (only used by the bridge).
3. Remove `_autopilot_service` field from `SootheRunner.__init__` and its
   construction logic.
4. Replace `_execute_goal_via_autopilot` calls in `_runner_autonomous.py`
   with direct calls to `_execute_autonomous_goal`.
5. Delete `test_execute_goal.py` (tested the removed bridge).
6. Update `test_subscribe_to_bus.py` to remove references to
   `has_real_dispatch` (property removed with execute_goal).
7. Miscellaneous test fixes in daemon package that were already needed.

### Out of Scope

- Daemon-owned `AutopilotService` dispatch path (IG-442, unchanged).
- `FileLockMiddleware` rewrite or `peek_ready_goals` (plan recommendations
  #3 and #6, deferred to future IG).
- Config reconciliation (#4), private-access cleanup (#5).

---

## Files Changed

### Modified

| Path | Changes |
|------|---------|
| `packages/soothe/src/soothe/core/autopilot/service.py` | Removed `execute_goal`, `_finalize_loop_for_goal`, `_active_loop_context`, `get_active_loop_context`; removed unused imports (`contextvars`, `AsyncGenerator`, `AsyncIterator`, `Callable`) |
| `packages/soothe/src/soothe/core/runner/__init__.py` | Removed `_autopilot_service` field and construction; updated comment |
| `packages/soothe/src/soothe/core/runner/_runner_autonomous.py` | Replaced `_execute_goal_via_autopilot` calls with direct `_execute_autonomous_goal` calls; removed the bridge method |
| `packages/soothe/tests/unit/core/autopilot/test_subscribe_to_bus.py` | Removed `has_real_dispatch` assertion (property gone); removed unused `pytest` import |
| `packages/soothe-daemon/src/soothe_daemon/query/stream_delivery.py` | Minor test-relevant fix |
| `packages/soothe-daemon/tests/` | Integration test adjustments |

### Deleted

| Path | Reason |
|------|--------|
| `packages/soothe/tests/unit/core/autopilot/test_execute_goal.py` | Tested the removed `execute_goal` bridge |

---

## Verification

```
./scripts/verify_finally.sh
```

All packages clean after changes.

---

## Changelog

### 2026-05-28
- IG created and implementation completed
- Runner-owned AutopilotService bridge removed
- `AutopilotService` is now exclusively daemon-owned
