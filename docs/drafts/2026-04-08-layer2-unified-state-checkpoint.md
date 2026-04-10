# Layer 2 Unified State Model and Independent Checkpoint

**Status:** Draft
**Created:** 2026-04-08
**Related:** RFC-201, RFC-203, IG-133

## Problem Statement

Layer 2 (AgentLoop) currently depends on Layer 1's LangGraph checkpoint for state persistence and recovery. This creates architectural coupling and loses semantic clarity about what Layer 2 execution means.

### Current Issues

1. **No architectural separation**: Layer 2 reads Layer 1's message-level checkpoint to derive prior conversation
2. **Loss of semantic structure**: Step I/O is embedded in verbose message traces, not stored as first-class data
3. **Recovery fragility**: Layer 2 state (decisions, working memory) lost on crashes
4. **Token overhead**: Reason loads full message history instead of semantic step traces

### Vision

Layer 2 should own its complete state lifecycle with:
- Independent checkpoint format (step I/O, not messages)
- Unified state model (loop state + working memory + Reason history)
- Per-iteration persistence
- Zero dependency on Layer 1 for recovery

---

## Core Concept

### Layer 1 vs Layer 2 Checkpoint Semantics

**Layer 1 (CoreAgent)**:
- **Granularity**: Message-level (HumanMessage, AIMessage, ToolMessage)
- **Purpose**: Execution trace, tool invocation history
- **Storage**: LangGraph checkpointer (SQLite/PostgreSQL)
- **Consumer**: CoreAgent runtime

**Layer 2 (AgentLoop)**:
- **Granularity**: Step-level (step input/output, decisions, reasoning)
- **Purpose**: Semantic goal execution trace
- **Storage**: JSON files in `runs/{thread_id}/`
- **Consumer**: Reason phase, recovery, observability

**Key insight**: Layer 2 checkpoint captures "what was attempted and what resulted" at the agentic level, not the execution level.

---

## Unified State Model

### Layer2Checkpoint

```python
class Layer2Checkpoint(BaseModel):
    """Complete Layer 2 state for a goal execution."""

    # Identity
    thread_id: str
    goal: str
    created_at: datetime
    updated_at: datetime

    # Execution state
    iteration: int
    max_iterations: int
    status: Literal["running", "completed", "failed", "cancelled"]

    # Reason history (step I/O, not messages)
    reason_history: list[ReasonStepRecord]

    # Act history
    act_history: list[ActWaveRecord]

    # Working memory state
    working_memory_state: WorkingMemoryState

    # Metrics
    total_duration_ms: int
    total_tokens_used: int
```

### ReasonStepRecord

```python
class ReasonStepRecord(BaseModel):
    """One Reason phase execution."""

    iteration: int
    timestamp: datetime

    # Input
    goal_text: str
    prior_step_outputs: list[str]  # From previous Act wave

    # Reasoning
    reasoning: str
    status: Literal["done", "continue", "replan"]
    goal_progress: float

    # Decision
    decision: AgentDecision | None

    # Output
    user_summary: str
    soothe_next_action: str
```

### ActWaveRecord

```python
class ActWaveRecord(BaseModel):
    """One Act wave execution."""

    iteration: int
    timestamp: datetime

    # Steps executed
    steps: list[StepExecutionRecord]

    # Metadata
    execution_mode: Literal["parallel", "sequential", "dependency"]
    duration_ms: int

    # Metrics
    tool_call_count: int
    subagent_task_count: int
    hit_subagent_cap: bool
    error_count: int
```

### StepExecutionRecord

```python
class StepExecutionRecord(BaseModel):
    """Single step execution with I/O."""

    step_id: str
    description: str

    # Input
    step_input: str  # Task text sent to execution

    # Output
    success: bool
    output: str  # Final result
    error: str | None

    # Tool/subagent metadata
    tool_calls: list[ToolCallRecord]
    subagent_calls: list[SubagentCallRecord]
```

### WorkingMemoryState

```python
class WorkingMemoryState(BaseModel):
    """Working memory snapshot."""

    entries: list[WorkingMemoryEntry]
    spill_files: list[str]  # Relative paths to spill files
```

---

## Reason Context Derivation

### Problem

How does Reason get prior conversation without Layer 1 messages?

### Solution

Derive conversation from Act step outputs:

```python
def derive_prior_conversation(checkpoint: Layer2Checkpoint, limit: int = 10) -> list[str]:
    """Derive Reason conversation from step I/O traces."""
    conversation = []

    for act_wave in checkpoint.act_history:
        for step in act_wave.steps:
            if step.success and step.output:
                conversation.append(f"<assistant>\n{step.output}\n</assistant>")

    return conversation[-limit:]
```

**Why this works**:
- Step outputs ARE user-visible deliverables
- No message-level detail needed
- Preserves what Reason cares about: "what was produced"

---

## Checkpoint Persistence

### Storage Location

```
SOOTHE_HOME/
  runs/
    {thread_id}/
      layer2_checkpoint.json     # Layer 2 unified state
      loop/                       # Working memory spill files
        step-{id}-{seq}.md
      steps/                      # Step reports
        step-{id}.json
      checkpoint.json            # Layer 1 checkpoint (separate)
```

### Write Timing

- **Per-iteration**: After each Reason-Act cycle completes
- **Atomic**: Write to temp file, then rename
- **Co-located**: Same directory as working memory and step reports

### File Format

JSON with schema versioning:

```json
{
  "schema_version": "1.0",
  "thread_id": "thread-123",
  "goal": "Translate the document",
  "created_at": "2026-04-08T10:30:00Z",
  "updated_at": "2026-04-08T10:35:00Z",
  "iteration": 2,
  "max_iterations": 8,
  "status": "running",
  "reason_history": [...],
  "act_history": [...],
  "working_memory_state": {...},
  "total_duration_ms": 90000,
  "total_tokens_used": 25000
}
```

---

## Module Organization

### New Structure

```
src/soothe/cognition/agent_loop/
├── checkpoint.py              # Layer2Checkpoint model
├── state_manager.py           # Persistence + recovery
├── loop_agent.py              # Main orchestrator (refactored)
├── executor.py                # Act phase (existing)
├── reason.py                  # Reason phase (existing)
└── schemas.py                 # StepAction, AgentDecision (existing)
```

### Layer2StateManager

```python
class Layer2StateManager:
    """Manages Layer 2 checkpoint lifecycle."""

    def __init__(self, thread_id: str, workspace: Path):
        self.checkpoint_path = workspace / "layer2_checkpoint.json"
        self._checkpoint: Layer2Checkpoint | None = None

    def initialize(self, goal: str, max_iterations: int) -> Layer2Checkpoint:
        """Create new checkpoint."""

    def load(self) -> Layer2Checkpoint | None:
        """Load for recovery."""

    def save(self, checkpoint: Layer2Checkpoint) -> None:
        """Persist to disk."""

    def record_iteration(
        self,
        reason_result: ReasonResult,
        act_wave: ActWaveRecord,
        working_memory: LoopWorkingMemory
    ) -> None:
        """Update after each iteration."""

    def derive_reason_conversation(self, limit: int = 10) -> list[str]:
        """Get prior conversation from step outputs."""
```

---

## Recovery Flow

### Crash Scenario

**Crash at iteration 3, step 2**:

1. User restarts: `soothe "continue"`
2. Layer 2 loads `layer2_checkpoint.json`
3. Finds `status="running"`, `iteration=3`
4. Restores state from checkpoint
5. Resumes from iteration 3

### Recovery Benefits

- ✅ Layer 2 state fully recoverable
- ✅ Working memory spill files preserved
- ✅ Reason history intact
- ✅ No Layer 1 dependency

---

## Benefits

| Aspect | Before | After |
|--------|--------|-------|
| **Separation** | Coupled to Layer 1 | Independent |
| **Recovery** | State lost | Full recovery |
| **Reason context** | Verbose messages | Step I/O |
| **Debugging** | Message traces | Step traces |
| **Storage** | Full history | Summarized |

---

## Implementation Tasks

1. Create `Layer2Checkpoint` model
2. Implement `Layer2StateManager`
3. Refactor `AgentLoop` to use state manager
4. Update Reason context derivation
5. Add recovery tests

---

## Verification

After implementation:

```bash
./scripts/verify_finally.sh
```

Expected: All tests pass, Layer 2 has independent checkpoint.

---

**Next steps**: Implement Layer2StateManager and refactor AgentLoop integration.