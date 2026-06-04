# IG-295: Autopilot Job IPC Commands (RFC-228 Implementation)

> **Status**: Completed
> **RFC**: RFC-228
> **Created**: 2026-06-04
> **Updated**: 2026-06-05
> **Dependencies**: RFC-222, RFC-450

## Progress

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | ✅ Completed | WebSocket RPC handlers in router.py |
| Phase 2 | ✅ Completed | DAG snapshot export in AutopilotService |
| Phase 3 | ✅ Completed | Guidance absorption in GoalEngine |
| Phase 4 | ✅ Completed | Worker subscription bypass in session.py |
| Phase 5 | ✅ Completed | Goal/worker event emission + daemon bridge |

## Files Modified

| Package | File | Changes |
|---------|------|---------|
| soothe-daemon | `protocol/router.py` | 9 WebSocket handlers + autopilot topic subscription |
| soothe-daemon | `server/session.py` | `autopilot_subscribed` flag + filter bypass |
| soothe-daemon | `server/core.py` | Internal→client event bridge |
| soothe | `core/autopilot/service.py` | `dag_snapshot()` method |
| soothe | `core/goal_engine/engine.py` | `absorb_guidance()` method |
| soothe | `core/goal_engine/models.py` | `guidance_accumulated` field |
| soothe | `core/events/internal_events.py` | Client-visible events + conversion helper |

## Goal

Implement WebSocket IPC commands for desktop client interaction with daemon's AutopilotService, per RFC-228 specification.

## Scope

| In Scope | Out of Scope |
|----------|--------------|
| WebSocket RPC handlers for job commands | Desktop client implementation (RFC-700) |
| Autopilot worker subscription bypass | GoalEngine internal modifications |
| Goal/worker event emission | Job persistence (desktop-owned) |

## Current State Analysis

### Existing Infrastructure

| Component | Location | Status |
|-----------|----------|--------|
| HTTP REST autopilot endpoints | `channels/http_rest.py` | ✅ Implemented |
| AutopilotService in daemon | `server/core.py` | ✅ Daemon-owned singleton |
| GoalEngine DAG | `goal_engine/engine.py` | ✅ `depends_on`, `list_goals` |
| WorkerPool namespace filter | `server/session.py:218` | ✅ `is_autopilot_worker_loop_id()` |
| MessageRouter pattern | `protocol/router.py` | ✅ `_handle_{msg_type}` |
| InternalEventBus | `events/internal_bus.py` | ✅ `InternalGoalStateChangedEvent` |

### Gaps

1. **No WebSocket job commands** - HTTP REST only, desktop needs bidirectional streaming
2. **No DAG snapshot method** - Need structured export for React Flow visualization
3. **No guidance absorption** - User comments need route to GoalEngine as BackoffDecision
4. **Worker events filtered** - `autopilot__*` loop_ids blocked from `subscribe_loop`

## Implementation Plan

### Phase 1: WebSocket RPC Handlers (router.py)

Add handlers in `MessageRouter.dispatch()`:

| Message Type | Handler | Implementation |
|--------------|---------|----------------|
| `job_create` | `_handle_job_create` | Call `AutopilotService.submit_task()` |
| `job_status` | `_handle_job_status` | Call `AutopilotService.get_goal()` + traverse DAG |
| `job_pause` | `_handle_job_pause` | Call `GoalEngine.suspend_goal()` |
| `job_resume` | `_handle_job_resume` | Call `GoalEngine.reactivate_goal()` |
| `job_cancel` | `_handle_job_cancel` | Call `AutopilotService.cancel_goal()` |
| `job_dag` | `_handle_job_dag` | NEW: Export DAG snapshot for visualization |
| `job_guidance` | `_handle_job_guidance` | NEW: Route guidance to GoalEngine |
| `autopilot_subscribe` | `_handle_autopilot_subscribe` | NEW: Bypass worker filter |
| `autopilot_unsubscribe` | `_handle_autopilot_unsubscribe` | Release subscription |

**Files to modify**:
- `packages/soothe-daemon/src/soothe_daemon/protocol/router.py` - Add handlers
- `packages/soothe-daemon/src/soothe_daemon/server/session.py` - Add autopilot subscription mode

### Phase 2: DAG Snapshot Export (AutopilotService)

Add method to export DAG structure for React Flow:

```python
async def dag_snapshot(self, root_goal_id: str) -> dict[str, Any]:
    """Export DAG structure for visualization (RFC-228)."""
    goals = await self._goal_engine.list_goals()
    # Filter to goals under root_goal_id tree
    descendants = _traverse_descendants(root_goal_id, goals)
    nodes = [
        {
            "id": g.id,
            "description": g.description[:100],
            "status": g.status,
            "priority": g.priority,
            "depends_on": g.depends_on,
            "assigned_loop_id": g.assigned_loop_id,
            "steps_completed": g.report.steps_completed if g.report else 0,
            "steps_total": g.report.steps_total if g.report else 0,
            "tool_calls": g.report.tool_calls if g.report else 0,
            "summary": g.report.summary if g.report and g.status == "completed" else None,
        }
        for g in descendants
    ]
    edges = [
        {"source": g.id, "target": dep_id}
        for g in descendants
        for dep_id in g.depends_on
    ]
    return {"nodes": nodes, "edges": edges}
```

**Files to modify**:
- `packages/soothe/src/soothe/core/autopilot/service.py` - Add `dag_snapshot()`
- `packages/soothe/src/soothe/core/goal_engine/models.py` - Ensure `GoalReport` has fields

### Phase 3: Guidance Absorption (GoalEngine)

Add method to absorb user guidance as BackoffDecision:

```python
async def absorb_guidance(
    self,
    goal_id: str,
    guidance_text: str,
    scope: str = "goal",  # "goal" or "job" (root)
) -> bool:
    """Absorb user guidance as directive (RFC-228).

    Desktop sends guidance via job_guidance IPC. GoalEngine receives
    and applies as BackoffDecision-like directive without full backoff reasoning.
    """
    goal = self._goals.get(goal_id)
    if goal is None:
        return False

    # Add guidance to goal's context (available for next reasoning cycle)
    if goal.guidance_accumulated is None:
        goal.guidance_accumulated = []
    goal.guidance_accumulated.append({
        "text": guidance_text,
        "timestamp": datetime.now(UTC),
        "scope": scope,
    })

    # Emit event for scheduler to re-evaluate
    await self._emit_guidance_absorbed(goal_id, guidance_text)
    return True
```

**Files to modify**:
- `packages/soothe/src/soothe/core/goal_engine/engine.py` - Add `absorb_guidance()`
- `packages/soothe/src/soothe/core/goal_engine/models.py` - Add `guidance_accumulated` field to Goal

### Phase 4: Worker Event Subscription (session.py)

Add autopilot subscription mode that bypasses namespace filter:

```python
# In ClientSession dataclass
autopilot_subscribed: bool = False  # RFC-228: receives autopilot__* events

# In ClientSessionManager
async def subscribe_autopilot(self, client_id: str) -> bool:
    """Subscribe to autopilot worker events (RFC-228).

    Bypasses is_autopilot_worker_loop_id() filter for this client.
    Client receives soothe.goal.* and soothe.worker.* events.
    """
    session = self._sessions.get(client_id)
    if session is None:
        return False
    session.autopilot_subscribed = True
    return True

# In subscribe_client_to_loop (session.py:213-230)
if is_autopilot_worker_loop_id(loop_id):
    if not session.autopilot_subscribed:
        logger.warning("[Session] rejected subscribe to autopilot worker...")
        return False
    # Allow subscription if autopilot_subscribed=True
```

**Files to modify**:
- `packages/soothe-daemon/src/soothe_daemon/server/session.py` - Add `autopilot_subscribed` flag and bypass

### Phase 5: Goal/Worker Events (internal_events.py)

Add event types for desktop streaming:

| Event Type | Class | Fields |
|------------|-------|--------|
| `soothe.goal.status` | `GoalStatusEvent` | `goal_id`, `status`, `previous_status`, `reason` |
| `soothe.goal.progress` | `GoalProgressEvent` | `goal_id`, `steps_completed`, `steps_total`, `tool_calls` |
| `soothe.worker.assigned` | `WorkerAssignedEvent` | `goal_id`, `loop_id` |
| `soothe.worker.unassigned` | `WorkerUnassignedEvent` | `goal_id`, `loop_id` |

**Note**: `InternalGoalStateChangedEvent` already exists. Need to:
1. Bridge internal events to client-visible events
2. Add progress event emission in GoalEngine

**Files to modify**:
- `packages/soothe/src/soothe/core/events/internal_events.py` - Add client-visible event types
- `packages/soothe/src/soothe/core/goal_engine/engine.py` - Emit progress events
- `packages/soothe-daemon/src/soothe_daemon/server/core.py` - Bridge internal→client events

## File Changes Summary

| Package | File | Changes |
|---------|------|---------|
| soothe-daemon | `protocol/router.py` | Add 9 job handlers |
| soothe-daemon | `server/session.py` | Add `autopilot_subscribed` flag + bypass |
| soothe | `core/autopilot/service.py` | Add `dag_snapshot()` |
| soothe | `core/goal_engine/engine.py` | Add `absorb_guidance()`, emit progress events |
| soothe | `core/goal_engine/models.py` | Add `guidance_accumulated` field, ensure GoalReport fields |
| soothe | `core/events/internal_events.py` | Add client-visible goal/worker events |

## Testing Strategy

1. **Unit tests**: Each new handler/method has corresponding test
2. **Integration tests**: WebSocket client → daemon → AutopilotService flow
3. **Manual tests**: Use desktop app prototype to verify DAG visualization

## Implementation Order

1. Phase 1 (router.py) - WebSocket handlers using existing AutopilotService methods
2. Phase 4 (session.py) - Worker subscription bypass (enables LOR)
3. Phase 2 (service.py) - DAG snapshot for visualization
4. Phase 5 (events) - Goal/worker event emission
5. Phase 3 (engine.py) - Guidance absorption

## Risks

| Risk | Mitigation |
|------|------------|
| GoalReport may lack step/tool fields | Check existing fields, add if missing |
| Internal→Client event bridging complex | Use existing EventBus publish pattern |
| Guidance absorption semantics unclear | Start as simple accumulation, refine later |

## Success Criteria

- All RFC-228 WebSocket commands functional
- Desktop can subscribe to autopilot worker events
- DAG snapshot returns React Flow-compatible structure
- Guidance sent from desktop reaches GoalEngine