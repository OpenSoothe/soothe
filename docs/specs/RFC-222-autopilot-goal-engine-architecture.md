# RFC-222: Autopilot and Goal Engine Architecture

**RFC**: 222
**Title**: Autopilot and Goal Engine Architecture
**Status**: Draft
**Kind**: Architecture Design
**Created**: 2026-05-27
**Dependencies**: RFC-000, RFC-201, RFC-204
**Related**: RFC-200 (Goal Lifecycle), RFC-401 (Event System)

---

## Abstract

This RFC defines the unified architecture for Autopilot (agent-swarm orchestration) and GoalEngine (goal DAG management), establishing them as Layer 3 peers that coordinate multi-goal autonomous execution. AutopilotService manages AgentLoop worker pools and scheduling; GoalEngine owns goal lifecycle and DAG state. AgentLoop instances sync with GoalEngine via an internal EventBus. The design preserves existing solo mode execution (no GE involvement) while enabling true 24/7 autonomous operation with parallel agent workers.

---

## Architecture Position

### Layer Model

```
Layer 3: Autonomous Management (AP + GE as peers)
  ┌───────────────────────┐  ┌───────────────────────────┐
  │  AutopilotService     │  │  GoalEngine               │
  │  • Channel messaging  │◄─┤  • Goal lifecycle/DAG     │
  │  • Webhooks           │  │  • Goal state authority   │
  │  • AL resource mgmt   │──┤  • Backoff reasoning      │
  │  • AL scheduling      │  │  • File lock registry     │
  │  • Daemon lifecycle   │  │  • Internal EventBus      │
  └───────────────────────┘  └───────────────────────────┘

Layer 2: AgentLoop (multiple workers in autopilot mode)
  ┌─────────────────────────────────────────────────────────┐
  │  [AL₁]     [AL₂]     [AL₃]     ... (Loop Pool)          │
  │  Each AL syncs with GE via internal EventBus            │
  │  PULL: GE.get_goal(), GE.ready_goals()                  │
  │  REACTIVE: emit GoalCompletedEvent, GoalFailedEvent     │
  └─────────────────────────────────────────────────────────┘

Layer 1: CoreAgent (per AgentLoop)
  ┌─────────────────────────────────────────────────────────┐
  │  [CA₁]     [CA₂]     [CA₃]     ...                      │
  │  Tools, subagents, MCP servers                          │
  │  FileLockMiddleware (autopilot mode only)               │
  └─────────────────────────────────────────────────────────┘
```

### Service Boundary Definition

**AutopilotService Responsibilities**:
- Monitor GoalEngine state changes (goals ready, failed, completed)
- Spawn and manage AgentLoop workers (loop pool)
- Schedule ready goals to available loops (lineage-aware assignment)
- Process ChannelInbox messages (user task submissions)
- Send webhook notifications for goal events
- Handle daemon lifecycle (start, stop, health)
- Enter dreaming mode when no goals active

**NOT responsible for**:
- Single-goal execution logic (AgentLoop owns this)
- Goal DAG management (GoalEngine owns this)
- Tool/subagent execution (CoreAgent owns this)
- AL ↔ GE event coordination (EventBus handles this)

**GoalEngine Responsibilities**:
- Goal lifecycle management (7-state machine per RFC-204)
- DAG dependency resolution (depends_on, conflicts_with)
- Backoff reasoning (LLM-driven DAG restructuring)
- File lock registry (multi-AL conflict tracking)
- Internal EventBus dispatch (AL ↔ GE events)
- Goal state authority (single source of truth)

**NOT responsible for**:
- AL worker spawning (AutopilotService owns this)
- AL scheduling decisions (AutopilotService owns this)
- Webhook notifications (AutopilotService owns this)

---

## Integration Contracts

### AP → GE → AL Flow

```
┌─────────────────────────────────────────────────────────────┐
│  AutopilotService Scheduling Loop                           │
│                                                             │
│  1. AP polls GE.ready_goals(limit=max_loops)                │
│  2. GE returns goals whose deps satisfied, not file-locked  │
│  3. AP assigns each ready goal to a loop:                   │
│     - Check lineage: goal.parent_id?                        │
│     - If parent completed → reuse parent's loop             │
│     - Else → use idle loop or spawn new                     │
│  4. AP launches AL.run_with_progress(goal, loop_id)         │
│  5. AL executes goal, emits events to GE via EventBus       │
│  6. GE updates goal status (completed/failed/backoff)       │
│  7. GE emits GoalStateChangedEvent → AP receives            │
│  8. AP re-evaluates scheduling on state change              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### PULL/REACTIVE Trigger Table

| Trigger | When | Source | Target | Method |
|---------|------|--------|--------|--------|
| **AP PULL #1** | Scheduling loop tick | AP | GE | `GE.ready_goals()` |
| **AL PULL #1** | Before Plan phase | AL | GE | `GE.get_goal(goal_id)` |
| **AL PULL #2** | After backoff | AL | GE | `GE.get_goal(goal_id)` |
| **AL REACTIVE #1** | Goal completion | AL | GE (EventBus) | `GoalCompletedEvent` |
| **AL REACTIVE #2** | Goal failure | AL | GE (EventBus) | `GoalFailedEvent + EvidenceBundle` |
| **AL REACTIVE #3** | File lock | AL | GE (EventBus) | `FileLockedEvent` |
| **GE PUSH #1** | Goal state change | GE | AP (EventBus) | `GoalStateChangedEvent` |
| **GE PUSH #2** | Goals ready | GE | AP (EventBus) | `GoalsReadyEvent` |

---

## Internal EventBus Specification

### Event Namespace Separation

Two distinct event channels ensure isolation:

| Namespace | Bus | Purpose |
|-----------|-----|---------|
| `soothe.internal.goal.*` | Internal | AL ↔ GE goal coordination |
| `soothe.internal.loop.*` | Internal | Loop lifecycle and lineage |
| `soothe.internal.file.*` | Internal | File lock conflict resolution |
| `soothe.internal.autopilot.*` | Internal | AP lifecycle, worker pool |
| `soothe.cognition.*` | External | User-facing progress (existing) |
| `soothe.output.*` | External | User-facing output (existing) |

**Key Principle**: Internal events never leak to external clients (WebSocket, TUI).

### Internal Event Types

```python
# soothe.internal.goal.* (AL ↔ GE goal coordination)
class GoalCompletedEvent(SootheEvent):
    type: str = "soothe.internal.goal.completed"
    goal_id: str
    loop_id: str
    plan_result: PlanResult

class GoalFailedEvent(SootheEvent):
    type: str = "soothe.internal.goal.failed"
    goal_id: str
    loop_id: str
    evidence: EvidenceBundle

class GoalProgressEvent(SootheEvent):
    type: str = "soothe.internal.goal.progress"
    goal_id: str
    loop_id: str
    iteration: int
    phase: str  # "planning", "executing", "reflecting"

class GoalStateChangedEvent(SootheEvent):
    type: str = "soothe.internal.goal.state_changed"
    goal_id: str
    old_status: GoalStatus
    new_status: GoalStatus
    reason: str | None

class GoalsReadyEvent(SootheEvent):
    type: str = "soothe.internal.goal.ready"
    goal_ids: list[str]
    count: int

# soothe.internal.loop.* (Loop lifecycle)
class LoopAssignedEvent(SootheEvent):
    type: str = "soothe.internal.loop.assigned"
    loop_id: str
    goal_id: str

class LoopIdleEvent(SootheEvent):
    type: str = "soothe.internal.loop.idle"
    loop_id: str
    last_goal_id: str
    idle_since: datetime

class LoopReleasedEvent(SootheEvent):
    type: str = "soothe.internal.loop.released"
    loop_id: str

# soothe.internal.file.* (File lock conflict)
class FileLockedEvent(SootheEvent):
    type: str = "soothe.internal.file.locked"
    goal_id: str
    loop_id: str
    file_path: str
    operation: str

class FileReleasedEvent(SootheEvent):
    type: str = "soothe.internal.file.released"
    goal_id: str
    file_path: str

class FileConflictEvent(SootheEvent):
    type: str = "soothe.internal.file.conflict"
    goal_id: str
    file_path: str
    blocking_goal_id: str
    blocking_loop_id: str

# soothe.internal.autopilot.* (AP lifecycle)
class AutopilotStartedEvent(SootheEvent):
    type: str = "soothe.internal.autopilot.started"
    max_loops: int

class AutopilotStoppedEvent(SootheEvent):
    type: str = "soothe.internal.autopilot.stopped"
    reason: str

class LoopPoolChangedEvent(SootheEvent):
    type: str = "soothe.internal.autopilot.pool_changed"
    active_count: int
    idle_count: int
```

### EventBus Implementation

```python
class InternalEventBus:
    """In-memory async event dispatch for AL ↔ GE ↔ AP."""

    _subscribers: dict[str, list[Callable]]

    async def emit(self, event: SootheEvent) -> None:
        handlers = self._subscribers.get(event.type, [])
        for handler in handlers:
            await handler(event)

    def subscribe(self, event_type: str, handler: Callable) -> None:
        self._subscribers.setdefault(event_type, []).append(handler)

# GE subscribes to AL events
internal_bus.subscribe("soothe.internal.goal.completed", ge.handle_goal_completed)
internal_bus.subscribe("soothe.internal.goal.failed", ge.handle_goal_failed)
internal_bus.subscribe("soothe.internal.file.locked", ge.handle_file_locked)

# AP subscribes to GE events
internal_bus.subscribe("soothe.internal.goal.state_changed", ap.handle_state_changed)
internal_bus.subscribe("soothe.internal.goal.ready", ap.handle_goals_ready)
```

---

## Goal Lifecycle & DAG

### Goal Lifecycle States

```
┌─────────────────────────────────────────────────────────────┐
│  Goal Lifecycle State Machine                               │
│                                                             │
│  States (7 total):                                          │
│  pending → active → completed (success path)               │
│  active → failed → pending (retry path)                    │
│  failed → suspended (budget exhaustion)                    │
│  pending → blocked → pending (external dependency)         │
│  active → validated (Layer 3 acceptance)                   │
│                                                             │
│  Autopilot-specific transitions:                            │
│  • pending → active: AP assigns loop                       │
│  • active → completed: AL emits GoalCompletedEvent         │
│  • active → failed: AL emits GoalFailedEvent               │
│  • Goal assigned_loop_id tracks AL assignment              │
│  • Goal locked_files tracks file locks per goal            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Goal Model (Enhanced for Autopilot)

```python
class Goal(BaseModel):
    id: str
    description: str
    status: GoalStatus  # 7 states per RFC-204
    priority: int
    parent_id: str | None
    depends_on: list[str]
    conflicts_with: list[str]
    informs: list[str]

    # Autopilot-specific fields (NEW)
    assigned_loop_id: str | None = None
    lock_status: Literal["none", "acquired", "released"] = "none"
    locked_files: list[str] = []
    lock_acquired_at: datetime | None = None

    # Retry/backoff fields (RFC-200)
    retry_count: int = 0
    max_retries: int = 2
    send_back_count: int = 0
    max_send_backs: int = 3
```

### DAG Scheduling Algorithm

```
GE.ready_goals(limit, exclude_file_locked):

1. Filter goals with status in ("pending", "active")
2. For each candidate goal:
   a. Check hard dependencies (depends_on):
      - All deps must be in TERMINAL_STATES
      - Skip if any dep not terminal
   b. Check conflicts_with:
      - Skip if conflicting goal is "active"
   c. Check soft dependencies (informs):
      - Prefer after inform goals complete
      - Can run concurrently if needed
   d. Check file locks (NEW):
      - Skip if goal's target files locked by other AL
3. Sort by (priority DESC, created_at ASC)
4. Return top N goals
```

### Backoff Reasoning Integration

When goal fails:
1. AL emits `GoalFailedEvent(evidence)`
2. GE receives event, calls `BackoffReasoner.reason_backoff()`
3. BackoffReasoner determines `backoff_to_goal_id` and `new_directives`
4. GE applies `BackoffDecision`:
   - Reset backoff target to "pending"
   - Mark failed goal as "failed"
   - Apply directives to backoff target
5. GE emits `GoalStateChangedEvent`
6. AP re-evaluates scheduling

---

## File Lock Conflict Resolution

### Goal-AL Exclusive Assignment

**Rule**: Each Goal has exactly ONE AL assigned (exclusive lock).

**Assignment Contract**:
- `Goal.assigned_loop_id`: AL's loop_id that owns this goal
- `Goal.locked_files`: Files currently edited by this AL
- Lock acquired when AP assigns goal to AL
- Lock released when goal completes or fails

### File Lock Registry

```python
class FileLockRegistry(BaseModel):
    """GE's view of file locks across all active goals."""

    locks: dict[str, FileLockEntry]  # file_path → lock entry

    def get_lock(self, path: str) -> FileLockEntry | None:
        return self.locks.get(path)

    def is_locked_by_other(self, path: str, loop_id: str) -> bool:
        lock = self.locks.get(path)
        return lock and lock.loop_id != loop_id

class FileLockEntry(BaseModel):
    file_path: str
    goal_id: str
    loop_id: str
    locked_at: datetime
    operation: str  # "edit", "write", "delete"
```

### CoreAgent Middleware Integration

```python
class FileLockMiddleware(AgentMiddleware):
    """Enforces file lock conflicts across ALs (autopilot mode only)."""

    def __init__(self, goal_engine: GoalEngine, loop_id: str):
        self.ge = goal_engine
        self.loop_id = loop_id

    async def intercept_tool_call(self, tool_name: str, input: dict):
        if tool_name in ("edit_file", "write_file", "delete_file"):
            path = input.get("path") or input.get("file_path")

            if self.ge.file_registry.is_locked_by_other(path, self.loop_id):
                lock = self.ge.file_registry.get_lock(path)
                raise FileConflictError(
                    f"File {path} locked by goal {lock.goal_id}"
                )

            # Allow + emit lock event
            await emit_event(FileLockedEvent(
                goal_id=self.goal_id,
                loop_id=self.loop_id,
                file_path=path,
                operation="edit"
            ))
```

### Conflict Resolution Strategies

| Scenario | Resolution |
|----------|------------|
| Same AL edits same file | ALLOW (same lock holder) |
| Different AL edits locked file | BLOCK → AL waits or replans |
| Lock released, new AL edits | ALLOW + new lock |
| Goal completes | Release all locks for that goal |

---

## Autopilot Mode Operations

### Scheduling Loop

```python
async def run_autopilot_loop():
    while running:
        # 1. Process incoming messages
        messages = await channel_inbox.read_pending()
        for msg in messages:
            if msg.type == "task_submit":
                await ge.create_goal(msg.payload)
            elif msg.type == "goal_cancel":
                await ge.fail_goal(msg.goal_id)

        # 2. Check scheduled tasks
        due_tasks = scheduler.get_due_tasks()
        for task in due_tasks:
            await ge.create_goal(task.description)

        # 3. Schedule ready goals
        ready = await ge.ready_goals(limit=max_loops)
        for goal in ready:
            loop = await assign_loop_with_lineage(goal)
            if loop:
                await launch_al_in_loop(goal, loop)

        # 4. Monitor active loops
        await monitor_loop_health()

        # 5. Clean up idle loops
        await release_idle_loops()

        # 6. Sleep for next tick
        await asyncio.sleep(poll_interval)

        # 7. Dreaming mode if complete
        if ge.is_complete():
            await enter_dreaming_mode()
```

### Lineage-Aware Loop Assignment

```python
async def assign_loop_with_lineage(goal: Goal) -> LoopHandle | None:
    """Assign loop, preferring parent's loop for context reuse."""

    # 1. Check lineage affinity
    if goal.parent_id:
        parent_loop = loop_pool.goal_to_loop.get(goal.parent_id)
        if parent_loop:
            handle = loop_pool.loops.get(parent_loop)
            if handle and handle.status in ("active", "idle"):
                # REUSE: preserves working_memory
                handle.current_goal_id = goal.id
                handle.status = "active"
                goal.assigned_loop_id = parent_loop
                return handle

    # 2. Check idle loops
    if loop_pool.idle_loops:
        idle_id = loop_pool.idle_loops.pop(0)
        handle = loop_pool.loops.get(idle_id)
        if handle:
            handle.current_goal_id = goal.id
            handle.status = "active"
            goal.assigned_loop_id = idle_id
            return handle

    # 3. Spawn new loop
    if len(loop_pool.loops) < max_loops:
        new_loop = await spawn_new_loop()
        new_loop.current_goal_id = goal.id
        goal.assigned_loop_id = new_loop.loop_id
        return new_loop

    # 4. No capacity
    return None
```

### Loop Pool Management

```python
class LoopHandle(BaseModel):
    loop_id: str
    current_goal_id: str | None
    goal_history: list[str]
    status: Literal["active", "idle", "completed", "error"]
    idle_since: datetime | None

class LoopPool(BaseModel):
    loops: dict[str, LoopHandle]
    goal_to_loop: dict[str, str]  # completed goal → loop
    idle_loops: list[str]
    max_loops: int
    active_tasks: dict[str, asyncio.Task]
```

### Idle Loop Release

```python
async def release_idle_loops():
    """Release idle loops after timeout."""
    timeout = config.autopilot.loop_idle_timeout

    for loop_id in list(loop_pool.idle_loops):
        loop = loop_pool.loops.get(loop_id)
        if loop and loop.idle_since:
            elapsed = (datetime.now() - loop.idle_since).total_seconds()
            if elapsed > timeout:
                await stop_loop(loop_id)
                del loop_pool.loops[loop_id]
                emit_event(LoopReleasedEvent(loop_id=loop_id))
```

### Dreaming Mode

```python
async def enter_dreaming_mode():
    """Low-power mode when no goals active."""
    emit_event(AutopilotDreamingEvent())
    interval = config.autopilot.dreaming_poll_interval

    while dreaming:
        messages = await channel_inbox.read_pending()
        if messages or scheduler.get_due_tasks():
            await wake_from_dreaming()
            return
        await asyncio.sleep(interval)
```

### Channel Integration

| Channel Message | AP Action |
|-----------------|-----------|
| `task_submit` | Create goal in GE |
| `goal_cancel` | Fail goal in GE |
| `goal_pause` | Suspend goal in GE |
| `goal_resume` | Reactivate goal in GE |
| `must_goal_confirmation` | User approves/rejects goal |

### Webhook Integration

| Webhook | Trigger |
|---------|---------|
| `on_goal_completed` | GE emits GoalStateChangedEvent → completed |
| `on_goal_failed` | GE emits GoalStateChangedEvent → failed |
| `on_autopilot_started` | AP starts |
| `on_autopilot_stopped` | AP stops |
| `on_dreaming_entered` | AP enters dreaming |
| `on_dreaming_exited` | AP wakes |

---

## Solo Mode Compatibility

### Mode Separation

```
┌─────────────────────────────────────────────────────────────┐
│  Solo Mode (No GE Integration)                              │
│                                                             │
│  Entry:                                                     │
│  • `soothe "user input"` (CLI headless)                     │
│  • `soothe` → TUI → user input                              │
│                                                             │
│  Flow:                                                      │
│  CLI/TUI → SootheRunner → AgentLoop ↔ CoreAgent             │
│                                                             │
│  GE Status: NOT ACTIVE                                      │
│  • AL runs independently                                    │
│  • No PULL/REACTIVE triggers                                │
│  • No internal EventBus events                              │
│  • Goal lifecycle in SootheRunner only                      │
│                                                             │
│  Preserved:                                                 │
│  • RFC-201 Plan-Execute loop unchanged                      │
│  • Working memory, loop_messages as-is                      │
│  • Intent classification, routing unchanged                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Autopilot Mode (GE Active)                                 │
│                                                             │
│  Entry:                                                     │
│  • `soothed start` (daemon with autopilot.enabled)          │
│  • `soothe --autopilot` (TUI autopilot UI)                  │
│  • `/autopilot` command in TUI                              │
│                                                             │
│  Flow:                                                      │
│  AutopilotService → GE ↔ [AL Pool] ↔ CoreAgent              │
│                                                             │
│  GE Status: ACTIVE                                          │
│  • Goal DAG management                                      │
│  • Internal EventBus AL ↔ GE                                │
│  • File lock registry                                       │
│  • Backoff reasoning                                        │
│                                                             │
│  NEW:                                                       │
│  • Loop pool with lineage reuse                             │
│  • Multi-AL file conflict resolution                        │
│  • Channel inbox processing                                 │
│  • Webhook notifications                                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Solo Mode Flow (Preserved)

```python
# SootheRunner (solo mode) - Current, unchanged
async def run_stream(user_input: str):
    # No GoalEngine involvement
    agent_loop = AgentLoop(core_agent, planner, config)

    async for event in agent_loop.run_with_progress(
        goal=user_input,  # Goal text, not Goal object
        thread_id=thread_id,
    ):
        yield event

    # Result returned directly to user
    # No GE.complete_goal() or EventBus events
```

### Autopilot Mode Flow (NEW)

```python
# AutopilotService (autopilot mode) - New
async def schedule_goal(goal: Goal):
    loop = await assign_loop_with_lineage(goal)
    al = AgentLoop(core_agent, planner, config)

    # GE integration
    al.core_agent.add_middleware(
        FileLockMiddleware(ge, loop.loop_id)
    )

    async for event in al.run_with_progress(
        goal=goal.description,
        loop_id=loop.loop_id,
    ):
        yield event  # Includes GE sync via EventBus
```

---

## Configuration

```yaml
autopilot:
  enabled: false  # false = solo mode, true = autopilot mode

  # Loop pool settings (autopilot only)
  max_loops: 4
  loop_idle_timeout: 300  # seconds before releasing idle loop
  poll_interval: 5  # scheduling loop tick interval
  dreaming_poll_interval: 60  # reduced polling when idle

  # Channels
  inbox_dir: "$SOOTHE_HOME/autopilot/inbox"
  outbox_dir: "$SOOTHE_HOME/autopilot/outbox"

  # Webhooks
  webhooks:
    on_goal_completed: null
    on_goal_failed: null
    on_autopilot_started: null
    on_autopilot_stopped: null
    on_dreaming_entered: null
    on_dreaming_exited: null
```

---

## Implementation Phases

### Phase 1: Core Architecture
- AutopilotService class extraction from AutonomousMixin
- Internal EventBus implementation (namespace separation)
- LoopPool and LoopHandle data models
- AP daemon lifecycle (start/stop/status)

### Phase 2: GE Integration
- Goal.assigned_loop_id field
- Goal.locked_files field
- File lock registry in GoalEngine
- ready_goals() file lock exclusion

### Phase 3: File Lock Middleware
- FileLockMiddleware implementation
- EventBus file lock events
- Conflict detection and blocking

### Phase 4: Scheduling & Lineage
- Lineage-aware loop assignment
- Loop reuse for parent-child goals
- Idle loop timeout release
- Dreaming mode integration

### Phase 5: CLI/Daemon Integration
- `soothed start` autopilot enable check
- `soothe --autopilot` TUI mode
- `/autopilot` TUI command
- `soothed autopilot status/stop` subcommands

---

## References

- RFC-000: System Conceptual Design
- RFC-201: AgentLoop Plan-Execute Loop Architecture
- RFC-204: Goal File Discovery & Status Tracking
- RFC-200: Layer 3 Goal Management and Backoff Authority
- RFC-401: Event System Architecture

---

## Changelog

### 2026-05-27 (Draft)
- Initial RFC draft defining Autopilot + GoalEngine as Layer 3 peers
- Internal EventBus specification with `soothe.internal.*` namespace
- Goal-AL exclusive assignment and file lock conflict resolution
- Lineage-aware loop reuse for context preservation
- Solo mode preserved (no GE integration) vs Autopilot mode (GE active)
- Channel and webhook integration patterns

---

*AutopilotService and GoalEngine as Layer 3 peers, enabling 24/7 autonomous goal execution with multi-AL orchestration while preserving solo mode compatibility.*