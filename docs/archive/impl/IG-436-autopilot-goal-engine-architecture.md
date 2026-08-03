# IG-436: Autopilot and Goal Engine Architecture

**Status**: Phase 1 complete — `_run_autonomous` now delegates per-goal execution to `AutopilotService.execute_goal`  
**RFC**: [RFC-222](../specs/RFC-222-autopilot-goal-engine-architecture.md)  
**Created**: 2026-05-27  
**Dependencies**: RFC-204, RFC-200, IG-420

> **Historical note (IG-677)**: This guide predates assignment-scoped loop ids.
> Current autopilot assignment ids are `autopilot__{job_id}__{uuid}` with separate
> pool slots; durable job↔loop membership is `JobLoopIndex`. See
> [IG-677](../../impl/IG-677-autopilot-job-loop-index.md).

---

## Purpose

This implementation guide documents the architectural refactoring to establish **AutopilotService** and **GoalEngine** as Layer 3 peers. The refactoring extracts loop pool management from AutonomousMixin, introduces internal EventBus for AL ↔ GE coordination, and enables multi-AL parallel execution with file lock conflict resolution.

---

## Scope

### In Scope
1. AutopilotService class extraction (loop pool, scheduling, lifecycle)
2. Internal EventBus (`soothe.internal.*` namespace)
3. LoopPool and LoopHandle data models
4. Goal model extensions (assigned_loop_id, locked_files)
5. File lock registry and conflict resolution
6. Lineage-aware loop assignment

### Out of Scope
- Solo mode changes (preserved unchanged)
- CoreAgent modifications (FileLockMiddleware in separate phase)
- CLI/Daemon integration commands (Phase 5)
- Webhook implementation (uses existing webhooks.py)

---

## Architecture Overview

### Before (Current)
```
SootheRunner
  └── AutonomousMixin
       └── GoalEngine (embedded)
       └── AgentLoop (per-goal inline creation)
       └── _run_autonomous() inline scheduling
```

### After (RFC-222)
```
AutopilotService (new)
  └── LoopPool (worker management)
  └── SchedulingLoop (goal → loop assignment)
  └── InternalEventBus (AL ↔ GE ↔ AP)

GoalEngine (enhanced)
  └── FileLockRegistry (multi-AL conflict tracking)
  └── InternalEventBus subscription
  └── Goal.assigned_loop_id tracking

AgentLoop (unchanged)
  └── Emits events to InternalEventBus
  └── FileLockMiddleware (autopilot mode only)
```

---

## Implementation Phases

### Phase 1: Core Architecture

#### 1.1 Internal EventBus

**Location**: `packages/soothe/src/soothe/core/events/internal_bus.py`

**Implementation**:
```python
class InternalEventBus:
    """In-memory async event dispatch for AL ↔ GE ↔ AP."""
    
    _subscribers: dict[str, list[Callable]]
    _lock: asyncio.Lock
    
    async def emit(self, event: SootheEvent) -> None:
        """Dispatch event to all subscribers."""
        async with self._lock:
            handlers = self._subscribers.get(event.type, [])
            for handler in handlers:
                try:
                    await handler(event)
                except Exception:
                    logger.warning("Event handler failed", exc_info=True)
    
    def subscribe(self, event_type: str, handler: Callable) -> None:
        """Register handler for event type."""
        self._subscribers.setdefault(event_type, []).append(handler)
    
    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """Remove handler registration."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                h for h in self._subscribers[event_type] if h != handler
            ]
```

#### 1.2 Internal Event Types

**Location**: `packages/soothe/src/soothe/core/events/internal_events.py`

**Event Classes**:
- `InternalGoalCompletedEvent`
- `InternalGoalFailedEvent`
- `InternalGoalProgressEvent`
- `InternalGoalStateChangedEvent`
- `InternalGoalsReadyEvent`
- `InternalLoopAssignedEvent`
- `InternalLoopIdleEvent`
- `InternalLoopReleasedEvent`
- `InternalFileLockedEvent`
- `InternalFileReleasedEvent`
- `InternalFileConflictEvent`
- `InternalAutopilotStartedEvent`
- `InternalAutopilotStoppedEvent`
- `InternalLoopPoolChangedEvent`

#### 1.3 LoopPool and LoopHandle

**Location**: `packages/soothe/src/soothe/core/autopilot/loop_pool.py`

```python
class LoopHandle(BaseModel):
    loop_id: str
    current_goal_id: str | None = None
    goal_history: list[str] = Field(default_factory=list)
    status: Literal["active", "idle", "completed", "error"] = "idle"
    idle_since: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

class LoopPool(BaseModel):
    loops: dict[str, LoopHandle] = Field(default_factory=dict)
    goal_to_loop: dict[str, str] = Field(default_factory=dict)  # completed goal → loop
    idle_loops: list[str] = Field(default_factory=list)
    max_loops: int = 4
    active_tasks: dict[str, asyncio.Task] = Field(default_factory=dict)
```

#### 1.4 AutopilotService

**Location**: `packages/soothe/src/soothe/core/autopilot/service.py`

**Key Methods**:
- `start()` — Initialize loop pool, subscribe to GE events
- `stop()` — Release all loops, unsubscribe
- `run_scheduling_loop()` — Main scheduling coroutine
- `assign_loop_with_lineage(goal)` — Lineage-aware loop selection
- `spawn_loop()` — Create new AgentLoop worker
- `release_idle_loops()` — Timeout-based cleanup
- `handle_goal_state_changed(event)` — React to GE state changes
- `handle_goals_ready(event)` — Schedule newly ready goals

---

### Phase 2: GoalEngine Integration

#### 2.1 Goal Model Extensions

**Location**: `packages/soothe/src/soothe/core/goal_engine/models.py`

**New Fields**:
```python
class Goal(BaseModel):
    # ... existing fields ...
    
    # RFC-222: Autopilot-specific fields
    assigned_loop_id: str | None = None
    lock_status: Literal["none", "acquired", "released"] = "none"
    locked_files: list[str] = Field(default_factory=list)
    lock_acquired_at: datetime | None = None
```

#### 2.2 File Lock Registry

**Location**: `packages/soothe/src/soothe/core/goal_engine/file_lock_registry.py`

```python
class FileLockEntry(BaseModel):
    file_path: str
    goal_id: str
    loop_id: str
    locked_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    operation: Literal["edit", "write", "delete"] = "edit"

class FileLockRegistry(BaseModel):
    locks: dict[str, FileLockEntry] = Field(default_factory=dict)
    
    def get_lock(self, path: str) -> FileLockEntry | None:
        return self.locks.get(path)
    
    def is_locked_by_other(self, path: str, loop_id: str) -> bool:
        lock = self.locks.get(path)
        return lock is not None and lock.loop_id != loop_id
    
    def acquire_lock(self, path: str, goal_id: str, loop_id: str, operation: str) -> None:
        self.locks[path] = FileLockEntry(
            file_path=path, goal_id=goal_id, loop_id=loop_id, operation=operation
        )
    
    def release_lock(self, path: str) -> None:
        self.locks.pop(path, None)
    
    def release_all_for_goal(self, goal_id: str) -> list[str]:
        released = []
        for path, lock in list(self.locks.items()):
            if lock.goal_id == goal_id:
                self.locks.pop(path)
                released.append(path)
        return released
```

#### 2.3 GoalEngine.ready_goals() Enhancement

**Modification**: `packages/soothe/src/soothe/core/goal_engine/engine.py`

Add file lock exclusion to `ready_goals()`:
```python
async def ready_goals(self, limit: int = 1, exclude_file_locked: bool = True) -> list[Goal]:
    # ... existing DAG checks ...
    
    # RFC-222: File lock check
    if exclude_file_locked and self._file_registry:
        for goal in ready:
            # Check if goal's target files are locked by other loops
            if self._file_registry.has_conflicts_for_goal(goal.id, goal.assigned_loop_id):
                logger.debug("Goal %s deferred: file lock conflict", goal.id)
                ready.remove(goal)
    
    # ... rest of existing logic ...
```

---

### Phase 3: File Lock Middleware

#### 3.1 FileLockMiddleware

**Location**: `packages/soothe/src/soothe/middleware/file_lock.py`

```python
class FileLockMiddleware(AgentMiddleware):
    """Enforces file lock conflicts across ALs (autopilot mode only)."""
    
    def __init__(self, goal_engine: GoalEngine, loop_id: str, goal_id: str):
        self.ge = goal_engine
        self.loop_id = loop_id
        self.goal_id = goal_id
    
    async def intercept_tool_call(self, tool_name: str, input: dict):
        if tool_name in ("edit_file", "write_file", "delete_file"):
            path = input.get("path") or input.get("file_path")
            
            if self.ge.file_registry.is_locked_by_other(path, self.loop_id):
                lock = self.ge.file_registry.get_lock(path)
                raise FileConflictError(
                    f"File {path} locked by goal {lock.goal_id} in loop {lock.loop_id}"
                )
            
            # Emit lock event
            await self.ge.internal_bus.emit(InternalFileLockedEvent(
                goal_id=self.goal_id,
                loop_id=self.loop_id,
                file_path=path,
                operation="edit"
            ))
```

---

### Phase 4: Scheduling & Lineage

#### 4.1 Lineage-Aware Loop Assignment

**Implementation in**: `packages/soothe/src/soothe/core/autopilot/service.py`

```python
async def assign_loop_with_lineage(self, goal: Goal) -> LoopHandle | None:
    """Assign loop, preferring parent's loop for context reuse."""
    
    # 1. Check lineage affinity
    if goal.parent_id:
        parent_loop_id = self._loop_pool.goal_to_loop.get(goal.parent_id)
        if parent_loop_id:
            handle = self._loop_pool.loops.get(parent_loop_id)
            if handle and handle.status in ("active", "idle"):
                # REUSE: preserves working_memory
                handle.current_goal_id = goal.id
                handle.status = "active"
                handle.idle_since = None
                goal.assigned_loop_id = parent_loop_id
                logger.info("Reused loop %s for child goal %s", parent_loop_id, goal.id)
                return handle
    
    # 2. Check idle loops
    if self._loop_pool.idle_loops:
        idle_id = self._loop_pool.idle_loops.pop(0)
        handle = self._loop_pool.loops.get(idle_id)
        if handle:
            handle.current_goal_id = goal.id
            handle.status = "active"
            handle.idle_since = None
            goal.assigned_loop_id = idle_id
            logger.info("Assigned idle loop %s to goal %s", idle_id, goal.id)
            return handle
    
    # 3. Spawn new loop
    if len(self._loop_pool.loops) < self._loop_pool.max_loops:
        new_loop = await self._spawn_loop()
        new_loop.current_goal_id = goal.id
        new_loop.status = "active"
        goal.assigned_loop_id = new_loop.loop_id
        logger.info("Spawned new loop %s for goal %s", new_loop.loop_id, goal.id)
        return new_loop
    
    # 4. No capacity
    logger.warning("No loop capacity for goal %s", goal.id)
    return None
```

#### 4.2 Idle Loop Release

```python
async def release_idle_loops(self) -> None:
    """Release idle loops after timeout."""
    timeout = self._config.autopilot.loop_idle_timeout
    
    for loop_id in list(self._loop_pool.idle_loops):
        loop = self._loop_pool.loops.get(loop_id)
        if loop and loop.idle_since:
            elapsed = (datetime.now(UTC) - loop.idle_since).total_seconds()
            if elapsed > timeout:
                await self._stop_loop(loop_id)
                del self._loop_pool.loops[loop_id]
                await self._internal_bus.emit(InternalLoopReleasedEvent(loop_id=loop_id))
                logger.info("Released idle loop %s after %ds", loop_id, elapsed)
```

---

### Phase 5: CLI/Daemon Integration

#### 5.1 Daemon Autopilot Endpoints

**Location**: `packages/soothe-daemon/src/soothe_daemon/server/http_routes.py`

Add endpoints:
- `GET /autopilot/status`
- `GET /autopilot/goals`
- `POST /autopilot/submit`
- `DELETE /autopilot/goals/{id}`
- `POST /autopilot/wake`
- `POST /autopilot/dream`

#### 5.2 CLI Commands

**Location**: `packages/soothe-cli/src/soothe_cli/cli/commands/autopilot_cmd.py`

Commands already exist - update to use AutopilotService.

---

## File Changes

### New Files
| Path | Purpose |
|------|---------|
| `core/autopilot/__init__.py` | Package exports |
| `core/autopilot/service.py` | AutopilotService class |
| `core/autopilot/loop_pool.py` | LoopPool, LoopHandle models |
| `core/autopilot/scheduling.py` | SchedulingLoop implementation |
| `core/events/internal_bus.py` | InternalEventBus |
| `core/events/internal_events.py` | Internal event types |
| `core/goal_engine/file_lock_registry.py` | File lock tracking |
| `middleware/file_lock.py` | FileLockMiddleware |

### Modified Files
| Path | Changes |
|------|---------|
| `core/goal_engine/models.py` | Add Goal.assigned_loop_id, locked_files |
| `core/goal_engine/engine.py` | Add file_registry, internal_bus subscription |
| `core/runner/_runner_autonomous.py` | Use AutopilotService instead of inline |
| `core/runner/__init__.py` | Export AutopilotService |
| `config/config.template.yml` | Add autopilot.* config section |

---

## Tests

### Unit Tests
| Path | Coverage |
|------|----------|
| `tests/unit/core/autopilot/test_loop_pool.py` | LoopPool, LoopHandle |
| `tests/unit/core/autopilot/test_service.py` | AutopilotService methods |
| `tests/unit/core/events/test_internal_bus.py` | EventBus emit/subscribe |
| `tests/unit/core/goal_engine/test_file_lock_registry.py` | Lock acquire/release |
| `tests/unit/middleware/test_file_lock.py` | Middleware intercept |

### Integration Tests
| Path | Coverage |
|------|----------|
| `tests/integration/autopilot/test_multi_loop.py` | Parallel goal execution |
| `tests/integration/autopilot/test_lineage_reuse.py` | Loop reuse flow |
| `tests/integration/autopilot/test_file_conflict.py` | Conflict resolution |

---

## Configuration

```yaml
# config/config.template.yml addition
autopilot:
  enabled: false
  
  max_loops: 4
  loop_idle_timeout: 300
  poll_interval: 5
  dreaming_poll_interval: 60
  
  inbox_dir: "$SOOTHE_HOME/autopilot/inbox"
  outbox_dir: "$SOOTHE_HOME/autopilot/outbox"
  
  webhooks:
    on_goal_completed: null
    on_goal_failed: null
    on_autopilot_started: null
    on_autopilot_stopped: null
    on_dreaming_entered: null
    on_dreaming_exited: null
```

---

## Dependencies

- RFC-222 (this RFC)
- RFC-204 (Autopilot Mode - implemented)
- RFC-200 (Goal Management - implemented)
- IG-420 (GE-AgentLoop Integration - in progress)

---

## Verification

Run full verification:
```bash
./scripts/verify_finally.sh
```

Key tests:
```bash
pytest packages/soothe/tests/unit/core/autopilot/ -v
pytest packages/soothe/tests/unit/core/events/test_internal_bus.py -v
pytest packages/soothe/tests/unit/core/goal_engine/test_file_lock_registry.py -v
```

---

## Phase 1.5: Wiring + corrections (2026-05-27 follow-up)

This phase fixed correctness defects in the initial Phase 1 scaffolding (commit
`f3e76fb9`) so the new classes become functional building blocks rather than
orphaned code. Triggered by a review finding several wiring gaps and one broken
middleware contract.

### Delivered

- **GoalEngine wiring** — `GoalEngine.__init__` now accepts `internal_bus`
  (optional) and `file_registry` (optional, defaults to a fresh
  `FileLockRegistry`). `file_registry` and `internal_bus` are exposed as
  public properties.
- **State-change events** — every state-mutating method
  (`create_goal`, `validate_goal`, `suspend_goal`, `block_goal`,
  `reactivate_goal`, `check_reactivated_goals`, `complete_goal`, `fail_goal`,
  `ready_goals`) now emits `InternalGoalStateChangedEvent` when a bus is wired.
  `ready_goals` additionally emits a single `InternalGoalsReadyEvent` per call.
- **Lock release on terminal transitions** — `complete_goal` and `fail_goal`
  release any file locks for the goal and emit `InternalFileReleasedEvent` per
  released path. Backoff and retry branches also release locks.
- **Read-only `peek_ready_goals`** added — same filter as `ready_goals` but
  does not mutate status and does not emit events. Used by AutopilotService
  for capacity planning.
- **Atomic `claim_goal(goal_id, *, loop_id=None)`** added — flips a specific
  goal to `active`, stamps `assigned_loop_id`, re-checks conflicts at claim
  time, emits the state-change event. Resolves the race that would have
  occurred if the service used `ready_goals(limit=1)` to claim by index.
- **FileLockMiddleware rewritten** to extend `langchain.agents.middleware.types.AgentMiddleware`
  with the canonical `awrap_tool_call(request, handler)` hook
  (previous version was a plain class with a non-existent `intercept_tool_call`
  hook). Conflict now returns `ToolMessage(status="error")` — same pattern as
  `SoothePolicyMiddleware` — so the agent can read the message and replan
  instead of the chain raising. `read_file` interception was removed (reads
  are not write operations).
- **AutopilotService config unified** — the parallel `AutopilotConfig`
  `BaseModel` was deleted. The service now accepts the project's
  `AutonomousConfig` directly, which gained six RFC-222 fields
  (`max_loops`, `loop_idle_timeout`, `poll_interval`,
  `dreaming_poll_interval`, `inbox_dir`, `outbox_dir`). Both
  `config/config.template.yml` and `config/config.dev.yml` were updated
  (CLAUDE.md Critical Rule #2).
- **Private-state reaches removed** — `AutopilotService` no longer touches
  `_goal_engine._goals` or `_goal_engine._file_registry`. It uses the public
  `get_goal`, `peek_ready_goals`, `claim_goal`, and `file_registry` surfaces.
  `_assign_loop_with_lineage` is typed as `Goal` instead of `Any`.
- **Reactivate log bug fix** — `reactivate_goal` previously read
  `goal.status` after mutating it, so it always logged `"was pending"`.
  Captured the old status first.

### Test coverage added / changed

- `tests/unit/core/goal_engine/test_engine_events.py` (new) — verifies
  solo-mode silence, every state transition's emitted event, lock release on
  completion, `peek_ready_goals` non-mutation, and `claim_goal` atomicity.
- `tests/unit/middleware/test_file_lock.py` (rewritten) — drives the new
  `awrap_tool_call(ToolCallRequest, handler)` API; asserts `ToolMessage`
  error responses for conflicts (no more raising `FileConflictError`).

### Still deferred to a follow-up IG

- Channel inbox processing (`_process_inbox` is still TODO).
- Scheduled task integration (`_check_scheduled_tasks` is still TODO).
- Loop health monitoring (`_monitor_loop_health` is still TODO).
- Daemon HTTP endpoints (`/autopilot/status`, `/autopilot/submit`, etc.).
- Integration tests under `tests/integration/autopilot/`.
- Real implementation of `FileLockRegistry.has_conflicts_for_goal` /
  `get_conflicting_goals` (requires goals to declare their target files,
  which they don't today).

---

## Changelog

### 2026-05-27 (initial scaffolding)
- IG created for RFC-222 implementation
- Defined 5 implementation phases
- Identified new and modified files
- Defined unit and integration test scope

### 2026-05-27 (Phase 1.5 follow-up)
- GoalEngine wired with InternalEventBus + FileLockRegistry
- State-change event emission added to all mutating methods
- `peek_ready_goals` and `claim_goal` added; `ready_goals` factored on
  shared filter helper
- FileLockMiddleware rewritten as a real `AgentMiddleware`
- AutopilotService now consumes `AutonomousConfig`; RFC-222 fields landed in
  the unified config + both YAML templates
- Private-state reaches in AutopilotService replaced with public methods
- New event-emission tests + rewritten middleware tests

### 2026-05-27 (Phase 1 proper — runner delegation)
- `AutopilotService.execute_goal(goal_id, executor)` async-generator added:
  claims the goal, performs lineage-aware loop assignment, stamps
  `assigned_loop_id`, sets the active-loop ContextVar, runs the executor,
  finalizes the loop on completion/failure.
- `_active_loop_context` ContextVar exported via `get_active_loop_context()`
  so downstream middleware/observers can attribute work to the current
  AutopilotService run without threading loop_id/goal_id through call sites.
- `resolve_goal_engine` now wires the singleton `InternalEventBus` into
  `GoalEngine` automatically — observers (AutopilotService) see every
  state transition in production runs.
- `SootheRunner.__init__` constructs an `AutopilotService` whenever a
  `GoalEngine` is present, sharing the singleton bus.
- `_runner_autonomous._execute_goal_via_autopilot` is the new delegation
  seam: both the single-goal and parallel `asyncio.gather` call sites in
  `_run_autonomous` now go through it. Intent classification, parallel
  batching, proposal queue, send-back logic remain in the runner.
- **Parallel-execution concurrency control (RFC-222)**:
  - `AutopilotService._assignment_lock` (`asyncio.Lock`) serializes
    `_assign_loop_with_lineage` so two concurrent `execute_goal` calls
    can't double-claim a loop slot — even if a future refactor adds an
    `await` inside the assignment path.
  - `AutopilotService._execution_semaphore` (`asyncio.Semaphore`) sized at
    `AutonomousConfig.max_parallel_goals` caps in-flight `execute_goal`
    runs. This makes the service safe to call directly from any caller
    (not just the runner, which had its own ConcurrencyController cap).
- **Bus deadlock fix**: `InternalEventBus.emit` previously held its lock
  for the entire handler fanout. Handlers that emit further events
  (e.g. `_handle_goal_state_changed` → `_mark_loop_idle` → emit) would
  deadlock. The lock now only protects the subscriber snapshot.
- 11 new tests in `test_execute_goal.py`: happy path, missing goal,
  no capacity, executor exception, claim race, lineage reuse, idle reuse,
  and three parallel-execution tests (distinct loops under contention,
  semaphore cap enforcement, assignment-lock serialization).

---

*AutopilotService and GoalEngine as Layer 3 peers, enabling multi-AL orchestration with file lock conflict resolution.*