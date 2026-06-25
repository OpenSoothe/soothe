# Autopilot Goal Intake and DAG State Management Flow

> **Analysis Date**: 2026-06-25
> **Scope**: Goal lifecycle from intake → scheduling → execution → completion
> **Key RFCs**: RFC-625 (ContextEngine/AutopilotMonitor), RFC-222 (Autopilot Architecture), RFC-204 (Autopilot Mode)

---

## Overview

The autopilot system manages goals through a centralized **ContextEngine** that serves as the sole source of truth for goal/step DAG state. The flow involves three main components:

```
┌─────────────────────────────────────────────────────────────────┐
│                     LAYER 3: ORCHESTRATION                      │
│  ┌──────────────────┐    ┌──────────────────┐                   │
│  │ AutopilotService │◄──►│ AutopilotMonitor │                   │
│  │ (scheduling)     │    │ (verification)   │                   │
│  └──────────────────┘    └──────────────────┘                   │
│           │                        │                            │
│           ▼                        ▼                            │
│  ┌──────────────────────────────────────────────┐               │
│  │          ContextEngine                        │               │
│  │  • GoalStepDAG (goal + embedded step DAGs)   │               │
│  │  • LedgerManager (cross-goal context)        │               │
│  │  • ProjectionEngine (bounded context)        │               │
│  │  • GoalScheduler (ready goal computation)    │               │
│  └──────────────────────────────────────────────┘               │
└─────────────────────────────────────────────────────────────────┘
                          │
              JOB/STREAM CONTRACT (RFC-221)
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│               LAYER 2: EXECUTION (StrangeLoop)                  │
│  • Receives GoalDispatchEnvelope                               │
│  • Executes single goal with no DAG knowledge                   │
│  • Emits GoalCompletionChunk on termination                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 1. Goal Intake Flow

### Entry Points

Goals enter the autopilot DAG through three primary channels:

#### 1.1 HTTP API Submission (RFC-228)

```
POST /autopilot/submit
    │
    ▼
AutopilotService.submit_task()
    │
    ├─► ContextEngine.create_goal()
    │       • Generate GoalNode with unique ID
    │       • Validate parent exists + depth limit (<5)
    │       • Initialize status = "pending"
    │       • Fire "goal_created" event
    │
    ├─► InternalEventBus.emit("goal_created")
    │
    └─► _persist_goals() → AsyncPersistStore
```

#### 1.2 Monitor Intake with Placement Analysis (RFC-625)

```
AutopilotMonitor.intake_goal()
    │
    ├─► _analyze_placement() via GoalDAGVerifier
    │       • LLM-driven analysis of DAG state
    │       • Adjust priority based on load
    │       • Suggest dependencies (depends_on)
    │       • Detect merge opportunities
    │
    ├─► ContextEngine.create_goal()
    │       • Use adjusted_priority
    │       • Merge suggested_dependencies with user deps
    │
    └─► InternalEventBus.emit("goal_created")
```

#### 1.3 GoalDirective from Completed Goal (RFC-204 Group C)

```
GoalCompletionChunk (from worker)
    │  goal_directives: [{action: "create", ...}]
    │
    ▼
AutopilotService._consume_worker_stream()
    │
    ├─► ContextEngine.apply_directives()
    │       • action="create": new GoalNode with parent_id
    │       • action="adjust_priority": update existing goal
    │       • action="add_dependency": extend depends_on
    │       • action="fail/complete": transition goal state
    │
    └─► Log created goal IDs
```

### GoalNode Model (RFC-624)

```python
class GoalNode:
    id: str                    # UUID hex[:8]
    description: str           # Human-readable text
    priority: int              # 0-100, higher schedules earlier
    status: GoalStatus         # pending | active | completed | failed | suspended | blocked | cancelled
    
    # DAG relationships
    parent_id: str | None      # Hierarchical decomposition
    depends_on: list[str]      # Hard dependencies (must be terminal)
    informs: list[str]         # Soft dependencies (context flow)
    conflicts_with: list[str]  # Workspace conflict gates
    
    # Embedded step DAG
    steps: StepDAG             # Plan nodes for this goal
    
    # Execution tracking
    iteration_count: int       # Current loop iteration
    retry_count: int           # Attempt count
    assigned_loop_id: str      # Worker assignment
```

---

## 2. DAG State Management

### Goal Status Lifecycle

```
┌─────────┐
│ pending │ ◄─── Initial state after intake
└────┬────┘
     │ claim_goal() (dispatch)
     ▼
┌─────────┐
│ active  │ ◄─── Assigned to worker, executing
└────┬────┘
     │
     ├─► complete_goal() ──► ┌───────────┐
     │                       │ completed │ (terminal)
     │                       └───────────┘
     │
     ├─► fail_goal() ──────► ┌─────────┐
     │   (evidence bundle)   │ failed  │ (terminal)
     │                       └─────────┘
     │
     ├─► suspend_goal() ───► ┌───────────┐     reactivate_goal()
     │   (reason string)     │ suspended │ ─────────────────────► pending
     │                       └───────────┘
     │
     ├─► block_goal() ─────► ┌─────────┐     unblock_goal()
     │                       │ blocked │ ──────────────────► pending
     │                       └─────────┘
     │
     └─► cancel_goal() ────► ┌───────────┐
         (user_cancelled)    │ cancelled │ (terminal)
                             └───────────┘
```

### Terminal States (RFC-624)

```python
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
BLOCKED_STATES = frozenset({"awaiting_clarification", "suspended"})
```

Goals in terminal states:
- Release their workspace reservation
- Unblock dependent goals (dependents become schedulable)
- Persist final state to storage

### ContextEngine Event Callbacks

```python
EngineEvent = Literal[
    "goal_created",       # New goal added
    "goal_activated",     # Claimed for dispatch
    "goal_completed",     # Marked completed
    "goal_failed",        # Marked failed (with evidence)
    "goal_suspended",     # Paused (dependency/blockage)
    "goal_cancelled",     # User cancelled
    "goal_blocked",       # Workspace conflict
    "goal_unblocked",     # Dependency resolved
]
```

Event flow triggers downstream handlers:
- `goal_completed` → AutopilotMonitor `_on_goal_completed()` → post-completion verification
- `goal_failed` → AutopilotMonitor `_on_goal_failed()` → backoff reasoning (LLM)
- `goal_unblocked` → AutopilotService `_handle_goal_unblocked()` → check reactivated goals

---

## 3. Scheduling Flow

### Ready Goal Computation (RFC-625)

```python
GoalStepDAG.peek_ready_goals(limit=1) → list[GoalNode]
```

Eligibility criteria:
1. `status == "pending"`
2. All `depends_on` goals in TERMINAL_STATES
3. No `conflicts_with` goals currently active
4. Priority sorting: `-priority DESC, created_at ASC`

```python
# Implementation in models.py:385-411
active_ids = {gid for gid, g in goals.items() if g.status == "active"}
for goal in goals.values():
    if goal.status != "pending":
        continue
    if goal.status in BLOCKED_STATES:
        continue
    deps_met = all(
        (dep := goals.get(dep_id)) is not None and dep.status in TERMINAL_STATES
        for dep_id in goal.depends_on
    )
    if not deps_met:
        continue
    has_conflict = any(dep_id in active_ids for dep_id in goal.conflicts_with)
    if has_conflict:
        continue
    ready.append(goal)
ready.sort(key=lambda g: (-g.priority, g.created_at))
return ready[:limit]
```

### Scheduling Loop (AutopilotService)

```
AutopilotService._run_scheduling_loop() [background task]
    │  poll_interval = config.poll_interval
    │
    ├─► _check_scheduled_tasks() (cron triggers)
    │       • SchedulerService.get_due_tasks()
    │       • Create goals for due tasks
    │
    ├─► _schedule_ready_goals()
    │       │
    │       ├─► [has_real_dispatch]
    │       │       _schedule_via_worker_pool()
    │       │           │
    │       │           ├─► peek_ready_goals(cap_remaining)
    │       │           ├─► WorkspaceReservation.conflicts_with_active()
    │       │           ├─► WorkerPool.pick_worker()
    │       │           ├─► ContextEngine.claim_goal(goal_id, loop_id)
    │       │           │       • Atomic status → "active"
    │       │           │       • Re-check conflicts at claim time
    │       │           ├─► _dispatch_to_worker()
    │       │           │       • Build GoalDispatchEnvelope
    │       │           │       • Create _consume_worker_stream task
    │       │           │
    │       │           [ELSE: legacy LoopPool path]
    │       │
    │       └─► _monitor_loop_health()
    │       │       • Check deadline overruns
    │       │       • Cancel workers exceeding goal_deadline_seconds
    │       │
    │       └─► _release_idle_loops()
    │       │       • Workers idle > loop_idle_timeout
    │       │
    │       └─► [DAG complete] _enter_dreaming_mode()
    │       │       • No active goals
    │       │       • Trigger dreaming distillation
    │       │
    │       └─► sleep(poll_interval)
```

### Goal Claim (Atomic Transition)

```python
# models.py:413-442
def claim_goal(self, goal_id: str, loop_id: str | None = None) -> GoalNode | None:
    goal = self.goals.get(goal_id)
    if goal is None or goal.status != "pending":
        return None
    # Re-check conflicts at claim time (race prevention)
    active_ids = {gid for gid, g in goals.items() 
                  if g.status == "active" and gid != goal_id}
    if any(dep_id in active_ids for dep_id in goal.conflicts_with):
        return None
    # Re-check dependencies
    deps_met = all(
        goals.get(dep_id) is not None and goals.get(dep_id).status in TERMINAL_STATES
        for dep_id in goal.depends_on
    )
    if not deps_met:
        return None
    goal.status = "active"
    goal.assigned_loop_id = loop_id
    return goal
```

---

## 4. Dispatch to Worker

### GoalDispatchEnvelope Construction

```python
# service.py:664-678
LoopRunRequest(
    loop_id=worker.loop_id,
    thread_id=f"autopilot__goal_{goal.id}__attempt_{goal.retry_count + 1}",
    user_input="",  # Empty for autopilot
    client_workspace=goal.workspace,
    autopilot_job=GoalDispatchEnvelope(
        goal_id=goal.id,
        goal_description=goal.description,
        merged_context=GoalDispatchContextBundle,  # from ContextProjector
        deadline_seconds=goal_deadline_seconds,
        attempt=goal.retry_count + 1,
    ),
    autonomous=True,
    max_iterations=max_iterations,
)
```

### Worker Stream Consumption

```
AutopilotService._consume_worker_stream()
    │
    ├─► async for chunk in worker.runner.run(request):
    │       │
    │       └─► [chunk.type == "soothe.internal.autopilot.goal_completion"]
    │               │
    │               ├─► outcome = data.get("outcome")  # "completed" | "failed" | "needs_replan"
    │               ├─► contribution = GoalDispatchContextContribution
    │               ├─► directives = data.get("goal_directives")
    │               │
    │               ├─► ContextEngine.apply_directives(directives)
    │               │       • Create subgoals before outcome handling
    │               │
    │               ├─► [outcome == "completed"]
    │               │       _apply_consensus_and_finalize()
    │               │           • RFC-204 consensus validation (optional)
    │               │           • finalize_goal(status="completed")
    │               │           • WorkspaceReservation.release()
    │               │
    │               └─► [outcome == "failed" | "needs_replan"]
    │                       ContextEngine.fail_goal(evidence=EvidenceBundle)
    │                           • Fire "goal_failed" event
    │                           • Triggers backoff reasoning
    │
    └─► [no completion chunk]
            treat as failed → fail_goal()
```

---

## 5. Completion and Post-Processing

### GoalCompletionChunk from StrangeLoop

Emitted by `goal_completion` node in StrangeLoop orchestrator:

```python
# goal_completion.py
{
    "type": "soothe.internal.autopilot.goal_completion",
    "outcome": "completed" | "failed" | "needs_replan",
    "evidence_summary": str,
    "plan_result_status": str,
    "goal_directives": [
        {"action": "create", "description": "...", "parent_id": "..."},
        {"action": "adjust_priority", "goal_id": "...", "priority": 80},
        ...
    ],
    "context_contribution": {
        "ledger_delta": [...],
        "findings": [...],
        "procedures_used": [...],
    }
}
```

### Backoff Reasoning on Failure (RFC-200)

```
AutopilotMonitor._on_goal_failed()
    │
    ├─► GoalBackoffReasoner.reason_backoff(goal_id, goals, evidence)
    │       • LLM analyzes failure context
    │       • Determines backoff point in DAG
    │       • May suggest parent goal or ancestor
    │       • Generates new directives for recovery
    │
    ├─► BackoffDecision:
    │       backoff_to_goal_id: str  # Where to resume
    │       reason: str              # Natural language reasoning
    │       new_directives: list     # Corrective goals to create
    │       evidence_summary: str    # Condensed analysis
    │
    └─► _apply_backoff_decision()
            • Reset failed goal to pending (if retry_count < max_retries)
            • Create new goals from directives
            • Update DAG dependencies
```

### Post-Completion Verification (RFC-625)

```
AutopilotMonitor._on_goal_completed()
    │
    ├─► GoalDAGVerifier.verify_post_completion(goal_id)
    │       • LLM analyzes goal outcome
    │       • Detect decomposition opportunities
    │       • Identify follow-up goals
    │       • Check for redundant goals to remove
    │
    └─► [DAG complete] _trigger_dreaming()
            • Gather completed goals + ledger
            • Distill episodic memory
            • Extract reusable procedures
            • Update semantic knowledge
```

---

## 6. Dreaming Mode

Triggered when all goals are in terminal states:

```python
# monitor.py:271-289
async def _trigger_dreaming(modes, scope):
    enabled_modes = ["episodic", "procedure", "semantic", "profile"]
    context = await _gather_dreaming_context(scope)
    
    for mode in enabled_modes:
        await _distill_mode(mode, context)
    
    # Store results in ContextEngine
    await ce.record_episodic_memory(episodes)
```

Dreaming modes:
- **episodic**: Summarize goal execution trajectories
- **procedure**: Extract reusable task procedures
- **semantic**: Update knowledge base
- **profile**: Refine user preferences

---

## 7. Crash Recovery

### Active Goal Recovery

```python
# models.py:478-493
def recover_active_goals() -> list[str]:
    """Reset goals stuck in 'active' to 'pending' after daemon restart."""
    for goal in goals.values():
        if goal.status != "active":
            continue
        goal.assigned_loop_id = None
        goal.status = "pending"
        goal.updated_at = now
        recovered.append(goal.id)
    return recovered
```

Executed on daemon startup:
1. Load persisted DAG snapshot from storage
2. Call `recover_active_goals()` to reset orphaned active goals
3. Resume scheduling loop

---

## Key Files Reference

| Component | Location |
|-----------|----------|
| ContextEngine | `packages/soothe/src/soothe/foundation/context/engine.py` |
| GoalStepDAG | `packages/soothe/src/soothe/foundation/context/models.py` |
| AutopilotService | `packages/soothe/src/soothe/foundation/autopilot/service/service.py` |
| AutopilotMonitor | `packages/soothe/src/soothe/foundation/autopilot/monitor/monitor.py` |
| GoalIntakeHandler | `packages/soothe/src/soothe/foundation/autopilot/monitor/goal_intake_handler.py` |
| GoalDAGVerifier | `packages/soothe/src/soothe/foundation/autopilot/monitor/goal_dag_verifier.py` |
| GoalBackoffReasoner | `packages/soothe/src/soothe/foundation/autopilot/monitor/backoff_reasoner.py` |
| GoalScheduler | `packages/soothe/src/soothe/foundation/context/planning/scheduling.py` |
| GoalCompletionNode | `packages/soothe/src/soothe/foundation/loop/orchestrator/nodes/goal_completion.py` |

---

## Summary

The autopilot goal intake and DAG state management follows a **single source of truth** pattern with ContextEngine as the central state owner. Goals flow through:

1. **Intake** → `create_goal()` → status="pending"
2. **Scheduling** → `peek_ready_goals()` → `claim_goal()` → status="active"
3. **Dispatch** → WorkerPool → GoalDispatchEnvelope → StrangeLoop execution
4. **Completion** → GoalCompletionChunk → `complete_goal()`/`fail_goal()` → terminal state
5. **Post-processing** → AutopilotMonitor → verification/backoff/dreaming

All state transitions are atomic with conflict re-checking at claim time, ensuring safe concurrent scheduling across multiple workers.