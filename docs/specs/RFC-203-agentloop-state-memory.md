# RFC-203: AgentLoop State & Memory Architecture

**RFC**: 203
**Title**: AgentLoop State & Memory Architecture
**Status**: Draft
**Kind**: Architecture Design / Impl Interface
**Created**: 2026-04-17
**Dependencies**: RFC-201, RFC-100
**Related**: RFC-207 (Thread), RFC-213 (Reasoning)

---

## Abstract

This RFC defines AgentLoop state management architecture combining LoopState unified model, Loop Working Memory bounded scratchpad, and Loop Unified State Checkpoint progressive persistence. AgentLoop state spans working memory (iteration-bounded), wave metrics (evidence-driven), and checkpoint envelope (durable persistence). This consolidation unifies state management concerns previously fragmented across multiple RFCs.

---

## LoopState Model

### Wave Execution Metrics

```python
class LoopState(BaseModel):
    """AgentLoop unified state model spanning iterations."""

    # Wave execution metrics (inform Plan decisions)
    last_wave_tool_call_count: int = 0
    """Number of tool calls in last Execute wave."""
    last_wave_subagent_task_count: int = 0
    """Number of subagent tasks in last Execute wave."""
    last_wave_hit_subagent_cap: bool = False
    """Whether last wave hit subagent task cap."""
    last_wave_output_length: int = 0
    """Character length of last wave output."""
    last_wave_error_count: int = 0
    """Number of errors in last Execute wave."""

    # Context window metrics (resource tracking)
    total_tokens_used: int = 0
    """Cumulative tokens used across iterations."""
    context_percentage_consumed: float = 0.0
    """Context window utilization percentage."""

    # Iteration tracking
    iteration: int = 0
    """Current iteration number."""
    max_iterations: int = 8
    """Maximum iterations allowed."""

    # State preservation
    previous_plan: PlanResult | None = None
    """Previous PlanResult for decision reuse."""
    plan_conversation_excerpts: list[str] = []
    """Excerpts for Plan phase context."""
```

### Metrics Purpose

**Inform Plan decisions** with structured evidence beyond truncated summary:
- Translation task: 8000 char output + 1 subagent call → `done`
- Research task: cap hit + partial output → `replan`
- Multi-phase task: 2000 char output + cap not hit → `continue`

**Metrics aggregation** occurs after each Execute wave, before Plan phase.

---

## Loop Working Memory

### Bounded Scratchpad Design

The agentic Plan-Execute loop passes progress to the next Plan call mainly via truncated step outputs. That loses structure and forces redundant exploration. **Loop working memory** provides a small, explicit store of durable facts and pointers that survives iterations, can live entirely in RAM, and **spills to the thread workspace** when content is too large for inline prompts.

**Not a second context ledger** (see RFC-400). This is a **bounded scratchpad** scoped to one agentic goal run, optimized for planner-facing summaries and spill artifacts.

### Design Principles

1. **In-memory first**: Fast, no I/O until spill triggers
2. **Runs-local files**: Spilled bytes stay under `SOOTHE_HOME/runs/{thread_id}/loop/`
3. **Deterministic layout**: Paths predictable so prompts can reference files
4. **Optional**: Implementations may disable working memory via config
5. **No secrets**: Do not store raw credentials; redact or omit sensitive tool output

### Data Model

#### Memory Entry (Logical)

| Field | Description |
|-------|-------------|
| `step_id` | Loop step identifier from `StepAction.id` |
| `description` | Short copy of step description (for human scan) |
| `success` | Whether the step succeeded |
| `inline_summary` | Short text always embedded in Plan prompt (may be truncated) |
| `spill_relpath` | Optional path relative to workspace root when body was spilled |

#### Spill Artifact

- **File**: UTF-8 text (`.md` or `.txt`)
- **Content**: Full or large excerpt of step output (or structured dump)
- **Index**: In-memory entry's `inline_summary` references relative path (e.g. `See runs/<thread_id>/loop/step-<id>.md`)

### Filesystem Layout

```text
SOOTHE_HOME/
  runs/
    {thread_id}/
      loop/
        step-<step_id>-<seq>.md
```

- **`thread_id`**: Canonical durability thread identifier (same as used by RunArtifactStore)
- **`<seq>`**: Monotonic integer per `(thread_id, step_id)` to avoid overwrites when same step id is retried

Implementations **must** create parent directories before writing. Spill files co-locate with other run artifacts (manifest, checkpoints, step reports) under `runs/{thread_id}/`.

### Protocol

```python
class LoopWorkingMemoryProtocol(Protocol):
    """Working memory protocol for AgentLoop."""

    def __init__(
        self,
        thread_id: str,
        *,
        max_inline_chars: int,
        max_entry_chars_before_spill: int,
    ) -> None:
        """Construct working memory scoped to thread."""

    def record_step_result(
        self,
        step_id: str,
        description: str,
        output: str,
        success: bool,
        *,
        workspace: Path,
        thread_id: str,
    ) -> None:
        """Append/update memory from one Execute step. May spill when large."""

    def render_for_reason(*, max_chars: int | None = None) -> str:
        """Return single prompt section (empty if disabled/no entries)."""

    def clear() -> None:
        """Reset for new goal (optional; AgentLoop may create fresh instance)."""
```

### Concrete Implementations

- **`LoopWorkingMemory`**: In-memory deque/list + spill writer (`soothe.cognition.loop_working_memory`)
- **`NullLoopWorkingMemory`**: No-op when disabled (optional)

### Integration Points

1. **Loop start**: Runner/AgentLoop constructs working memory from config
2. **Post-Execute**: After each batch of `StepResult`, call `record_step_result` for each
3. **Pre-Plan**: `build_loop_plan_prompt` receives `working_memory_excerpt: str` from `render_for_reason()`

### Prompt Contract

Plan prompts include bounded block:

```text
<SOOTHE_LOOP_WORKING_MEMORY>
... concise bullets + spill path references ...
</SOOTHE_LOOP_WORKING_MEMORY>
```

**Rules stated to model**:
- Treat bullets as **authoritative** for what has already been inspected
- Prefer `read_file` on spill paths over re-running expensive listings
- Do not repeat successful exploration verbatim

### Configuration

```yaml
agentic:
  working_memory:
    enabled: true
    max_inline_chars: 1000  # Aggregated working-memory block max chars
    max_entry_chars_before_spill: 500  # Per-step output length above which spill
```

---

## Loop Unified State Checkpoint

### CheckpointEnvelope Model

```python
class CheckpointEnvelope(BaseModel):
    """Progressive checkpoint model for AgentLoop state."""

    version: int = 1
    """Checkpoint schema version."""
    timestamp: str = ""
    """Checkpoint save timestamp."""
    mode: Literal["single_pass", "autonomous"] = "single_pass"
    """Execution mode (Layer 2 or Layer 3)."""
    last_query: str = ""
    """Last user query."""
    thread_id: str = ""
    """Thread identifier."""

    # Goal state (Layer 3 only)
    goals: list[dict[str, Any]] = []
    """GoalEngine snapshot for autonomous mode."""
    active_goal_id: str | None = None
    """Currently executing goal ID."""

    # Plan state (Layer 2)
    plan: dict[str, Any] | None = None
    """Serialized Plan model."""
    completed_step_ids: list[str] = []
    """Steps completed before checkpoint."""

    # Iteration state
    total_iterations: int = 0
    """Total iterations executed."""
    status: Literal["in_progress", "completed", "failed"] = "in_progress"
    """Execution status."""
```

### Progressive Persistence

**Checkpoint after each step/goal completion**:
- Goal checkpoint: After each goal completes (Layer 3)
- Step checkpoint: After each step batch completes (Layer 2)
- Atomic writes: Write to tmp file, then rename (prevent partial checkpoint on crash)

### Recovery Flow

#### Thread Resume

```python
def _pre_stream(thread_id: str):
    # 1. Resume thread lifecycle
    resume_thread(thread_id)

    # 2. Restore context
    context.restore(thread_id)

    # 3. Load checkpoint envelope
    envelope = artifact_store.load_checkpoint()

    # 4. Restore AgentLoop state
    if envelope and envelope.status == "in_progress":
        # Restore GoalEngine (Layer 3)
        if envelope.mode == "autonomous":
            goal_engine.restore_from_snapshot(envelope.goals)
            active_goal = envelope.active_goal_id

        # Restore Plan (Layer 2)
        plan = Plan.model_validate(envelope.plan) if envelope.plan else None
        completed_steps = envelope.completed_step_ids

        # Mark completed steps in scheduler
        scheduler = StepScheduler(plan)
        for step_id in completed_steps:
            scheduler.mark_completed(step_id, "restored")

        emit soothe.recovery.resumed
```

#### Recovery Scenarios

**Crash mid-step-loop**:
```
Before crash:
  Step 1: completed (checkpoint saved)
  Step 2: completed (checkpoint saved)
  Step 3: in_progress (not saved)
  Step 4: pending

After resume:
  Step 1-2: restored from checkpoint
  Step 3-4: re-executed
```

**Crash mid-goal-DAG**:
```
Before crash:
  Goal A: completed
  Goal B: in_progress, Step 1 done, Step 2 in_progress
  Goal C: pending (depends on A, B)

After resume:
  Goal A: restored, report on disk
  Goal B: active, Step 1 restored, Step 2+ pending
  Goal C: pending (deps not met)
```

### Storage Integration

```python
class RunArtifactStore:
    """Manages $SOOTHE_HOME/runs/{thread_id}/ directory."""

    def save_checkpoint(self, envelope: CheckpointEnvelope) -> None:
        """Save checkpoint atomically (tmp → rename)."""
        checkpoint_path = self.run_dir / "checkpoint.json"
        tmp_path = checkpoint_path.with_suffix(".tmp")

        with open(tmp_path, "w") as f:
            f.write(envelope.model_dump_json())

        tmp_path.rename(checkpoint_path)  # Atomic

    def load_checkpoint(self) -> CheckpointEnvelope | None:
        """Load checkpoint if exists."""
        checkpoint_path = self.run_dir / "checkpoint.json"
        if checkpoint_path.exists():
            return CheckpointEnvelope.model_validate_json(
                checkpoint_path.read_text()
            )
        return None
```

---

## State Flow Integration

### Iteration Lifecycle

```
Loop Start:
  ├─ Load CheckpointEnvelope (if resuming)
  ├─ Restore LoopState (iteration, previous_plan)
  ├─ Initialize WorkingMemory (in-memory)
  └─ Restore completed steps in scheduler

Each Iteration:
  ├─ PLAN Phase:
  │   ├─ LoopState.metrics → Plan prompt
  │   ├─ WorkingMemory.render_for_reason() → Plan prompt
  │   └─ Produce PlanResult
  │
  ├─ EXECUTE Phase:
  │   ├─ Execute steps via CoreAgent
  │   ├─ Collect step results
  │   ├─ WorkingMemory.record_step_result() for each
  │   ├─ LoopState.metrics aggregation
  │   └─ Save checkpoint (step completion)
  │
  └─ Decision:
      ├─ "done" → complete loop
      ├─ "continue" → reuse plan, next iteration
      └─ "replan" → new Plan phase, next iteration

Loop End:
  ├─ Save final checkpoint (status: "completed")
  ├─ ContextProtocol.persist(thread_id)
  └─ Emit soothe.agentic.loop.completed
```

### Memory Hierarchy

```
Layer 2 State Hierarchy:
  ├─ LoopState (iteration-bounded metrics)
  ├─ WorkingMemory (iteration-bounded scratchpad)
  ├─ CheckpointEnvelope (durable persistence)
  └─ ContextProtocol (unbounded knowledge ledger, separate RFC-400)
```

**Boundaries**:
- LoopState: Iteration-scoped (reset per goal)
- WorkingMemory: Goal-scoped (bounded scratchpad)
- CheckpointEnvelope: Thread-scoped (durable persistence)
- ContextProtocol: Thread-scoped (unbounded, separate system)

---

## Configuration

```yaml
agentic:
  max_iterations: 8
  working_memory:
    enabled: true
    max_inline_chars: 1000
    max_entry_chars_before_spill: 500
  checkpoint:
    progressive: true  # Save after each step/goal completion
    auto_resume_on_start: false  # Manual resume required
```

---

## Implementation Status

- ✅ LoopState unified model with wave metrics
- ✅ LoopWorkingMemory bounded scratchpad (in-memory + spill)
- ✅ CheckpointEnvelope progressive persistence
- ✅ Recovery flow (thread resume, crash recovery)
- ✅ Metrics aggregation in executor
- ✅ Token tracking with tiktoken fallback
- ✅ Working memory integration in Plan phase
- ✅ Step checkpoint saving (atomic writes)
- ⚠️ Goal checkpoint saving (Layer 3 integration)

---

## References

- RFC-200: AgentLoop Plan-Execute Loop Architecture
- RFC-100: CoreAgent Runtime
- RFC-207: AgentLoop Thread Management & Goal Context
- RFC-400: ContextProtocol (separate unbounded knowledge system)

---

## Changelog

### 2026-04-17
- Consolidated RFC-203 (Working Memory), RFC-203 (LoopState), RFC-203 (Checkpoint) into unified state management architecture
- Combined LoopState metrics model with working memory bounded scratchpad
- Unified checkpoint envelope progressive persistence with recovery flow
- Maintained all implementation status and configuration details
- Added state flow integration and memory hierarchy boundaries

---

*AgentLoop state management through LoopState metrics, working memory bounded scratchpad, and progressive checkpoint persistence.*