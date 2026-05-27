# Thread Inheritance with LangGraph Checkpoint Forking

**Draft**: 2026-05-27
**Status**: Draft
**Scope**: Execute phase thread management in AgentLoop (Layer 2)

---

## Problem Statement

Current thread management in the Execute phase creates isolated branch threads for each step:

```python
stream_thread_id = f"{logical_tid}__p{step_id}"  # Parallel isolation, no inheritance
```

Each step starts with an empty checkpoint namespace. Predecessor context is injected via message copying (`predecessor_execute_messages_for_branch`), which:
- Deep-copies messages (memory overhead)
- Only includes `execute_step` phase messages (filtered)
- Does not preserve full checkpoint state (artifacts, intermediate state)

**Goals**:
1. **ID alignment**: Main thread ID equals loop_id (`thread_id = loop_id`)
2. **Checkpoint inheritance**: Steps inherit full predecessor history via LangGraph fork
3. **DAG handling**: Hybrid strategy for singleton vs multi-dependency steps

---

## Design Overview

### Thread Naming Scheme

| Thread Type | Pattern | Example |
|-------------|---------|---------|
| Main thread | `{loop_id}` | `"abc123"` |
| Step thread | `{loop_id}__step_{step_id}` | `"abc123__step_GHT-01"` |

The `__step_` prefix distinguishes sequential fork threads from the existing `__p` (parallel isolation) pattern.

### Fork Strategy (Hybrid)

| Dependency Count | Fork Source | Context Mechanism |
|------------------|-------------|-------------------|
| 0 (first step) | Main thread | Empty history |
| 1 (singleton) | Predecessor's step thread | Checkpoint inheritance (full history) |
| >1 (multi-dep) | Main thread | Message injection from all predecessors |

**Why hybrid**: LangGraph checkpoint forking can only copy from one source thread. Multi-dependency steps need context from multiple predecessors, which cannot be merged via checkpoint. The existing message injection mechanism handles multi-dep cases.

---

## Architecture

### Position in Existing Flow

```
Executor.execute()
  → _execute_parallel(steps, state)
     → _execute_step_collecting_events(step, ...)
        → ThreadForkManager.prepare_thread_for_step(step, decision, state)
           → select_fork_source(step, decision, state) → source_thread_id
           → fork_checkpoint(source, target, checkpointer) → forked_thread_id
        → CoreAgent.astream() with forked_thread_id as configurable.thread_id
        → (multi-dep only) predecessor_execute_messages_for_branch(...)
```

### Component Interaction

```
┌─────────────────────────────────────────────────────────────────────┐
│  Executor                                                           │
│  • Orchestrates step execution                                      │
│  • Calls ThreadForkManager before each step                         │
│  • Uses forked_thread_id for CoreAgent stream                       │
│  • Injects messages for multi-dep steps                             │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  ThreadForkManager (NEW)                                            │
│  • select_fork_source(): determines source thread based on deps     │
│  • fork_checkpoint(): calls checkpointer.acopy_thread()             │
│  • track_fork_lineage(): updates LoopState mappings                 │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  LoopState (MODIFIED)                                               │
│  • step_thread_ids: dict[str, str] - step_id → thread_id            │
│  • thread_fork_sources: dict[str, str] - thread_id → source         │
└─────────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────────┐
│  LangGraph Checkpointer                                             │
│  • acopy_thread(source, target) - checkpoint copy API               │
│  • Stores full conversation history, artifacts, state               │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. ThreadForkManager (NEW)

**Location**: `packages/soothe/src/soothe/core/loop/engine/thread_fork_manager.py`

**Responsibilities**:
- Determine fork source based on step dependencies
- Execute checkpoint fork via LangGraph `acopy_thread()`
- Track step-to-thread and fork lineage mappings
- Handle edge cases (missing checkpoint, fork failure)

**Interface**:

```python
class ThreadForkManager:
    """Manages thread checkpoint forking for step inheritance."""

    def __init__(self, checkpointer: BaseCheckpointSaver) -> None:
        self._checkpointer = checkpointer

    def select_fork_source(
        self,
        step: StepAction,
        decision: AgentDecision,
        state: LoopState,
    ) -> str:
        """Select source thread_id for checkpoint fork.

        Args:
            step: Current step to execute.
            decision: Current decision with dependency information.
            state: Loop state with step_thread_ids mapping.

        Returns:
            Source thread_id to fork from.

        Rules:
            - First step (no deps): returns main thread (loop_id)
            - Singleton dep: returns predecessor's step thread
            - Multi-deps: returns main thread (fallback)
        """
        ...

    async def fork_checkpoint(
        self,
        source_thread_id: str,
        target_thread_id: str,
    ) -> str:
        """Execute checkpoint fork from source to target thread.

        Args:
            source_thread_id: Thread to copy checkpoint from.
            target_thread_id: Thread to copy checkpoint to.

        Returns:
            target_thread_id if successful, source_thread_id as fallback.

        Behavior:
            - Calls checkpointer.acopy_thread(source, target)
            - On failure: logs warning, returns source (proceed without fork)
        """
        ...

    async def prepare_thread_for_step(
        self,
        step: StepAction,
        decision: AgentDecision,
        state: LoopState,
        main_thread_id: str,
    ) -> str:
        """Prepare thread for step execution (full preparation flow).

        Args:
            step: Step to execute.
            decision: Decision with dependency info.
            state: Loop state to update with mappings.
            main_thread_id: The loop's main thread_id.

        Returns:
            Thread_id to use for CoreAgent stream.

        Updates:
            - state.step_thread_ids[step.id] = thread_id
            - state.thread_fork_sources[thread_id] = source
        """
        ...
```

**Implementation Details**:

```python
def select_fork_source(
    self,
    step: StepAction,
    decision: AgentDecision,
    state: LoopState,
) -> str:
    # Use DIRECT dependencies only (not transitive closure)
    # For chain A→B→C: C depends on B only → singleton, fork from B
    # For DAG A→C, B→C: C depends on [A, B] → multi-dep, fork from main
    direct_deps = step.dependencies or []

    # No direct dependencies → first step, fork from main
    if not direct_deps:
        return state.thread_id  # main thread = loop_id

    # Multiple direct dependencies → fork from main, use message injection
    if len(direct_deps) > 1:
        return state.thread_id  # main thread

    # Singleton direct dependency → fork from predecessor's thread
    pred_step_id = direct_deps[0]
    pred_thread_id = state.step_thread_ids.get(pred_step_id)

    # Predecessor thread not tracked → fallback to main
    if not pred_thread_id:
        return state.thread_id

    return pred_thread_id


async def fork_checkpoint(
    self,
    source_thread_id: str,
    target_thread_id: str,
) -> str:
    try:
        await self._checkpointer.acopy_thread(source_thread_id, target_thread_id)
        logger.info(
            "Checkpoint forked: %s → %s",
            source_thread_id,
            target_thread_id,
        )
        return target_thread_id
    except Exception:
        logger.warning(
            "Checkpoint fork failed: %s → %s, proceeding without inheritance",
            source_thread_id,
            target_thread_id,
            exc_info=True,
        )
        # Return source as fallback - step will run in source thread
        return source_thread_id
```

### 2. LoopState Extension (MODIFY)

**Location**: `packages/soothe/src/soothe/core/loop/state/schemas.py`

**Add fields**:

```python
class LoopState(BaseModel):
    # Existing fields...

    # NEW: Thread fork tracking
    step_thread_ids: dict[str, str] = Field(
        default_factory=dict,
        description="Maps step_id → thread_id used for execution",
    )
    thread_fork_sources: dict[str, str] = Field(
        default_factory=dict,
        description="Maps thread_id → source thread_id for fork lineage",
    )
```

**Why**:
- `step_thread_ids`: Executor needs to look up predecessor thread for singleton fork
- `thread_fork_sources`: Debugging/replay needs fork lineage visibility

### 3. Executor Modification (MODIFY)

**Location**: `packages/soothe/src/soothe/core/loop/engine/executor.py`

**Changes in `_execute_step_collecting_events()`**:

```python
async def _execute_step_collecting_events(
    self,
    step: StepAction,
    thread_id: str,  # logical thread_id (loop_id)
    ...
) -> tuple[...]:
    # NEW: Prepare fork thread via ThreadForkManager
    fork_manager = ThreadForkManager(self._checkpointer)
    stream_thread_id = await fork_manager.prepare_thread_for_step(
        step=step,
        decision=loop_state.current_decision,
        state=loop_state,
        main_thread_id=thread_id,
    )

    # Determine if multi-dep (needs message injection)
    # Use direct dependencies only, not transitive closure
    direct_deps = step.dependencies or []
    needs_message_injection = len(direct_deps) > 1

    # Build graph input messages
    graph_input_messages: list[BaseMessage] = []

    # Multi-dep: inject predecessor messages (existing logic)
    # Note: Message injection uses TRANSITIVE deps to get all ancestors' context
    # while fork source uses DIRECT deps for the fork decision
    if needs_message_injection and loop_state.current_decision:
        transitive_preds = transitive_dependency_step_ids(step, loop_state.current_decision)
        if transitive_preds:
            cap = self._branch_predecessor_message_cap()
            graph_input_messages = predecessor_execute_messages_for_branch(
                loop_state.loop_messages,
                transitive_preds,
                max_messages=cap,
            )

    # Build HumanMessage envelope and append
    envelope = build_execute_step_envelope(...)
    human_msg = LoopHumanMessage(...)
    graph_input_messages.append(human_msg)

    # Use forked thread_id for CoreAgent config
    configurable: dict[str, Any] = {
        "thread_id": stream_thread_id,  # forked thread, not logical
        ...
    }
    config: dict[str, Any] = {"configurable": configurable}

    # Stream with prepared thread
    stream = self._core_agent_astream_with_interrupt_resume(
        self._execute_graph_input(graph_input_messages, ...),
        config,
    )
    ...
```

**Key changes**:
1. Create `ThreadForkManager` with checkpointer reference
2. Call `prepare_thread_for_step()` to get forked thread_id
3. Use forked thread_id in `configurable["thread_id"]`
4. Keep message injection for multi-dep steps (unchanged)

### 4. Checkpointer Access (MODIFY)

Executor currently doesn't have direct checkpointer access. Need to:

**Option**: Pass checkpointer to Executor constructor

```python
class Executor:
    def __init__(
        self,
        core_agent: CoreAgent,
        *,
        checkpointer: BaseCheckpointSaver | None = None,  # NEW
        max_parallel_steps: int = 16,
        config: SootheConfig | None = None,
        ...
    ) -> None:
        self._checkpointer = checkpointer
        ...
```

**In AgentLoop (executor instantiation)**:

```python
# AgentLoop creates Executor with checkpointer
self._executor = Executor(
    self.core_agent,
    checkpointer=self._checkpointer,  # pass from AgentLoop
    max_parallel_steps=...,
    config=...,
)
```

---

## Data Flow Examples

### Example 1: Singleton Dependency Chain

**DAG**: A → B → C (each depends on previous)

```
Step A (no deps):
  select_fork_source(A) → "abc123" (main thread)
  fork_checkpoint("abc123", "abc123__step_A") → creates empty fork
  state.step_thread_ids["A"] = "abc123__step_A"
  CoreAgent runs with thread "abc123__step_A"
  Checkpoint saved with A's tool calls

Step B (depends on A):
  select_fork_source(B) → "abc123__step_A" (predecessor's thread)
  fork_checkpoint("abc123__step_A", "abc123__step_B")
    → copies A's checkpoint to B's thread
    → B's thread now has A's full history
  state.step_thread_ids["B"] = "abc123__step_B"
  CoreAgent runs with thread "abc123__step_B"
    → Inherits A's messages from checkpoint
    → Accumulates B's tool calls on top
  Checkpoint saved with A + B's tool calls

Step C (depends on B):
  select_fork_source(C) → "abc123__step_B" (predecessor's thread)
  fork_checkpoint("abc123__step_B", "abc123__step_C")
    → copies B's checkpoint (includes A + B history)
  CoreAgent runs with thread "abc123__step_C"
    → Inherits A + B's messages from checkpoint
    → Accumulates C's tool calls
```

### Example 2: Multi-Dependency

**DAG**: A → C, B → C (C depends on A and B, A and B run parallel)

```
Step A (no deps):
  fork from "abc123" → "abc123__step_A"
  isolated execution

Step B (no deps):
  fork from "abc123" → "abc123__step_B"
  isolated execution (parallel with A)

Step C (depends on A + B):
  select_fork_source(C) → "abc123" (main thread, multi-dep fallback)
  fork_checkpoint("abc123", "abc123__step_C") → empty history
  predecessor_execute_messages_for_branch([A, B])
    → injects A and B's execute_step messages
  CoreAgent runs with thread "abc123__step_C"
    → No checkpoint inheritance
    → Context via injected messages only
```

### Example 3: Mixed DAG

**DAG**: A → B → D, A → C → D (D depends on B and C)

```
Step A: fork from main → "abc123__step_A"

Step B (depends on A only):
  fork from "abc123__step_A" → "abc123__step_B"
  inherits A's checkpoint

Step C (depends on A only):
  fork from "abc123__step_A" → "abc123__step_C"
  inherits A's checkpoint (parallel with B, same source)

Step D (depends on B + C):
  select_fork_source(D) → "abc123" (multi-dep)
  fork_checkpoint("abc123", "abc123__step_D") → empty
  predecessor_execute_messages_for_branch([B, C])
    → injects B and C's messages
```

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Source thread has no checkpoint | `acopy_thread` creates empty target thread; proceed |
| `acopy_thread` fails | Log warning, use source thread directly (fallback) |
| Predecessor thread_id not in `step_thread_ids` | Fallback to main thread |
| Checkpointer not available | Skip forking entirely, use main thread |
| Parallel steps with same singleton predecessor | Both fork from same source (valid, isolated writes) |

---

## Configuration

No new configuration required. Fork behavior is deterministic based on DAG structure.

Optional future configuration:
```yaml
agent:
  loop:
    thread_fork:
      enabled: true  # disable to revert to current behavior
      max_fork_depth: 10  # prevent deep fork chains
```

---

## Testing Strategy

### Unit Tests (ThreadForkManager)

```python
# test_thread_fork_manager.py

def test_select_fork_source_no_deps_returns_main():
    """First step (no deps) forks from main thread."""
    manager = ThreadForkManager(mock_checkpointer)
    step = StepAction(id="A", dependencies=[])
    decision = AgentDecision(steps=[step])
    state = LoopState(thread_id="loop1")

    source = manager.select_fork_source(step, decision, state)
    assert source == "loop1"


def test_select_fork_source_singleton_returns_predecessor():
    """Singleton DIRECT dep forks from predecessor's thread."""
    manager = ThreadForkManager(mock_checkpointer)
    step_b = StepAction(id="B", dependencies=["A"])  # B directly depends on A only
    step_a = StepAction(id="A", dependencies=[])
    decision = AgentDecision(steps=[step_a, step_b])
    state = LoopState(
        thread_id="loop1",
        step_thread_ids={"A": "loop1__step_A"},
    )

    source = manager.select_fork_source(step_b, decision, state)
    assert source == "loop1__step_A"


def test_select_fork_source_chain_singleton_inherits():
    """Chain A→B→C: C depends on B only (singleton), fork from B's thread."""
    manager = ThreadForkManager(mock_checkpointer)
    step_a = StepAction(id="A", dependencies=[])
    step_b = StepAction(id="B", dependencies=["A"])
    step_c = StepAction(id="C", dependencies=["B"])  # Direct dep on B only
    decision = AgentDecision(steps=[step_a, step_b, step_c])
    state = LoopState(
        thread_id="loop1",
        step_thread_ids={"A": "loop1__step_A", "B": "loop1__step_B"},
    )

    source = manager.select_fork_source(step_c, decision, state)
    assert source == "loop1__step_B"  # Fork from B, inherits A+B history


def test_select_fork_source_multi_dep_returns_main():
    """Multiple DIRECT deps falls back to main thread."""
    manager = ThreadForkManager(mock_checkpointer)
    step_c = StepAction(id="C", dependencies=["A", "B"])  # C depends on A AND B
    decision = AgentDecision(steps=[
        StepAction(id="A", dependencies=[]),
        StepAction(id="B", dependencies=[]),
        step_c,
    ])
    state = LoopState(
        thread_id="loop1",
        step_thread_ids={"A": "loop1__step_A", "B": "loop1__step_B"},
    )

    source = manager.select_fork_source(step_c, decision, state)
    assert source == "loop1"  # Multi-dep → main thread


async def test_fork_checkpoint_calls_acopy_thread():
    """Verify checkpointer.acopy_thread is called."""
    mock_checkpointer = AsyncMock()
    mock_checkpointer.acopy_thread = AsyncMock()
    manager = ThreadForkManager(mock_checkpointer)

    result = await manager.fork_checkpoint("source1", "target1")

    mock_checkpointer.acopy_thread.assert_called_once_with("source1", "target1")
    assert result == "target1"


async def test_fork_checkpoint_failure_returns_source():
    """On failure, return source as fallback."""
    mock_checkpointer = AsyncMock()
    mock_checkpointer.acopy_thread = AsyncMock(side_effect=Exception("DB error"))
    manager = ThreadForkManager(mock_checkpointer)

    result = await manager.fork_checkpoint("source1", "target1")

    assert result == "source1"  # fallback
```

### Integration Tests

```python
# test_executor_fork_integration.py

async def test_singleton_chain_inherits_checkpoint():
    """A → B chain: B's checkpoint contains A's messages."""
    # Setup: Create goal with steps A, B (B depends on A)
    # Run execution
    # Verify: B's thread checkpoint has A's tool calls in history

async def test_multi_dep_injects_messages():
    """C depends on A + B: verify message injection."""
    # Setup: Create goal with A, B parallel, C depends on both
    # Run execution
    # Verify: C's graph_input_messages contains A and B's execute_step messages

async def test_parallel_singleton_same_source():
    """B and C both depend on A: both fork from A."""
    # Setup: A → B, A → C (parallel)
    # Run execution
    # Verify: Both B and C fork from "loop__step_A"
    # Verify: B and C have isolated writes (no cross-contamination)
```

---

## Migration Path

### Phase 1: Add ThreadForkManager
- Create `thread_fork_manager.py` with full implementation
- Add `step_thread_ids` and `thread_fork_sources` to LoopState
- Unit tests for ThreadForkManager

### Phase 2: Modify Executor
- Add checkpointer parameter to Executor constructor
- Call ThreadForkManager in `_execute_step_collecting_events`
- Thread naming change: `__p{step_id}` → `__step_{step_id}`
- Integration tests

### Phase 3: Thread ID Alignment
- Ensure main thread_id equals loop_id throughout AgentLoop
- Update any code that derives thread_id differently
- Verify existing tests pass

### Phase 4: Cleanup
- Remove or deprecate `predecessor_branch_context.py` logic for singleton case
- Keep for multi-dep case
- Update documentation

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Checkpoint storage bloat (many forked threads) | Fork cleanup after goal completion; limit fork depth |
| Race condition in parallel fork | `acopy_thread` is atomic; each target thread isolated |
| Existing tests fail due to thread_id change | Thread naming is internal; tests should use mocks or verify behavior not IDs |
| Backward compatibility with solo mode | ThreadForkManager only active in AgentLoop; solo mode unchanged |

---

## References

- RFC-222: Autopilot and Goal Engine Architecture (loop_id, loop pool)
- RFC-214: Unified message ledger (predecessor_execute_messages_for_branch)
- LangGraph Checkpointer API: `acopy_thread(source_thread_id, target_thread_id)`
- executor.py: `_execute_step_collecting_events()` - current thread branching logic
- predecessor_branch_context.py: Current message injection implementation

---

## Resolved Design Decisions

1. **Fork cleanup**: Forked threads are **kept** after goal completes for replay/debugging. Future: optional cleanup via configuration when storage becomes concern.

2. **Fork depth limit**: No explicit limit in initial implementation. Practical depth rarely exceeds 5-7 steps. If needed, add configurable `max_fork_depth` later.

3. **Singleton backup injection**: **No backup injection** for singleton deps. Rely purely on checkpoint inheritance. If checkpoint fork fails, fallback to source thread (which already has the history). This keeps the design clean and avoids duplicate context.

---

## Summary

This design introduces LangGraph checkpoint forking to enable true thread inheritance between steps with singleton dependencies. A hybrid strategy handles DAG complexity: singleton deps fork from predecessor, multi-deps fork from main thread and use message injection. The main thread ID aligns with loop_id for clean ID mapping. A new `ThreadForkManager` component encapsulates fork logic, keeping Executor focused on execution.

---

*Draft for review before RFC formalization.*