# Goal Engine and AgentLoop Integration Analysis

## Executive Summary

This document analyzes the integration points between the **Goal Engine** (Layer 3 - autonomous goal management) and **AgentLoop** (Layer 2 - plan-and-execute orchestration) in the Soothe architecture. The integration follows a layered design where GoalEngine manages goal lifecycles and DAG scheduling, while AgentLoop handles iterative plan execution.

---

## 1. Architectural Overview

### 1.1 Component Responsibilities

| Component | Layer | Primary Responsibility |
|-----------|-------|----------------------|
| `GoalEngine` | Layer 3 | Goal lifecycle management, DAG scheduling, consensus validation |
| `AgentLoop` | Layer 2 | Plan-and-execute iteration, step orchestration, checkpoint management |
| `CoreAgent` | Layer 1 | Tool execution, LLM interaction, message streaming |
| `SootheRunner` | Orchestrator | Mode selection, component wiring, event streaming |

### 1.2 RFC References

- **RFC-0007**: Autonomous iteration with goal-driven execution
- **RFC-0008**: Agentic loop (Plan → Execute)
- **RFC-200**: Goal backoff reasoning and Layer 2/3 integration
- **RFC-201**: AgentLoop plan-and-execute pattern
- **RFC-204**: Goal consensus and lifecycle extensions
- **RFC-220**: Compiled loop graph (LangGraph)

---

## 2. Integration Points

### 2.1 Direct Integration via SootheRunner

**File**: `/packages/soothe/src/soothe/core/runner/__init__.py`

```python
# Line 160 - GoalEngine resolution
self._goal_engine: GoalEngine | None = resolve_goal_engine(self._config)
```

The `SootheRunner` initializes both components:
- `AgentLoop` is instantiated per execution in `_run_agentic_loop()`
- `GoalEngine` is initialized once at runner construction via `resolve_goal_engine()`

### 2.2 AgentLoop Instantiation

**File**: `/packages/soothe/src/soothe/core/runner/_runner_agentic.py` (Lines 325-329)

```python
loop_agent = AgentLoop(
    core_agent=self._agent,
    loop_planner=self._planner,
    config=self._config,
)
```

**Dependencies Injected:**
- `core_agent`: Layer 1 CoreAgent for step execution
- `loop_planner`: Implements `LoopPlannerProtocol` for plan generation
- `config`: SootheConfig for behavior tuning

### 2.3 GoalEngine Instantiation

**File**: `/packages/soothe/src/soothe/core/resolver/_resolver_tools.py` (Lines 523-538)

```python
def resolve_goal_engine(config: SootheConfig) -> GoalEngine:
    return GoalEngine(
        max_retries=config.autonomous.max_retries,
        config=config,  # Enable LLM-driven backoff reasoning (RFC-200)
    )
```

---

## 3. Data Flow and Contracts

### 3.1 Execution Modes

The runner selects execution mode based on configuration:

1. **Agentic Mode** (`_run_agentic_loop`): Uses AgentLoop directly, minimal GoalEngine interaction
2. **Autonomous Mode** (`_run_autonomous`): Full GoalEngine integration with DAG scheduling

### 3.2 Data Contracts

#### GoalEngine → AgentLoop (via Runner)

| Data | Type | Flow | Purpose |
|------|------|------|---------|
| `goal.description` | `str` | `create_goal()` → `AgentLoop.run()` | Execution target |
| `goal.id` | `str` | `create_goal()` → `thread_id` | Correlation identifier |
| `goal.priority` | `int` | DAG scheduling | Execution ordering |
| `goal.depends_on` | `list[str]` | `ready_goals()` | Dependency resolution |

#### AgentLoop → GoalEngine (via Evidence)

**File**: `/packages/soothe/src/soothe/core/goal_engine/models.py` (Lines 70-95)

```python
class EvidenceBundle(BaseModel):
    """RFC-200 §14-22: Canonical evidence payload for Layer 2 → Layer 3"""
    structured: dict[str, Any]      # Machine-readable metrics
    narrative: str                  # Natural language synthesis
    source: Literal["layer2_execute", "layer2_plan", "layer3_reflect"]
    timestamp: datetime
```

### 3.3 State Flow Diagram

```
┌─────────────┐     create_goal()      ┌─────────────┐
│   User      │ ─────────────────────→ │ GoalEngine  │
│  Request    │                        │  (Layer 3)  │
└─────────────┘                        └──────┬──────┘
                                             │
                    ready_goals()            │
                                             ▼
┌─────────────┐     run_with_progress()     ┌─────────────┐
│   Goal      │ ←─────────────────────────→ │  AgentLoop  │
│   Report    │   (goal, thread_id)        │  (Layer 2)  │
└─────────────┘                             └──────┬──────┘
                                                   │
                          ┌────────────────────────┼────────────────────────┐
                          │                        │                        │
                          ▼                        ▼                        ▼
                   ┌─────────────┐        ┌─────────────┐          ┌─────────────┐
                   │  Plan Phase │        │ Execute     │          │ Checkpoint  │
                   │  (Planner)  │        │ (CoreAgent) │          │  Manager    │
                   └─────────────┘        └─────────────┘          └─────────────┘
```

---

## 4. Shared Interfaces

### 4.1 Protocols

#### LoopPlannerProtocol

**File**: `/packages/soothe/src/soothe/protocols/loop_planner.py`

```python
@runtime_checkable
class LoopPlannerProtocol(Protocol):
    async def plan(
        self,
        goal: str,
        state: LoopState,
        context: PlanContext,
        *,
        plan_manager: Any = None,
    ) -> PlanResult: ...
```

**Purpose**: Bridges AgentLoop's plan phase with pluggable planning implementations

#### PlannerProtocol (GoalEngine context)

**File**: `/packages/soothe/src/soothe/protocols/planner.py`

```python
class GoalReport(BaseModel):
    """Aggregate report from completed goal (RFC-0009, RFC-0010)"""
    goal_id: str
    description: str
    status: Literal["completed", "failed", "partial"]
    step_reports: list[StepReport]
```

### 4.2 Runtime Context

**File**: `/packages/soothe/src/soothe/core/loop/orchestrator/runtime_context.py`

```python
@dataclass
class LoopRuntimeContext:
    agent_loop: AgentLoop
    state_manager: AgentLoopStateManager
    anchor_manager: CheckpointAnchorManager
    goal_context_manager: GoalContextManager
    plan_manager: PlanManager
    checkpoint: AgentLoopCheckpoint
    goal_record: GoalExecutionRecord | None
    loop_state: LoopState
    emit: EmitFn
```

---

## 5. Coupling Analysis

### 5.1 Coupling Matrix

| Component A | Component B | Coupling Type | Strength | Notes |
|-------------|-------------|---------------|----------|-------|
| GoalEngine | AgentLoop | Indirect via Runner | Loose | Runner mediates all interactions |
| AgentLoop | CoreAgent | Direct injection | Tight | AgentLoop requires CoreAgent |
| AgentLoop | LoopPlannerProtocol | Protocol-based | Loose | Pluggable planning |
| GoalEngine | DurabilityProtocol | Direct | Medium | Persistence via protocols |
| AgentLoop | AgentLoopStateManager | Direct | Tight | State management internal |

### 5.2 Dependency Direction

```
GoalEngine ←──(creates goals for)── SootheRunner ──(instantiates)──→ AgentLoop
     │                                                              │
     │                                                              │
     └──(receives EvidenceBundle)──────(via fail_goal)─────────────┘
```

### 5.3 Decoupling Mechanisms

1. **Protocol-based Planning**: `LoopPlannerProtocol` allows custom planners
2. **Event-driven Communication**: `emit` function for progress streaming
3. **EvidenceBundle Abstraction**: Structured data exchange between layers
4. **Checkpoint Isolation**: AgentLoop state persistence is self-contained

---

## 6. Event Flow

### 6.1 AgentLoop Events (RFC-0020)

**File**: `/packages/soothe/src/soothe/core/runner/_runner_agentic.py` (Lines 352-500)

| Event Type | Emitter | Consumer | Purpose |
|------------|---------|----------|---------|
| `iteration_started` | AgentLoop | Runner (logging) | Iteration tracking |
| `plan_decision` | AgentLoop | Runner (debug) | Plan debugging |
| `step_started` | AgentLoop | TUI/CLI | Step progress |
| `step_completed` | AgentLoop | TUI/CLI | Step result |
| `stream_event` | CoreAgent | TUI/CLI | Tool streaming |
| `assess` | AgentLoop | TUI/CLI | Assessment reasoning |
| `plan` | AgentLoop | TUI/CLI | Plan reasoning |
| `completed` | AgentLoop | Runner | Final result |

### 6.2 GoalEngine Events

GoalEngine primarily uses logging for observability rather than structured events.

---

## 7. Configuration Integration

### 7.1 Shared Configuration

**File**: `/packages/soothe/src/soothe/config/models.py`

```python
class AgentLoopConfig(BaseModel):
    max_iterations: int = 8
    working_memory: WorkingMemoryConfig
    limits: ConcurrencyLimits
    goal_context: GoalContextConfig

class AutonomousConfig(BaseModel):
    max_retries: int = 2
    max_parallel_goals: int = 3
```

### 7.2 Configuration Flow

```
SootheConfig
    ├── AgentLoopConfig ──→ AgentLoop
    ├── AutonomousConfig ──→ GoalEngine
    └── PersistenceConfig ──→ StateManager + Durability
```

---

## 8. Threading and Concurrency

### 8.1 Thread Isolation

**File**: `/packages/soothe/src/soothe/core/runner/_runner_autonomous.py` (Lines 265-300)

```python
# Parallel goal execution with isolated threads
goal_tid = f"{state.thread_id}__goal_{g.id}"
async with self._concurrency.acquire_goal():
    async for chunk in self._execute_autonomous_goal(...):
        yield chunk
```

### 8.2 Concurrency Controls

| Resource | Controller | Limit |
|----------|-----------|-------|
| Parallel Goals | `ConcurrencyController` | `max_parallel_goals` |
| Parallel Steps | `StepScheduler` | `max_parallel_steps` |
| LLM Calls | `LLMRateLimitMiddleware` | `global_max_llm_calls` |
| Subagents | `ConcurrencyController` | `max_parallel_subagents` |

---

## 9. Checkpoint and State Persistence

### 9.1 AgentLoop State Management

**File**: `/packages/soothe/src/soothe/core/loop/state/manager.py`

```python
class AgentLoopStateManager:
    """RFC-205: Checkpoint management for loop-scoped persistence"""
    
    async def load(self) -> AgentLoopCheckpoint | None: ...
    async def save(self, checkpoint: AgentLoopCheckpoint) -> None: ...
```

### 9.2 GoalEngine Persistence

GoalEngine relies on `DurabilityProtocol` for persistence:

```python
# Goals are in-memory; persistence via DurabilityProtocol
self._goals: dict[str, Goal] = {}  # In-memory store
```

---

## 10. Integration Strengths and Weaknesses

### 10.1 Strengths

1. **Clear Layer Separation**: Layer 2 (execution) vs Layer 3 (management)
2. **Protocol-based Extensibility**: Planners and durability backends
3. **Event-driven Observability**: Rich progress streaming via RFC-0020
4. **Checkpoint Recovery**: AgentLoop supports resume after interruption
5. **Evidence-based Communication**: Structured `EvidenceBundle` for cross-layer data

### 10.2 Weaknesses

1. **Indirect GoalEngine-AgentLoop Coupling**: Both depend on Runner orchestration
2. **Asymmetric Event Models**: AgentLoop emits events; GoalEngine uses logging
3. **State Synchronization**: Goal state in GoalEngine vs loop state in AgentLoop
4. **Limited Back-pressure**: No explicit flow control between components

### 10.3 Recommendations

1. **Unified Event Bus**: Consider shared event bus for both components
2. **Goal State Reconciliation**: Explicit sync points between GoalEngine and AgentLoop
3. **Back-pressure Protocol**: Implement explicit capacity signaling
4. **Evidence Stream**: Make EvidenceBundle streaming for real-time Layer 3 updates

---

## 11. Key Files Reference

| File | Purpose |
|------|---------|
| `/packages/soothe/src/soothe/core/goal_engine/engine.py` | GoalEngine implementation |
| `/packages/soothe/src/soothe/core/goal_engine/models.py` | Goal, EvidenceBundle models |
| `/packages/soothe/src/soothe/core/loop/engine/agent_loop.py` | AgentLoop implementation |
| `/packages/soothe/src/soothe/core/loop/orchestrator/runner.py` | Loop graph invocation |
| `/packages/soothe/src/soothe/core/loop/orchestrator/runtime_context.py` | Runtime context bundle |
| `/packages/soothe/src/soothe/core/runner/__init__.py` | SootheRunner, component wiring |
| `/packages/soothe/src/soothe/core/runner/_runner_agentic.py` | Agentic mode integration |
| `/packages/soothe/src/soothe/core/runner/_runner_autonomous.py` | Autonomous mode integration |
| `/packages/soothe/src/soothe/protocols/loop_planner.py` | LoopPlannerProtocol |
| `/packages/soothe/src/soothe/protocols/planner.py` | PlannerProtocol, GoalReport |

---

## 12. Conclusion

The Goal Engine and AgentLoop integration follows a well-structured layered architecture with clear separation of concerns. GoalEngine manages goal lifecycles and DAG scheduling at Layer 3, while AgentLoop handles iterative plan execution at Layer 2. The integration is primarily orchestrated through `SootheRunner`, which mediates component interactions and manages event streaming.

The coupling is intentionally loose through protocol-based interfaces and event-driven communication, enabling independent evolution of both components. Key integration points include:

1. **Runner-mediated instantiation** with dependency injection
2. **EvidenceBundle** for structured cross-layer communication
3. **RFC-0020 events** for progress observability
4. **Checkpoint persistence** for fault tolerance

The architecture supports both agentic (direct) and autonomous (scheduled) execution modes, with the latter providing full GoalEngine DAG capabilities.
