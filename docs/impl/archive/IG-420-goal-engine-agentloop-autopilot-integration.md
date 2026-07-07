# IG-420: Goal Engine and AgentLoop Integration for Autopilot

**Status**: In Progress  
**RFC**: [RFC-200](../specs/RFC-200-autonomous-goal-management.md), [RFC-201](../specs/RFC-201-agentloop-plan-execute-loop.md), [RFC-204](../specs/RFC-204-autopilot-mode.md)  
**Created**: 2026-05-15  

---

## Purpose

This implementation guide documents the integration between the **GoalEngine** (Layer 3 - Autonomous Goal Management) and **AgentLoop** (Layer 2 - Agentic Goal Execution) to create the **Autopilot** mode in Soothe. The integration enables long-running autonomous operation with goal DAG orchestration, consensus validation, and dreaming mode.

---

## Architecture Overview

### Three-Layer Execution Model

Soothe operates through a hierarchical execution model with three distinct layers:

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: Autonomous Goal Management (GoalEngine)               │
│ ├─ Scope: Long-running complex workflows, multi-goal DAGs     │
│ ├─ Loop: Goal/Goals → PLAN → PERFORM → REFLECT → Update      │
│ ├─ Delegation: PERFORM invokes Layer 2's full Plan → Execute   │
│ └─ Key Components:                                            │
│    • GoalEngine (packages/soothe/src/soothe/core/goal_engine/)│
│    • Goal lifecycle management (pending → active → validated)  │
│    • DAG orchestration with dependencies, priorities           │
│    • Consensus loop with send-back budget                      │
│    • Dreaming mode for continuous operation                  │
└─────────────────────────────────────────────────────────────────┘
                              ↓ PERFORM delegation
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: Agentic Goal Execution (AgentLoop)                    │
│ ├─ Scope: Single-goal execution through iterative refinement   │
│ ├─ Loop: Plan → Execute (max iterations: ~8)                   │
│ ├─ Delegation: Execute invokes Layer 1 CoreAgent              │
│ └─ Key Components:                                            │
│    • AgentLoop (packages/soothe/src/soothe/core/loop/)         │
│    • LangGraph-based orchestration (RFC-220)                   │
│    • PlanPhase with assessment + conditional planning        │
│    • Checkpoint-based state persistence                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓ Execute delegation
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: CoreAgent Runtime                                     │
│ ├─ Foundation: create_soothe_agent() → CompiledStateGraph     │
│ └─ Execution: Model → Tools → Model loop (LangGraph native)   │
└─────────────────────────────────────────────────────────────────┘
```

### Integration Pattern: Pull-Based Architecture

The integration uses an **inverted control flow** where Layer 2 (AgentLoop) actively queries Layer 3 (GoalEngine) for goal assignment:

```python
# Simplified integration flow (_runner_autonomous.py)

# 1. GoalEngine provides ready goals
ready_goals = await self._goal_engine.ready_goals(limit=max_par_goals)

# 2. For each ready goal, create AgentLoop instance
agent_loop = AgentLoop(
    core_agent=self._agent,
    loop_planner=self._planner,
    config=self._config,
)

# 3. Delegate goal execution to AgentLoop
async for event_type, event_data in agent_loop.run_with_progress(
    goal=goal.description,
    thread_id=thread_id,
    max_iterations=DEFAULT_AGENT_LOOP_MAX_ITERATIONS,
):
    # Process events and stream to client
    ...

# 4. AgentLoop reports completion back to GoalEngine
if goal_result.status == "completed":
    await self._goal_engine.complete_goal(goal.id)
else:
    await self._goal_engine.fail_goal(goal.id, error=...)
```

---

## Key Integration Components

### 1. GoalEngine (Layer 3)

**Location**: `/packages/soothe/src/soothe/core/goal_engine/engine.py`

**Responsibilities**:
- Goal lifecycle management (create, activate, complete, fail, suspend, block)
- DAG-aware scheduling with dependency resolution
- Priority-based goal selection
- Consensus validation with send-back budget
- Relationship management (depends_on, informs, conflicts_with)

**Key Methods**:
```python
class GoalEngine:
    async def create_goal(description, priority=50, parent_id=None, ...) -> Goal
    async def ready_goals(limit=1) -> list[Goal]  # DAG-aware scheduling
    async def complete_goal(goal_id) -> Goal
    async def fail_goal(goal_id, error) -> Goal
    async def validate_goal(goal_id) -> Goal  # RFC-204: Layer 3 acceptance
    async def suspend_goal(goal_id, reason) -> Goal  # Send-back budget exhausted
    async def block_goal(goal_id, reason) -> Goal   # External input needed
    def is_complete() -> bool  # All goals resolved
```

**Goal States** (RFC-204):
```
pending → active → validated → completed
   ↓         ↓         ↓
suspended ←──┘    failed
blocked   ←──┘
```

### 2. AgentLoop (Layer 2)

**Location**: `/packages/soothe/src/soothe/core/loop/engine/agent_loop.py`

**Responsibilities**:
- Single-goal execution via Plan → Execute loop
- LangGraph-based orchestration (RFC-220)
- Checkpoint-based persistence
- Progress streaming to caller

**Key Methods**:
```python
class AgentLoop:
    async def run(goal, thread_id, max_iterations=8) -> PlanResult
    async def run_with_progress(goal, thread_id, ...) -> AsyncGenerator[tuple[str, Any], None]
    # Yields: ("plan", {...}), ("iteration_started", {...}), ("completed", {"result": PlanResult})
```

**PlanResult** (returned to GoalEngine):
```python
class PlanResult:
    status: str  # "done", "replan", "continue", "stop"
    evidence_summary: str
    goal_progress: str  # "none", "partial", "substantial", "complete"
    full_output: str
    decision: AgentDecision
```

### 3. AutonomousMixin (Integration Layer)

**Location**: `/packages/soothe/src/soothe/core/runner/_runner_autonomous.py`

**Responsibilities**:
- Orchestrates GoalEngine → AgentLoop delegation
- Handles parallel goal execution
- Manages intent classification and thread continuation
- Implements dreaming mode transition

**Key Methods**:
```python
class AutonomousMixin:
    async def initialize_autopilot(soothe_home: Path) -> None
    async def _run_autonomous(user_input, ...) -> AsyncGenerator[StreamChunk]
    async def _execute_autonomous_goal(goal, ...) -> AsyncGenerator[StreamChunk]
```

---

## Integration Contracts

### Contract 1: Goal Pull Integration

| Trigger | AgentLoop Action | GoalEngine Response |
|---------|------------------|---------------------|
| Goal assignment | `ready_goals(limit)` | Return highest-priority DAG-satisfied goal(s) |
| Goal completion | AgentLoop yields `"completed"` event | `complete_goal(goal_id)` updates status |
| Goal failure | AgentLoop yields failed result | `fail_goal(goal_id, evidence)` applies backoff |
| Send-back | AgentLoop yields `"replan"` status | GoalEngine tracks send-back budget |

### Contract 2: Context Envelope

Layer 3 provides rich context to Layer 2 through:

| Category | Delivery Method | Contents |
|----------|-----------------|----------|
| Core context | System prompt | Goal description, constraints, priority |
| World info | System prompt | Current state, environment data |
| Related goals | Query tool | `get_related_goals()`, `get_goal_progress()` |
| Memory | Query tool | `search_memory(query)` |
| Instructions | System prompt | High-level guidance, success criteria |

### Contract 3: Bidirectional Communication

Layer 2 can query and propose updates through tools:

**Query Operations** (read-only):
- `get_related_goals()` — Goals that might inform current work
- `get_goal_progress(goal_id)` — Status of another goal
- `get_world_info()` — Current world state snapshot
- `search_memory(query)` — Cross-thread memory lookup

**Proposal Operations** (queued, applied after iteration):
- `report_progress(status, findings)` — Update current goal progress
- `add_finding(content, tags)` — Contribute to context ledger
- `suggest_goal(description, priority)` — Propose new goal
- `flag_blocker(reason, dependencies)` — Signal goal is blocked

---

## Execution Flow

### Autopilot Mode Execution Flow

```
1. Initialization
   └─ initialize_autopilot(SOOTHE_HOME)
      └─ discover_goals(autopilot_dir)  # From GOAL.md files
      └─ Create goals in GoalEngine

2. Intent Classification (IG-226)
   └─ Classify user input intent
      ├─ "new_goal" → Create new goal
      ├─ "continue_thread" → Reuse active goal
      └─ "quiz" → Fast path (skip goal engine)

3. Goal Creation
   └─ Create goal via GoalEngine.create_goal()
   └─ Goal enters "pending" state

4. Autonomous Loop (_run_autonomous)
   while not goal_engine.is_complete() and iterations < max:
      ├─ Get ready goals: ready_goals(limit=max_parallel)
      ├─ For each ready goal:
      │   └─ _execute_autonomous_goal(goal)
      │      └─ Create AgentLoop instance
      │      └─ agent_loop.run_with_progress(goal.description)
      │         └─ LangGraph Loop Graph execution (RFC-220)
      │            ├─ Plan phase (assess + generate)
      │            ├─ Execute phase (CoreAgent delegation)
      │            └─ Return PlanResult
      │      └─ Process PlanResult
      │         ├─ If completed: goal_engine.complete_goal()
      │         ├─ If failed: goal_engine.fail_goal()
      │         └─ Store memory, emit events
      └─ Increment iteration count

5. Completion / Dreaming
   └─ If all goals complete:
      └─ _check_scheduled_and_dream()
         ├─ Check for scheduled tasks
         └─ Enter dreaming mode (if enabled)
```

### Single Goal Execution Flow

```
_execute_autonomous_goal(goal):
  ├─ Create AgentLoop(core_agent, loop_planner, config)
  ├─ agent_loop.run_with_progress(
  │     goal=goal.description,
  │     thread_id=f"{base_tid}__goal_{goal.id}",
  │     max_iterations=8
  │  )
  │  └─ LangGraph Loop Graph (RFC-220):
  │     ├─ init_or_resume: Load checkpoint
  │     ├─ iteration_gate: Check max iterations
  │     ├─ plan_assess: Assess current state
  │     ├─ plan_generate: Generate plan
  │     ├─ execute_steps: Execute via CoreAgent
  │     ├─ record_iteration: Save state
  │     └─ goal_completion: Determine completion
  ├─ Process events:
  │  ├─ "plan" → Emit PlanCreatedEvent
  │  ├─ "iteration_started" → Propagate iteration events
  │  └─ "completed" → Extract PlanResult
  ├─ Update goal status via GoalEngine
  ├─ Store memory
  └─ Emit reflection events
```

---

## Implementation Status

### Completed Components

| Component | Status | Location |
|-----------|--------|----------|
| GoalEngine core | ✅ | `core/goal_engine/engine.py` |
| AgentLoop LangGraph | ✅ | `core/loop/orchestrator/` |
| AutonomousMixin | ✅ | `core/runner/_runner_autonomous.py` |
| Intent classification | ✅ | `core/intention/` |
| Goal discovery | ✅ | `core/goal_engine/discovery.py` |
| Proposal queue | ✅ | `core/goal_engine/proposal_queue.py` |
| Consensus / send-back | ✅ | `core/goal_engine/consensus.py` |
| Dreaming mode | ✅ | `core/goal_engine/dreaming.py` |

### In-Progress Components

| Component | Status | Notes |
|-----------|--------|-------|
| LangGraph Agent Loop | 🔄 | IG-394: Optional bounded gather / repair loops remain |
| Evidence-bound steps | 🔄 | `evidence_refs` in StepAction |
| Validation node | 🔄 | Bounded repair loops |

---

## Key Files and Modules

### GoalEngine

```
packages/soothe/src/soothe/core/goal_engine/
├── __init__.py
├── engine.py              # GoalEngine class - main orchestrator
├── models.py              # Goal, GoalStatus dataclasses
├── discovery.py           # GOAL.md file discovery
├── proposal_queue.py      # Layer 2 → Layer 3 proposals
├── consensus.py           # Send-back validation
├── backoff_reasoner.py    # LLM-driven backoff decisions
├── dreaming.py            # Dreaming mode implementation
├── scheduled_tasks.py     # Time-based task scheduling
└── relationship_detector.py # Auto-detect goal relationships
```

### AgentLoop

```
packages/soothe/src/soothe/core/loop/
├── __init__.py
├── engine/
│   ├── agent_loop.py       # AgentLoop facade
│   └── goal_context_manager.py  # Goal-level context injection
├── orchestrator/
│   ├── builder.py          # LoopGraphBuilder (RFC-220)
│   ├── runner.py           # invoke_agent_loop_graph
│   ├── routing.py          # Graph edge routing
│   ├── state.py            # LoopState TypedDict
│   └── nodes/              # LangGraph nodes
│       ├── init_or_resume.py
│       ├── iteration_gate.py
│       ├── plan_assess.py
│       ├── plan_generate.py
│       ├── execute_steps.py
│       ├── goal_completion.py
│       └── ...
├── planning/
│   ├── manager.py          # PlanManager
│   └── phase.py            # PlanPhase (assess + generate)
└── state/
    ├── manager.py          # AgentLoopStateManager
└── schemas.py            # LoopState, PlanResult
```

### Runner Integration

```
packages/soothe/src/soothe/core/runner/
├── _runner_autonomous.py   # AutonomousMixin - integration layer
├── _runner_agentic.py      # Agentic execution (non-autonomous)
├── local_runner.py         # Subprocess-isolated runner (RFC-221)
└── ...
```

---

## Configuration

### Autopilot Configuration

```yaml
# config/config.template.yml
autopilot:
  enabled: true
  max_parallel_goals: 3
  max_iterations: 50
  dreaming:
    enabled: true
    memory_consolidation: true
    health_monitoring: true
  consensus:
    max_send_backs: 3
    enabled: true
```

### Goal File Format (GOAL.md)

```markdown
---
id: goal-unique-id
priority: 80
depends_on: [other-goal-id]
informs: [related-goal-id]
conflicts_with: [conflicting-goal-id]
---

# Goal Description

Detailed description of what needs to be accomplished.

## Success Criteria

- Criterion 1
- Criterion 2

## Progress

Current status and findings.
```

---

## Testing

### Unit Tests

```bash
# GoalEngine tests
pytest packages/soothe/tests/unit/core/goal_engine/ -v

# AgentLoop tests
pytest packages/soothe/tests/unit/core/loop/ -v

# Runner integration tests
pytest packages/soothe/tests/unit/core/runner/ -v
```

### Integration Tests

```bash
# Full autopilot integration
pytest packages/soothe/tests/integration/autopilot/ -v
```

---

## References

### RFCs

- [RFC-200](../specs/RFC-200-autonomous-goal-management.md) - Autonomous Goal Management
- [RFC-201](../specs/RFC-201-agentloop-plan-execute-loop.md) - AgentLoop Plan-Execute
- [RFC-204](../specs/RFC-204-autopilot-mode.md) - Autopilot Mode
- [RFC-220](../specs/RFC-220-langgraph-agent-loop-orchestrator.md) - LangGraph Agent Loop

### Implementation Guides

- [IG-394](IG-394-langgraph-agent-loop-orchestrator.md) - LangGraph Agent Loop Orchestrator
- [IG-396](IG-396-rfc-220-loop-graph-topology-langfuse.md) - RFC-220 Loop Graph Topology

---

## Summary

The GoalEngine-AgentLoop integration creates a powerful autonomous execution system:

1. **GoalEngine** (Layer 3) provides DAG-based goal orchestration with dependency management, priority scheduling, and consensus validation.

2. **AgentLoop** (Layer 2) provides single-goal execution through iterative Plan → Execute loops using LangGraph orchestration.

3. **AutonomousMixin** (Integration Layer) connects the two through a pull-based architecture where AgentLoop queries GoalEngine for goals and reports results back.

4. **Autopilot Mode** enables continuous operation with dreaming mode, scheduled tasks, and bidirectional Layer 2 ↔ Layer 3 communication.

The integration is **already implemented** and operational in the Soothe codebase. Remaining work (IG-394) focuses on optional bounded evidence gather and repair loops within the LangGraph orchestration.
