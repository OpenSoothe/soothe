# RFC-223: Thread Inheritance with LangGraph Checkpoint Forking

**RFC**: 223
**Title**: Thread Inheritance with LangGraph Checkpoint Forking
**Status**: Draft (revised 2026-05-28)
**Kind**: Architecture Design
**Created**: 2026-05-27
**Revised**: 2026-05-28 — sole-child optimization; in-house ``copy_thread_via_public_api`` (no LangGraph saver implements ``acopy_thread`` natively).
**Dependencies**: RFC-201, RFC-214, RFC-207, RFC-218
**Related**: RFC-222 (Autopilot loop management), RFC-452 (Unified Thread Management), RFC-224 (Context Window Management)

---

## Abstract

This RFC defines a checkpoint-based thread inheritance mechanism for step execution in StrangeLoop. Steps with singleton dependencies fork from their predecessor's checkpoint to inherit full conversation history (tool calls, messages, artifacts). Steps with multiple dependencies fork from the main thread and use message injection for predecessor context. This design achieves two goals: (1) main thread ID alignment with loop_id, and (2) efficient history inheritance via LangGraph's `acopy_thread()` API instead of deep-copying messages.

---

## Problem Statement

### Current Behavior

The Execute phase creates isolated branch threads for each step:

```python
stream_thread_id = f"{logical_tid}__p{step_id}"  # Parallel isolation, no inheritance
```

Each step starts with an empty checkpoint namespace. Predecessor context is injected via `predecessor_execute_messages_for_branch()`, which:
- Deep-copies messages (memory overhead)
- Only includes `execute_step` phase messages (filtered subset)
- Does not preserve full checkpoint state (artifacts, intermediate state, channel versions)

### Goals

1. **ID alignment**: Main thread ID equals loop_id (`thread_id = loop_id`)
2. **Checkpoint inheritance**: Steps inherit full predecessor history via LangGraph fork
3. **DAG handling**: Hybrid strategy for singleton vs multi-dependency steps

---

## Thread Naming Scheme

| Thread Type | Pattern | Example |
|-------------|---------|---------|
| Main thread | `{loop_id}` | `"abc123"` |
| Step thread | `{loop_id}__step_{step_id}` | `"abc123__step_GHT-01"` |

The `__step_` prefix distinguishes sequential fork threads from the existing `__p` (parallel isolation) pattern.

**Why `__step_` vs `__p`**:
- `__p{step_id}`: Current pattern for parallel execution isolation (empty checkpoint)
- `__step_{step_id}`: New pattern for sequential fork threads (inherited checkpoint)

---

## Fork Strategy (Hybrid + Sole-Child Optimization)

Per the 2026-05-28 revision, the strategy now distinguishes singleton-with-siblings from singleton-sole-child:

| Direct deps | Predecessor's other dependents | Fork source | Should fork? | Resulting thread_id | Context |
|---|---|---|---|---|---|
| 0           | n/a                            | main           | ✅ fork (empty source) | `{loop_id}__step_<id>` | empty |
| 1           | 0 (sole child)                 | predecessor    | ❌ reuse — **no copy** | predecessor's thread | inherited |
| 1           | ≥1 (has sibling)               | predecessor    | ✅ fork (copy parent) | `{loop_id}__step_<id>` | inherited via fork |
| ≥2          | n/a                            | main           | ✅ fork (empty source) | `{loop_id}__step_<id>` | message injection |

**Sole-child optimization rationale**: when a step is the *only* dependent of its predecessor, no sibling will race on the predecessor's checkpoint namespace. Reusing the predecessor's thread directly is correct (no race) and saves the cost of copying every checkpoint row. For a linear chain A→B→C with no branches, every link reuses A's thread — total checkpoint copies = 0.

**Sibling fork rationale**: when two or more steps depend on the same predecessor (e.g. fan-out A→{B,C}), both B and C want to write under their own histories without polluting each other. Each forks an independent copy of A's checkpoints into its own `__step_<id>` namespace.

**No-deps fork rationale**: parallel-safety. Two no-deps steps running concurrently must not share a thread namespace, so each gets its own `__step_<id>` namespace sourced from main (empty when main has no checkpoints yet).

**Multi-deps fork rationale**: as before, no single source thread carries the union of all parents' history. The step gets a fresh isolated namespace and the executor injects transitive predecessor messages into the input list.

**Key distinction**:
- **Direct dependencies** + sibling count determine fork source AND whether to copy
- **Transitive dependencies** determine message injection scope (multi-dep only)

### In-house copy implementation

LangGraph's stock savers (`InMemorySaver`, `AsyncSqliteSaver`, `AsyncPostgresSaver`, ...) all inherit `BaseCheckpointSaver.acopy_thread` which raises `NotImplementedError`. We supply our own copy via `core/loop/engine/checkpoint_copy.py::copy_thread_via_public_api`, which iterates the source thread's checkpoints with `alist`, rewrites `configurable.thread_id` to the target, and replays them with `aput` + `aput_writes`. Works on every saver because it relies only on the public protocol surface. ``ThreadForkManager.fork_checkpoint`` calls this helper instead of the saver's broken `acopy_thread`.

---

## Architecture

### Component Interaction

```
┌─────────────────────────────────────────────────────────────────────┐
│  Executor                                                           │
│  • Orchestrates step execution                                      │
│  • Calls ThreadForkManager before each step                         │
│  • Uses forked_thread_id for CoreAgent stream                       │
│  • Injects messages for multi-dep steps                             │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ prepare_thread_for_step()
┌─────────────────────────────────────────────────────────────────────┐
│  ThreadForkManager (NEW)                                            │
│  • select_fork_source(): determines source thread based on deps     │
│  • fork_checkpoint(): calls checkpointer.acopy_thread()             │
│  • track_fork_lineage(): updates LoopState mappings                 │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ fork_checkpoint()
┌─────────────────────────────────────────────────────────────────────┐
│  LoopState (MODIFIED)                                               │
│  • step_thread_ids: dict[str, str] - step_id → thread_id            │
│  • thread_fork_sources: dict[str, str] - thread_id → source         │
└─────────────────────────────────────────────────────────────────────┘
                              ↓ acopy_thread()
┌─────────────────────────────────────────────────────────────────────┐
│  LangGraph Checkpointer                                             │
│  • acopy_thread(source, target) - checkpoint copy API               │
│  • Stores full conversation history, artifacts, state               │
└─────────────────────────────────────────────────────────────────────┘
```

### Position in Existing Flow

```
Executor.execute()
  → _execute_parallel(steps, state)
     → _execute_step_collecting_events(step, ...)
        → ThreadForkManager.prepare_thread_for_step(step, decision, state)
           → select_fork_source(step, decision, state) → source_thread_id
           → fork_checkpoint(source, target, checkpointer) → forked_thread_id
        → CoreAgent.astream() with forked_thread_id as configurable.thread_id
        → (multi-dep only) predecessor_execute_messages_for_branch(transitive_deps)
```

---

## Components

### ThreadForkManager (NEW)

**Location**: `packages/soothe/src/soothe/core/loop/engine/thread_fork_manager.py`

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
    ) -> tuple[str, bool]:
        """Select source thread_id and whether to fork.

        Returns ``(source_thread_id, should_fork)``:
            - 0 deps                          → (main, True)
            - 1 dep, sole child of pred       → (pred_thread, False)  # reuse, no copy
            - 1 dep, pred has siblings        → (pred_thread, True)   # fork
            - ≥2 deps                         → (main, True)
        """
        ...

    async def fork_checkpoint(
        self,
        source_thread_id: str,
        target_thread_id: str,
    ) -> str:
        """Execute checkpoint fork. Returns target_thread_id or source on failure."""
        ...

    async def prepare_thread_for_step(
        self,
        step: StepAction,
        decision: AgentDecision,
        state: LoopState,
        main_thread_id: str,
    ) -> str:
        """Prepare thread for step execution. Updates state mappings."""
        ...
```

**Implementation**:

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
        return state.thread_id

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
        logger.info("Checkpoint forked: %s → %s", source_thread_id, target_thread_id)
        return target_thread_id
    except Exception:
        logger.warning(
            "Checkpoint fork failed: %s → %s, proceeding without inheritance",
            source_thread_id,
            target_thread_id,
            exc_info=True,
        )
        return source_thread_id  # Fallback
```

### LoopState Extension (MODIFY)

**Location**: `packages/soothe/src/soothe/core/loop/state/schemas.py`

**Add fields**:

```python
class LoopState(BaseModel):
    # Existing fields...

    # RFC-223: Thread fork tracking
    step_thread_ids: dict[str, str] = Field(
        default_factory=dict,
        description="Maps step_id → thread_id used for execution",
    )
    thread_fork_sources: dict[str, str] = Field(
        default_factory=dict,
        description="Maps thread_id → source thread_id for fork lineage",
    )
```

### Executor Modification (MODIFY)

**Location**: `packages/soothe/src/soothe/core/loop/engine/executor.py`

**Changes in `_execute_step_collecting_events()`**:

```python
async def _execute_step_collecting_events(...):
    # RFC-223: Prepare fork thread via ThreadForkManager
    fork_manager = ThreadForkManager(self._checkpointer)
    stream_thread_id = await fork_manager.prepare_thread_for_step(
        step=step,
        decision=loop_state.current_decision,
        state=loop_state,
        main_thread_id=thread_id,
    )

    # Determine if multi-dep (needs message injection)
    direct_deps = step.dependencies or []
    needs_message_injection = len(direct_deps) > 1

    # Multi-dep: inject predecessor messages (transitive for full ancestor context)
    if needs_message_injection and loop_state.current_decision:
        transitive_preds = transitive_dependency_step_ids(step, loop_state.current_decision)
        if transitive_preds:
            graph_input_messages = predecessor_execute_messages_for_branch(
                loop_state.loop_messages,
                transitive_preds,
                max_messages=self._branch_predecessor_message_cap(),
            )

    # Use forked thread_id for CoreAgent config
    configurable["thread_id"] = stream_thread_id
    ...
```

### Checkpointer Access (MODIFY)

Executor needs checkpointer access. Pass via constructor:

```python
class Executor:
    def __init__(
        self,
        core_agent: CoreAgent,
        *,
        checkpointer: BaseCheckpointSaver | None = None,  # NEW
        max_parallel_steps: int = 16,
        ...
    ) -> None:
        self._checkpointer = checkpointer
```

---

## Data Flow Examples

### Example 1: Singleton Dependency Chain (A → B → C)

```
Step A (no deps):
  select_fork_source(A) → "abc123" (main)
  fork_checkpoint("abc123", "abc123__step_A") → empty fork
  state.step_thread_ids["A"] = "abc123__step_A"
  Checkpoint saved with A's tool calls

Step B (depends on A):
  select_fork_source(B) → "abc123__step_A" (singleton predecessor)
  fork_checkpoint("abc123__step_A", "abc123__step_B")
    → B's thread now has A's full history
  CoreAgent inherits A's messages from checkpoint

Step C (depends on B):
  select_fork_source(C) → "abc123__step_B"
  fork_checkpoint("abc123__step_B", "abc123__step_C")
    → C's thread has A + B history (checkpoint accumulates)
```

### Example 2: Multi-Dependency (A → C, B → C)

```
Step A: fork from main → "abc123__step_A" (isolated)
Step B: fork from main → "abc123__step_B" (isolated, parallel with A)

Step C (depends on A + B):
  select_fork_source(C) → "abc123" (multi-dep fallback)
  fork_checkpoint("abc123", "abc123__step_C") → empty history
  predecessor_execute_messages_for_branch([A, B]) → message injection
  CoreAgent sees A and B's context via injected messages
```

### Example 3: Mixed DAG (A → B → D, A → C → D)

```
Step A: fork from main → "abc123__step_A"

Step B (depends on A):
  fork from "abc123__step_A" → "abc123__step_B"
  inherits A's checkpoint

Step C (depends on A):
  fork from "abc123__step_A" → "abc123__step_C"
  inherits A's checkpoint (parallel with B, same source)

Step D (depends on B + C):
  select_fork_source(D) → "abc123" (multi-dep)
  fork_checkpoint("abc123", "abc123__step_D") → empty
  predecessor_execute_messages_for_branch([B, C]) → injection
```

---

## Edge Cases

| Scenario | Handling |
|----------|----------|
| Source thread has no checkpoint | `acopy_thread` creates empty target; proceed |
| `acopy_thread` fails | Log warning, use source thread (proceed without fork) |
| Predecessor thread_id not in `step_thread_ids` | Fallback to main thread |
| Checkpointer not available | Skip forking, use main thread |
| Parallel steps with same singleton predecessor | Both fork from same source (valid, isolated writes) |

---

## Design Decisions

1. **Fork cleanup**: Forked threads are **kept** after goal completes for replay/debugging. Future: optional cleanup via configuration.

2. **Fork depth limit**: No explicit limit. Practical depth rarely exceeds 5-7 steps. Add `max_fork_depth` if needed.

3. **Singleton backup injection**: **No backup injection**. Rely purely on checkpoint inheritance. Fork failure fallback to source thread preserves history.

---

## Testing Strategy

### Unit Tests (ThreadForkManager)

- `test_select_fork_source_no_deps_returns_main()`
- `test_select_fork_source_singleton_returns_predecessor()`
- `test_select_fork_source_chain_singleton_inherits()` - A→B→C chain
- `test_select_fork_source_multi_dep_returns_main()`
- `test_fork_checkpoint_calls_acopy_thread()`
- `test_fork_checkpoint_failure_returns_source()`

### Integration Tests

- `test_singleton_chain_inherits_checkpoint()` - B's checkpoint contains A's messages
- `test_multi_dep_injects_messages()` - C receives injected messages from A, B
- `test_parallel_singleton_same_source()` - B, C both fork from A (isolated writes)

---

## Migration Path

### Phase 1: Add ThreadForkManager
- Create `thread_fork_manager.py`
- Add `step_thread_ids`, `thread_fork_sources` to LoopState
- Unit tests

### Phase 2: Modify Executor
- Add checkpointer parameter to Executor
- Call ThreadForkManager in `_execute_step_collecting_events`
- Thread naming: `__p{step_id}` → `__step_{step_id}`
- Integration tests

### Phase 3: Thread ID Alignment
- Ensure main thread_id equals loop_id throughout StrangeLoop
- Verify existing tests pass

### Phase 4: Cleanup
- `predecessor_branch_context.py` logic unchanged for multi-dep
- Singleton case now uses checkpoint inheritance

---

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Checkpoint storage bloat | Fork cleanup after goal; limit depth if needed |
| Race condition in parallel fork | `acopy_thread` atomic; isolated writes |
| Existing tests fail | Thread naming internal; verify behavior not IDs |
| Solo mode compatibility | ThreadForkManager only in StrangeLoop; solo unchanged |

---

## References

- RFC-201: StrangeLoop Plan-Execute Loop Architecture
- RFC-214: Unified message ledger (`predecessor_execute_messages_for_branch`)
- RFC-207: StrangeLoop Thread Lifecycle & Goal Context (supersedes RFC-216)
- RFC-218: StrangeLoop Checkpoint Tree Architecture
- RFC-222: Autopilot and Goal Engine Architecture (loop_id, loop pool)
- RFC-452: Unified Thread Management Architecture
- LangGraph Checkpointer API: `acopy_thread(source_thread_id, target_thread_id)`

---

## Changelog

### 2026-05-27 (Draft)
- Initial RFC draft defining checkpoint-based thread inheritance
- Hybrid fork strategy: singleton deps fork from predecessor, multi-dep fork from main
- Thread naming scheme: `{loop_id}` for main, `{loop_id}__step_{step_id}` for steps
- ThreadForkManager component specification
- LoopState extension with fork tracking fields

### 2026-05-28 (Revised)
- **Sole-child optimization**: singleton-dependency step that is the only
  dependent of its predecessor reuses the predecessor's thread directly
  with no copy. Linear chains (A→B→C with no branches) skip every fork
  cost. Siblings of the same predecessor still fork to keep histories
  independent.
- ``select_fork_source`` return type changed from ``str`` to
  ``tuple[str, bool]`` so the caller can distinguish reuse from fork.
- **In-house ``copy_thread_via_public_api``** helper added in
  ``core/loop/engine/checkpoint_copy.py``. Implements ``acopy_thread``
  semantics on top of any ``BaseCheckpointSaver`` via ``alist`` + ``aput``
  + ``aput_writes`` because no concrete saver in the current LangGraph
  release implements ``acopy_thread`` natively. ThreadForkManager calls
  the helper instead of the saver's stub.
- Tests added: ``test_checkpoint_copy.py`` (helper unit tests against
  ``InMemorySaver``), expanded ``test_thread_fork_manager.py`` for the
  sole-child / siblings split, updated executor integration tests.

---

*Enabling efficient thread inheritance via LangGraph checkpoint forking while preserving DAG complexity handling.*